"""Runbook retriever interface.

Reuses the existing multimodal doc-intelligence RAG pipeline (run as a service)
to fetch human-facing remediation guidance. The agent only *reads* runbooks and
surfaces them as suggested next steps for a human — it never acts on them.

Two SEPARATE, ADDITIVE sources, neither replacing the other:
  * :class:`LocalRunbookRetriever` — over documents uploaded through the
    dashboard's Runbooks tab (``rag/local_store.py``). Fully local, no
    network, no LLM. Built, working today.
  * ``HttpRunbookRetriever`` — calling an external doc-intelligence service.
    Still 🔲, unbuilt — for when you have network access to such a service.
    Left exactly as its original TODO; not touched by the work below.
"""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from typing import ClassVar

from pydantic import BaseModel

from rca_agent.rag.local_store import LocalRunbookStore

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Kubernetes-generated suffixes (pod-template-hash, replicaset/pod random
# suffixes, e.g. "7f9d8c6b5", "a1b2c") look like short hex strings -- not
# real words. Stripped from the query so an incident's resource name doesn't
# score purely on noise.
_HASH_LIKE_RE = re.compile(r"^[0-9a-f]{6,}$")
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "to", "of", "in",
    "on", "for", "and", "or", "it", "this", "that", "these", "those", "with", "as", "by",
    "at", "from", "into", "about", "over", "after", "before", "between", "during", "through",
    "above", "below", "up", "down", "out", "off", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "can", "will", "just", "should", "now", "do", "does", "did", "has", "have",
    "had", "having", "if", "because", "until", "while", "against", "its", "i", "you", "he",
    "she", "we", "they", "them", "his", "her", "our", "your", "their",
})


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1 and t not in _STOPWORDS]


def _normalize_query_tokens(query: str) -> list[str]:
    return [t for t in _tokenize(query) if not _HASH_LIKE_RE.match(t)]


_SNIPPET_MAX = 320


def _snippet(text: str, limit: int = _SNIPPET_MAX) -> str:
    """Build a readable one-paragraph excerpt for a runbook hit.

    Collapses internal whitespace/newlines to single spaces (a chunk may span
    several wrapped lines) and truncates at a word boundary with an ellipsis,
    so the suggested next step reads as a sentence rather than a raw,
    mid-word-truncated dump.
    """
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    # Back up to the last word boundary so we don't slice mid-word.
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" .,;:") + " …"


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


class LocalRunbookRetriever(RunbookRetriever):
    """Retrieves from documents uploaded through the dashboard's Runbooks tab.

    Lightweight TF-IDF-style scoring (rarity-weighted term overlap) -- no
    embeddings, no vector DB, no ML dependency. Keeps at most one hit per
    document (its best-scoring chunk) so one large runbook can't crowd out
    everything else.
    """

    def __init__(self, store: LocalRunbookStore) -> None:
        self._store = store

    def retrieve(self, query: str, top_k: int = 3) -> list[RunbookHit]:
        chunks = self._store.all_chunks()
        if not chunks:
            return []
        query_tokens = set(_normalize_query_tokens(query))
        if not query_tokens:
            return []

        chunk_tokens = [(c, _tokenize(c.text)) for c in chunks]
        doc_freq: Counter[str] = Counter()
        for _, toks in chunk_tokens:
            doc_freq.update(set(toks))
        n_chunks = len(chunk_tokens)

        def idf(tok: str) -> float:
            return math.log((n_chunks + 1) / (doc_freq.get(tok, 0) + 1)) + 1.0

        best_per_doc: dict[str, tuple[float, object]] = {}
        for chunk, toks in chunk_tokens:
            if not toks:
                continue
            tf = Counter(toks)
            score = sum(tf[tok] * idf(tok) for tok in query_tokens if tok in tf)
            if score <= 0:
                continue
            prev = best_per_doc.get(chunk.doc_name)
            if prev is None or score > prev[0]:
                best_per_doc[chunk.doc_name] = (score, chunk)

        ranked = sorted(best_per_doc.values(), key=lambda pair: pair[0], reverse=True)
        return [
            RunbookHit(
                title=chunk.doc_name,
                snippet=_snippet(chunk.text),
                source=f"{chunk.doc_name}#chunk{chunk.chunk_index}",
                score=round(score, 3),
            )
            for score, chunk in ranked[:top_k]
        ]


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


def get_runbook_retriever(
    rag_url: str | None,
    local_store: LocalRunbookStore | None = None,
) -> RunbookRetriever:
    """Factory. Priority order:

    1. :class:`LocalRunbookRetriever` -- if ``local_store`` is given AND has
       at least one uploaded document. Added for the dashboard's Runbooks
       tab; purely additive, does not touch the branches below.
    2. HTTP-backed retriever when ``rag_url`` is configured -- TODO (Phase 2),
       still unbuilt, unchanged from before the local_store branch existed.
    3. :class:`NullRunbookRetriever` -- no source configured/no local docs,
       so no misleading canned runbooks appear.

    The keyword ``StubRunbookRetriever`` still exists for demos/tests but is
    not reachable from here: emitting its canned UPF/SMF runbooks against a
    real cluster implied findings that did not come from the cluster.
    """
    if local_store is not None and local_store.has_documents():
        return LocalRunbookRetriever(local_store)
    if not rag_url:
        return NullRunbookRetriever()
    # TODO (Phase 2): implement HttpRunbookRetriever against the doc-intelligence service.
    return NullRunbookRetriever()
