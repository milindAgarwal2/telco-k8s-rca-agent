"""Tests for the opt-in semantic runbook RAG ([rag-semantic]) and its
extractive-first fallback.

Covered:
  * Factory gating: semantic is used ONLY when opt-in + deps + live sidecar;
    otherwise it falls back to the extractive TF-IDF retriever.
  * Structure-aware extraction is the DEFAULT (pymupdf4llm preferred, pypdf
    fallback) and markdown tables are captured per chunk with citations.
  * RunbookHit carries tables/images; build_next_steps renders them with
    citations.
  * No persistence: the semantic index is in-memory (no on-disk Chroma file).
  * The LLM sidecar liveness probe gates correctly.

The embeddings/Chroma deps ([rag-semantic]) may not be installed in CI, so the
semantic-path tests skip gracefully when unavailable; the fallback/gating tests
run regardless (that is the whole point of the fallback).
"""
from __future__ import annotations

import importlib.util

import pytest

from rca_agent.config import Settings
from rca_agent.rag.local_store import (
    LocalRunbookStore,
    _extract_markdown_tables,
    extract_document,
)
from rca_agent.rag.runbook_retriever import (
    LocalRunbookRetriever,
    get_runbook_retriever,
)

SEMANTIC_DEPS = all(
    importlib.util.find_spec(m) is not None
    for m in ("fastembed", "chromadb", "langchain_text_splitters")
)
requires_semantic = pytest.mark.skipif(
    not SEMANTIC_DEPS, reason="[rag-semantic] deps not installed"
)

RUNBOOK_MD = (
    "# Volume occupancy high on eric-pm-server\n\n"
    "Solution: Delete old performance-management files from the data volume "
    "until occupancy drops below 80 percent.\n\n"
    "| Step | Action |\n"
    "| --- | --- |\n"
    "| 1 | Identify large files |\n"
    "| 2 | Remove the oldest files |\n"
)


def _store(tmp_path) -> LocalRunbookStore:
    return LocalRunbookStore(str(tmp_path / "store.json"))


# ---- structure-aware extraction (DEFAULT) ----------------------------------

def test_extract_document_plain_text_returns_no_images():
    text, images = extract_document("notes.txt", b"hello world")
    assert text == "hello world"
    assert images == []


def test_extract_markdown_tables_detects_pipe_tables():
    tables = _extract_markdown_tables(RUNBOOK_MD)
    assert len(tables) == 1
    assert "| Step | Action |" in tables[0]
    assert "| 2 | Remove the oldest files |" in tables[0]


def test_store_captures_tables_on_chunk(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    chunks = store.all_chunks()
    # At least one chunk should carry the captured markdown table.
    assert any(getattr(c, "tables", []) for c in chunks)


def test_store_attaches_images_to_first_chunk(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD, images=["/tmp/assets/vol/p1-i0.png"])
    chunks = sorted(store.all_chunks(), key=lambda c: c.chunk_index)
    assert chunks[0].images == ["/tmp/assets/vol/p1-i0.png"]


# ---- RunbookHit assets surface with citations ------------------------------

def test_extractive_retriever_surfaces_table_with_citation(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    hits = LocalRunbookRetriever(store).retrieve("volume occupancy high delete files", top_k=3)
    assert hits
    top = hits[0]
    assert top.tables, "expected the markdown table to be surfaced"
    # Citation points back to the doc + chunk.
    assert top.tables[0].source.startswith("vol.md#chunk")


def test_extractive_retriever_surfaces_image_with_citation(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD, images=["/tmp/assets/vol/p1-i0.png"])
    hits = LocalRunbookRetriever(store).retrieve("volume occupancy high delete files", top_k=3)
    assert hits
    assert any(h.images for h in hits)
    img = next(h.images[0] for h in hits if h.images)
    assert img.kind == "image"
    assert img.path == "/tmp/assets/vol/p1-i0.png"
    assert img.source.startswith("vol.md#chunk")


def test_build_next_steps_renders_table_and_figure_citations(tmp_path):
    from rca_agent.models.alert import Alert
    from rca_agent.reasoning.state import ReasoningState
    from rca_agent.reasoning.steps import build_next_steps

    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD, images=["/tmp/assets/vol/p1-i0.png"])
    retriever = LocalRunbookRetriever(store)
    # build_next_steps derives its query from the top hypothesis cause (the
    # realistic path), so give it a cause overlapping the runbook's wording.
    # The point of this test is the asset rendering, not token-coincidence.
    from rca_agent.models.incident import Hypothesis

    state = ReasoningState(
        alert=Alert(name="VolumeOccupancyHigh", target="eric-pm-server-0"),
        namespace="ns",
        affected_resource="eric-pm-server-0",
    )
    state.hypotheses = [
        Hypothesis(cause="volume occupancy high: delete old files from the data volume",
                   confidence=0.8)
    ]
    build_next_steps(state, retriever, top_k=3)
    joined = "\n".join(state.suggested_next_steps)
    assert "[table — vol.md#chunk" in joined
    assert "[figure — vol.md#chunk" in joined


# ---- factory gating: extractive-first fallback -----------------------------

def test_factory_falls_back_to_extractive_when_semantic_off(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    # semantic opt-in False -> extractive regardless of sidecar.
    r = get_runbook_retriever(None, local_store=store, semantic=False, sidecar_available=True)
    assert isinstance(r, LocalRunbookRetriever)


def test_factory_falls_back_when_sidecar_down(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    # opt-in True but sidecar not available -> extractive.
    r = get_runbook_retriever(None, local_store=store, semantic=True, sidecar_available=False)
    assert isinstance(r, LocalRunbookRetriever)


@pytest.mark.skipif(SEMANTIC_DEPS, reason="only meaningful when deps are MISSING")
def test_factory_falls_back_when_deps_missing(tmp_path):
    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    # opt-in + sidecar 'up' but deps absent -> still extractive (no crash).
    r = get_runbook_retriever(None, local_store=store, semantic=True, sidecar_available=True)
    assert isinstance(r, LocalRunbookRetriever)


# ---- semantic retriever (when deps present) --------------------------------

@requires_semantic
def test_semantic_retriever_returns_relevant_hit(tmp_path):
    from rca_agent.rag.semantic_store import SemanticRunbookRetriever

    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    store.add_document(
        "unrelated.md",
        "# Pod CrashLoopBackOff\n\nSolution: inspect the container logs and "
        "fix the failing readiness probe.",
    )
    r = SemanticRunbookRetriever(store)
    hits = r.retrieve("disk is almost full, how do I free space on the volume", top_k=2)
    assert hits
    # Semantic match should favor the volume doc over the crashloop doc.
    assert hits[0].title == "vol.md"


@requires_semantic
def test_semantic_retriever_is_in_memory_no_persistence(tmp_path):
    """The semantic index must NOT write any on-disk Chroma sqlite file."""
    from rca_agent.rag.semantic_store import SemanticRunbookRetriever

    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    SemanticRunbookRetriever(store).retrieve("free disk space", top_k=1)
    # No chroma.sqlite3 (or any .sqlite3) anywhere under the temp tree.
    leftovers = list(tmp_path.rglob("*.sqlite3")) + list(tmp_path.rglob("chroma*"))
    assert not leftovers, f"semantic index must be in-memory; found {leftovers}"


@requires_semantic
def test_semantic_factory_used_when_all_conditions_met(tmp_path):
    from rca_agent.rag.semantic_store import SemanticRunbookRetriever

    store = _store(tmp_path)
    store.add_document("vol.md", RUNBOOK_MD)
    r = get_runbook_retriever(None, local_store=store, semantic=True, sidecar_available=True)
    assert isinstance(r, SemanticRunbookRetriever)


# ---- sidecar liveness probe ------------------------------------------------

def test_sidecar_available_false_when_not_llm_mode():
    from rca_agent.reasoning.llm_rerank import sidecar_available

    cfg = Settings(reasoning_mode="extractive")
    assert sidecar_available(cfg) is False


def test_sidecar_available_false_when_unreachable():
    from rca_agent.reasoning.llm_rerank import sidecar_available

    # llm mode but nothing is listening on this port -> not available.
    cfg = Settings(
        reasoning_mode="llm",
        llm_base_url="http://127.0.0.1:59999",
        llm_timeout_seconds=1.0,
    )
    assert sidecar_available(cfg) is False
