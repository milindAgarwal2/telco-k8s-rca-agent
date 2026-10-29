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

    # --- Runbook query log ---
    # Records every runbook-retrieval attempt (not LLM calls -- this project
    # has no LLM call anywhere in the default extractive pipeline) so you can
    # see what's being asked and whether anything matched. A "negative"
    # entry is one with zero hits -- the signal for "write a runbook for this."
    runbook_query_log_max_entries: int = 1000

    # --- LLM (only used when reasoning_mode == "llm") ---
    llm_provider: str = "none"
    llm_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
