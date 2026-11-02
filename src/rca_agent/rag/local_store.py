"""Local runbook document storage.

Uploaded through the dashboard's Runbooks tab (``POST /runbooks``), stored as
plain JSON on local disk — no database, no vector store. Documents are
chunked into paragraphs; :class:`~rca_agent.rag.runbook_retriever.LocalRunbookRetriever`
scores those chunks against an incident's query.

Deliberately local-disk, not persistent storage: same accepted limitation as
the in-memory incident list (``detection/event_watcher.py``) — wiped on
redeploy until Postgres persistence (still on the pending list) covers both.
Both the FastAPI backend and the Streamlit dashboard read/write the same file
path since they run in the same container (see ``docker/entrypoint.sh``).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger("rca_agent.rag")

# A paragraph shorter than this is almost never a useful standalone chunk
# (e.g. a lone heading) -- merged into the next one instead of stored alone.
_MIN_CHUNK_CHARS = 40
# A paragraph longer than this is hard-wrapped so no single chunk dominates
# scoring just by being huge.
_MAX_CHUNK_CHARS = 1200


@dataclass
class RunbookChunk:
    doc_name: str
    chunk_index: int
    text: str
    # Structure-aware extras (default extraction). Markdown tables and
    # extracted image file paths that belong to the same page/section as this
    # chunk, so a retriever can surface them WITH the text hit and a citation.
    # Defaulted so older stored JSON (without these keys) still loads.
    tables: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


@dataclass
class RunbookDocument:
    name: str
    added_at: str
    chunk_count: int
    chars: int


@dataclass
class _StoreState:
    documents: dict[str, RunbookDocument] = field(default_factory=dict)
    chunks: dict[str, list[RunbookChunk]] = field(default_factory=dict)  # doc_name -> chunks


_SECTION_HEADING_RE = re.compile(
    r"^(?:Solution|Cause|Diagnostics|Verification|Prerequisites)\b", re.IGNORECASE
)
# A numbered-section heading like "4.5 Pod Is in CrashLoopBackOff Status" or
# "4.5.1 eric-pm-server-0 Pod Is in CrashLoopBackoff Status ...".
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+){0,3}\s+[A-Z]")


def chunk_text(text: str) -> list[str]:
    """Split ``text`` into coherent, readable chunks.

    Primary split is on the document's own structure -- a new chunk starts at a
    section heading (``Solution:``, ``Cause:``, ``Diagnostics``, ``Verification``)
    or a numbered section heading (``4.5 Pod Is in ...``). Within that, blank
    lines still separate paragraphs. This keeps a remedy ("Solution: ... 1. ...
    2. ...") together as one chunk instead of mixing it with the next section,
    and stops a heading from being stranded on its own.

    A too-short fragment is merged into the next one (a lone heading is useless
    alone); a too-long one is hard-wrapped at a word boundary so no single chunk
    dominates scoring just by being huge.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    pending = ""

    def flush() -> None:
        nonlocal pending
        if pending.strip():
            chunks.extend(_hard_wrap(pending.strip()))
        pending = ""

    for p in paragraphs:
        first_line = p.splitlines()[0].strip() if p else ""
        starts_section = bool(
            _SECTION_HEADING_RE.match(first_line) or _NUMBERED_HEADING_RE.match(first_line)
        )
        # Start a fresh chunk at a section boundary -- but only if what we've
        # accumulated is already a usable chunk; otherwise keep appending so a
        # lone heading isn't stranded.
        if starts_section and len(pending) >= _MIN_CHUNK_CHARS:
            flush()
        pending = f"{pending}\n\n{p}".strip() if pending else p
        # A section that has grown past the floor is closed on the next heading
        # to keep remedies whole; but a non-heading block that's already huge is
        # flushed now so no single chunk dominates scoring.
        if not starts_section and len(pending) >= _MAX_CHUNK_CHARS:
            flush()
    flush()
    return chunks


def _hard_wrap(text: str) -> list[str]:
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]
    words = text.split()
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        if cur_len + len(w) + 1 > _MAX_CHUNK_CHARS and cur:
            out.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += len(w) + 1
    if cur:
        out.append(" ".join(cur))
    return out


class LocalRunbookStore:
    """Thread-safe, JSON-file-backed store of uploaded runbook documents."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._state = self._load()

    # ---- persistence -------------------------------------------------
    def _load(self) -> _StoreState:
        if not os.path.exists(self.path):
            return _StoreState()
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            documents = {
                name: RunbookDocument(**d) for name, d in raw.get("documents", {}).items()
            }
            chunks = {
                name: [RunbookChunk(**c) for c in cs]
                for name, cs in raw.get("chunks", {}).items()
            }
            return _StoreState(documents=documents, chunks=chunks)
        except Exception:
            logger.exception("failed to load runbook store at %s; starting empty", self.path)
            return _StoreState()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        raw = {
            "documents": {name: asdict(d) for name, d in self._state.documents.items()},
            "chunks": {name: [asdict(c) for c in cs] for name, cs in self._state.chunks.items()},
        }
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.replace(tmp, self.path)  # atomic on the same filesystem

    # ---- mutation ------------------------------------------------------
    def add_document(
        self, name: str, text: str, images: list[str] | None = None
    ) -> RunbookDocument:
        """Chunk and store ``text`` under ``name``. Re-uploading the same
        name is a safe overwrite (previous chunks are replaced, not
        duplicated).

        Structure-aware extras (default): any markdown TABLE blocks inside a
        chunk are captured on that chunk (so a tabular remedy is surfaced as a
        table, not flattened prose). Extracted ``images`` (page diagrams) are
        attached at the document level -- associated with the first chunk so a
        retriever can cite them -- since markdown image placement is not always
        reliable enough to pin to a specific chunk.
        """
        pieces = chunk_text(text)
        images = images or []
        with self._lock:
            chunks: list[RunbookChunk] = []
            for i, p in enumerate(pieces):
                tables = _extract_markdown_tables(p)
                chunks.append(
                    RunbookChunk(
                        doc_name=name,
                        chunk_index=i,
                        text=p,
                        tables=tables,
                        # Attach all document images to the first chunk so they
                        # are retrievable with a citation; cheaper and more
                        # honest than guessing which chunk a diagram belongs to.
                        images=images if i == 0 else [],
                    )
                )
            self._state.chunks[name] = chunks
            doc = RunbookDocument(
                name=name,
                added_at=datetime.now(timezone.utc).isoformat(),
                chunk_count=len(pieces),
                chars=len(text),
            )
            self._state.documents[name] = doc
            self._save()
        logger.info("runbook store: added '%s' (%d chunks, %d chars, %d images)",
                   name, len(pieces), len(text), len(images))
        return doc

    def delete_document(self, name: str) -> dict:
        with self._lock:
            existed = name in self._state.documents
            chunks_deleted = len(self._state.chunks.pop(name, []))
            self._state.documents.pop(name, None)
            if existed:
                self._save()
        return {"deleted": existed, "chunks_deleted": chunks_deleted}

    def clear(self) -> int:
        with self._lock:
            n = len(self._state.documents)
            self._state = _StoreState()
            self._save()
        return n

    # ---- queries (read-only) -------------------------------------------
    def list_documents(self) -> list[RunbookDocument]:
        return sorted(self._state.documents.values(), key=lambda d: d.added_at, reverse=True)

    def has_documents(self) -> bool:
        return bool(self._state.documents)

    def all_chunks(self) -> list[RunbookChunk]:
        return [c for cs in self._state.chunks.values() for c in cs]

    def stats(self) -> dict:
        return {
            "documents": len(self._state.documents),
            "chunks": sum(d.chunk_count for d in self._state.documents.values()),
        }


@lru_cache
def get_local_store(path: str | None = None) -> LocalRunbookStore:
    """Process-wide singleton, mirroring ``config.get_settings()``."""
    from rca_agent.config import get_settings
    return LocalRunbookStore(path or get_settings().runbook_store_path)


def _normalize_pdf_text(raw: str) -> str:
    """Clean pypdf's raw extraction into readable prose.

    pypdf renders this guide's layout with three kinds of noise that make
    snippets unreadable (and pollute scoring):

    1. Soft-wrap markers: a line hard-wrapped by the PDF layout ends with a
       trailing ``→`` (U+2192) and continues on the next line. We rejoin those
       so ``v1. →\n17.3`` becomes ``v1.17.3``.
    2. Repeated page header/footer boilerplate, e.g.
       ``113/154 51-AXB 250 19 Uen C | 2025-01-24`` and the running title
       ``Troubleshoot Common Issues in Kubernetes Clusters`` plus bare page
       numbers -- these repeat on every page and add nothing.
    3. Long literal example-output blocks (sample ``kubectl get nodes`` tables,
       node lists like ``seliius06950 Ready master 146d v1.17.3``). They are
       illustrations, not instructions, and they drown the actual remedy text
       in a snippet. We drop obvious tabular example rows.

    This is deliberately conservative: it only removes lines that match
    recognizable noise patterns, so real instruction text is preserved.
    """
    lines = raw.splitlines()

    # --- step 1: rejoin soft-wrapped lines (trailing arrow) ---
    joined: list[str] = []
    carry = ""
    for ln in lines:
        s = ln.rstrip()
        if s.endswith("\u2192"):  # trailing → : continues on next line
            carry += s[:-1].rstrip()
            continue
        if carry:
            # The continuation of a soft-wrapped line. pypdf splits mid-token
            # (e.g. "VER" + "SION"), so join with no space.
            joined.append((carry + s.lstrip()).strip())
            carry = ""
        else:
            joined.append(s)
    if carry:
        joined.append(carry.strip())

    # --- step 2/3: drop boilerplate and example-output rows ---
    footer_re = re.compile(r"^\d+\s*/\s*\d+\s+[\dA-Za-z \-]*Uen\b")  # "113/154 51-AXB ... Uen C"
    title_re = re.compile(r"^Troubleshoot Common Issues in Kubernetes Clusters\s*$")
    page_num_re = re.compile(r"^\d{1,3}\s*$")
    date_tail_re = re.compile(r"\|\s*20\d\d-\d\d-\d\d\s*$")
    # Example node/pod table rows: a hostname-ish token followed by Ready/NotReady
    # and a kube version, or many columns of whitespace-separated sample data.
    example_row_re = re.compile(
        r"^\S+\s+(Ready|NotReady|Running|Pending|Completed|CrashLoopBackOff)\b.*\bv?\d+\.\d+")

    cleaned: list[str] = []
    for ln in joined:
        s = ln.strip()
        if not s:
            cleaned.append("")
            continue
        if footer_re.match(s) or title_re.match(s) or page_num_re.match(s):
            continue
        if date_tail_re.search(s):
            continue
        if example_row_re.match(s):
            continue
        cleaned.append(s)

    text = "\n".join(cleaned)
    # Collapse 3+ blank lines to a single blank line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(filename: str, content: bytes) -> str:
    """Backward-compatible wrapper: return just the extracted text/markdown.

    Prefer :func:`extract_document` (returns text + extracted image paths) for
    the upload path. This wrapper is kept for callers/tests that only want the
    text body.
    """
    text, _images = extract_document(filename, content, asset_dir=None)
    return text


def extract_document(
    filename: str, content: bytes, asset_dir: str | None = None
) -> tuple[str, list[str]]:
    """Structure-aware extraction (DEFAULT). Returns ``(text, image_paths)``.

    ``.txt``/``.md`` are decoded directly (no images). ``.pdf`` has two paths:

    * **Structure-aware (default, preferred)** -- ``pymupdf4llm`` renders the
      PDF to **markdown**, preserving TABLES and the ``kubectl`` command blocks
      that the old flat-text path mangled (the root cause of the bad
      ``#chunk42`` answer). When ``asset_dir`` is given, page IMAGES are also
      extracted to disk and their paths returned, so results can show diagrams
      with a citation. Markdown output skips :func:`_normalize_pdf_text` (that
      repairs pypdf's flat text; markdown is already structured).
    * **Fallback** -- ``pypdf`` flat text + :func:`_normalize_pdf_text`, only
      when pymupdf4llm/PyMuPDF are unavailable. No tables, no images.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext != ".pdf":
        # .txt, .md, or anything else: treat as plain text.
        return content.decode("utf-8", errors="replace"), []

    md, images = _extract_pdf_markdown(content, asset_dir)
    if md is not None:
        return md, images

    # Fallback: pypdf flat text + artifact cleanup.
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "No PDF extractor available. Install the rag extra "
            "(pip install '.[rag]') for structure-aware extraction (pymupdf4llm) "
            "or at least pypdf."
        ) from exc
    import io
    reader = PdfReader(io.BytesIO(content))
    raw = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return _normalize_pdf_text(raw), []


def _extract_pdf_markdown(
    content: bytes, asset_dir: str | None
) -> tuple[str | None, list[str]]:
    """Render a PDF to markdown via pymupdf4llm; extract page images to disk.

    Returns ``(markdown, image_paths)``, or ``(None, [])`` if pymupdf4llm /
    PyMuPDF are not installed or parsing fails (caller falls back to pypdf).
    Never hard-fails the upload path. Opens the bytes in-memory (no temp file).
    """
    try:
        import fitz  # PyMuPDF, a pymupdf4llm dependency
        import pymupdf4llm
    except ImportError:
        return None, []
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception:
        logger.warning("PyMuPDF could not open PDF; falling back to pypdf", exc_info=True)
        return None, []
    try:
        markdown = pymupdf4llm.to_markdown(doc).strip()
        images = _extract_pdf_images(doc, asset_dir) if asset_dir else []
        return markdown, images
    except Exception:
        logger.warning("pymupdf4llm extraction failed; falling back to pypdf", exc_info=True)
        return None, []
    finally:
        doc.close()


def _extract_pdf_images(doc, asset_dir: str) -> list[str]:
    """Extract embedded images from a PyMuPDF document to ``asset_dir``.

    Returns the list of written file paths (``<asset_dir>/p<page>-i<n>.png``).
    Deliberately conservative: skips tiny images (icons/bullets < 64px) that
    are layout decoration, not diagrams. Any per-image failure is skipped, not
    fatal.
    """
    os.makedirs(asset_dir, exist_ok=True)
    paths: list[str] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        for img_i, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                import fitz
                pix = fitz.Pixmap(doc, xref)
                if pix.width < 64 or pix.height < 64:
                    continue  # decorative, skip
                if pix.n >= 5:  # CMYK/alpha -> convert to RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                out = os.path.join(asset_dir, f"p{page_index + 1}-i{img_i}.png")
                pix.save(out)
                paths.append(out)
            except Exception:  # noqa: BLE001, S112 - skip a bad image, keep going
                continue
    return paths


# A markdown table block: one or more lines starting with "|". pymupdf4llm
# emits tables in GitHub-flavored markdown, so a chunk that contains a table
# has contiguous pipe-prefixed lines (header | --- | rows).
_MD_TABLE_RE = re.compile(r"(?:^\|.*\|\s*$\n?){2,}", re.MULTILINE)


def _extract_markdown_tables(text: str) -> list[str]:
    """Return the markdown table blocks found in ``text`` (may be empty)."""
    return [m.group(0).strip() for m in _MD_TABLE_RE.finditer(text)]
