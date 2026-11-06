"""Plan-bound namespaced Kubernetes server-side apply operations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?$")
CONTEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,252}$")
KIND = re.compile(r"^[A-Za-z][A-Za-z0-9.]{0,127}$")
PLAN_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_MANIFEST_BYTES = 1_048_576
MAX_ERROR_CHARS = 2_000
FORBIDDEN_KINDS = {
    "APIService",
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "Namespace",
    "Node",
    "PersistentVolume",
    "Secret",
    "StorageClass",
    "ValidatingWebhookConfiguration",
}


def _bounded_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*\S+", r"\1=[REDACTED]", text
    )
    return text[:MAX_ERROR_CHARS]


def _contains_forbidden_key(value: object) -> bool:
    forbidden = {
        "authorization",
        "client_certificate_data",
        "client_key_data",
        "password",
        "secret",
        "token",
        "username",
    }
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _integer(value: object, minimum: int, maximum: int, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be from {minimum} through {maximum}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kubeconfig_fingerprint(raw: str, context: str, namespace: str) -> str:
    digest = hashlib.sha256()
    digest.update(context.encode("utf-8"))
    digest.update(b"\0")
    digest.update(namespace.encode("utf-8"))
    for value in raw.split(os.pathsep):
        if not value.strip():
            continue
        path = Path(value).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("KUBECONFIG contains an unreadable path") from exc
        if not resolved.is_file():
            raise ValueError("KUBECONFIG must reference regular files")
        try:
            content = resolved.read_bytes()
        except OSError as exc:
            raise ValueError("KUBECONFIG contains an unreadable path") from exc
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} file is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError(f"{label} schema_version must be 1")
    return value


@dataclass(frozen=True)
class KubernetesTarget:
    context: str
    namespace: str
    source: str = "target-file"
    fingerprint: str = ""

    @classmethod
    def load(cls, path: Path) -> KubernetesTarget:
        value = _read_json(path, "Kubernetes target")
        if _contains_forbidden_key(value):
            raise ValueError("Kubernetes target file must not contain credentials")
        context = str(value.get("context", ""))
        namespace = str(value.get("namespace", ""))
        if not CONTEXT.fullmatch(context) or context == "example-context":
            raise ValueError("context is missing, example, or unsupported")
        if not NAME.fullmatch(namespace) or namespace == "example-namespace":
            raise ValueError("namespace is missing, example, or unsupported")
        return cls(
            context=context,
            namespace=namespace,
            source="target-file",
            fingerprint=_sha256(path),
        )

    def summary(self) -> dict[str, str]:
        return {
            "context": self.context,
            "namespace": self.namespace,
            "source": self.source,
        }


@dataclass(frozen=True)
class KubernetesChangePolicy:
    enabled: bool
    manifest_roots: tuple[str, ...]
    allowed_kinds: frozenset[str]
    allow_create: bool
    allow_update: bool
    max_objects: int
    plan_ttl_minutes: int
    field_manager: str

    @classmethod
    def load(cls, path: Path) -> KubernetesChangePolicy:
        value = _read_json(path, "Kubernetes change policy")
        if _contains_forbidden_key(value):
            raise ValueError("Kubernetes change policy must not contain credentials")
        roots = value.get("manifest_roots")
        kinds = value.get("allowed_kinds")
        if (
            not isinstance(roots, list)
            or not roots
            or any(not str(item).strip() for item in roots)
        ):
            raise ValueError("manifest_roots must be a non-empty list")
        enabled = value.get("enabled") is True
        if not isinstance(kinds, list) or (enabled and not kinds):
            raise ValueError(
                "allowed_kinds must be a non-empty list when policy is enabled"
            )
        normalized = frozenset(str(item) for item in kinds)
        if any(not KIND.fullmatch(item) for item in normalized):
            raise ValueError("allowed_kinds contains an unsupported value")
        blocked = normalized & FORBIDDEN_KINDS
        if blocked:
            raise ValueError(
                "allowed_kinds contains forbidden cluster/security kinds: "
                + ", ".join(sorted(blocked))
            )
        manager = str(value.get("field_manager", "aide-baseline"))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", manager):
            raise ValueError("field_manager has an unsupported shape")
        return cls(
            enabled=enabled,
            manifest_roots=tuple(
                str(item).replace("\\", "/").strip("/") for item in roots
            ),
            allowed_kinds=normalized,
            allow_create=value.get("allow_create") is True,
            allow_update=value.get("allow_update") is True,
            max_objects=_integer(value.get("max_objects", 10), 1, 50, "max_objects"),
            plan_ttl_minutes=_integer(
                value.get("plan_ttl_minutes", 30), 5, 120, "plan_ttl_minutes"
            ),
            field_manager=manager,
        )

    def summary(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "manifest_roots": list(self.manifest_roots),
            "allowed_kinds": sorted(self.allowed_kinds),
            "allow_create": self.allow_create,
            "allow_update": self.allow_update,
            "max_objects": self.max_objects,
            "plan_ttl_minutes": self.plan_ttl_minutes,
            "field_manager": self.field_manager,
        }


class CommandRunner(Protocol):
    available: bool

    def run(self, args: list[str], target: KubernetesTarget) -> Any:
        """Run one fixed kubectl command."""

    def discover_target(self) -> KubernetesTarget:
        """Resolve the active kubeconfig context and namespace."""


class Kubectl:
    def __init__(self, executable: str | None = None, timeout: int = 300) -> None:
        self.executable = (
            executable or shutil.which("kubectl") or shutil.which("kubectl.exe")
        )
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def run(self, args: list[str], target: KubernetesTarget) -> Any:
        if not self.executable:
            raise RuntimeError("kubectl executable was not found")
        command = [
            self.executable,
            *args,
            "--context",
            target.context,
            "--namespace",
            target.namespace,
            "--output",
            "json",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"kubectl execution failed: {_bounded_text(exc)}"
            ) from exc
        if completed.returncode != 0:
            raise RuntimeError(
                _bounded_text(completed.stderr.strip() or "kubectl returned an error")
            )
        return _decode_json_stream(completed.stdout)

    def discover_target(self) -> KubernetesTarget:
        """Resolve and fingerprint the active target from KUBECONFIG."""

        if not self.executable:
            raise ValueError("kubectl executable was not found")
        kubeconfig = os.environ.get("KUBECONFIG", "").strip()
        if not kubeconfig:
            raise ValueError(
                "KUBECONFIG is required when no Kubernetes target override exists"
            )
        context = self._config_value(["config", "current-context"])
        namespace = self._config_value(
            ["config", "view", "--minify", "--output", "jsonpath={..namespace}"]
        )
        namespace = namespace or "default"
        if not CONTEXT.fullmatch(context):
            raise ValueError("kubeconfig current context has an unsupported shape")
        if not NAME.fullmatch(namespace):
            raise ValueError("kubeconfig namespace has an unsupported shape")
        return KubernetesTarget(
            context=context,
            namespace=namespace,
            source="kubeconfig-current-context",
            fingerprint=_kubeconfig_fingerprint(kubeconfig, context, namespace),
        )

    def _config_value(self, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                [str(self.executable), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=min(self.timeout, 30),
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(
                f"kubectl configuration lookup failed: {_bounded_text(exc)}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "kubectl returned an error"
            raise ValueError(_bounded_text(detail))
        return completed.stdout.strip()


class KubernetesChangeService:
    def __init__(
        self,
        root: Path,
        target_path: Path,
        policy_path: Path,
        plan_dir: Path,
        runner: CommandRunner | None = None,
    ) -> None:
        self.root = root.resolve()
        self.target_path = target_path
        self.policy_path = policy_path
        self.plan_dir = plan_dir
        self.runner = runner or Kubectl()
        self.target: KubernetesTarget | None = None
        self.policy: KubernetesChangePolicy | None = None
        self.problems: list[str] = []
        try:
            if target_path.exists():
                self.target = KubernetesTarget.load(target_path)
            else:
                discover = getattr(self.runner, "discover_target", None)
                if not callable(discover):
                    raise ValueError(
                        "Kubernetes target override is missing and target discovery "
                        "is unavailable"
                    )
                self.target = discover()
        except ValueError as exc:
            self.problems.append(str(exc))
        try:
            self.policy = KubernetesChangePolicy.load(policy_path)
        except ValueError as exc:
            self.problems.append(str(exc))

    @classmethod
    def from_environment(cls) -> KubernetesChangeService:
        root = Path(os.environ.get("AIDE_WORKSPACE_ROOT", ".")).resolve()
        policy_override = os.environ.get("AIDE_KUBERNETES_CHANGE_POLICY_FILE", "")
        local_policy = root / ".aide/local/kubernetes-change-policy.json"
        packaged_policy = root / ".aide/templates/kubernetes-change-policy.example.json"
        policy_path = (
            Path(policy_override)
            if policy_override.strip()
            else local_policy
            if local_policy.exists()
            else packaged_policy
        )
        return cls(
            root,
            Path(
                os.environ.get(
                    "AIDE_KUBERNETES_TARGET_FILE",
                    str(root / ".aide/local/kubernetes-target.json"),
                )
            ),
            policy_path,
            Path(
                os.environ.get(
                    "AIDE_KUBERNETES_CHANGE_PLAN_DIR",
                    ".aide/local/kubernetes-change-plans",
                )
            ),
        )

    def status(self) -> dict[str, object]:
        problems = list(self.problems)
        if self.policy and not self.policy.enabled:
            problems.append("Kubernetes change policy is disabled")
        available = getattr(self.runner, "available", True)
        if not available:
            problems.append("kubectl executable was not found")
        try:
            self._safe_plan_dir(create=False)
        except ValueError as exc:
            problems.append(str(exc))
        return {
            "status": "ready" if not problems else "blocked",
            "read_only": False,
            "target": self.target.summary() if self.target else None,
            "policy": self.policy.summary() if self.policy else None,
            "target_file": self.target_path.as_posix(),
            "policy_file": self.policy_path.as_posix(),
            "plan_dir": self.plan_dir.as_posix(),
            "kubectl_available": bool(available),
            "authentication": "operator-managed kubeconfig",
            "problems": problems,
        }

    def validate_manifest(self, manifest_path: str) -> dict[str, object]:
        _, policy = self._ready()
        path, relative = self._manifest(manifest_path, policy)
        return {
            "status": "validated",
            "manifest_path": relative,
            "manifest_sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }

    def plan_manifest(self, manifest_path: str) -> dict[str, object]:
        target, policy = self._ready()
        path, relative = self._manifest(manifest_path, policy)
        target_fingerprint = self._target_fingerprint()
        response = self.runner.run(self._apply_args(path, policy, dry_run=True), target)
        objects = self._project_objects(response, target, policy)
        if self._target_fingerprint() != target_fingerprint:
            raise ValueError("Kubernetes target changed during planning")
        plan_id = uuid.uuid4().hex
        created = _now()
        receipt = {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "planned",
            "created_at": _timestamp(created),
            "expires_at": _timestamp(
                created + timedelta(minutes=policy.plan_ttl_minutes)
            ),
            "target": target.summary(),
            "manifest_path": relative,
            "manifest_sha256": _sha256(path),
            "target_sha256": target_fingerprint,
            "policy_sha256": _sha256(self.policy_path),
            "field_manager": policy.field_manager,
            "objects": objects,
        }
        self._save_receipt(receipt)
        return self._public_receipt(receipt)

    def apply_manifest(self, plan_id: str, confirmation: str) -> dict[str, object]:
        if not PLAN_ID.fullmatch(plan_id):
            raise ValueError("plan_id must be 32 lowercase hexadecimal characters")
        if confirmation != f"APPLY {plan_id}":
            raise ValueError(f"confirmation must equal APPLY {plan_id}")
        target, policy = self._ready()
        receipt = self._load_receipt(plan_id)
        if receipt.get("status") != "planned":
            raise ValueError("plan is not in planned state")
        try:
            expires = datetime.fromisoformat(str(receipt["expires_at"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("plan expiry is invalid") from exc
        if _now() >= expires:
            raise ValueError("plan has expired")
        if receipt.get("target_sha256") != self._target_fingerprint() or receipt.get(
            "policy_sha256"
        ) != _sha256(self.policy_path):
            raise ValueError("target or policy changed after planning")
        path, relative = self._manifest(str(receipt.get("manifest_path", "")), policy)
        if relative != receipt.get("manifest_path") or _sha256(path) != receipt.get(
            "manifest_sha256"
        ):
            raise ValueError("manifest changed after planning")
        checked = self._project_objects(
            self.runner.run(self._apply_args(path, policy, dry_run=True), target),
            target,
            policy,
        )
        if checked != receipt.get("objects"):
            raise ValueError(
                "server-side dry-run changed after planning; create a new plan"
            )
        if receipt.get("target_sha256") != self._target_fingerprint():
            raise ValueError("Kubernetes target changed during apply revalidation")
        receipt["status"] = "applying"
        receipt["apply_started_at"] = _timestamp(_now())
        self._save_receipt(receipt)
        planned_operations = {
            (str(item["kind"]), str(item["namespace"]), str(item["name"])): str(
                item["operation"]
            )
            for item in receipt.get("objects", [])
            if isinstance(item, dict)
        }
        try:
            applied = self._project_objects(
                self.runner.run(self._apply_args(path, policy, dry_run=False), target),
                target,
                policy,
                planned_operations=planned_operations,
            )
            if receipt.get("target_sha256") != self._target_fingerprint():
                raise ValueError("Kubernetes target changed during apply")
        except (RuntimeError, ValueError) as exc:
            receipt["status"] = "outcome_unknown"
            receipt["error"] = _bounded_text(exc)
            receipt["finished_at"] = _timestamp(_now())
            self._save_receipt(receipt)
            raise RuntimeError(
                "Kubernetes apply failed or timed out; outcome is unknown "
                "and must not be retried automatically"
            ) from exc
        receipt["status"] = "applied"
        receipt["finished_at"] = _timestamp(_now())
        receipt["applied_objects"] = applied
        self._save_receipt(receipt)
        return self._public_receipt(receipt)

    def plan_status(self, plan_id: str) -> dict[str, object]:
        return self._public_receipt(self._load_receipt(plan_id))

    def _ready(self) -> tuple[KubernetesTarget, KubernetesChangePolicy]:
        if self.problems or self.target is None or self.policy is None:
            raise ValueError(
                "; ".join(self.problems)
                or "Kubernetes change configuration is unavailable"
            )
        if not self.policy.enabled:
            raise ValueError("Kubernetes change policy is disabled")
        if not getattr(self.runner, "available", True):
            raise ValueError("kubectl executable was not found")
        self._safe_plan_dir(create=False)
        return self.target, self.policy

    def _target_fingerprint(self) -> str:
        if self.target_path.exists():
            return _sha256(self.target_path)
        discover = getattr(self.runner, "discover_target", None)
        if not callable(discover):
            raise ValueError("Kubernetes target discovery is unavailable")
        current = discover()
        if self.target is None or current.summary() != self.target.summary():
            raise ValueError("Kubernetes target changed after service initialization")
        return current.fingerprint

    def _safe_plan_dir(self, *, create: bool) -> Path:
        candidate = (
            self.plan_dir if self.plan_dir.is_absolute() else self.root / self.plan_dir
        )
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(
                "Kubernetes change plan directory is outside the workspace"
            )
        if create:
            resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _manifest(self, value: str, policy: KubernetesChangePolicy) -> tuple[Path, str]:
        raw = Path(value)
        candidate = raw if raw.is_absolute() else self.root / raw
        try:
            path = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"manifest is unreadable: {value}") from exc
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.is_relative_to(self.root)
        ):
            raise ValueError("manifest must be a regular workspace file")
        relative = path.relative_to(self.root).as_posix()
        if path.suffix.casefold() not in {".json", ".yaml", ".yml"}:
            raise ValueError("manifest must use .json, .yaml, or .yml")
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds the 1 MiB limit")
        if not any(
            relative == root or relative.startswith(root + "/")
            for root in policy.manifest_roots
        ):
            raise ValueError("manifest is outside policy manifest_roots")
        return path, relative

    def _apply_args(
        self, path: Path, policy: KubernetesChangePolicy, *, dry_run: bool
    ) -> list[str]:
        args = ["apply", "--server-side", f"--field-manager={policy.field_manager}"]
        if dry_run:
            args.append("--dry-run=server")
        args.extend(["--filename", str(path)])
        return args

    def _project_objects(
        self,
        value: object,
        target: KubernetesTarget,
        policy: KubernetesChangePolicy,
        *,
        planned_operations: dict[tuple[str, str, str], str] | None = None,
    ) -> list[dict[str, str]]:
        items = _items(value)
        if not items:
            raise ValueError("kubectl returned no planned objects")
        if len(items) > policy.max_objects:
            raise ValueError("planned object count exceeds policy max_objects")
        result = []
        for item in items:
            metadata = (
                item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            )
            kind = str(item.get("kind", ""))
            name = str(metadata.get("name", ""))
            namespace = str(metadata.get("namespace") or target.namespace)
            if kind in FORBIDDEN_KINDS or kind not in policy.allowed_kinds:
                raise ValueError(
                    f"resource kind is not allowlisted: {kind or 'unknown'}"
                )
            if not NAME.fullmatch(name) or namespace != target.namespace:
                raise ValueError(
                    "every object must have a valid name in the configured namespace"
                )
            identity = (kind, namespace, name)
            if planned_operations is None:
                existing = self.runner.run(
                    ["get", kind, name, "--ignore-not-found"], target
                )
                operation = "update" if _items(existing) else "create"
            else:
                try:
                    operation = planned_operations[identity]
                except KeyError as exc:
                    raise ValueError(
                        "applied object identity differs from the approved plan"
                    ) from exc
            if operation == "create" and not policy.allow_create:
                raise ValueError("policy does not allow create")
            if operation == "update" and not policy.allow_update:
                raise ValueError("policy does not allow update")
            result.append(
                {
                    "api_version": str(item.get("apiVersion", "")),
                    "kind": kind,
                    "name": name,
                    "namespace": namespace,
                    "operation": operation,
                }
            )
        return sorted(
            result, key=lambda item: (item["kind"], item["namespace"], item["name"])
        )

    def _receipt_path(self, plan_id: str) -> Path:
        if not PLAN_ID.fullmatch(plan_id):
            raise ValueError("plan_id must be 32 lowercase hexadecimal characters")
        return self._safe_plan_dir(create=False) / f"{plan_id}.json"

    def _save_receipt(self, receipt: dict[str, object]) -> None:
        directory = self._safe_plan_dir(create=True)
        target = directory / f"{receipt['plan_id']}.json"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, newline="\n"
        ) as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, target)

    def _load_receipt(self, plan_id: str) -> dict[str, Any]:
        try:
            value = json.loads(self._receipt_path(plan_id).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("plan receipt was not found") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("plan receipt is unreadable") from exc
        if not isinstance(value, dict) or value.get("plan_id") != plan_id:
            raise ValueError("plan receipt is invalid")
        return value

    @staticmethod
    def _public_receipt(receipt: dict[str, Any]) -> dict[str, object]:
        return {
            key: receipt.get(key)
            for key in (
                "plan_id",
                "status",
                "created_at",
                "expires_at",
                "finished_at",
                "target",
                "manifest_path",
                "manifest_sha256",
                "objects",
                "applied_objects",
                "error",
            )
            if receipt.get(key) is not None
        }


def _items(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    raw = value.get("items")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return [value] if value.get("kind") else []


def _decode_json_stream(text: str) -> object:
    decoder = json.JSONDecoder()
    offset = 0
    values: list[object] = []
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text):
            break
        try:
            value, offset = decoder.raw_decode(text, offset)
        except json.JSONDecodeError as exc:
            raise RuntimeError("kubectl did not return valid JSON") from exc
        values.append(value)
    if not values:
        return None
    return values[0] if len(values) == 1 else values
