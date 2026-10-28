"""Runbook retriever — thin interface over the existing doc-intelligence RAG,
plus a fully local, additive document store/retriever and query log."""

from rca_agent.rag.local_store import LocalRunbookStore, extract_text, get_local_store
from rca_agent.rag.query_log import QueryLog, QueryLogEntry, get_query_log
from rca_agent.rag.runbook_retriever import (
    LocalRunbookRetriever,
    RunbookHit,
    RunbookRetriever,
    StubRunbookRetriever,
    get_runbook_retriever,
)

__all__ = [
    "LocalRunbookRetriever",
    "LocalRunbookStore",
    "QueryLog",
    "QueryLogEntry",
    "RunbookHit",
    "RunbookRetriever",
    "StubRunbookRetriever",
    "extract_text",
    "get_local_store",
    "get_query_log",
    "get_runbook_retriever",
]
