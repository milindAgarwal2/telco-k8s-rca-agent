"""Canonical JSON Lines manifest models shared by both graph loaders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from tools.spec_brain.config import SpecBrainSettings

DOCUMENTATION_PRIORITIES = {
    "primary",
    "secondary",
    "implementation_evidence",
}

NODE_LABELS: dict[str, tuple[str, ...]] = {
    "knowledge_plane": ("KB_KnowledgePlane",),
    "service": ("KB_Service",),
    "repository": ("KB_Repository",),
    "artifact": ("KB_Artifact",),
    "section": ("KB_Section",),
    "folder": ("KB_Folder",),
    "folder_spec": ("KB_Artifact", "KB_FolderSpec"),
    "wiki_page": ("KB_Artifact", "KB_WikiPage"),
    "claim": ("KB_Claim",),
    "evidence_span": ("KB_EvidenceSpan",),
    "source_file": ("KB_SourceFile",),
    "test_file": ("KB_SourceFile", "KB_TestFile"),
    "component": ("KB_Component",),
    "interface": ("KB_Interface",),
    "event": ("KB_Event",),
    "data_store": ("KB_DataStore",),
    "flow": ("KB_Flow",),
    "question": ("KB_Question",),
}

RELATIONSHIP_TYPES = {
    "BELONGS_TO",
    "REPRESENTS_SERVICE",
    "DEPENDS_ON_SERVICE",
    "PROVIDES_INTERFACE",
    "CONSUMES_INTERFACE",
    "PUBLISHES_EVENT",
    "SUBSCRIBES_TO_EVENT",
    "CONTAINS",
    "HAS_SECTION",
    "HAS_SPEC",
    "PARENT_OF",
    "DEPENDS_ON",
    "CONSUMED_BY",
    "ASSERTS",
    "EVIDENCED_BY",
    "LOCATED_IN",
    "DESCRIBES",
    "IMPLEMENTED_BY",
    "VERIFIED_BY",
    "PARTICIPATES_IN",
    "HAS_QUESTION",
}


def sha256_text(value: str) -> str:
    """Return a manifest-compatible SHA-256 digest."""

    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def stable_digest(*parts: str, length: int = 24) -> str:
    """Return a compact deterministic digest for a composite identifier."""

    content = "\x1f".join(parts)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]


def normalize_relative_path(value: str) -> str:
    """Normalize a repository-relative path to POSIX form.

    Args:
        value: A relative path, optionally prefixed with ``./``.

    Returns:
        A normalized forward-slash path.

    Raises:
        ValueError: If the path is absolute or escapes the repository root.
    """

    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must stay within the repository: {value!r}")
    return path.as_posix()


def project_namespace() -> str:
    """Return the configured or repository-derived graph namespace."""

    return SpecBrainSettings.from_env().project_id


def folder_stable_id(folder: str) -> str:
    """Return the canonical stable identifier for a repository folder."""

    return f"{project_namespace()}:folder:{normalize_relative_path(folder)}"


def file_stable_id(relative_path: str) -> str:
    """Return the canonical stable identifier for a source or test file."""

    return f"{project_namespace()}:file:{normalize_relative_path(relative_path)}"


def edge_stable_id(relationship_type: str, source_id: str, target_id: str) -> str:
    """Return an identifier that makes relationship ingestion idempotent."""

    return (
        f"{project_namespace()}:edge:{relationship_type.lower()}:"
        f"{stable_digest(source_id, target_id)}"
    )


def knowledge_plane_stable_id(knowledge_plane_id: str) -> str:
    """Return the canonical identifier for a shared knowledge plane."""

    return f"plane:{knowledge_plane_id}"


def service_stable_id(knowledge_plane_id: str, service_id: str) -> str:
    """Return a service identifier shared by independently ingested projects."""

    return f"{knowledge_plane_stable_id(knowledge_plane_id)}:service:{service_id}"


def interface_stable_id(knowledge_plane_id: str, interface_id: str) -> str:
    """Return a plane-scoped interface identifier."""

    return f"{knowledge_plane_stable_id(knowledge_plane_id)}:interface:{interface_id}"


def event_stable_id(knowledge_plane_id: str, event_id: str) -> str:
    """Return a plane-scoped event identifier."""

    return f"{knowledge_plane_stable_id(knowledge_plane_id)}:event:{event_id}"


def federated_edge_stable_id(
    knowledge_plane_id: str,
    relationship_type: str,
    source_id: str,
    target_id: str,
) -> str:
    """Return an edge ID that converges across repository ingestion runs."""

    return (
        f"{knowledge_plane_stable_id(knowledge_plane_id)}:edge:"
        f"{relationship_type.lower()}:{stable_digest(source_id, target_id)}"
    )


@dataclass(frozen=True)
class ManifestNode:
    """One normalized exact-graph node and optional semantic episode source."""

    stable_id: str
    record_type: str
    name: str | None = None
    relative_path: str | None = None
    artifact_kind: str | None = None
    heading_path: tuple[str, ...] = ()
    review_status: str | None = None
    documentation_priority: str | None = None
    content_hash: str | None = None
    body: str | None = None
    mentioned_paths: tuple[str, ...] = ()
    mentioned_tests: tuple[str, ...] = ()
    page_path: str | None = None
    statement: str | None = None
    resource: str | None = None
    version: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.stable_id.strip():
            raise ValueError("stable_id must not be empty")
        if self.record_type not in NODE_LABELS:
            raise ValueError(f"unsupported node record_type: {self.record_type}")
        if (
            self.documentation_priority is not None
            and self.documentation_priority not in DOCUMENTATION_PRIORITIES
        ):
            raise ValueError(
                f"unsupported documentation_priority: {self.documentation_priority}"
            )

    @property
    def labels(self) -> tuple[str, ...]:
        """Return the fixed Neo4j labels for this record type."""

        return NODE_LABELS[self.record_type]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the node as a flat JSON Lines record."""

        result: dict[str, Any] = {
            "stable_id": self.stable_id,
            "record_type": self.record_type,
            "labels": list(self.labels),
        }
        optional: dict[str, Any] = {
            "name": self.name,
            "relative_path": self.relative_path,
            "artifact_kind": self.artifact_kind,
            "heading_path": list(self.heading_path) if self.heading_path else None,
            "review_status": self.review_status,
            "documentation_priority": self.documentation_priority,
            "content_hash": self.content_hash,
            "body": self.body,
            "mentioned_paths": (
                list(self.mentioned_paths) if self.mentioned_paths else None
            ),
            "mentioned_tests": (
                list(self.mentioned_tests) if self.mentioned_tests else None
            ),
            "page_path": self.page_path,
            "statement": self.statement,
            "resource": self.resource,
            "version": self.version,
        }
        result.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        result.update(self.properties)
        return result


@dataclass(frozen=True)
class ManifestRelationship:
    """One normalized relationship between two manifest nodes."""

    stable_id: str
    relationship_type: str
    source_id: str
    target_id: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    record_type: str = field(default="relationship", init=False)

    def __post_init__(self) -> None:
        if self.relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"unsupported relationship_type: {self.relationship_type}")
        if not self.source_id or not self.target_id:
            raise ValueError("relationship endpoints must not be empty")

    @classmethod
    def between(
        cls,
        relationship_type: str,
        source_id: str,
        target_id: str,
        **properties: Any,
    ) -> ManifestRelationship:
        """Construct an idempotent relationship record."""

        return cls(
            stable_id=edge_stable_id(relationship_type, source_id, target_id),
            relationship_type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            properties=properties,
        )

    @classmethod
    def federated_between(
        cls,
        knowledge_plane_id: str,
        relationship_type: str,
        source_id: str,
        target_id: str,
        **properties: Any,
    ) -> ManifestRelationship:
        """Construct a relationship shared across repository manifests."""

        return cls(
            stable_id=federated_edge_stable_id(
                knowledge_plane_id,
                relationship_type,
                source_id,
                target_id,
            ),
            relationship_type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            properties=properties,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the relationship as a flat JSON Lines record."""

        result = {
            "stable_id": self.stable_id,
            "record_type": self.record_type,
            "relationship_type": self.relationship_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
        }
        result.update(self.properties)
        return result


ManifestEntry = ManifestNode | ManifestRelationship


def encode_jsonl(entries: Iterable[ManifestEntry]) -> str:
    """Encode entries as deterministic JSON Lines text."""

    return "".join(
        json.dumps(entry.to_dict(), sort_keys=True, ensure_ascii=False) + "\n"
        for entry in entries
    )


def decode_jsonl(text: str) -> tuple[ManifestEntry, ...]:
    """Decode and validate canonical manifest JSON Lines text."""

    entries: list[ManifestEntry] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on manifest line {line_number}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"manifest line {line_number} must be an object")
        try:
            entries.append(_entry_from_dict(payload))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid manifest record on line {line_number}: {exc}"
            ) from exc
    return tuple(entries)


def _entry_from_dict(payload: dict[str, Any]) -> ManifestEntry:
    data = dict(payload)
    record_type = data.pop("record_type")
    data.pop("labels", None)
    if record_type == "relationship":
        stable_id = data.pop("stable_id")
        relationship_type = data.pop("relationship_type")
        source_id = data.pop("source_id")
        target_id = data.pop("target_id")
        return ManifestRelationship(
            stable_id=stable_id,
            relationship_type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            properties=data,
        )

    known_names = {
        "stable_id",
        "name",
        "relative_path",
        "artifact_kind",
        "heading_path",
        "review_status",
        "documentation_priority",
        "content_hash",
        "body",
        "mentioned_paths",
        "mentioned_tests",
        "page_path",
        "statement",
        "resource",
        "version",
    }
    known = {name: data.pop(name) for name in tuple(data) if name in known_names}
    for tuple_name in ("heading_path", "mentioned_paths", "mentioned_tests"):
        if tuple_name in known:
            known[tuple_name] = tuple(known[tuple_name])
    return ManifestNode(
        record_type=record_type,
        properties=data,
        **known,
    )
