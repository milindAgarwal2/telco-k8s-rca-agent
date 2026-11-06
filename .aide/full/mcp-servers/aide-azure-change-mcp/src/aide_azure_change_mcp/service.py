"""Plan-bound Azure resource-group deployment service."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}$")
DEPLOYMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,63}$")
RESOURCE_TYPE = re.compile(
    r"^[A-Za-z0-9.]+/[A-Za-z0-9.]+(?:/[A-Za-z0-9.]+)*$"
)
PLAN_ID = re.compile(r"^[a-f0-9]{32}$")
SAFE_CHANGE_TYPES = {"create", "modify", "nochange", "ignore"}
MAX_ERROR_CHARS = 2_000


class CommandRunner(Protocol):
    """Protocol used by the service and deterministic tests."""

    def run(self, args: list[str], subscription_id: str) -> Any:
        """Run one fixed Azure CLI command and return decoded JSON."""


def _bounded_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    return text[:MAX_ERROR_CHARS]


def _contains_forbidden_key(value: object) -> bool:
    forbidden = {
        "access_token",
        "api_key",
        "client_secret",
        "password",
        "refresh_token",
        "token",
    }
    if isinstance(value, dict):
        return any(
            str(key).lower() in forbidden or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} file is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if _contains_forbidden_key(value):
        raise ValueError(f"{label} must not contain credentials")
    return value


def _bounded_int(value: object, minimum: int, maximum: int, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}"
        ) from exc
    if result < minimum or result > maximum:
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}"
        )
    return result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Azure change plan has an invalid timestamp") from exc


@dataclass(frozen=True)
class AzureTarget:
    """Validated resource-group deployment boundary."""

    subscription_id: str
    tenant_id: str | None
    resource_group: str
    location: str | None

    @classmethod
    def load(cls, path: Path) -> AzureTarget:
        value = _load_json(path, "Azure target")
        if value.get("schema_version") != 1:
            raise ValueError("Azure target schema_version must be 1")
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
        location = str(value.get("location", "")) or None
        return cls(
            subscription_id=subscription.lower(),
            tenant_id=tenant.lower() if tenant else None,
            resource_group=resource_group,
            location=location,
        )

    @property
    def resource_prefix(self) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourcegroups/"
            f"{self.resource_group}/"
        ).lower()

    def summary(self) -> dict[str, object]:
        return {
            "subscription_id": self.subscription_id,
            "tenant_id": self.tenant_id,
            "resource_group": self.resource_group,
            "location": self.location,
        }


@dataclass(frozen=True)
class ChangePolicy:
    """Local fail-closed mutation policy."""

    enabled: bool
    template_roots: tuple[str, ...]
    allowed_resource_types: frozenset[str]
    allow_create: bool
    allow_modify: bool
    max_changes: int
    plan_ttl_minutes: int

    @classmethod
    def load(cls, path: Path) -> ChangePolicy:
        value = _load_json(path, "Azure change policy")
        if value.get("schema_version") != 1:
            raise ValueError("Azure change policy schema_version must be 1")
        enabled = value.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("Azure change policy enabled must be true or false")
        roots = value.get("template_roots", [])
        if not isinstance(roots, list) or not roots:
            raise ValueError("template_roots must contain reviewed directories")
        normalized_roots = []
        for item in roots:
            root = PurePosixPath(str(item).replace("\\", "/"))
            if root.is_absolute() or ".." in root.parts or str(root) in {"", "."}:
                raise ValueError("template_roots must be safe workspace paths")
            normalized_roots.append(root.as_posix().rstrip("/"))
        types = value.get("allowed_resource_types", [])
        if not isinstance(types, list):
            raise ValueError("allowed_resource_types must be an array")
        normalized_types = frozenset(str(item).lower() for item in types)
        if enabled and not normalized_types:
            raise ValueError(
                "enabled Azure change policy needs allowed_resource_types"
            )
        if any(not RESOURCE_TYPE.fullmatch(str(item)) for item in types):
            raise ValueError("allowed_resource_types contains an invalid type")
        return cls(
            enabled=enabled,
            template_roots=tuple(dict.fromkeys(normalized_roots)),
            allowed_resource_types=normalized_types,
            allow_create=value.get("allow_create") is True,
            allow_modify=value.get("allow_modify") is True,
            max_changes=_bounded_int(
                value.get("max_changes", 20), 1, 100, "max_changes"
            ),
            plan_ttl_minutes=_bounded_int(
                value.get("plan_ttl_minutes", 30),
                5,
                240,
                "plan_ttl_minutes",
            ),
        )

    def summary(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "template_roots": list(self.template_roots),
            "allowed_resource_types": sorted(self.allowed_resource_types),
            "allow_create": self.allow_create,
            "allow_modify": self.allow_modify,
            "max_changes": self.max_changes,
            "plan_ttl_minutes": self.plan_ttl_minutes,
            "deployment_mode": "Incremental",
        }


class AzureCli:
    """Subprocess adapter for fixed Azure CLI deployment commands."""

    def __init__(self, executable: str | None = None, timeout: int = 600) -> None:
        self.executable = executable or shutil.which("az") or shutil.which("az.cmd")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def run(self, args: list[str], subscription_id: str) -> Any:
        if not self.executable:
            raise RuntimeError("Azure CLI executable 'az' was not found")
        command = [
            self.executable,
            *args,
            "--subscription",
            subscription_id,
            "--only-show-errors",
            "--output",
            "json",
        ]
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
            raise RuntimeError(
                f"Azure CLI execution failed: {_bounded_text(exc)}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "Azure CLI returned an error"
            raise RuntimeError(_bounded_text(detail))
        if not completed.stdout.strip():
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Azure CLI did not return valid JSON") from exc


class AzureChangeService:
    """Validate, plan, and apply one bounded incremental Azure deployment."""

    def __init__(
        self,
        workspace_root: Path,
        target_path: Path,
        policy_path: Path,
        plan_directory: Path,
        runner: CommandRunner | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.target_path = target_path
        self.policy_path = policy_path
        self.plan_directory = plan_directory
        self.runner = runner or AzureCli()
        self.target: AzureTarget | None = None
        self.policy: ChangePolicy | None = None
        self.configuration_errors: list[str] = []
        try:
            self.target = AzureTarget.load(target_path)
        except ValueError as exc:
            self.configuration_errors.append(str(exc))
        try:
            self.policy = ChangePolicy.load(policy_path)
        except ValueError as exc:
            self.configuration_errors.append(str(exc))

    @classmethod
    def from_environment(cls) -> AzureChangeService:
        workspace = Path(os.environ.get("AIDE_WORKSPACE_ROOT", "."))
        return cls(
            workspace,
            Path(
                os.environ.get(
                    "AIDE_AZURE_TARGET_FILE", ".aide/local/azure-target.json"
                )
            ),
            Path(
                os.environ.get(
                    "AIDE_AZURE_CHANGE_POLICY_FILE",
                    ".aide/local/azure-change-policy.json",
                )
            ),
            Path(
                os.environ.get(
                    "AIDE_AZURE_CHANGE_PLAN_DIR",
                    ".aide/local/azure-change-plans",
                )
            ),
        )

    def status(self) -> dict[str, object]:
        problems = list(self.configuration_errors)
        if self.policy and not self.policy.enabled:
            problems.append("Azure change policy is disabled")
        available = getattr(self.runner, "available", True)
        if not available:
            problems.append("Azure CLI executable 'az' was not found")
        return {
            "status": "ready" if not problems else "blocked",
            "read_only": False,
            "mutation_mode": "plan-bound incremental resource-group deployment",
            "target": self.target.summary() if self.target else None,
            "policy": self.policy.summary() if self.policy else None,
            "target_file": self.target_path.as_posix(),
            "policy_file": self.policy_path.as_posix(),
            "plan_directory": self.plan_directory.as_posix(),
            "azure_cli_available": bool(available),
            "authentication": "existing Azure CLI Microsoft Entra session",
            "problems": problems,
        }

    def validate_deployment(
        self, template_path: str, parameters_path: str | None = None
    ) -> dict[str, object]:
        target, policy = self._ready()
        template = self._workspace_file(
            template_path, {".bicep", ".json"}, policy
        )
        parameters = (
            self._workspace_file(parameters_path, {".json"}, policy)
            if parameters_path
            else None
        )
        if template.suffix.lower() == ".json":
            value = _load_json(template, "ARM template")
            if "$schema" not in value or "resources" not in value:
                raise ValueError("JSON template is not an ARM deployment template")
        return {
            "status": "validated",
            "target": target.summary(),
            "deployment_mode": "Incremental",
            "template_path": template.relative_to(self.workspace_root).as_posix(),
            "template_sha256": _hash_file(template),
            "parameters_path": (
                parameters.relative_to(self.workspace_root).as_posix()
                if parameters
                else None
            ),
            "parameters_sha256": _hash_file(parameters) if parameters else None,
            "policy": policy.summary(),
        }

    def plan_deployment(
        self,
        template_path: str,
        parameters_path: str | None = None,
        deployment_name: str | None = None,
    ) -> dict[str, object]:
        target, policy = self._ready()
        validated = self.validate_deployment(template_path, parameters_path)
        self._verify_context(target)
        template = self.workspace_root / str(validated["template_path"])
        parameter_value = validated["parameters_path"]
        parameters = (
            self.workspace_root / str(parameter_value) if parameter_value else None
        )
        name = deployment_name or self._deployment_name(
            str(validated["template_sha256"])
        )
        if not DEPLOYMENT_NAME.fullmatch(name):
            raise ValueError("deployment_name has an unsupported shape")
        args = [
            "deployment",
            "group",
            "what-if",
            "--resource-group",
            target.resource_group,
            "--name",
            name,
            "--template-file",
            str(template),
            "--mode",
            "Incremental",
            "--result-format",
            "ResourceIdOnly",
            "--validation-level",
            "Provider",
            "--no-pretty-print",
        ]
        if parameters:
            args.extend(["--parameters", f"@{parameters}"])
        result = self.runner.run(args, target.subscription_id)
        if _hash_file(template) != validated["template_sha256"]:
            raise ValueError("Azure template changed during What-If")
        if parameters and _hash_file(parameters) != validated["parameters_sha256"]:
            raise ValueError("Azure parameters changed during What-If")
        changes = self._validate_changes(result, target, policy)
        active = [item for item in changes if item["change_type"] != "NoChange"]
        now = _utc_now()
        plan_id = secrets.token_hex(16)
        receipt = {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "planned" if active else "no_changes",
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(minutes=policy.plan_ttl_minutes)),
            "subscription_id": target.subscription_id,
            "tenant_id": target.tenant_id,
            "resource_group": target.resource_group,
            "deployment_name": name,
            "deployment_mode": "Incremental",
            "template_path": validated["template_path"],
            "template_sha256": validated["template_sha256"],
            "parameters_path": validated["parameters_path"],
            "parameters_sha256": validated["parameters_sha256"],
            "target_sha256": _hash_file(self.target_path),
            "policy_sha256": _hash_file(self.policy_path),
            "changes": changes,
            "active_change_count": len(active),
        }
        self._write_receipt(receipt)
        return self._public_plan(receipt)

    def apply_deployment(self, plan_id: str, confirmation: str) -> dict[str, object]:
        target, policy = self._ready()
        receipt = self._load_receipt(plan_id)
        if receipt.get("status") != "planned":
            raise ValueError("Azure change plan is not in planned state")
        if confirmation != f"APPLY {plan_id}":
            raise ValueError(f"confirmation must exactly equal APPLY {plan_id}")
        if _utc_now() >= _parse_time(receipt.get("expires_at")):
            raise ValueError("Azure change plan has expired; run What-If again")
        self._validate_receipt_binding(receipt, target, policy)
        self._verify_context(target)
        template = self.workspace_root / str(receipt["template_path"])
        parameter_value = receipt.get("parameters_path")
        parameters = (
            self.workspace_root / str(parameter_value)
            if parameter_value
            else None
        )
        args = [
            "deployment",
            "group",
            "create",
            "--resource-group",
            target.resource_group,
            "--name",
            str(receipt["deployment_name"]),
            "--template-file",
            str(template),
            "--mode",
            "Incremental",
        ]
        if parameters:
            args.extend(["--parameters", f"@{parameters}"])
        receipt["apply_started_at"] = _iso(_utc_now())
        receipt["status"] = "applying"
        self._write_receipt(receipt)
        try:
            result = self.runner.run(args, target.subscription_id)
        except Exception as exc:
            receipt["status"] = "outcome_unknown"
            receipt["last_error"] = _bounded_text(exc)
            receipt["updated_at"] = _iso(_utc_now())
            self._write_receipt(receipt)
            raise RuntimeError(
                "Azure deployment outcome is unknown; inspect the saved plan "
                "with the deployment-status tool before any retry"
            ) from exc
        properties = result.get("properties", {}) if isinstance(result, dict) else {}
        properties = properties if isinstance(properties, dict) else {}
        state = str(properties.get("provisioningState", ""))
        receipt["status"] = (
            "applied" if state.lower() == "succeeded" else "outcome_unknown"
        )
        receipt["updated_at"] = _iso(_utc_now())
        receipt["provisioning_state"] = state or None
        receipt["correlation_id"] = properties.get("correlationId")
        self._write_receipt(receipt)
        return {
            "status": receipt["status"],
            "plan_id": plan_id,
            "deployment_name": receipt["deployment_name"],
            "deployment_mode": "Incremental",
            "provisioning_state": state or None,
            "correlation_id": properties.get("correlationId"),
            "next_action": (
                "review deployment status and evidence"
                if receipt["status"] == "applied"
                else "inspect deployment status; do not retry blindly"
            ),
        }

    def deployment_status(self, plan_id: str) -> dict[str, object]:
        target, _ = self._configured()
        receipt = self._load_receipt(plan_id)
        if receipt.get("subscription_id") != target.subscription_id or receipt.get(
            "resource_group"
        ) != target.resource_group:
            raise ValueError("Azure change plan target no longer matches configuration")
        if receipt.get("status") in {"planned", "no_changes"}:
            return {
                "status": receipt["status"],
                "plan_id": plan_id,
                "deployment_name": receipt["deployment_name"],
                "remote_checked": False,
            }
        self._verify_context(target)
        result = self.runner.run(
            [
                "deployment",
                "group",
                "show",
                "--resource-group",
                target.resource_group,
                "--name",
                str(receipt["deployment_name"]),
            ],
            target.subscription_id,
        )
        properties = result.get("properties", {}) if isinstance(result, dict) else {}
        properties = properties if isinstance(properties, dict) else {}
        return {
            "status": "observed",
            "plan_id": plan_id,
            "local_plan_status": receipt.get("status"),
            "deployment_name": receipt["deployment_name"],
            "provisioning_state": properties.get("provisioningState"),
            "timestamp": properties.get("timestamp"),
            "correlation_id": properties.get("correlationId"),
            "remote_checked": True,
        }

    def _configured(self) -> tuple[AzureTarget, ChangePolicy]:
        if self.configuration_errors or not self.target or not self.policy:
            raise ValueError("; ".join(self.configuration_errors) or "not configured")
        return self.target, self.policy

    def _ready(self) -> tuple[AzureTarget, ChangePolicy]:
        target, policy = self._configured()
        if not policy.enabled:
            raise ValueError("Azure change policy is disabled")
        if not getattr(self.runner, "available", True):
            raise ValueError("Azure CLI executable 'az' was not found")
        return target, policy

    def _workspace_file(
        self, raw: str, suffixes: set[str], policy: ChangePolicy
    ) -> Path:
        value = PurePosixPath(str(raw).replace("\\", "/"))
        if value.is_absolute() or ".." in value.parts or str(value) in {"", "."}:
            raise ValueError("deployment paths must be safe workspace-relative files")
        candidate = self.workspace_root.joinpath(*value.parts)
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(self.workspace_root).as_posix()
        except (OSError, ValueError) as exc:
            raise ValueError(
                "deployment file is missing or outside the workspace"
            ) from exc
        if not resolved.is_file() or resolved.suffix.lower() not in suffixes:
            raise ValueError("deployment file has an unsupported type")
        if not any(
            relative == root or relative.startswith(root + "/")
            for root in policy.template_roots
        ):
            raise ValueError("deployment file is outside approved template_roots")
        return resolved

    def _verify_context(self, target: AzureTarget) -> None:
        value = self.runner.run(["account", "show"], target.subscription_id)
        account = value if isinstance(value, dict) else {}
        if str(account.get("id", "")).lower() != target.subscription_id:
            raise ValueError("Azure CLI subscription does not match the target")
        actual_tenant = str(account.get("tenantId", "")).lower()
        if target.tenant_id and actual_tenant != target.tenant_id:
            raise ValueError("Azure CLI tenant does not match the target")
        if str(account.get("state", "")).lower() != "enabled":
            raise ValueError("Azure CLI subscription is not enabled")

    def _validate_changes(
        self, value: object, target: AzureTarget, policy: ChangePolicy
    ) -> list[dict[str, str]]:
        raw = value.get("changes") if isinstance(value, dict) else None
        if not isinstance(raw, list):
            raise ValueError("Azure What-If did not return a changes array")
        changes = []
        active = 0
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Azure What-If returned an invalid change")
            resource_id = str(item.get("resourceId", ""))
            change = str(item.get("changeType", "")).lower()
            if change not in SAFE_CHANGE_TYPES:
                raise ValueError(f"Azure change type is blocked: {change or 'unknown'}")
            if not resource_id.lower().startswith(target.resource_prefix):
                raise ValueError("Azure What-If includes an out-of-scope resource")
            if change == "ignore":
                continue
            resource_type = _resource_type(resource_id)
            if resource_type.lower() not in policy.allowed_resource_types:
                raise ValueError(
                    f"Azure resource type is not allowlisted: {resource_type}"
                )
            if change == "create" and not policy.allow_create:
                raise ValueError("Azure create changes are disabled by policy")
            if change == "modify" and not policy.allow_modify:
                raise ValueError("Azure modify changes are disabled by policy")
            normalized = "NoChange" if change == "nochange" else change.title()
            changes.append(
                {
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "change_type": normalized,
                }
            )
            if change != "nochange":
                active += 1
        if active > policy.max_changes:
            raise ValueError("Azure What-If exceeds the maximum allowed changes")
        return changes

    def _validate_receipt_binding(
        self,
        receipt: dict[str, Any],
        target: AzureTarget,
        policy: ChangePolicy,
    ) -> None:
        if receipt.get("deployment_mode") != "Incremental":
            raise ValueError("only Incremental Azure deployments are allowed")
        if receipt.get("subscription_id") != target.subscription_id or receipt.get(
            "resource_group"
        ) != target.resource_group:
            raise ValueError("Azure change plan target has changed")
        if receipt.get("target_sha256") != _hash_file(self.target_path):
            raise ValueError("Azure target changed after What-If")
        if receipt.get("policy_sha256") != _hash_file(self.policy_path):
            raise ValueError("Azure change policy changed after What-If")
        template = self._workspace_file(
            str(receipt.get("template_path", "")), {".bicep", ".json"}, policy
        )
        if receipt.get("template_sha256") != _hash_file(template):
            raise ValueError("Azure deployment template changed after What-If")
        parameter_value = receipt.get("parameters_path")
        if parameter_value:
            parameters = self._workspace_file(str(parameter_value), {".json"}, policy)
            if receipt.get("parameters_sha256") != _hash_file(parameters):
                raise ValueError("Azure parameters changed after What-If")
        elif receipt.get("parameters_sha256") is not None:
            raise ValueError("Azure parameter binding is inconsistent")
        if int(receipt.get("active_change_count", 0)) < 1:
            raise ValueError("Azure change plan has no active changes")

    def _plan_root(self) -> Path:
        candidate = (
            self.plan_directory
            if self.plan_directory.is_absolute()
            else self.workspace_root / self.plan_directory
        )
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError(
                "Azure change plan directory is outside the workspace"
            ) from exc
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _write_receipt(self, value: dict[str, Any]) -> None:
        plan_id = str(value.get("plan_id", ""))
        if not PLAN_ID.fullmatch(plan_id):
            raise ValueError("Azure change plan ID is invalid")
        path = self._plan_root() / f"{plan_id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    def _load_receipt(self, plan_id: str) -> dict[str, Any]:
        if not PLAN_ID.fullmatch(plan_id):
            raise ValueError("Azure change plan ID is invalid")
        value = _load_json(self._plan_root() / f"{plan_id}.json", "Azure change plan")
        if value.get("schema_version") != 1 or value.get("plan_id") != plan_id:
            raise ValueError("Azure change plan is invalid")
        return value

    @staticmethod
    def _deployment_name(template_hash: str) -> str:
        timestamp = _utc_now().strftime("%Y%m%d%H%M%S")
        return f"aide-{timestamp}-{template_hash[:8]}"

    @staticmethod
    def _public_plan(receipt: dict[str, Any]) -> dict[str, object]:
        return {
            key: receipt[key]
            for key in (
                "status",
                "plan_id",
                "created_at",
                "expires_at",
                "subscription_id",
                "tenant_id",
                "resource_group",
                "deployment_name",
                "deployment_mode",
                "template_path",
                "template_sha256",
                "parameters_path",
                "parameters_sha256",
                "changes",
                "active_change_count",
            )
        }


def _resource_type(resource_id: str) -> str:
    parts = [part for part in resource_id.strip("/").split("/") if part]
    lowered = [part.lower() for part in parts]
    try:
        index = lowered.index("providers")
    except ValueError as exc:
        raise ValueError("Azure resource ID has no provider segment") from exc
    tail = parts[index + 1 :]
    if len(tail) < 3 or len(tail) % 2 == 0:
        raise ValueError("Azure resource ID has an unsupported shape")
    return "/".join([tail[0], *tail[1::2]])
