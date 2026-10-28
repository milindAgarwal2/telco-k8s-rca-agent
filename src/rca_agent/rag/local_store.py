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


def chunk_text(text: str) -> list[str]:
    """Split ``text`` into paragraph-sized chunks.

    Splits on blank lines; a too-short paragraph is merged into the next one
    (a lone heading is useless alone); a too-long one is hard-wrapped at a
    word boundary so no single chunk can dominate scoring just by being huge.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    pending = ""
    for p in paragraphs:
        pending = f"{pending} {p}".strip() if pending else p
        if len(pending) < _MIN_CHUNK_CHARS:
            continue
        chunks.extend(_hard_wrap(pending))
        pending = ""
    if pending:
        chunks.extend(_hard_wrap(pending))
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


def extract_text(filename: str, content: bytes) -> str:
    """Best-effort plain-text extraction for an uploaded runbook file.

    ``.txt``/``.md`` are decoded directly. ``.pdf`` uses ``pypdf`` (pure
    Python, no compiled/native dependency, unlike PyMuPDF or Spire.PDF) --
    deliberately the lighter choice given this image already carries
    Streamlit's own dependency weight.
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
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    # .txt, .md, or anything else: treat as plain text.
    return content.decode("utf-8", errors="replace")
