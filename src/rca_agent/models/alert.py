"""Input schemas for detection sources: Alertmanager webhooks and K8s events."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Alert(BaseModel):
    """A single Alertmanager alert (subset of the v4 webhook schema)."""

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None

    model_config = {"populate_by_name": True}

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "UnknownAlert")

    @property
    def namespace(self) -> str | None:
        return self.labels.get("namespace")

    @property
    def target(self) -> str | None:
        """Best-effort affected resource (pod > deployment > service > job)."""
        for key in ("pod", "deployment", "statefulset", "service", "job", "instance"):
            if key in self.labels:
                return self.labels[key]
        return None


class AlertmanagerPayload(BaseModel):
    """Top-level Alertmanager webhook payload (v4)."""

    version: str = "4"
    group_key: str | None = Field(default=None, alias="groupKey")
    status: str = "firing"
    receiver: str | None = None
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(
        default_factory=dict, alias="commonAnnotations"
    )
    external_url: str | None = Field(default=None, alias="externalURL")
    alerts: list[Alert] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class KubeEvent(BaseModel):
    """A normalized Kubernetes event (CrashLoopBackOff, OOMKilled, etc.)."""

    reason: str
    message: str = ""
    kind: str | None = None  # involved object kind
    name: str | None = None  # involved object name
    namespace: str | None = None
    event_type: str = "Warning"  # Normal | Warning
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    count: int = 1
    raw: dict[str, Any] = Field(default_factory=dict)

    # Event reasons that the agent treats as fault signals.
    FAULT_REASONS: tuple[str, ...] = (
        "CrashLoopBackOff",
        "OOMKilled",
        "ImagePullBackOff",
        "ErrImagePull",
        "FailedScheduling",
        "Unhealthy",
        "FailedMount",
        "NodeNotReady",
        "Evicted",
    )

    @property
    def is_fault_signal(self) -> bool:
        return self.reason in self.FAULT_REASONS or self.event_type == "Warning"
