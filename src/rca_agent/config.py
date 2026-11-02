"""Application settings.

All configuration is read from environment variables (prefix ``RCA_``) or a
local ``.env`` file. Defaults are chosen so the agent runs out-of-the-box in
no-LLM extractive mode without a cluster connection.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RCA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Service ---
    app_name: str = "k8s-rca-agent"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    # --- Reasoning mode ---
    # "extractive" = deterministic, no LLM (default; reproducible & cheap).
    # "llm"        = LLM ranks/explains the rule-gathered evidence.
    reasoning_mode: Literal["extractive", "llm"] = "extractive"

    # --- Cluster access ---
    # When False, graph/query tools use stubbed/in-memory data (safe for demos
    # and CI). When True, the kubernetes client is used in read-only fashion.
    cluster_enabled: bool = False

    # How to load kube config:
    #   "auto"      — in-cluster if a ServiceAccount token is present, else kubeconfig
    #   "incluster" — force the mounted ServiceAccount token (normal in-pod path)
    #   "local"     — force the local kubeconfig (dev from a jumphost/laptop)
    kubeconfig_mode: Literal["auto", "incluster", "local"] = "auto"

    namespace: str = Field(
        default="open5gs",
        description="Namespace holding the NF/application to monitor.",
    )

    # Label selector scoping the monitored application within the namespace.
    # Empty (default) = the whole namespace is treated as the one application.
    # Narrow it later to a single NF, e.g. "app=upf" or "app.kubernetes.io/name=upf".
    nf_selector: str = ""

    # --- Graph ---
    graph_rebuild_interval_seconds: int = 60
    graph_history_window_minutes: int = 120

    # --- Event watcher (automatic fault detection) ---
    # Polls K8s Warning events in ``namespace`` and feeds any recognized fault
    # reason (CrashLoopBackOff/OOMKilled/.../Unhealthy, see
    # ``KubeEvent.FAULT_REASONS``) through the SAME reasoning entry point as
    # the Alertmanager webhook — no human has to hand-craft an alert payload
    # for a pod that is already visibly unhealthy. Only acts when
    # ``cluster_enabled`` is True (no events exist in demo/stub mode).
    event_watch_enabled: bool = True
    event_watch_interval_seconds: int = 15
    # Maximum age of a Kubernetes Warning event still worth acting on. Kubernetes
    # stops refreshing an event's lastTimestamp while a fault is ongoing (e.g. a
    # readiness probe that has been failing for an hour emits its Unhealthy event
    # only periodically, then goes quiet), so a too-short window makes the
    # watcher blind to a still-active outage. Default 90 min; raise for faults
    # that recur slowly, lower to reduce reacting to old, resolved events.
    event_max_age_minutes: int = 90

    # --- Status-based detection (does NOT depend on fresh K8s events) ---
    # The graph rolls up each pod's health on every rebuild. A pod that stays
    # unhealthy across this many consecutive rebuilds is raised as an incident
    # even when no fresh Event exists — so the agent survives Kubernetes aging
    # events out from under a still-broken pod. 0 disables status-based
    # detection (event-only behavior).
    status_detection_enabled: bool = True
    status_unhealthy_rebuilds: int = 2

    # --- Incident correlation ---
    # Links incidents (auto-detected OR manually posted via the webhook) that
    # share an identical failure signature on a DIFFERENT resource within this
    # window — e.g. "12 pods failed their readiness probe the same way within
    # 10 minutes" becomes one visible, linked pattern instead of 12 isolated
    # low-confidence guesses. Deliberately NOT a substitute for real
    # NF-to-NF ``calls`` edges: it never names or claims a specific shared
    # cause, only flags the pattern (see PLAN.md Known Issues).
    incident_correlation_window_minutes: int = 10

    # --- Evidence gathering ---
    log_tail_lines: int = 200
    change_correlation_window_minutes: int = 15

    # Optional Prometheus base URL for the metrics() query tool. When unset,
    # metrics are skipped gracefully (pod status/events/logs/changes still work).
    prometheus_url: str | None = None

    # --- RAG runbook retriever ---
    # Two SEPARATE, ADDITIVE sources (neither replaces the other):
    #   runbook_rag_url    -> HttpRunbookRetriever, calling an external
    #                         doc-intelligence service. Still 🔲 (not built) —
    #                         for when network access to such a service is
    #                         available. Setting this URL alone does nothing
    #                         yet (see rag/runbook_retriever.py).
    #   runbook_store_path -> LocalRunbookRetriever, over documents uploaded
    #                         through the dashboard's Runbooks tab. Fully
    #                         local, no network/LLM needed. Takes priority
    #                         when documents have actually been uploaded.
    runbook_rag_url: str | None = None  # existing doc-intelligence service
    runbook_rag_top_k: int = 3
    runbook_store_path: str = "/tmp/runbooks/store.json"
    # Directory for images extracted from uploaded PDFs (structure-aware
    # default). Page diagrams are written here and surfaced in results with a
    # citation. Local disk, wiped on redeploy like the store itself.
    runbook_asset_dir: str = "/tmp/runbooks/assets"

    # --- Semantic runbook RAG (opt-in; the [rag-semantic] extra) ---
    # When True, the runbook retriever is upgraded from TF-IDF keyword overlap
    # to embeddings-based semantic search (fastembed bge-small ONNX + in-memory
    # ChromaDB), with pymupdf4llm structure-aware extraction. This is GATED:
    # semantic mode is only used when ALL of the following hold, else the agent
    # transparently falls back to the extractive TF-IDF retriever:
    #   1. runbook_rag_semantic is True (this opt-in flag), AND
    #   2. the [rag-semantic] deps actually import, AND
    #   3. the LLM sidecar is opted-in (reasoning_mode == "llm") AND reachable
    #      on llm_base_url (a live /health probe succeeds).
    # Rationale: semantic retrieval pays off when an LLM then synthesizes the
    # hits into coherent next-steps; with no sidecar, the lighter extractive
    # path is the honest default. The index is held IN MEMORY only (no on-disk
    # Chroma sqlite volume) -- rebuilt from the local runbook store on startup.
    runbook_rag_semantic: bool = False
    # fastembed model name (ONNX, CPU). bge-small matches the ChatBOT project.
    runbook_rag_embed_model: str = "BAAI/bge-small-en-v1.5"

    # --- Service-area impact (scoped) ---
    # Path to the curated pod->service-area mapping workbook (xlsx). When set
    # AND the file exists, incidents gain a `service_area` field naming the
    # service area the affected pod belongs to + factual redundancy counts.
    # Unset/missing -> feature inert (no service_area attached). Read-only.
    service_area_map_path: str | None = None

    # --- Runbook query log ---
    # Records every runbook-retrieval attempt (not LLM calls -- this project
    # has no LLM call anywhere in the default extractive pipeline) so you can
    # see what's being asked and whether anything matched. A "negative"
    # entry is one with zero hits -- the signal for "write a runbook for this."
    runbook_query_log_max_entries: int = 1000

    # --- LLM (only used when reasoning_mode == "llm") ---
    # The LLM ONLY re-ranks & explains the rule-gathered hypotheses; it can
    # never invent a cause. It runs as a LOCAL llama.cpp server SIDECAR (no
    # internet, no public IP) serving a GGUF model (e.g. the Qwen2.5-1.5B GGUF
    # reused from ChatBOT). The agent reaches it over LOOPBACK only. On any
    # error/timeout/unavailable, reasoning transparently falls back to the
    # deterministic extractive order -- so enabling the LLM can never break or
    # change WHICH causes exist, only their order + a short explanation.
    llm_provider: str = "none"
    llm_model: str = "qwen2.5-1.5b-instruct"
    # Loopback base URL of the llama.cpp sidecar (OpenAI-compatible API).
    # 127.0.0.1 (NOT 0.0.0.0) matters on the --network host jumpserver so the
    # endpoint is not reachable by other users on that shared box.
    llm_base_url: str = "http://127.0.0.1:8090"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 512
    llm_temperature: float = 0.1

    # --- Incident capture (for offline precision/recall labeling later) ---
    # When a path is set, every incident (auto-detected OR webhook-posted) is
    # appended as one JSONL record capturing the INPUTS (alert + gathered
    # evidence + optional graph neighborhood) and the agent's OUTPUT (ranked
    # hypotheses + citations), plus an empty ``labels`` block a human fills in
    # later. OFF by default (empty path) -- safe to ship. Turn on at DEPLOY
    # time by setting RCA_INCIDENT_CAPTURE_PATH to a writable (ideally mounted)
    # file, e.g. RCA_INCIDENT_CAPTURE_PATH=/data/captures/incidents.jsonl
    #
    # NOTE: capture records include real log lines / object names from the
    # monitored namespace -- treat the file as SENSITIVE. Set
    # RCA_INCIDENT_CAPTURE_REDACT_LOGS=true to drop log bodies (keep reasons/
    # timestamps). RCA_INCIDENT_CAPTURE_INCLUDE_GRAPH toggles the neighborhood
    # snapshot (bigger records, but needed for full replay). A rolling cap of
    # RCA_INCIDENT_CAPTURE_MAX_RECORDS keeps the file bounded.
    incident_capture_path: str | None = None
    incident_capture_redact_logs: bool = False
    incident_capture_include_graph: bool = True
    incident_capture_max_records: int = 5000
    incident_capture_graph_radius: int = 2


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
