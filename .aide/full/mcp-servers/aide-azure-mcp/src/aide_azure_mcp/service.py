"""Bounded read-only Azure CLI access for the AIDE MCP surface."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}$")
ACR_NAME = re.compile(r"^[A-Za-z0-9]{5,50}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
METRIC_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.%/()-]{0,127}$")
SAFE_INTERVALS = {"PT1M", "PT5M", "PT15M", "PT30M", "PT1H"}
SAFE_AGGREGATIONS = {"Average", "Count", "Maximum", "Minimum", "Total"}
MAX_ERROR_CHARS = 2_000
MAX_RESULT_ITEMS = 200


class CommandRunner(Protocol):
    """Protocol used by the service and deterministic tests."""

    def run(
        self,
        args: list[str],
        subscription_id: str,
        *,
        include_subscription: bool = True,
    ) -> Any:
        """Run one allowlisted Azure CLI command and return decoded JSON."""


def _bounded_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    return text[:MAX_ERROR_CHARS]


@dataclass(frozen=True)
class AzureTarget:
    """Validated, project-local Azure observation boundary."""

    subscription_id: str
    tenant_id: str | None
    resource_group: str
    location: str | None
    foundry_resource: str | None
    container_registry: str | None
    activity_log_hours: int
    max_events: int
    metric_interval: str
    metric_window_hours: int

    @classmethod
    def load(cls, path: Path) -> AzureTarget:
        """Load and validate a target descriptor without accepting secrets."""
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"Azure target file is missing: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Azure target file is unreadable: {path}") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Azure target schema_version must be 1")
        forbidden = {
            "access_token",
            "api_key",
            "client_secret",
            "password",
            "refresh_token",
            "token",
        }
        if _contains_forbidden_key(value, forbidden):
            raise ValueError("Azure target file must not contain credentials")
        subscription = str(value.get("subscription_id", ""))
        if not GUID.fullmatch(subscription):
            raise ValueError("subscription_id must be an Azure subscription GUID")
        if set(subscription) <= {"0", "-"}:
            raise ValueError("replace the example subscription_id before use")
        tenant_value = value.get("tenant_id")
        tenant = str(tenant_value) if tenant_value else None
        if tenant and not GUID.fullmatch(tenant):
            raise ValueError("tenant_id must be an Entra tenant GUID when set")
        if tenant and set(tenant) <= {"0", "-"}:
            raise ValueError("replace or remove the example tenant_id before use")
        resource_group = str(value.get("resource_group", ""))
        if not RESOURCE_NAME.fullmatch(resource_group):
            raise ValueError("resource_group has an unsupported shape")
        foundry = _optional_name(value.get("foundry_resource"), "foundry_resource")
        registry_value = value.get("container_registry")
        registry = str(registry_value) if registry_value else None
        if registry and not ACR_NAME.fullmatch(registry):
            raise ValueError("container_registry has an unsupported shape")
        monitoring = value.get("monitoring", {})
        if not isinstance(monitoring, dict):
            raise ValueError("monitoring must be an object")
        hours = _bounded_int(monitoring.get("activity_log_hours", 1), 1, 24)
        max_events = _bounded_int(monitoring.get("max_events", 50), 1, 100)
        interval = str(monitoring.get("metric_interval", "PT5M")).upper()
        if interval not in SAFE_INTERVALS:
            raise ValueError("metric_interval is not allowlisted")
        metric_hours = _bounded_int(
            monitoring.get("metric_window_hours", 1), 1, 24
        )
        location_value = value.get("location")
        return cls(
            subscription_id=subscription.lower(),
            tenant_id=tenant.lower() if tenant else None,
            resource_group=resource_group,
            location=str(location_value) if location_value else None,
            foundry_resource=foundry,
            container_registry=registry,
            activity_log_hours=hours,
            max_events=max_events,
            metric_interval=interval,
            metric_window_hours=metric_hours,
        )

    @property
    def resource_prefix(self) -> str:
        """Return the only ARM resource prefix accepted for metric tools."""
        return (
            f"/subscriptions/{self.subscription_id}/resourcegroups/"
            f"{self.resource_group}/"
        ).lower()

    def public_summary(self) -> dict[str, object]:
        """Return target metadata that never includes identity or credentials."""
        return {
            "subscription_id": self.subscription_id,
            "tenant_id": self.tenant_id,
            "resource_group": self.resource_group,
            "location": self.location,
            "foundry_resource": self.foundry_resource,
            "container_registry": self.container_registry,
        }


def _contains_forbidden_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in forbidden
            or _contains_forbidden_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def _optional_name(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if not RESOURCE_NAME.fullmatch(text):
        raise ValueError(f"{field} has an unsupported shape")
    return text


def _bounded_int(value: object, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        message = f"expected an integer from {minimum} through {maximum}"
        raise ValueError(message) from exc
    if result < minimum or result > maximum:
        raise ValueError(f"expected an integer from {minimum} through {maximum}")
    return result


class AzureCli:
    """Subprocess adapter that invokes Azure CLI without a shell."""

    def __init__(self, executable: str | None = None, timeout: int = 60) -> None:
        self.executable = executable or shutil.which("az") or shutil.which("az.cmd")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def run(
        self,
        args: list[str],
        subscription_id: str,
        *,
        include_subscription: bool = True,
    ) -> Any:
        """Execute one already-validated command and decode its JSON output."""
        if not self.executable:
            raise RuntimeError("Azure CLI executable 'az' was not found")
        command = [self.executable, *args]
        if include_subscription:
            command.extend(["--subscription", subscription_id])
        command.extend(["--only-show-errors", "--output", "json"])
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            message = f"Azure CLI execution failed: {_bounded_text(exc)}"
            raise RuntimeError(message) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "Azure CLI returned an error"
            raise RuntimeError(_bounded_text(detail))
        if not completed.stdout.strip():
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Azure CLI did not return valid JSON") from exc


class AzureService:
    """Read-only Azure observation operations constrained to one target."""

    def __init__(
        self,
        target_path: Path,
        runner: CommandRunner | None = None,
    ) -> None:
        self.target_path = target_path
        self.runner = runner or AzureCli()
        self.target: AzureTarget | None = None
        self.configuration_error: str | None = None
        try:
            self.target = AzureTarget.load(target_path)
        except ValueError as exc:
            self.configuration_error = str(exc)

    @classmethod
    def from_environment(cls) -> AzureService:
        path = Path(
            os.environ.get(
                "AIDE_AZURE_TARGET_FILE", ".aide/local/azure-target.json"
            )
        )
        return cls(path)

    def status(self) -> dict[str, object]:
        """Report local readiness without attempting authentication or mutation."""
        problems = []
        if self.configuration_error:
            problems.append(self.configuration_error)
        available = getattr(self.runner, "available", True)
        if not available:
            problems.append("Azure CLI executable 'az' was not found")
        return {
            "status": "ready" if not problems else "blocked",
            "read_only": True,
            "target_file": self.target_path.as_posix(),
            "target": self.target.public_summary() if self.target else None,
            "azure_cli_available": bool(available),
            "authentication": "existing Azure CLI Microsoft Entra session",
            "problems": problems,
        }

    def verify_context(self) -> dict[str, object]:
        """Verify the current Entra session can read the configured subscription."""
        target = self._target()
        value = self.runner.run(
            ["account", "show"], target.subscription_id
        )
        account = value if isinstance(value, dict) else {}
        actual_subscription = str(account.get("id", "")).lower()
        actual_tenant = str(account.get("tenantId", "")).lower()
        problems = []
        if actual_subscription != target.subscription_id:
            problems.append("Azure CLI subscription does not match the target file")
        if target.tenant_id and actual_tenant != target.tenant_id:
            problems.append("Azure CLI tenant does not match the target file")
        return {
            "status": "verified" if not problems else "blocked",
            "subscription_id": actual_subscription or None,
            "subscription_name": account.get("name"),
            "tenant_id": actual_tenant or None,
            "environment": account.get("environmentName"),
            "state": account.get("state"),
            "problems": problems,
        }

    def list_resources(self, limit: int = 100) -> dict[str, object]:
        """List projected resource metadata in the configured resource group."""
        target = self._target()
        requested = _bounded_int(limit, 1, MAX_RESULT_ITEMS)
        value = self.runner.run(
            ["resource", "list", "--resource-group", target.resource_group],
            target.subscription_id,
        )
        items = value if isinstance(value, list) else []
        resources = []
        for item in items[:requested]:
            if not isinstance(item, dict):
                continue
            tags = item.get("tags")
            resources.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "kind": item.get("kind"),
                    "location": item.get("location"),
                    "tag_keys": sorted(tags)[:50] if isinstance(tags, dict) else [],
                }
            )
        return self._result("resources", resources, len(items), requested)

    def list_activity(
        self, hours: int | None = None, max_events: int | None = None
    ) -> dict[str, object]:
        """List projected Azure activity events for a bounded recent window."""
        target = self._target()
        window = _bounded_int(
            hours if hours is not None else target.activity_log_hours, 1, 24
        )
        limit = _bounded_int(
            max_events if max_events is not None else target.max_events, 1, 100
        )
        value = self.runner.run(
            [
                "monitor",
                "activity-log",
                "list",
                "--resource-group",
                target.resource_group,
                "--offset",
                f"{window}h",
                "--max-events",
                str(limit),
            ],
            target.subscription_id,
        )
        items = value if isinstance(value, list) else []
        events = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            events.append(
                {
                    "timestamp": item.get("eventTimestamp"),
                    "level": item.get("level"),
                    "status": _named_value(item.get("status")),
                    "sub_status": _named_value(item.get("subStatus")),
                    "operation": _named_value(item.get("operationName")),
                    "resource_id": item.get("resourceId"),
                    "resource_type": item.get("resourceType"),
                    "correlation_id": item.get("correlationId"),
                }
            )
        result = self._result("events", events, len(items), limit)
        result["window_hours"] = window
        return result

    def metric_definitions(
        self, resource_id: str, limit: int = 100
    ) -> dict[str, object]:
        """List bounded metric definitions for one in-scope ARM resource."""
        target = self._target()
        self._validate_resource_id(resource_id)
        requested = _bounded_int(limit, 1, MAX_RESULT_ITEMS)
        value = self.runner.run(
            ["monitor", "metrics", "list-definitions", "--resource", resource_id],
            target.subscription_id,
        )
        items = value if isinstance(value, list) else []
        definitions = []
        for item in items[:requested]:
            if not isinstance(item, dict):
                continue
            dimensions = item.get("dimensions")
            definitions.append(
                {
                    "name": _named_value(item.get("name")),
                    "namespace": item.get("namespace"),
                    "unit": item.get("unit"),
                    "primary_aggregation": item.get("primaryAggregationType"),
                    "dimensions": [
                        _named_value(dimension.get("name"))
                        for dimension in dimensions[:20]
                        if isinstance(dimension, dict)
                    ]
                    if isinstance(dimensions, list)
                    else [],
                }
            )
        return self._result("definitions", definitions, len(items), requested)

    def query_metrics(
        self,
        resource_id: str,
        metric_names: list[str],
        hours: int | None = None,
        interval: str | None = None,
        aggregation: str = "Average",
    ) -> dict[str, object]:
        """Query selected metrics with bounded duration and projected points."""
        target = self._target()
        self._validate_resource_id(resource_id)
        if not metric_names or len(metric_names) > 10:
            raise ValueError("metric_names must contain from 1 through 10 names")
        names = [str(name) for name in metric_names]
        if any(not METRIC_NAME.fullmatch(name) for name in names):
            raise ValueError("metric_names contains an unsupported value")
        window = _bounded_int(
            hours if hours is not None else target.metric_window_hours, 1, 24
        )
        grain = str(interval or target.metric_interval).upper()
        if grain not in SAFE_INTERVALS:
            raise ValueError("interval is not allowlisted")
        normalized_aggregation = aggregation.title()
        if normalized_aggregation not in SAFE_AGGREGATIONS:
            raise ValueError("aggregation is not allowlisted")
        value = self.runner.run(
            [
                "monitor",
                "metrics",
                "list",
                "--resource",
                resource_id,
                "--metrics",
                *names,
                "--offset",
                f"{window}h",
                "--interval",
                grain,
                "--aggregation",
                normalized_aggregation,
            ],
            target.subscription_id,
        )
        raw_metrics = value.get("value", []) if isinstance(value, dict) else []
        metrics = [_project_metric(item) for item in raw_metrics[:10]]
        return {
            "status": "observed",
            "resource_id": resource_id,
            "window_hours": window,
            "interval": grain,
            "aggregation": normalized_aggregation,
            "metrics": metrics,
            "truncated": len(raw_metrics) > 10,
        }

    def foundry_deployments(self, limit: int = 100) -> dict[str, object]:
        """List safe deployment metadata for the configured Foundry account."""
        target = self._target()
        if not target.foundry_resource:
            raise ValueError("foundry_resource is not configured")
        requested = _bounded_int(limit, 1, 100)
        value = self.runner.run(
            [
                "cognitiveservices",
                "account",
                "deployment",
                "list",
                "--resource-group",
                target.resource_group,
                "--name",
                target.foundry_resource,
            ],
            target.subscription_id,
        )
        items = value if isinstance(value, list) else []
        deployments = []
        for item in items[:requested]:
            if not isinstance(item, dict):
                continue
            properties = item.get("properties", {})
            properties = properties if isinstance(properties, dict) else {}
            model = properties.get("model", {})
            model = model if isinstance(model, dict) else {}
            sku = item.get("sku", {})
            sku = sku if isinstance(sku, dict) else {}
            deployments.append(
                {
                    "name": item.get("name"),
                    "provisioning_state": properties.get("provisioningState"),
                    "model": {
                        "format": model.get("format"),
                        "name": model.get("name"),
                        "version": model.get("version"),
                    },
                    "sku": {"name": sku.get("name"), "capacity": sku.get("capacity")},
                    "version_upgrade_option": properties.get("versionUpgradeOption"),
                }
            )
        return self._result("deployments", deployments, len(items), requested)

    def acr_repositories(self, limit: int = 100) -> dict[str, object]:
        """List repository names from the configured Azure Container Registry."""
        target = self._target()
        if not target.container_registry:
            raise ValueError("container_registry is not configured")
        requested = _bounded_int(limit, 1, 100)
        value = self.runner.run(
            [
                "acr",
                "repository",
                "list",
                "--name",
                target.container_registry,
                "--top",
                str(requested),
            ],
            target.subscription_id,
        )
        items = value if isinstance(value, list) else []
        repositories = [str(item) for item in items[:requested]]
        return self._result("repositories", repositories, len(items), requested)

    def acr_tags(self, repository: str, limit: int = 30) -> dict[str, object]:
        """List recent tag names for one repository in the configured ACR."""
        target = self._target()
        if not target.container_registry:
            raise ValueError("container_registry is not configured")
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("repository has an unsupported shape")
        requested = _bounded_int(limit, 1, 100)
        value = self.runner.run(
            [
                "acr",
                "repository",
                "show-tags",
                "--name",
                target.container_registry,
                "--repository",
                repository,
                "--top",
                str(requested),
                "--orderby",
                "time_desc",
            ],
            target.subscription_id,
        )
        items = value if isinstance(value, list) else []
        tags = [str(item) for item in items[:requested]]
        return self._result("tags", tags, len(items), requested)

    def _target(self) -> AzureTarget:
        if not self.target:
            raise ValueError(self.configuration_error or "Azure target is unavailable")
        return self.target

    def _validate_resource_id(self, resource_id: str) -> None:
        target = self._target()
        normalized = str(resource_id).lower()
        if not normalized.startswith(target.resource_prefix):
            raise ValueError(
                "resource_id must belong to the configured subscription and "
                "resource group"
            )
        if len(resource_id) > 2_048 or any(char in resource_id for char in "\r\n"):
            raise ValueError("resource_id has an unsupported shape")

    @staticmethod
    def _result(
        key: str, items: list[object], observed_count: int, limit: int
    ) -> dict[str, object]:
        return {
            "status": "observed",
            key: items,
            "returned_count": len(items),
            "observed_count": observed_count,
            "limit": limit,
            "truncated": observed_count > len(items),
        }


def _named_value(value: object) -> object:
    if isinstance(value, dict):
        return value.get("localizedValue") or value.get("value")
    return value


def _project_metric(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    projected_series = []
    timeseries = value.get("timeseries", [])
    if isinstance(timeseries, list):
        for series in timeseries[:20]:
            if not isinstance(series, dict):
                continue
            points_value = series.get("data", [])
            points = points_value if isinstance(points_value, list) else []
            projected_series.append(
                {
                    "metadata": series.get("metadatavalues", [])[:20]
                    if isinstance(series.get("metadatavalues"), list)
                    else [],
                    "data": [
                        {
                            key: point.get(key)
                            for key in (
                                "timeStamp",
                                "average",
                                "count",
                                "maximum",
                                "minimum",
                                "total",
                            )
                            if point.get(key) is not None
                        }
                        for point in points[:300]
                        if isinstance(point, dict)
                    ],
                    "truncated": len(points) > 300,
                }
            )
    return {
        "name": _named_value(value.get("name")),
        "unit": value.get("unit"),
        "timeseries": projected_series,
        "truncated": isinstance(timeseries, list) and len(timeseries) > 20,
    }
