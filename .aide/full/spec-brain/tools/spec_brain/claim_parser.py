"""Read-only parser for OpenWiki claim sidecars and evidence resources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tools.spec_brain.models import (
    ManifestNode,
    ManifestRelationship,
    file_stable_id,
    normalize_relative_path,
    project_namespace,
    stable_digest,
)

_RESOURCE_RE = re.compile(
    r"^repo://(?P<path>[^#]+)(?:#L(?P<start>\d+)(?:-L(?P<end>\d+))?)?$"
)


@dataclass(frozen=True)
class EvidenceReference:
    """A validated repository evidence span."""

    resource: str
    relative_path: str
    line_start: int | None
    line_end: int | None
    version: str | None


@dataclass(frozen=True)
class ParsedClaims:
    """Manifest records derived from one OpenWiki claim sidecar."""

    nodes: tuple[ManifestNode, ...]
    relationships: tuple[ManifestRelationship, ...]


def parse_evidence_resource(resource: str, version: str | None) -> EvidenceReference:
    """Parse a ``repo://`` evidence resource and validate its line range."""

    match = _RESOURCE_RE.fullmatch(resource.strip())
    if match is None:
        raise ValueError(f"unsupported evidence resource: {resource!r}")
    relative_path = normalize_relative_path(match.group("path"))
    start = int(match.group("start")) if match.group("start") else None
    end = int(match.group("end")) if match.group("end") else start
    if start is not None and start <= 0:
        raise ValueError(f"evidence line must be positive: {resource!r}")
    if start is not None and end is not None and end < start:
        raise ValueError(f"evidence line range is reversed: {resource!r}")
    return EvidenceReference(resource, relative_path, start, end, version)


def infer_page_path(claim_path: str) -> str:
    """Map an OpenWiki claim sidecar path to its Markdown page path."""

    normalized = normalize_relative_path(claim_path)
    parts = list(PurePosixPath(normalized).parts)
    try:
        claim_index = parts.index(".claims")
    except ValueError as exc:
        raise ValueError(f"claim path is not under .claims: {claim_path!r}") from exc
    del parts[claim_index]
    page = PurePosixPath(*parts).with_suffix(".md")
    return normalize_relative_path(page.as_posix())


def parse_claim_file(path: Path, repository_root: Path) -> ParsedClaims:
    """Parse one claim sidecar without mutating OpenWiki content.

    Args:
        path: Absolute or repository-relative JSON sidecar path.
        repository_root: Repository boundary used for path validation.

    Returns:
        Normalized claim, evidence, source, and relationship records.

    Raises:
        ValueError: If the sidecar schema or an evidence reference is invalid.
    """

    absolute_path = _resolve_within_root(path, repository_root)
    relative_claim_path = absolute_path.relative_to(repository_root).as_posix()
    try:
        payload = json.loads(absolute_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid claim JSON in {relative_claim_path}: {exc}") from exc
    _validate_claim_payload(payload, relative_claim_path)

    page_path = infer_page_path(relative_claim_path)
    page_id = f"{project_namespace()}:wiki:{page_path}"
    nodes: dict[str, ManifestNode] = {
        page_id: ManifestNode(
            stable_id=page_id,
            record_type="wiki_page",
            name=PurePosixPath(page_path).stem,
            relative_path=page_path,
            artifact_kind="openwiki-page",
            review_status="draft",
            documentation_priority="secondary",
        )
    }
    relationships: dict[str, ManifestRelationship] = {}

    for claim in payload["claims"]:
        raw_claim_id = claim["id"].strip()
        claim_id = f"{project_namespace()}:claim:{raw_claim_id}"
        statement = claim["statement"].strip()
        claim_node = ManifestNode(
            stable_id=claim_id,
            record_type="claim",
            name=raw_claim_id,
            artifact_kind="openwiki-claim",
            documentation_priority="secondary",
            review_status="draft",
            page_path=page_path,
            statement=statement,
            content_hash=payload.get("pageVersion"),
            properties={"claim_sidecar": relative_claim_path},
        )
        nodes[claim_id] = claim_node
        _add_relationship(
            relationships,
            ManifestRelationship.between("ASSERTS", page_id, claim_id),
        )
        for raw_evidence in claim["evidence"]:
            evidence = parse_evidence_resource(
                raw_evidence["resource"], raw_evidence.get("version")
            )
            evidence_id = f"{project_namespace()}:evidence:" + stable_digest(
                claim_id,
                evidence.resource,
                evidence.version or "",
            )
            evidence_node = ManifestNode(
                stable_id=evidence_id,
                record_type="evidence_span",
                name=evidence.resource,
                relative_path=evidence.relative_path,
                artifact_kind="openwiki-evidence",
                documentation_priority="implementation_evidence",
                resource=evidence.resource,
                version=evidence.version,
                properties={
                    "line_start": evidence.line_start,
                    "line_end": evidence.line_end,
                },
            )
            source_id = file_stable_id(evidence.relative_path)
            source_type = (
                "test_file"
                if evidence.relative_path.startswith("tests/")
                else "source_file"
            )
            source_node = ManifestNode(
                stable_id=source_id,
                record_type=source_type,
                name=PurePosixPath(evidence.relative_path).name,
                relative_path=evidence.relative_path,
                artifact_kind="repository-file",
                documentation_priority="implementation_evidence",
            )
            nodes[evidence_id] = evidence_node
            nodes[source_id] = source_node
            _add_relationship(
                relationships,
                ManifestRelationship.between("EVIDENCED_BY", claim_id, evidence_id),
            )
            _add_relationship(
                relationships,
                ManifestRelationship.between("LOCATED_IN", evidence_id, source_id),
            )

    return ParsedClaims(
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        relationships=tuple(relationships[key] for key in sorted(relationships)),
    )


def _validate_claim_payload(payload: Any, relative_path: str) -> None:
    if not isinstance(payload, dict):
        raise TypeError(f"claim sidecar must contain an object: {relative_path}")
    if payload.get("schemaVersion") != 1:
        raise ValueError(f"unsupported claim schemaVersion in {relative_path}")
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise TypeError(f"claims must be a list in {relative_path}")
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise TypeError(f"claim {index} must be an object in {relative_path}")
        claim_id = claim.get("id")
        statement = claim.get("statement")
        evidence = claim.get("evidence")
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise ValueError(f"claim {index} has no id in {relative_path}")
        if claim_id in seen:
            raise ValueError(f"duplicate claim id {claim_id!r} in {relative_path}")
        seen.add(claim_id)
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"claim {claim_id!r} has no statement")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"claim {claim_id!r} has no evidence")
        for raw_evidence in evidence:
            if not isinstance(raw_evidence, dict) or not isinstance(
                raw_evidence.get("resource"), str
            ):
                raise TypeError(f"claim {claim_id!r} has invalid evidence")


def _resolve_within_root(path: Path, repository_root: Path) -> Path:
    root = repository_root.resolve()
    absolute = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {path}") from exc
    if not absolute.is_file():
        raise ValueError(f"claim sidecar does not exist: {absolute}")
    return absolute


def _add_relationship(
    relationships: dict[str, ManifestRelationship],
    relationship: ManifestRelationship,
) -> None:
    relationships.setdefault(relationship.stable_id, relationship)
