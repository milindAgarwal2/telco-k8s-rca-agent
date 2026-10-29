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
    def add_document(self, name: str, text: str) -> RunbookDocument:
        """Chunk and store ``text`` under ``name``. Re-uploading the same
        name is a safe overwrite (previous chunks are replaced, not
        duplicated)."""
        pieces = chunk_text(text)
        with self._lock:
            self._state.chunks[name] = [
                RunbookChunk(doc_name=name, chunk_index=i, text=p)
                for i, p in enumerate(pieces)
            ]
            doc = RunbookDocument(
                name=name,
                added_at=datetime.now(timezone.utc).isoformat(),
                chunk_count=len(pieces),
                chars=len(text),
            )
            self._state.documents[name] = doc
            self._save()
        logger.info("runbook store: added '%s' (%d chunks, %d chars)",
                   name, len(pieces), len(text))
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
    """Best-effort plain-text extraction for an uploaded runbook file.

    ``.txt``/``.md`` are decoded directly. ``.pdf`` uses ``pypdf`` (pure
    Python, no compiled/native dependency, unlike PyMuPDF or Spire.PDF) --
    deliberately the lighter choice given this image already carries
    Streamlit's own dependency weight. PDF output is passed through
    :func:`_normalize_pdf_text` to strip layout artifacts (soft-wrap arrows,
    page boilerplate, literal example-output tables) so chunks and snippets
    read as prose rather than mangled tables.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "pypdf is not installed. Install the rag extra: pip install '.[rag]'"
            ) from exc
        import io
        reader = PdfReader(io.BytesIO(content))
        raw = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return _normalize_pdf_text(raw)
    # .txt, .md, or anything else: treat as plain text.
    return content.decode("utf-8", errors="replace")
