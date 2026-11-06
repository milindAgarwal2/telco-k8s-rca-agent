---
type: workflow
title: Workflow - Runbook Retrieval (RAG)
description: How suggested next steps are retrieved from runbooks via the local and optional semantic retrievers, with the query log.
tags:
  - rag
  - runbooks
  - retrieval
  - semantic-search
  - workflow
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-0c95ee85b247e9baa8672815
    resource: repo://src/rca_agent/rag/local_store.py
  - id: openwiki-source-ffac8264b1e3c24c74775e94
    resource: repo://src/rca_agent/rag/query_log.py
  - id: openwiki-source-8990877acd61b533651868cc
    resource: repo://src/rca_agent/rag/runbook_retriever.py
  - id: openwiki-source-dedddeaa0ca98f12ba6cc3b4
    resource: repo://src/rca_agent/rag/semantic_store.py
  - id: openwiki-source-91386c0b169bf4a09d4c43b0
    resource: repo://src/rca_agent/webhook/app.py
  - id: openwiki-source-c04816b162233aeb0c9eb28d
    resource: repo://tests/test_runbook_rag.py
  - id: openwiki-source-382f361251334547d72d7d33
    resource: repo://tests/test_semantic_rag.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Workflow: Runbook Retrieval (RAG)

> Draft pending subject-matter expert (SME) review.

Retrieval-Augmented Generation (RAG) means fetching relevant documents and using
them to inform an answer. Here it supplies the incident report's "suggested next
steps" from uploaded runbooks. The agent only **reads** runbooks and surfaces
them for a human; it never acts on them. This is stated in the module docstring
of `src/rca_agent/rag/runbook_retriever.py`.

## Two additive sources

The retriever interface in `src/rca_agent/rag/runbook_retriever.py` defines two
separate, additive sources, neither replacing the other:

- **`LocalRunbookRetriever`** - over documents uploaded through the dashboard's
  Runbooks tab, scored with a term-frequency/inverse-document-frequency
  (TF-IDF) keyword method. Fully local, no network, no LLM. Built and working.
- **`HttpRunbookRetriever`** - calls an external doc-intelligence service. Still
  unbuilt; it exists only as a placeholder for when such a service is reachable.

## Document upload and extraction

Documents are uploaded through `POST /runbooks` and stored by
`src/rca_agent/rag/local_store.py` as plain JSON on local disk - no database and
no vector store. They are chunked into paragraphs, and `LocalRunbookRetriever`
scores those chunks against an incident's query. The store comment notes this is
deliberately local disk, wiped on redeploy, the same accepted limitation as the
in-memory incident list. Re-uploading the same filename replaces its chunks
rather than duplicating them (see the upload handler in
`src/rca_agent/webhook/app.py`).

## The query log and its negative-hit signal

`src/rca_agent/rag/query_log.py` records every runbook-retrieval attempt made via
`build_next_steps` - what was asked and whether anything matched. Its docstring
is explicit that a "negative" entry (zero hits) is the signal to write a runbook
for that situation. The log is thread-safe, in-memory, and bounded by
`runbook_query_log_max_entries` (oldest entries dropped first). It records
retrieval attempts, not LLM calls, because the extractive pipeline makes no LLM
call.

## The opt-in semantic retriever

`src/rca_agent/rag/semantic_store.py` provides an optional embeddings-based
semantic retriever (fastembed `bge-small` ONNX plus an in-memory ChromaDB
index). Per the configuration comments in `src/rca_agent/config.py`, semantic
mode is gated and used only when **all** of the following hold:

1. `runbook_rag_semantic` is `True`;
2. the `[rag-semantic]` dependencies import; and
3. the LLM sidecar is opted in (`reasoning_mode == "llm"`) and reachable on a
   live health probe.

If any gate fails, the retriever transparently falls back to the extractive
TF-IDF retriever. The index is held in memory only (no on-disk vector volume)
and is rebuilt from the local runbook store on startup.

## Verification

`tests/test_runbook_rag.py` verifies the local TF-IDF retrieval path and
`tests/test_semantic_rag.py` verifies the opt-in semantic path, including its
gating and fallback behavior.

## Related pages

- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
- [Configuration Reference](/openwiki/configuration.md)
- [Integrations and Data Inputs](/openwiki/integrations.md)
- [Testing and Evaluation](/openwiki/testing.md)
