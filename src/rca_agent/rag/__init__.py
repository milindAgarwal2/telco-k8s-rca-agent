"""Runbook retriever — thin interface over the existing doc-intelligence RAG,
plus a fully local, additive document store/retriever and query log.

Retrieval has two modes:
  * Extractive (default): TF-IDF keyword overlap (:class:`LocalRunbookRetriever`).
  * Semantic (opt-in, the ``[rag-semantic]`` extra): embeddings + in-memory
    ChromaDB (:class:`SemanticRunbookRetriever`), gated behind a live LLM
    sidecar. Falls back to extractive when deps are missing or the sidecar is
    down. Imported lazily so the base install never needs the heavy deps.

Structure-aware extraction (tables/commands preserved, page images extracted)
is DEFAULT via :func:`extract_document` -- not tied to the semantic opt-in.
"""

from rca_agent.rag.local_store import (
    LocalRunbookStore,
    extract_document,
    extract_text,
    get_local_store,
)
from rca_agent.rag.query_log import QueryLog, QueryLogEntry, get_query_log
from rca_agent.rag.runbook_retriever import (
    LocalRunbookRetriever,
    NullRunbookRetriever,
    RunbookAsset,
    RunbookHit,
    RunbookRetriever,
    StubRunbookRetriever,
    get_runbook_retriever,
)

__all__ = [
    "LocalRunbookRetriever",
    "LocalRunbookStore",
    "NullRunbookRetriever",
    "QueryLog",
    "QueryLogEntry",
    "RunbookAsset",
    "RunbookHit",
    "RunbookRetriever",
    "StubRunbookRetriever",
    "extract_document",
    "extract_text",
    "get_local_store",
    "get_query_log",
    "get_runbook_retriever",
]
