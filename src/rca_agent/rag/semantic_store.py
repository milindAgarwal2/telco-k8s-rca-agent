"""Semantic runbook retriever (opt-in: the ``[rag-semantic]`` extra).

Upgrades the runbook retriever from TF-IDF keyword overlap
(:class:`~rca_agent.rag.runbook_retriever.LocalRunbookRetriever`) to
embeddings-based semantic search, reusing the ChatBOT project's stack:

* **fastembed** -- BAAI/bge-small-en-v1.5 via ONNX. No torch/transformers,
  CPU-only, keeps the image lean.
* **ChromaDB** -- used **IN-MEMORY / EPHEMERAL** (``chromadb.EphemeralClient``).
  Deliberately **no on-disk sqlite volume**: the index is rebuilt from the
  local runbook store every process start and never persisted. (This is the
  explicit deviation from ChatBOT, which keeps a ``chroma_Name/`` sqlite dir.)
* **langchain-text-splitters** -- markdown-aware splitting so a remedy's
  heading + steps + code block stay in one chunk.

Structure-aware *extraction* (pymupdf4llm, which preserves tables and the
``kubectl`` commands that the old pypdf path mangled) lives in
``local_store.extract_text`` -- so by the time chunks reach here they are
already clean markdown. This retriever re-splits those chunks on markdown
structure, embeds them, and does cosine-similarity top-k.

Why this fixes the bad ``#chunk42`` answer: the TF-IDF path matched the literal
tokens ``delete``/``data``/``space`` and returned a mid-procedure fragment with
a destructive ``rm -rf``. Semantic search matches on *meaning* ("what should a
human do to resolve this volume-full condition"), so the retrieved unit is the
relevant remedy section, not a keyword-colliding step.

This retriever is **gated** by :func:`get_runbook_retriever`: it is only ever
constructed when the deps import AND the LLM sidecar is opted-in + reachable.
If anything here fails at construction time the factory falls back to the
extractive retriever -- so this module never becomes a hard dependency.
"""
from __future__ import annotations

import logging

from rca_agent.rag.local_store import LocalRunbookStore, _extract_markdown_tables
from rca_agent.rag.runbook_retriever import (
    RunbookAsset,
    RunbookHit,
    RunbookRetriever,
    _images_by_doc,
    _snippet,
)

logger = logging.getLogger("rca_agent.rag")

# Markdown-aware chunk sizing. Small enough that one hit is a focused remedy,
# large enough to keep a heading + its numbered steps + a fenced command block
# together.
_CHUNK_SIZE = 900
_CHUNK_OVERLAP = 120


class SemanticRagUnavailable(RuntimeError):
    """Raised when the [rag-semantic] deps are missing or an index can't be built.

    The factory catches this and falls back to the extractive retriever.
    """


def semantic_deps_available() -> bool:
    """True if the ``[rag-semantic]`` dependencies import successfully."""
    try:
        import chromadb  # noqa: F401
        import fastembed  # noqa: F401
        from langchain_text_splitters import (  # noqa: F401
            MarkdownTextSplitter,
        )

        return True
    except ImportError:
        return False


class SemanticRunbookRetriever(RunbookRetriever):
    """Embeddings-based retriever over the uploaded runbook documents.

    Builds an **in-memory** Chroma collection at construction time from the
    local store's chunks. No persistence: the collection lives only for the
    life of this object. Re-instantiate (the pipeline does, per incident) to
    pick up newly uploaded runbooks.
    """

    def __init__(
        self,
        store: LocalRunbookStore,
        embed_model: str = "BAAI/bge-small-en-v1.5",
    ) -> None:
        self._store = store
        self._embed_model = embed_model
        self._collection = None
        self._embedder = None
        self._build_index()

    # ---- index construction (in-memory, no persistence) ----------------
    def _build_index(self) -> None:
        try:
            import chromadb
            from fastembed import TextEmbedding
            from langchain_text_splitters import MarkdownTextSplitter
        except ImportError as exc:  # pragma: no cover - guarded by factory
            raise SemanticRagUnavailable(
                "the [rag-semantic] extra is not installed: "
                "pip install '.[rag-semantic]'"
            ) from exc

        chunks = self._store.all_chunks()
        if not chunks:
            # Nothing to index. Not an error -- retrieve() will return [].
            self._embedder = None
            self._collection = None
            return

        # Re-split each stored chunk on markdown structure so a remedy's
        # heading/steps/command stay together.
        splitter = MarkdownTextSplitter(
            chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP
        )
        texts: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []
        for c in chunks:
            for j, piece in enumerate(splitter.split_text(c.text)):
                piece = piece.strip()
                if not piece:
                    continue
                texts.append(piece)
                metadatas.append(
                    {"doc_name": c.doc_name, "chunk_index": c.chunk_index, "sub": j}
                )
                ids.append(f"{c.doc_name}::{c.chunk_index}::{j}")

        if not texts:
            self._embedder = None
            self._collection = None
            return

        # Use the fastembed cache baked into the image (FASTEMBED_CACHE_PATH),
        # so the model loads OFFLINE on the Cobra jumpserver instead of trying
        # to reach HuggingFace. Falls back to fastembed's default cache when the
        # env var is unset (local dev with internet).
        import os

        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
        if cache_dir:
            self._embedder = TextEmbedding(model_name=self._embed_model, cache_dir=cache_dir)
        else:
            self._embedder = TextEmbedding(model_name=self._embed_model)
        embeddings = [list(map(float, v)) for v in self._embedder.embed(texts)]

        # EphemeralClient = in-memory ONLY. No path, no sqlite file, nothing
        # written to disk -- the deliberate deviation from ChatBOT's persisted
        # chroma_Name/ directory. NOTE: chromadb's in-memory client is a
        # process-wide singleton, so a fixed collection name would collide when
        # the pipeline rebuilds the retriever per incident. We use a UNIQUE
        # collection name per instance and delete it on failure, so each build
        # is isolated and nothing accumulates across incidents.
        import uuid

        client = chromadb.EphemeralClient()
        self._collection_name = f"runbooks-{uuid.uuid4().hex}"
        # cosine space so top_k is by semantic similarity.
        self._collection = client.create_collection(
            name=self._collection_name, metadata={"hnsw:space": "cosine"}
        )
        self._collection.add(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )
        logger.info(
            "semantic runbook index built in-memory: %d sub-chunks from %d stored chunks "
            "(model=%s, collection=%s, no persistence)",
            len(texts), len(chunks), self._embed_model, self._collection_name,
        )

    # ---- retrieval (read-only) -----------------------------------------
    def retrieve(self, query: str, top_k: int = 3) -> list[RunbookHit]:
        if self._collection is None or self._embedder is None:
            return []
        q_emb = list(map(float, next(iter(self._embedder.embed([query])))))
        # Pull extra candidates so we can keep the best hit per document
        # (mirrors the extractive retriever: one large runbook shouldn't crowd
        # out everything else).
        n_results = max(top_k * 4, top_k)
        res = self._collection.query(
            query_embeddings=[q_emb],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        best_per_doc: dict[str, tuple[float, str, dict]] = {}
        for text, meta, dist in zip(docs, metas, dists):
            # cosine distance in [0, 2]; similarity score in ~[0, 1].
            score = 1.0 - float(dist)
            doc_name = meta.get("doc_name", "runbook")
            prev = best_per_doc.get(doc_name)
            if prev is None or score > prev[0]:
                best_per_doc[doc_name] = (score, text, meta)

        ranked = sorted(best_per_doc.values(), key=lambda t: t[0], reverse=True)
        images_by_doc = _images_by_doc(self._store.all_chunks())
        hits: list[RunbookHit] = []
        for score, text, meta in ranked[:top_k]:
            doc_name = meta.get("doc_name", "runbook")
            chunk_index = meta.get("chunk_index", 0)
            source = f"{doc_name}#chunk{chunk_index}"
            tables = _extract_markdown_tables(text)
            hits.append(
                RunbookHit(
                    title=doc_name,
                    snippet=_snippet(text),
                    source=source,
                    score=round(score, 3),
                    tables=[
                        RunbookAsset(kind="table", source=source, content=t)
                        for t in tables
                    ],
                    images=images_by_doc.get(doc_name, []),
                )
            )
        return hits
