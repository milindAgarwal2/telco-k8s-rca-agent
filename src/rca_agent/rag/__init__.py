"""Runbook retriever — thin interface over the existing doc-intelligence RAG."""

from rca_agent.rag.runbook_retriever import (
    RunbookHit,
    RunbookRetriever,
    StubRunbookRetriever,
    get_runbook_retriever,
)

__all__ = [
    "RunbookHit",
    "RunbookRetriever",
    "StubRunbookRetriever",
    "get_runbook_retriever",
]
