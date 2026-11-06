"""Validated repository-owned knowledge-plane descriptor."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.spec_brain.models import normalize_relative_path

DESCRIPTOR_PATH = "knowledge-base/knowledge-plane.json"
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass(frozen=True)
class KnowledgePlaneDescriptor:
    """One service's reviewed contribution to a shared knowledge plane."""

    knowledge_plane_id: str
    service_id: str
    service_name: str
    service_kind: str
    review_status: str
    description: str | None
    dependencies: tuple[dict[str, str], ...]
    interfaces: tuple[dict[str, str], ...]
    events: tuple[dict[str, str], ...]
    relative_path: str
    canonical_body: str


def load_knowledge_plane_descriptor(
    repository_root: Path,
) -> KnowledgePlaneDescriptor | None:
    """Load the optional descriptor and reject ambiguous topology data."""

    root = repository_root.resolve()
    path = root / DESCRIPTOR_PATH
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {DESCRIPTOR_PATH}: {exc.msg}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"{DESCRIPTOR_PATH} requires schema_version 1")

    plane_id = _identifier(payload.get("knowledge_plane"), "knowledge_plane")
    service = payload.get("service")
    if not isinstance(service, dict):
        raise TypeError(f"{DESCRIPTOR_PATH} requires a service object")
    service_id = _identifier(service.get("id"), "service.id")
    service_name = _text(service.get("name"), "service.name")
    service_kind = _text(service.get("kind", "microservice"), "service.kind")
    review_status = _text(service.get("status", "draft"), "service.status")
    description = service.get("description")
    if description is not None:
        description = _text(description, "service.description")

    dependencies = _records(
        payload.get("dependencies", []),
        "dependencies",
        required=("service",),
        identifiers=("service", "interface"),
        paths=("evidence",),
        root=root,
    )
    interfaces = _records(
        payload.get("interfaces", []),
        "interfaces",
        required=("id", "direction", "kind"),
        identifiers=("id", "peer_service"),
        paths=("contract",),
        root=root,
        allowed={"direction": {"provides", "consumes"}},
    )
    events = _records(
        payload.get("events", []),
        "events",
        required=("id", "direction"),
        identifiers=("id", "peer_service"),
        paths=("schema",),
        root=root,
        allowed={"direction": {"publishes", "subscribes"}},
    )
    return KnowledgePlaneDescriptor(
        knowledge_plane_id=plane_id,
        service_id=service_id,
        service_name=service_name,
        service_kind=service_kind,
        review_status=review_status,
        description=description,
        dependencies=dependencies,
        interfaces=interfaces,
        events=events,
        relative_path=DESCRIPTOR_PATH,
        canonical_body=json.dumps(payload, sort_keys=True, ensure_ascii=False),
    )


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(
            f"{DESCRIPTOR_PATH} field {field} must use lowercase letters, "
            "digits, dashes, or underscores"
        )
    return text


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{DESCRIPTOR_PATH} field {field} must be non-empty text")
    return value.strip()


def _records(
    value: Any,
    field: str,
    *,
    required: tuple[str, ...],
    identifiers: tuple[str, ...],
    paths: tuple[str, ...],
    root: Path,
    allowed: dict[str, set[str]] | None = None,
) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise TypeError(f"{DESCRIPTOR_PATH} field {field} must be an array")
    records: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise TypeError(f"{DESCRIPTOR_PATH} {field}[{index}] must be an object")
        record = {
            str(key): _text(item, f"{field}[{index}].{key}")
            for key, item in raw.items()
            if item is not None and item != ""
        }
        missing = [name for name in required if name not in record]
        if missing:
            raise ValueError(
                f"{DESCRIPTOR_PATH} {field}[{index}] is missing: " + ", ".join(missing)
            )
        for name in identifiers:
            if name in record:
                record[name] = _identifier(record[name], f"{field}[{index}].{name}")
        for name in paths:
            if name in record:
                relative = normalize_relative_path(record[name])
                if not (root / relative).is_file():
                    raise ValueError(
                        f"{DESCRIPTOR_PATH} {field}[{index}].{name} does not "
                        f"exist: {relative}"
                    )
                record[name] = relative
        for name, choices in (allowed or {}).items():
            if record.get(name) not in choices:
                expected = ", ".join(sorted(choices))
                raise ValueError(
                    f"{DESCRIPTOR_PATH} {field}[{index}].{name} must be: {expected}"
                )
        identity = (
            record.get("id") or record.get("service", ""),
            record.get("direction", ""),
        )
        if identity in seen:
            raise ValueError(
                f"{DESCRIPTOR_PATH} contains duplicate {field}: {identity[0]}"
            )
        seen.add(identity)
        records.append(record)
    return tuple(records)
