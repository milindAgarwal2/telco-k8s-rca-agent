"""Runbook retriever interface.

Reuses the existing multimodal doc-intelligence RAG pipeline (run as a service)
to fetch human-facing remediation guidance. The agent only *reads* runbooks and
surfaces them as suggested next steps for a human — it never acts on them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel


class RunbookHit(BaseModel):
    title: str
    snippet: str
    source: str  # runbook page / URL / doc id
    score: float = 0.0


class RunbookRetriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 3) -> list[RunbookHit]:
        ...


class StubRunbookRetriever(RunbookRetriever):
    """Keyword-matched canned runbooks so the report has next-steps with no service."""

    _RUNBOOKS: ClassVar[list[RunbookHit]] = [
        RunbookHit(
            title="UPF OOMKilled / memory pressure",
            snippet=(
                "Check the UPF memory limit vs. working set. Recent ConfigMap "
                "limit reductions are the usual cause. Restore the prior limit or "
                "right-size based on session count."
            ),
            source="runbooks/upf-oom.md",
        ),
        RunbookHit(
            title="SMF PFCP association down",
            snippet=(
                "SMF errors about PFCP/UPF unreachable almost always point "
                "upstream to UPF health. Verify UPF pod readiness first."
            ),
            source="runbooks/smf-pfcp.md",
        ),
        RunbookHit(
            title="ConfigMap change rollback",
            snippet=(
                "Identify the offending key, compare against the last-known-good "
                "revision, and roll back. Restart consuming pods to reload."
            ),
            source="runbooks/configmap-rollback.md",
        ),
    ]

    def retrieve(self, query: str, top_k: int = 3) -> list[RunbookHit]:
        q = query.lower()
        scored: list[RunbookHit] = []
        for rb in self._RUNBOOKS:
            text = f"{rb.title} {rb.snippet}".lower()
            overlap = sum(1 for tok in set(q.split()) if tok in text)
            if overlap:
                scored.append(rb.model_copy(update={"score": float(overlap)}))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]


class NullRunbookRetriever(RunbookRetriever):
    """Returns no runbook hits — used when no runbook RAG service is configured.

    This keeps the incident report honest: with no runbook source wired, the
    agent must NOT emit canned remediation text (e.g. UPF/SMF runbooks) that
    could be mistaken for a real finding about the cluster. ``build_next_steps``
    turns an empty result into a single neutral "no runbook source configured"
    note.
    """

    def retrieve(self, query: str, top_k: int = 3) -> list[RunbookHit]:
        return []


def get_runbook_retriever(rag_url: str | None) -> RunbookRetriever:
    """Factory: HTTP-backed retriever when a URL is configured, else a neutral
    no-op retriever (so no misleading canned runbooks appear).

    The keyword ``StubRunbookRetriever`` still exists for demos/tests but is no
    longer the default: emitting its canned UPF/SMF runbooks against a real
    cluster implied findings that did not come from the cluster.
    """
    if not rag_url:
        return NullRunbookRetriever()
    # TODO (Phase 2): implement HttpRunbookRetriever against the doc-intelligence service.
    return NullRunbookRetriever()
