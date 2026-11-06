"""Bounded read-only kubectl access for the AIDE Kubernetes MCP."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?$")
CONTEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,252}$")
MAX_ERROR_CHARS = 2_000
READ_KINDS = {
    "configmap": "configmap",
    "cronjob": "cronjob.batch",
    "daemonset": "daemonset.apps",
    "deployment": "deployment.apps",
    "endpointslice": "endpointslice.discovery.k8s.io",
    "event": "event",
    "ingress": "ingress.networking.k8s.io",
    "job": "job.batch",
    "pod": "pod",
    "replicaset": "replicaset.apps",
    "service": "service",
    "serviceaccount": "serviceaccount",
    "statefulset": "statefulset.apps",
}


def _bounded_int(value: object, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"expected an integer from {minimum} through {maximum}"
        ) from exc
    if result < minimum or result > maximum:
        raise ValueError(f"expected an integer from {minimum} through {maximum}")
    return result


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


def _redact(value: object, limit: int) -> str:
    text = str(value)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*\S+", r"\1=[REDACTED]", text
    )
    return text[:limit]


@dataclass(frozen=True)
class KubernetesTarget:
    """Validated project-local Kubernetes observation boundary."""

    context: str
    namespace: str
    max_items: int
    log_tail_lines: int
    log_since_seconds: int
    max_log_chars: int
    source: str = "target-file"
    fingerprint: str = ""

    @classmethod
    def load(cls, path: Path) -> KubernetesTarget:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"Kubernetes target file is missing: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Kubernetes target file is unreadable: {path}") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Kubernetes target schema_version must be 1")
        if _contains_forbidden_key(value):
            raise ValueError("Kubernetes target file must not contain credentials")
        context = str(value.get("context", ""))
        namespace = str(value.get("namespace", ""))
        if not CONTEXT.fullmatch(context) or context == "example-context":
            raise ValueError("context is missing, example, or unsupported")
        if not NAME.fullmatch(namespace) or namespace == "example-namespace":
            raise ValueError("namespace is missing, example, or unsupported")
        observation = value.get("observation", {})
        if not isinstance(observation, dict):
            raise ValueError("observation must be an object")
        return cls(
            context=context,
            namespace=namespace,
            max_items=_bounded_int(observation.get("max_items", 100), 1, 200),
            log_tail_lines=_bounded_int(observation.get("log_tail_lines", 200), 1, 500),
            log_since_seconds=_bounded_int(
                observation.get("log_since_seconds", 3600), 1, 86400
            ),
            max_log_chars=_bounded_int(
                observation.get("max_log_chars", 12000), 1000, 20000
            ),
            source="target-file",
            fingerprint=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "context": self.context,
            "namespace": self.namespace,
            "source": self.source,
        }


class CommandRunner(Protocol):
    available: bool

    def run(
        self, args: list[str], target: KubernetesTarget, *, output: str = "json"
    ) -> Any:
        """Run one fixed kubectl command."""

    def discover_target(self) -> KubernetesTarget:
        """Resolve the active kubeconfig context and namespace."""


class Kubectl:
    """Subprocess adapter that invokes kubectl without a shell."""

    def __init__(self, executable: str | None = None, timeout: int = 60) -> None:
        self.executable = (
            executable or shutil.which("kubectl") or shutil.which("kubectl.exe")
        )
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def run(
        self, args: list[str], target: KubernetesTarget, *, output: str = "json"
    ) -> Any:
        if not self.executable:
            raise RuntimeError("kubectl executable was not found")
        command = [
            self.executable,
            *args,
            "--context",
            target.context,
            "--namespace",
            target.namespace,
        ]
        if output == "json":
            command.extend(["--output", "json"])
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
                f"kubectl execution failed: {_redact(exc, MAX_ERROR_CHARS)}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "kubectl returned an error"
            raise RuntimeError(_redact(detail, MAX_ERROR_CHARS))
        if output == "text":
            return completed.stdout
        if not completed.stdout.strip():
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("kubectl did not return valid JSON") from exc

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
            max_items=100,
            log_tail_lines=200,
            log_since_seconds=3600,
            max_log_chars=12000,
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
                f"kubectl configuration lookup failed: {_redact(exc, MAX_ERROR_CHARS)}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "kubectl returned an error"
            raise ValueError(_redact(detail, MAX_ERROR_CHARS))
        return completed.stdout.strip()


class KubernetesService:
    """Read-only Kubernetes operations constrained to one context/namespace."""

    def __init__(self, target_path: Path, runner: CommandRunner | None = None) -> None:
        self.target_path = target_path
        self.runner = runner or Kubectl()
        self.target: KubernetesTarget | None = None
        self.configuration_error: str | None = None
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
            self.configuration_error = str(exc)

    @classmethod
    def from_environment(cls) -> KubernetesService:
        return cls(
            Path(
                os.environ.get(
                    "AIDE_KUBERNETES_TARGET_FILE", ".aide/local/kubernetes-target.json"
                )
            )
        )

    def status(self) -> dict[str, object]:
        problems = []
        if self.configuration_error:
            problems.append(self.configuration_error)
        available = getattr(self.runner, "available", True)
        if not available:
            problems.append("kubectl executable was not found")
        return {
            "status": "ready" if not problems else "blocked",
            "read_only": True,
            "target_file": self.target_path.as_posix(),
            "target": self.target.public_summary() if self.target else None,
            "kubectl_available": bool(available),
            "authentication": "operator-managed kubeconfig",
            "problems": problems,
        }

    def verify_context(self) -> dict[str, object]:
        target = self._target()
        answer = (
            str(
                self.runner.run(["auth", "can-i", "get", "pods"], target, output="text")
            )
            .strip()
            .casefold()
        )
        allowed = answer == "yes"
        return {
            "status": "verified" if allowed else "blocked",
            "context": target.context,
            "namespace": target.namespace,
            "can_get_pods": allowed,
            "problems": []
            if allowed
            else ["current identity cannot get pods in the configured namespace"],
        }

    def list_workloads(self, limit: int | None = None) -> dict[str, object]:
        target = self._target()
        maximum = _bounded_int(limit or target.max_items, 1, 200)
        value = self.runner.run(
            ["get", "deployments,statefulsets,daemonsets,jobs,cronjobs,pods"], target
        )
        return self._project_list(value, maximum, "workloads")

    def list_networking(self, limit: int | None = None) -> dict[str, object]:
        target = self._target()
        maximum = _bounded_int(limit or target.max_items, 1, 200)
        value = self.runner.run(
            [
                "get",
                "services,endpointslices.discovery.k8s.io,ingresses.networking.k8s.io",
            ],
            target,
        )
        return self._project_list(value, maximum, "resources")

    def list_events(self, limit: int = 50) -> dict[str, object]:
        target = self._target()
        maximum = _bounded_int(limit, 1, 100)
        value = self.runner.run(["get", "events", "--sort-by=.lastTimestamp"], target)
        items = _items(value)[-maximum:]
        events = []
        for item in items:
            metadata = _mapping(item.get("metadata"))
            involved = _mapping(item.get("involvedObject"))
            events.append(
                {
                    "name": metadata.get("name"),
                    "type": item.get("type"),
                    "reason": item.get("reason"),
                    "count": item.get("count"),
                    "first_timestamp": item.get("firstTimestamp")
                    or item.get("eventTime"),
                    "last_timestamp": item.get("lastTimestamp")
                    or item.get("eventTime"),
                    "object": {
                        "kind": involved.get("kind"),
                        "name": involved.get("name"),
                    },
                    "message": _redact(item.get("message", ""), 1000),
                }
            )
        return {
            "status": "observed",
            "context": target.context,
            "namespace": target.namespace,
            "events": events,
            "truncated": len(_items(value)) > maximum,
        }

    def read_resource(self, kind: str, name: str) -> dict[str, object]:
        target = self._target()
        normalized = kind.strip().casefold()
        if normalized == "secret" or normalized not in READ_KINDS:
            raise ValueError(
                "kind is not allowlisted; Secret reads are never supported"
            )
        if not NAME.fullmatch(name):
            raise ValueError("name has an unsupported shape")
        value = self.runner.run(["get", READ_KINDS[normalized], name], target)
        item = value if isinstance(value, dict) else {}
        return {
            "status": "observed",
            "context": target.context,
            "namespace": target.namespace,
            "resource": _project_resource(item),
        }

    def pod_logs(
        self,
        pod: str,
        container: str | None = None,
        tail_lines: int | None = None,
        since_seconds: int | None = None,
    ) -> dict[str, object]:
        target = self._target()
        if not NAME.fullmatch(pod) or (container and not NAME.fullmatch(container)):
            raise ValueError("pod or container name has an unsupported shape")
        tail = _bounded_int(tail_lines or target.log_tail_lines, 1, 500)
        since = _bounded_int(since_seconds or target.log_since_seconds, 1, 86400)
        args = ["logs", pod, f"--tail={tail}", f"--since={since}s", "--timestamps=true"]
        if container:
            args.extend(["--container", container])
        text = str(self.runner.run(args, target, output="text"))
        return {
            "status": "observed",
            "context": target.context,
            "namespace": target.namespace,
            "pod": pod,
            "container": container,
            "tail_lines": tail,
            "since_seconds": since,
            "logs": _redact(text, target.max_log_chars),
            "truncated": len(text) > target.max_log_chars,
        }

    def _target(self) -> KubernetesTarget:
        if self.target is None:
            raise ValueError(
                self.configuration_error or "Kubernetes target is unavailable"
            )
        if not getattr(self.runner, "available", True):
            raise ValueError("kubectl executable was not found")
        return self.target

    def _project_list(self, value: object, limit: int, key: str) -> dict[str, object]:
        target = self._target()
        items = _items(value)
        return {
            "status": "observed",
            "context": target.context,
            "namespace": target.namespace,
            key: [_project_resource(item) for item in items[:limit]],
            "truncated": len(items) > limit,
        }


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw = value.get("items")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return [value] if value.get("kind") else []


def _project_resource(item: dict[str, Any]) -> dict[str, object]:
    metadata = _mapping(item.get("metadata"))
    spec = _mapping(item.get("spec"))
    status = _mapping(item.get("status"))
    owners = metadata.get("ownerReferences")
    conditions = status.get("conditions")
    ports = spec.get("ports")
    projected = {
        "api_version": item.get("apiVersion"),
        "kind": item.get("kind"),
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "creation_timestamp": metadata.get("creationTimestamp"),
        "owners": [
            {"kind": owner.get("kind"), "name": owner.get("name")}
            for owner in owners[:10]
            if isinstance(owner, dict)
        ]
        if isinstance(owners, list)
        else [],
        "status": {
            key: status.get(key)
            for key in (
                "phase",
                "replicas",
                "readyReplicas",
                "availableReplicas",
                "updatedReplicas",
                "currentReplicas",
                "succeeded",
                "failed",
                "active",
            )
            if key in status
        },
        "conditions": [
            {
                "type": condition.get("type"),
                "status": condition.get("status"),
                "reason": condition.get("reason"),
            }
            for condition in conditions[:20]
            if isinstance(condition, dict)
        ]
        if isinstance(conditions, list)
        else [],
    }
    if item.get("kind") == "Service":
        projected["service"] = {
            "type": spec.get("type"),
            "cluster_ip": spec.get("clusterIP"),
            "ports": [
                {
                    "name": port.get("name"),
                    "port": port.get("port"),
                    "protocol": port.get("protocol"),
                    "target_port": port.get("targetPort"),
                }
                for port in ports[:20]
                if isinstance(port, dict)
            ]
            if isinstance(ports, list)
            else [],
        }
    if item.get("kind") == "ConfigMap":
        data = _mapping(item.get("data"))
        binary = _mapping(item.get("binaryData"))
        projected["config_keys"] = sorted(set(data) | set(binary))[:100]
    return projected
