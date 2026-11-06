---
type: concept
title: Concurrency, State Ownership, and Resource Lifetime
description: The background tasks, which component owns each piece of mutable state, how the dependency graph is swapped atomically, how in-memory stores are bounded, and the one unresolved locking question.
tags:
  - concurrency
  - state-ownership
  - lifecycle
  - threading
  - background-tasks
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T20:42:17.288Z
sources:
  - id: openwiki-source-1c84a5c88eb780bf72e79fd5
    resource: repo://src/rca_agent/detection/event_watcher.py
  - id: openwiki-source-0cba96084ad97a9c0edf32a9
    resource: repo://src/rca_agent/graph/builder.py
  - id: openwiki-source-0c95ee85b247e9baa8672815
    resource: repo://src/rca_agent/rag/local_store.py
  - id: openwiki-source-ffac8264b1e3c24c74775e94
    resource: repo://src/rca_agent/rag/query_log.py
  - id: openwiki-source-91386c0b169bf4a09d4c43b0
    resource: repo://src/rca_agent/webhook/app.py
generated: { by: "kiro", at: "2026-11-03T20:42:17.288Z" }
---

# Concurrency, State Ownership, and Resource Lifetime

> Draft pending subject-matter expert (SME) review. The atomic-swap conclusion
> below is labelled as inference where the source does not state it verbatim.

The agent runs as a single process that serves requests on an asyncio event
loop while refreshing a shared dependency graph and polling the cluster in the
background. This page explains which component owns each piece of mutable
state, how that state is kept consistent for readers, and the one open
thread-safety question a reviewer should resolve.

## Three background tasks

The FastAPI lifespan in `src/rca_agent/webhook/app.py` starts three asyncio
tasks at startup and cancels them on shutdown:

1. **`_initial_build`** - runs the first graph build and then reassigns the
   module-level `_flow` (the `ReasoningFlow`) to use the freshly built graph.
2. **`_refresh_loop`** - rebuilds the dependency graph every
   `max(5, graph_rebuild_interval_seconds)` seconds; on error it logs and keeps
   the previous graph.
3. **`_event_watch_loop`** - polls the cluster for fault-signal events every
   `max(5, event_watch_interval_seconds)` seconds; it is a no-op unless both
   `cluster_enabled` and `event_watch_enabled` are true.

Each task offloads its blocking Kubernetes work with `asyncio.to_thread`, so the
long, synchronous `get`/`list` calls run on a worker thread and the event loop
stays responsive to HTTP requests. This is why the initial cluster build does
not block `/healthz`: it is kicked off in a background thread rather than run
before the lifespan yields.

## Who owns which mutable state

| State | Owner | Lifetime | Release |
| --- | --- | --- | --- |
| Dependency graph (`_graph`) | `GraphBuilder` (`graph/builder.py`) | process; rebuilt on the refresh interval | replaced each rebuild |
| Incident pool (`incidents`) | `EventWatcher` (`detection/event_watcher.py`) | process; in-memory, lost on restart | FIFO eviction past the cap |
| Seen-event UIDs | `EventWatcher` | process | LRU eviction past the cap |
| Unhealthy-streak / status-open latches | `EventWatcher` | process | cleared on recovery |
| Runbook query log | `QueryLog` (`rag/query_log.py`) | process | bounded `deque` drops oldest |
| Runbook store | `LocalRunbookStore` (`rag/local_store.py`) | local disk; wiped on redeploy | overwrite per filename |

All operational state is in-process memory or local disk; there is no external
database.

## The atomic graph swap

`GraphBuilder.rebuild` in `src/rca_agent/graph/builder.py` constructs a new
`DependencyGraph` and assigns it to `self._graph`, and read endpoints reach the
graph only through the `graph` property that returns `self._graph`.

*Inference (from the single-assignment pattern):* because the new graph is
built fully and then assigned in one step, a reader that dereferences the
property sees either the old complete graph or the new complete graph, never a
half-built one. The `_refresh_loop` docstring in
`src/rca_agent/webhook/app.py` describes this as an atomic swap. The source does
not contain a formal memory-ordering proof, so treat the "atomic" wording as
this inference rather than a guaranteed hardware-level invariant.

## Bounded in-memory stores

Three stores are explicitly bounded so a long-running process cannot grow them
without limit (all in `src/rca_agent/detection/event_watcher.py` and
`src/rca_agent/rag/query_log.py`):

- `EventWatcher._seen_uids` is capped at `_MAX_SEEN_UIDS = 2000`; the oldest UID
  is evicted first (an `OrderedDict` used as a least-recently-used set).
- `EventWatcher.incidents` is capped at `_MAX_STORED_INCIDENTS = 200`; the
  oldest incident is trimmed from the front of the list.
- `QueryLog` holds its entries in a `deque(maxlen=...)` sized by
  `runbook_query_log_max_entries`, so the oldest entry is dropped automatically.

## Thread-safety that is already in place

Two stores guard themselves explicitly:

- `QueryLog` (`src/rca_agent/rag/query_log.py`) wraps every read and write of
  its `deque` in a `threading.Lock`, because retrieval attempts are recorded
  from reasoning that may run on a worker thread while the dashboard reads the
  log from a request handler.
- `LocalRunbookStore` (`src/rca_agent/rag/local_store.py`) guards its mutations
  with a `threading.Lock` and persists atomically: it writes to a `<path>.tmp`
  file and then calls `os.replace(tmp, self.path)`, which is atomic on the same
  filesystem, so a concurrent reader never sees a partially written store file.

## Unresolved: unlocked EventWatcher shared state

> Review required.

`EventWatcher.incidents` and its `_unhealthy_streak` / `_status_incident_open`
dicts are mutated from the event-watch worker thread (through `poll_once`) and
read from request handlers (for example `/incidents` and `/debug/detection`)
without an explicit lock. In CPython simple list and dict operations are
usually safe, but that is not a documented guarantee of this code. Whether an
explicit lock is warranted under load is an open question for the detection
owner; it is recorded here and on the
[Unresolved Questions](unresolved-questions.md) page as a review item, **not**
asserted as a defect.

## Related pages

- [Architecture and Components](architecture.md)
- [Request Lifecycle and Representation Transitions](request-lifecycle.md)
- [Workflow: Fault Detection](workflow-detection.md)
- [Configuration Reference](configuration.md)
- [Unresolved Questions and Known Gaps](unresolved-questions.md)
