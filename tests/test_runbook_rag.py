"""Tests for the local runbook RAG feature: storage, retrieval, query log,
and the FastAPI endpoints that expose them to the dashboard's Runbooks and
Query Log tabs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rca_agent.models.alert import Alert
from rca_agent.models.incident import Evidence, Hypothesis
from rca_agent.rag.local_store import (
    LocalRunbookStore,
    _normalize_pdf_text,
    chunk_text,
    extract_text,
)
from rca_agent.rag.query_log import QueryLog
from rca_agent.rag.runbook_retriever import (
    LocalRunbookRetriever,
    NullRunbookRetriever,
    _snippet,
    get_runbook_retriever,
)
from rca_agent.reasoning.state import ReasoningState
from rca_agent.reasoning.steps import _enrich_runbook_query, build_next_steps

UPF_OOM_TEXT = (
    "UPF pods are getting OOMKilled frequently.\n\n"
    "Check the memory limit configured on the UPF deployment versus its "
    "working set. A recent ConfigMap change that reduced the memory limit "
    "is the usual cause. Restore the prior limit or right-size based on "
    "active session count."
)
SMF_PFCP_TEXT = (
    "SMF reports PFCP association down.\n\n"
    "When SMF logs show PFCP association failures or UPF unreachable "
    "errors, check UPF pod readiness and health first, since SMF depends "
    "on it."
)


# ---- chunk_text ------------------------------------------------------------

def test_chunk_text_merges_short_paragraphs():
    chunks = chunk_text("Heading\n\nA short follow-up paragraph that is still fairly brief.")
    assert len(chunks) == 1
    assert "Heading" in chunks[0]


def test_chunk_text_hard_wraps_long_paragraphs():
    long_paragraph = " ".join(["word"] * 500)
    chunks = chunk_text(long_paragraph)
    assert len(chunks) > 1
    assert all(len(c) <= 1200 for c in chunks)


def test_chunk_text_empty_input():
    assert chunk_text("   \n\n  ") == []


# ---- extract_text -----------------------------------------------------------

def test_extract_text_plain_text():
    assert extract_text("notes.txt", b"hello world") == "hello world"


def test_extract_text_markdown():
    assert extract_text("runbook.md", b"# Title\n\nBody") == "# Title\n\nBody"


# ---- _normalize_pdf_text (PDF layout cleanup) -------------------------------

def test_normalize_rejoins_softwrap_arrows():
    # pypdf marks a layout-wrapped line with a trailing arrow; the next line is
    # its continuation, often split mid-token ("VER" + "SION").
    raw = "kubectl get nodes NAME STATUS VER \u2192\nSION\nnext line"
    out = _normalize_pdf_text(raw)
    assert "VERSION" in out
    assert "\u2192" not in out  # no arrow artifacts remain


def test_normalize_strips_page_boilerplate():
    raw = (
        "Solution: do the thing\n"
        "Troubleshoot Common Issues in Kubernetes Clusters\n"
        "113/154 51-AXB 250 19 Uen C | 2025-01-24\n"
        "17\n"  # bare page number
        "2. do the next thing"
    )
    out = _normalize_pdf_text(raw)
    assert "Solution: do the thing" in out
    assert "2. do the next thing" in out
    assert "Troubleshoot Common Issues" not in out
    assert "Uen C" not in out


def test_normalize_drops_example_table_rows():
    raw = (
        "1. Check the nodes.\n"
        "seliius06950   Ready   master   146d   v1.17.3\n"
        "seliius19680   NotReady   worker   146d   v1.17.3\n"
        "Every worker in NotReady status is unavailable."
    )
    out = _normalize_pdf_text(raw)
    assert "Check the nodes" in out
    assert "Every worker in NotReady status is unavailable." in out
    assert "seliius06950" not in out  # sample table rows removed


# ---- chunk_text on document structure --------------------------------------

def test_chunk_text_splits_on_solution_heading():
    text = (
        "Cause: the pod ran out of memory and was terminated by the kernel.\n\n"
        "Solution: restore the previous memory limit and restart the pod so it "
        "picks up the corrected configuration value."
    )
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert chunks[0].startswith("Cause:")
    assert chunks[1].startswith("Solution:")


# ---- _snippet (readable excerpts) ------------------------------------------

def test_snippet_collapses_whitespace_and_newlines():
    s = _snippet("line one\n\nline   two\tline three")
    assert "\n" not in s
    assert "  " not in s
    assert s == "line one line two line three"


def test_snippet_truncates_on_word_boundary_with_ellipsis():
    s = _snippet(" ".join(["word"] * 200), limit=50)
    assert s.endswith("\u2026")  # ends with …
    assert len(s) <= 55
    assert not s[:-2].endswith("wor")  # not sliced mid-word


# ---- LocalRunbookStore ------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path) -> LocalRunbookStore:
    return LocalRunbookStore(str(tmp_path / "store.json"))


def test_store_add_and_list_document(store: LocalRunbookStore):
    doc = store.add_document("upf-oom.md", UPF_OOM_TEXT)
    assert doc.name == "upf-oom.md"
    assert doc.chunk_count > 0
    assert store.has_documents()
    assert [d.name for d in store.list_documents()] == ["upf-oom.md"]


def test_store_reupload_replaces_not_duplicates(store: LocalRunbookStore):
    store.add_document("upf-oom.md", UPF_OOM_TEXT)
    store.add_document("upf-oom.md", "short new text")
    assert len(store.list_documents()) == 1
    assert store.stats()["documents"] == 1


def test_store_delete_document(store: LocalRunbookStore):
    store.add_document("upf-oom.md", UPF_OOM_TEXT)
    result = store.delete_document("upf-oom.md")
    assert result == {"deleted": True, "chunks_deleted": result["chunks_deleted"]}
    assert result["chunks_deleted"] > 0
    assert not store.has_documents()


def test_store_delete_missing_document(store: LocalRunbookStore):
    result = store.delete_document("does-not-exist.md")
    assert result["deleted"] is False
    assert result["chunks_deleted"] == 0


def test_store_persists_across_instances(tmp_path: Path):
    path = str(tmp_path / "store.json")
    LocalRunbookStore(path).add_document("upf-oom.md", UPF_OOM_TEXT)
    reloaded = LocalRunbookStore(path)
    assert reloaded.has_documents()
    assert [d.name for d in reloaded.list_documents()] == ["upf-oom.md"]


def test_store_clear(store: LocalRunbookStore):
    store.add_document("upf-oom.md", UPF_OOM_TEXT)
    store.add_document("smf-pfcp.md", SMF_PFCP_TEXT)
    assert store.clear() == 2
    assert not store.has_documents()


# ---- LocalRunbookRetriever ---------------------------------------------------

@pytest.fixture
def populated_store(store: LocalRunbookStore) -> LocalRunbookStore:
    store.add_document("upf-oom.md", UPF_OOM_TEXT)
    store.add_document("smf-pfcp.md", SMF_PFCP_TEXT)
    return store


def test_local_retriever_ranks_the_matching_doc_first(populated_store: LocalRunbookStore):
    retriever = LocalRunbookRetriever(populated_store)
    hits = retriever.retrieve("UPF pod OOMKilled memory limit exceeded")
    assert hits
    assert hits[0].title == "upf-oom.md"


def test_local_retriever_strips_k8s_hash_noise(populated_store: LocalRunbookStore):
    """A pod-template-hash suffix (e.g. '7f9d8c6b5') shouldn't block matching
    or crowd out the real signal in the query -- see _HASH_LIKE_RE."""
    retriever = LocalRunbookRetriever(populated_store)
    hits = retriever.retrieve("eric-pc-upf-7f9d8c6b5-abcde OOMKilled memory limit")
    assert hits
    assert hits[0].title == "upf-oom.md"


def test_local_retriever_one_hit_per_document(populated_store: LocalRunbookStore):
    retriever = LocalRunbookRetriever(populated_store)
    hits = retriever.retrieve("UPF SMF PFCP memory association")
    names = [h.title for h in hits]
    assert len(names) == len(set(names))


def test_local_retriever_no_match_returns_empty(populated_store: LocalRunbookStore):
    retriever = LocalRunbookRetriever(populated_store)
    assert retriever.retrieve("completely unrelated query about billing invoices") == []


def test_local_retriever_empty_store_returns_empty(store: LocalRunbookStore):
    retriever = LocalRunbookRetriever(store)
    assert retriever.retrieve("anything") == []


# ---- get_runbook_retriever factory -------------------------------------------

def test_factory_prefers_local_store_when_populated(populated_store: LocalRunbookStore):
    retriever = get_runbook_retriever(None, local_store=populated_store)
    assert isinstance(retriever, LocalRunbookRetriever)


def test_factory_falls_back_to_null_when_store_empty(store: LocalRunbookStore):
    retriever = get_runbook_retriever(None, local_store=store)
    assert isinstance(retriever, NullRunbookRetriever)


def test_factory_falls_back_to_null_without_rag_url_or_store():
    assert isinstance(get_runbook_retriever(None), NullRunbookRetriever)


def test_factory_http_branch_still_unbuilt_and_unaffected(store: LocalRunbookStore):
    """The pre-existing rag_url/HttpRunbookRetriever TODO must still fall
    through to NullRunbookRetriever -- untouched by the local_store branch."""
    assert isinstance(
        get_runbook_retriever("https://doc-intelligence.example/rag", local_store=store),
        NullRunbookRetriever,
    )


# ---- QueryLog ----------------------------------------------------------------

def test_query_log_records_and_lists_newest_first():
    log = QueryLog(max_entries=10)
    log.record("query one", "NullRunbookRetriever", [])
    log.record("query two", "LocalRunbookRetriever", ["upf-oom.md"])
    entries = log.list_entries()
    assert [e.query for e in entries] == ["query two", "query one"]


def test_query_log_stats_counts_negative_and_positive():
    log = QueryLog(max_entries=10)
    log.record("a", "NullRunbookRetriever", [])
    log.record("b", "LocalRunbookRetriever", ["doc.md"])
    log.record("c", "NullRunbookRetriever", [])
    assert log.stats() == {"total": 3, "negative": 2, "positive": 1}


def test_query_log_bounded_by_max_entries():
    log = QueryLog(max_entries=2)
    for i in range(5):
        log.record(f"query {i}", "NullRunbookRetriever", [])
    entries = log.list_entries()
    assert len(entries) == 2
    assert [e.query for e in entries] == ["query 4", "query 3"]


def test_query_log_clear():
    log = QueryLog(max_entries=10)
    log.record("a", "NullRunbookRetriever", [])
    assert log.clear() == 1
    assert log.stats()["total"] == 0


# ---- FastAPI endpoints --------------------------------------------------------

@pytest.fixture
def api_client(tmp_path: Path, monkeypatch):
    """A TestClient wired to fresh, isolated local_store/query_log instances
    so these tests never touch the real default /tmp/runbooks path or the
    shared state used by tests/test_webhook.py."""
    # NB: ``import rca_agent.webhook.app as X`` can bind to the FastAPI
    # ``app`` attribute rather than the module (``webhook/__init__.py`` does
    # ``from .app import app``, shadowing the submodule name on the package)
    # -- fetch the module via sys.modules explicitly, as test_webhook.py does.
    import rca_agent.webhook.app  # noqa: F401  (side effect: populates sys.modules)
    appmod = sys.modules["rca_agent.webhook.app"]

    fresh_store = LocalRunbookStore(str(tmp_path / "store.json"))
    fresh_log = QueryLog(max_entries=100)
    monkeypatch.setattr(appmod, "_local_store", fresh_store)
    monkeypatch.setattr(appmod, "_query_log", fresh_log)
    return TestClient(appmod.app)


def test_upload_list_and_delete_runbook(api_client: TestClient):
    r = api_client.post(
        "/runbooks",
        files={"file": ("upf-oom.md", UPF_OOM_TEXT.encode(), "text/markdown")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "upf-oom.md"
    assert body["chunk_count"] > 0

    r = api_client.get("/runbooks")
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = api_client.delete("/runbooks/upf-oom.md")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    r = api_client.delete("/runbooks/upf-oom.md")
    assert r.status_code == 404


def test_upload_rejects_empty_text(api_client: TestClient):
    r = api_client.post(
        "/runbooks",
        files={"file": ("empty.txt", b"   ", "text/plain")},
    )
    assert r.status_code == 400


def test_runbook_queries_endpoint_reports_stats_and_entries(api_client: TestClient):
    appmod = sys.modules["rca_agent.webhook.app"]
    appmod._query_log.record("some query", "NullRunbookRetriever", [])

    r = api_client.get("/runbook-queries")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["total"] == 1
    assert body["entries"][0]["query"] == "some query"

    r = api_client.delete("/runbook-queries")
    assert r.status_code == 200
    assert r.json()["cleared"] == 1

    r = api_client.get("/runbook-queries")
    assert r.json()["stats"]["total"] == 0


# ---- runbook query enrichment (concrete failure reason injection) -----------

IMAGEPULL_RUNBOOK_TEXT = (
    "Pod Is in ImagePullBackOff or ErrImagePull Status\n\n"
    "A pod reports ImagePullBackOff when the kubelet cannot pull the container "
    "image. Verify the image name and tag, check the registry is reachable, and "
    "confirm the imagePullSecrets reference valid credentials. ErrImagePull "
    "usually precedes the backoff."
)


def _imagepull_state() -> ReasoningState:
    """An ImagePull incident whose TOP hypothesis is a *probe-failure* label
    (the exact miscorrelation case): the pod is in ImagePullBackOff but the
    ranked #1 cause reads "readiness probe failing", so the base query shares
    no vocabulary with the ImagePull runbook section."""
    alert = Alert(labels={"alertname": "KubePodNotReady", "pod": "rca-demo-imagepull-75fbbb5677-kthpw"})
    state = ReasoningState(alert=alert, namespace="plantx2avzwcspgc-y-oc-consp-301",
                           affected_resource="rca-demo-imagepull-75fbbb5677-kthpw")
    state.add_evidence(Evidence(
        category="event",
        summary="[14:02] ImagePullBackOff: Back-off pulling image \"bad/image:nope\"",
        resource="rca-demo-imagepull-75fbbb5677-kthpw",
    ))
    state.hypotheses = [Hypothesis(
        cause="rca-demo-imagepull-75fbbb5677-kthpw failing health probe (readiness probe failing)",
        confidence=0.8,
    )]
    return state


def test_enrich_runbook_query_injects_concrete_failure_reason():
    state = _imagepull_state()
    base = state.hypotheses[0].cause
    enriched = _enrich_runbook_query(base, state)
    # Base symptom label preserved, but the concrete rare error token is now present.
    assert base in enriched
    assert "ImagePullBackOff" in enriched
    # The base query on its own lacked the distinctive token.
    assert "ImagePullBackOff" not in base


def test_enrich_runbook_query_no_duplicate_when_reason_already_present():
    state = _imagepull_state()
    base = "rca-demo pod ImagePullBackOff loop"  # already names the reason
    enriched = _enrich_runbook_query(base, state)
    # Not appended a second time.
    assert enriched.count("ImagePullBackOff") == 1


def test_build_next_steps_correlates_imagepull_runbook_after_enrichment(store: LocalRunbookStore):
    """End-to-end: the probe-failure-labelled ImagePull incident now retrieves
    the ImagePullBackOff runbook section, which a bare top-cause query missed."""
    store.add_document("imagepull.md", IMAGEPULL_RUNBOOK_TEXT)
    store.add_document("upf-oom.md", UPF_OOM_TEXT)
    retriever = LocalRunbookRetriever(store)
    state = _imagepull_state()

    # Baseline: the un-enriched top-cause query does NOT surface the ImagePull doc first.
    base_hits = retriever.retrieve(state.hypotheses[0].cause)
    assert not base_hits or base_hits[0].title != "imagepull.md"

    # After enrichment via build_next_steps, the ImagePull runbook is found.
    out = build_next_steps(state, retriever, top_k=3)
    assert any("imagepull.md" in step for step in out.suggested_next_steps)
