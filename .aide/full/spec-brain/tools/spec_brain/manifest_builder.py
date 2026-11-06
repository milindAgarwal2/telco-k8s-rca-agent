"""Build the canonical manifest consumed by Neo4j and Graphiti loaders."""

from __future__ import annotations

import json
import posixpath
from collections.abc import Iterable
from dataclasses import fields, replace
from pathlib import Path, PurePosixPath
from typing import Any

from tools.spec_brain.claim_parser import parse_claim_file
from tools.spec_brain.knowledge_plane import (
    KnowledgePlaneDescriptor,
    load_knowledge_plane_descriptor,
)
from tools.spec_brain.markdown_parser import (
    MarkdownSection,
    document_metadata,
    extract_repository_references,
    iter_markdown_tables,
    parse_link_cell,
    parse_markdown,
)
from tools.spec_brain.models import (
    ManifestEntry,
    ManifestNode,
    ManifestRelationship,
    encode_jsonl,
    event_stable_id,
    file_stable_id,
    folder_stable_id,
    interface_stable_id,
    knowledge_plane_stable_id,
    normalize_relative_path,
    project_namespace,
    service_stable_id,
    sha256_text,
)

_EXCLUDED_DISCOVERY_ROOTS = {
    ".aide",
    ".git",
    ".gradle",
    ".idea",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


def _repository_id() -> str:
    return f"{project_namespace()}:repository"


class Manifest:
    """A deterministic, globally keyed set of manifest nodes and relationships."""

    def __init__(self) -> None:
        self._nodes: dict[str, ManifestNode] = {}
        self._relationships: dict[str, ManifestRelationship] = {}

    @property
    def nodes(self) -> tuple[ManifestNode, ...]:
        """Return nodes ordered by stable identifier."""

        return tuple(self._nodes[key] for key in sorted(self._nodes))

    @property
    def relationships(self) -> tuple[ManifestRelationship, ...]:
        """Return relationships ordered by stable identifier."""

        return tuple(self._relationships[key] for key in sorted(self._relationships))

    @property
    def entries(self) -> tuple[ManifestEntry, ...]:
        """Return all nodes followed by all relationships deterministically."""

        return (*self.nodes, *self.relationships)

    def add_node(self, node: ManifestNode) -> None:
        """Add or enrich a node without replacing established evidence."""

        existing = self._nodes.get(node.stable_id)
        if existing is None:
            self._nodes[node.stable_id] = node
            return
        if existing.record_type != node.record_type:
            if {existing.record_type, node.record_type} == {
                "source_file",
                "test_file",
            }:
                promoted = node if node.record_type == "test_file" else existing
                self._nodes[node.stable_id] = promoted
                return
            raise ValueError(
                f"stable ID {node.stable_id!r} has conflicting record types: "
                f"{existing.record_type!r} and {node.record_type!r}"
            )
        merged: dict[str, Any] = {}
        for item in fields(ManifestNode):
            name = item.name
            if name in {"stable_id", "record_type", "properties"}:
                continue
            old_value = getattr(existing, name)
            new_value = getattr(node, name)
            if name in {"heading_path", "mentioned_paths", "mentioned_tests"}:
                merged[name] = tuple(dict.fromkeys((*old_value, *new_value)))
            else:
                merged[name] = old_value if old_value not in {None, ""} else new_value
        properties = dict(node.properties)
        properties.update(existing.properties)
        self._nodes[node.stable_id] = replace(existing, properties=properties, **merged)

    def add_relationship(self, relationship: ManifestRelationship) -> None:
        """Add or merge an idempotent relationship record."""

        existing = self._relationships.get(relationship.stable_id)
        if existing is None:
            self._relationships[relationship.stable_id] = relationship
            return
        if (
            existing.relationship_type != relationship.relationship_type
            or existing.source_id != relationship.source_id
            or existing.target_id != relationship.target_id
        ):
            raise ValueError(
                f"stable relationship ID collision: {relationship.stable_id}"
            )
        properties = _merge_properties(existing.properties, relationship.properties)
        self._relationships[relationship.stable_id] = replace(
            existing, properties=properties
        )

    def validate(self) -> None:
        """Ensure all relationship endpoints exist in the manifest."""

        missing = sorted(
            {
                endpoint
                for relationship in self._relationships.values()
                for endpoint in (relationship.source_id, relationship.target_id)
                if endpoint not in self._nodes
            }
        )
        if missing:
            preview = ", ".join(missing[:5])
            raise ValueError(f"manifest relationships have missing nodes: {preview}")

    def write_jsonl(self, output: Path) -> None:
        """Write the canonical manifest, creating only its immediate directory."""

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encode_jsonl(self.entries), encoding="utf-8")


def build_manifest(
    repository_root: Path,
    markdown_paths: Iterable[str],
    claim_paths: Iterable[str],
) -> Manifest:
    """Build a manifest from explicit repository-relative inputs."""

    root = repository_root.resolve()
    manifest = Manifest()
    manifest.add_node(
        ManifestNode(
            stable_id=_repository_id(),
            record_type="repository",
            name=project_namespace(),
            relative_path=".",
            artifact_kind="repository",
            documentation_priority="implementation_evidence",
        )
    )
    _add_knowledge_plane(manifest, root)
    for relative_path in sorted(set(markdown_paths)):
        _add_markdown(manifest, root, relative_path)
    for relative_path in sorted(set(claim_paths)):
        parsed = parse_claim_file(Path(relative_path), root)
        for node in parsed.nodes:
            manifest.add_node(node)
        for relationship in parsed.relationships:
            manifest.add_relationship(relationship)
    manifest.validate()
    return manifest


def _add_knowledge_plane(manifest: Manifest, root: Path) -> None:
    descriptor = load_knowledge_plane_descriptor(root)
    if descriptor is None:
        return
    if descriptor.service_id != project_namespace():
        raise ValueError(
            "knowledge-base/knowledge-plane.json service.id must match "
            "SPEC_BRAIN_PROJECT_ID"
        )

    plane_id = descriptor.knowledge_plane_id
    plane_node_id = knowledge_plane_stable_id(plane_id)
    current_service_id = service_stable_id(plane_id, descriptor.service_id)
    manifest.add_node(
        ManifestNode(
            stable_id=plane_node_id,
            record_type="knowledge_plane",
            name=plane_id,
            artifact_kind="knowledge-plane",
            documentation_priority="primary",
            properties={"knowledge_plane_id": plane_id},
        )
    )
    manifest.add_node(
        _service_node(
            descriptor,
            descriptor.service_id,
            name=descriptor.service_name,
            kind=descriptor.service_kind,
            description=descriptor.description,
            body=descriptor.canonical_body,
        )
    )
    manifest.add_relationship(
        _plane_relationship(
            descriptor,
            "REPRESENTS_SERVICE",
            _repository_id(),
            current_service_id,
        )
    )
    manifest.add_relationship(
        _plane_relationship(
            descriptor,
            "BELONGS_TO",
            current_service_id,
            plane_node_id,
        )
    )

    for dependency in descriptor.dependencies:
        target_id = _add_peer_service(manifest, descriptor, dependency["service"])
        manifest.add_relationship(
            _plane_relationship(
                descriptor,
                "DEPENDS_ON_SERVICE",
                current_service_id,
                target_id,
                dependency_kind=dependency.get("kind", "unspecified"),
                interface=dependency.get("interface"),
                evidence=dependency.get("evidence"),
            )
        )
        if dependency.get("interface"):
            interface_id = _add_interface(manifest, descriptor, dependency)
            manifest.add_relationship(
                _plane_relationship(
                    descriptor,
                    "CONSUMES_INTERFACE",
                    current_service_id,
                    interface_id,
                    peer_service=dependency["service"],
                    evidence=dependency.get("evidence"),
                )
            )

    for interface in descriptor.interfaces:
        interface_id = _add_interface(manifest, descriptor, interface)
        relationship_type = (
            "PROVIDES_INTERFACE"
            if interface["direction"] == "provides"
            else "CONSUMES_INTERFACE"
        )
        peer = interface.get("peer_service")
        if peer:
            _add_peer_service(manifest, descriptor, peer)
        manifest.add_relationship(
            _plane_relationship(
                descriptor,
                relationship_type,
                current_service_id,
                interface_id,
                peer_service=peer,
                contract=interface.get("contract"),
            )
        )

    for event in descriptor.events:
        event_id = event_stable_id(plane_id, event["id"])
        manifest.add_node(
            ManifestNode(
                stable_id=event_id,
                record_type="event",
                name=event["id"],
                artifact_kind="event-contract",
                documentation_priority="primary",
                review_status=descriptor.review_status,
                properties={
                    "knowledge_plane_id": plane_id,
                    "event_id": event["id"],
                    "schema": event.get("schema"),
                },
            )
        )
        relationship_type = (
            "PUBLISHES_EVENT"
            if event["direction"] == "publishes"
            else "SUBSCRIBES_TO_EVENT"
        )
        peer = event.get("peer_service")
        if peer:
            _add_peer_service(manifest, descriptor, peer)
        manifest.add_relationship(
            _plane_relationship(
                descriptor,
                relationship_type,
                current_service_id,
                event_id,
                peer_service=peer,
                schema=event.get("schema"),
            )
        )


def _service_node(
    descriptor: KnowledgePlaneDescriptor,
    service_id: str,
    *,
    name: str | None = None,
    kind: str | None = None,
    description: str | None = None,
    body: str | None = None,
) -> ManifestNode:
    return ManifestNode(
        stable_id=service_stable_id(descriptor.knowledge_plane_id, service_id),
        record_type="service",
        name=name or service_id,
        artifact_kind=kind or "service-reference",
        review_status=descriptor.review_status,
        documentation_priority="primary",
        body=body,
        properties={
            "knowledge_plane_id": descriptor.knowledge_plane_id,
            "service_id": service_id,
            "description": description,
            "descriptor_path": descriptor.relative_path,
            "semantic_episode": body is not None,
        },
    )


def _add_peer_service(
    manifest: Manifest,
    descriptor: KnowledgePlaneDescriptor,
    service_id: str,
) -> str:
    node = _service_node(descriptor, service_id)
    manifest.add_node(node)
    plane_id = knowledge_plane_stable_id(descriptor.knowledge_plane_id)
    manifest.add_relationship(
        _plane_relationship(descriptor, "BELONGS_TO", node.stable_id, plane_id)
    )
    return node.stable_id


def _add_interface(
    manifest: Manifest,
    descriptor: KnowledgePlaneDescriptor,
    declaration: dict[str, str],
) -> str:
    interface_name = declaration.get("id") or declaration["interface"]
    node_id = interface_stable_id(descriptor.knowledge_plane_id, interface_name)
    manifest.add_node(
        ManifestNode(
            stable_id=node_id,
            record_type="interface",
            name=interface_name,
            artifact_kind=declaration.get("kind", "service-interface"),
            review_status=descriptor.review_status,
            documentation_priority="primary",
            properties={
                "knowledge_plane_id": descriptor.knowledge_plane_id,
                "interface_id": interface_name,
                "version": declaration.get("version"),
                "contract": declaration.get("contract"),
            },
        )
    )
    return node_id


def _plane_relationship(
    descriptor: KnowledgePlaneDescriptor,
    relationship_type: str,
    source_id: str,
    target_id: str,
    **properties: Any,
) -> ManifestRelationship:
    return ManifestRelationship.federated_between(
        descriptor.knowledge_plane_id,
        relationship_type,
        source_id,
        target_id,
        declared_by=descriptor.service_id,
        evidence_source=descriptor.relative_path,
        **{key: value for key, value in properties.items() if value is not None},
    )


def build_pilot_manifest(repository_root: Path) -> Manifest:
    """Build a small deterministic pilot from the repository's own corpus."""

    markdown, claims = discover_full_inputs(repository_root)
    primary = [path for path in markdown if not path.startswith("openwiki/")]
    secondary = [path for path in markdown if path.startswith("openwiki/")]
    selected_markdown = (*primary[:7], *secondary[:2])
    return build_manifest(repository_root, selected_markdown, claims[:2])


def discover_full_inputs(
    repository_root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Discover the full primary and secondary documentation corpus."""

    root = repository_root.resolve()
    preferred = (
        "knowledge-base/HLD.md",
        "knowledge-base/LLD.md",
        "knowledge-base/SPECS-RELATIONSHIP-MAP.md",
        "README.md",
    )
    primary = {path for path in preferred if (root / path).is_file()}
    primary.update(
        path.relative_to(root).as_posix()
        for path in root.rglob("SPECS.md")
        if not _excluded_from_discovery(path, root)
    )
    openwiki = root / "openwiki"
    secondary = (
        {path.relative_to(root).as_posix() for path in openwiki.rglob("*.md")}
        if openwiki.is_dir()
        else set()
    )
    claims_root = openwiki / ".claims"
    claims = (
        tuple(
            sorted(
                path.relative_to(root).as_posix()
                for path in claims_root.rglob("*.json")
            )
        )
        if claims_root.is_dir()
        else ()
    )
    return tuple(sorted(primary | secondary)), claims


def _excluded_from_discovery(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return bool(relative.parts and relative.parts[0] in _EXCLUDED_DISCOVERY_ROOTS)


def _add_markdown(manifest: Manifest, root: Path, relative_path: str) -> None:
    normalized = normalize_relative_path(relative_path)
    absolute = (root / normalized).resolve()
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {relative_path}") from exc
    if not absolute.is_file():
        raise ValueError(f"Markdown input does not exist: {normalized}")
    text = absolute.read_text(encoding="utf-8")
    parsed = parse_markdown(text)
    metadata = document_metadata(parsed)
    kind, record_type, priority = _classify_markdown(normalized, parsed.frontmatter)
    artifact_id = _artifact_stable_id(normalized, record_type, metadata)
    title = _artifact_title(normalized, parsed.sections, parsed.frontmatter, metadata)
    review_status = _review_status(metadata, parsed.frontmatter)
    artifact = ManifestNode(
        stable_id=artifact_id,
        record_type=record_type,
        name=title,
        relative_path=normalized,
        artifact_kind=kind,
        review_status=review_status,
        documentation_priority=priority,
        content_hash=sha256_text(text),
        properties={"frontmatter": json.dumps(parsed.frontmatter, sort_keys=True)},
    )
    manifest.add_node(artifact)
    manifest.add_relationship(
        ManifestRelationship.between("CONTAINS", _repository_id(), artifact_id)
    )

    if record_type == "folder_spec":
        folder = _folder_from_spec_path(normalized)
        folder_id = folder_stable_id(folder)
        manifest.add_node(_folder_node(folder))
        manifest.add_relationship(
            ManifestRelationship.between("HAS_SPEC", folder_id, artifact_id)
        )
        _add_folder_spec_interactions(manifest, parsed.sections, folder, normalized)

    for section in parsed.sections:
        mentioned_paths, mentioned_tests = extract_repository_references(
            section.body, normalized, root
        )
        section_id = f"{project_namespace()}:section:{normalized}#{section.slug}"
        manifest.add_node(
            ManifestNode(
                stable_id=section_id,
                record_type="section",
                name=section.title,
                relative_path=normalized,
                artifact_kind=kind,
                heading_path=section.heading_path,
                review_status=review_status,
                documentation_priority=priority,
                content_hash=sha256_text(section.body),
                body=section.body,
                mentioned_paths=mentioned_paths,
                mentioned_tests=mentioned_tests,
                properties={
                    "artifact_id": artifact_id,
                    "start_line": section.start_line,
                    "end_line": section.end_line,
                    "semantic_episode": _is_semantic_episode(kind, normalized, section),
                },
            )
        )
        manifest.add_relationship(
            ManifestRelationship.between("HAS_SECTION", artifact_id, section_id)
        )
        for path in mentioned_paths:
            _add_file_reference(manifest, section_id, path, is_test=False)
        for path in mentioned_tests:
            _add_file_reference(manifest, section_id, path, is_test=True)

    if kind == "relationship-map":
        _add_relationship_catalogs(manifest, parsed.sections, normalized)


def _classify_markdown(
    relative_path: str, frontmatter: dict[str, Any]
) -> tuple[str, str, str]:
    name = PurePosixPath(relative_path).name
    if relative_path == "knowledge-base/HLD.md":
        return "HLD", "artifact", "primary"
    if relative_path == "knowledge-base/LLD.md":
        return "LLD", "artifact", "primary"
    if relative_path == "knowledge-base/SPECS-RELATIONSHIP-MAP.md":
        return "relationship-map", "artifact", "primary"
    if name == "SPECS.md":
        return "folder-spec", "folder_spec", "primary"
    if relative_path.startswith("openwiki/"):
        kind = "openwiki-index" if name == "index.md" else "openwiki-page"
        return kind, "wiki_page", "secondary"
    kind = str(frontmatter.get("type") or "markdown")
    return kind, "artifact", "implementation_evidence"


def _artifact_stable_id(
    relative_path: str, record_type: str, metadata: dict[str, str]
) -> str:
    if record_type == "folder_spec":
        specification_id = metadata.get("specification id")
        if specification_id:
            return f"{project_namespace()}:{specification_id}"
    if record_type == "wiki_page":
        return f"{project_namespace()}:wiki:{relative_path}"
    return f"{project_namespace()}:artifact:{relative_path}"


def _artifact_title(
    relative_path: str,
    sections: tuple[MarkdownSection, ...],
    frontmatter: dict[str, Any],
    metadata: dict[str, str],
) -> str:
    if metadata.get("folder"):
        return metadata["folder"]
    if frontmatter.get("title"):
        return str(frontmatter["title"])
    if sections:
        return sections[0].title
    return PurePosixPath(relative_path).name


def _review_status(metadata: dict[str, str], frontmatter: dict[str, Any]) -> str:
    status = metadata.get("status", "")
    if "draft" in status.lower() or frontmatter.get("openwiki_generated"):
        return "draft"
    return status or "unreviewed"


def _folder_from_spec_path(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent.as_posix()
    return "." if parent == "." else normalize_relative_path(parent)


def _folder_node(folder: str, **properties: Any) -> ManifestNode:
    return ManifestNode(
        stable_id=folder_stable_id(folder),
        record_type="folder",
        name=folder,
        relative_path=folder,
        artifact_kind="repository-folder",
        documentation_priority="implementation_evidence",
        properties=properties,
    )


def _add_file_reference(
    manifest: Manifest, section_id: str, path: str, is_test: bool
) -> None:
    source_id = file_stable_id(path)
    manifest.add_node(
        ManifestNode(
            stable_id=source_id,
            record_type="test_file" if is_test else "source_file",
            name=PurePosixPath(path).name,
            relative_path=path,
            artifact_kind="repository-file",
            documentation_priority="implementation_evidence",
        )
    )
    manifest.add_relationship(
        ManifestRelationship.between(
            "VERIFIED_BY" if is_test else "IMPLEMENTED_BY",
            section_id,
            source_id,
        )
    )


def _add_folder_spec_interactions(
    manifest: Manifest,
    sections: tuple[MarkdownSection, ...],
    owner_folder: str,
    evidence_spec: str,
) -> None:
    owner_id = folder_stable_id(owner_folder)
    for section in sections:
        if "interaction" not in section.title.lower():
            continue
        for table in iter_markdown_tables(section.body):
            headers = tuple(header.lower() for header in table.headers)
            if len(headers) < 2 or headers[:2] != ("direction", "folder"):
                continue
            for row in table.rows:
                direction = row[0].strip().lower()
                target_folder, _ = parse_link_cell(row[1])
                target_folder = _normalize_folder_label(target_folder)
                if direction not in {"parent", "child", "outbound", "inbound"}:
                    continue
                target_id = folder_stable_id(target_folder)
                manifest.add_node(_folder_node(target_folder))
                relationship_type, source_id, destination_id = {
                    "parent": ("PARENT_OF", target_id, owner_id),
                    "child": ("PARENT_OF", owner_id, target_id),
                    "outbound": ("DEPENDS_ON", owner_id, target_id),
                    "inbound": ("DEPENDS_ON", target_id, owner_id),
                }[direction]
                manifest.add_relationship(
                    ManifestRelationship.between(
                        relationship_type,
                        source_id,
                        destination_id,
                        declaration=direction,
                        evidence_spec=evidence_spec,
                    )
                )


def _add_relationship_catalogs(
    manifest: Manifest,
    sections: tuple[MarkdownSection, ...],
    relationship_map_path: str,
) -> None:
    by_prefix = {section.title.split(".", 1)[0]: section for section in sections}
    node_section = by_prefix.get("8")
    structural_section = by_prefix.get("9")
    dependency_section = by_prefix.get("10")
    if not node_section or not structural_section or not dependency_section:
        raise ValueError("relationship map is missing a required complete catalog")

    node_tables = tuple(iter_markdown_tables(node_section.body))
    if not node_tables:
        raise ValueError("relationship map node catalog has no table")
    for row in node_tables[0].rows:
        if len(row) != 9:
            raise ValueError("relationship map node row has an unexpected shape")
        folder, spec_target = parse_link_cell(row[1])
        folder = _normalize_folder_label(folder)
        raw_spec_id = row[2].strip().strip("`")
        if not raw_spec_id.startswith("FSPEC-"):
            raise ValueError(
                f"invalid specification ID in relationship map: {raw_spec_id}"
            )
        spec_id = f"{project_namespace()}:{raw_spec_id}"
        spec_path = _resolve_map_target(relationship_map_path, spec_target)
        manifest.add_node(
            _folder_node(
                folder,
                role=row[3].strip(),
                child_count=_parse_count(row[5]),
                direct_file_count=_parse_count(row[6]),
                outbound_count=_parse_count(row[7]),
                inbound_count=_parse_count(row[8]),
            )
        )
        manifest.add_node(
            ManifestNode(
                stable_id=spec_id,
                record_type="folder_spec",
                name=folder,
                relative_path=spec_path,
                artifact_kind="folder-spec",
                review_status="draft",
                documentation_priority="primary",
                properties={"role": row[3].strip()},
            )
        )
        manifest.add_relationship(
            ManifestRelationship.between("HAS_SPEC", folder_stable_id(folder), spec_id)
        )

    structural_tables = tuple(iter_markdown_tables(structural_section.body))
    if not structural_tables:
        raise ValueError("relationship map structural catalog has no table")
    for row in structural_tables[0].rows:
        if len(row) != 3:
            raise ValueError("relationship map structural row has an unexpected shape")
        parent, _ = parse_link_cell(row[1])
        child, _ = parse_link_cell(row[2])
        parent = _normalize_folder_label(parent)
        child = _normalize_folder_label(child)
        manifest.add_node(_folder_node(parent))
        manifest.add_node(_folder_node(child))
        manifest.add_relationship(
            ManifestRelationship.between(
                "PARENT_OF",
                folder_stable_id(parent),
                folder_stable_id(child),
                evidence_spec=relationship_map_path,
                declaration="relationship-map",
            )
        )

    dependency_tables = tuple(iter_markdown_tables(dependency_section.body))
    if not dependency_tables:
        raise ValueError("relationship map dependency catalog has no table")
    for row in dependency_tables[0].rows:
        if len(row) != 5:
            raise ValueError("relationship map dependency row has an unexpected shape")
        source, _ = parse_link_cell(row[1])
        target, _ = parse_link_cell(row[2])
        source = _normalize_folder_label(source)
        target = _normalize_folder_label(target)
        manifest.add_node(_folder_node(source))
        manifest.add_node(_folder_node(target))
        manifest.add_relationship(
            ManifestRelationship.between(
                "DEPENDS_ON",
                folder_stable_id(source),
                folder_stable_id(target),
                declaration=[
                    item.strip() for item in row[3].split(",") if item.strip()
                ],
                evidence_spec=relationship_map_path,
                evidence_declarations=row[4].strip(),
            )
        )


def _is_semantic_episode(
    kind: str, relative_path: str, section: MarkdownSection
) -> bool:
    if kind == "openwiki-index":
        return False
    if kind != "relationship-map":
        return True
    number = section.title.split(".", 1)[0]
    return number in {"4", "5", "6", "13", "14"}


def _resolve_map_target(map_path: str, target: str | None) -> str:
    if target is None:
        raise ValueError("relationship map specification link has no target")
    target = target.strip().strip("<>").split("#", 1)[0]
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(map_path), target))
    return normalize_relative_path(resolved)


def _normalize_folder_label(value: str) -> str:
    stripped = value.strip().strip("`")
    if stripped in {"", ".", "repository root"}:
        return "."
    return normalize_relative_path(stripped)


def _parse_count(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid relationship-map count: {value!r}") from exc


def _merge_properties(
    existing: dict[str, Any] | Any, incoming: dict[str, Any] | Any
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
        elif merged[key] == value:
            continue
        elif isinstance(merged[key], list):
            additions = value if isinstance(value, list) else [value]
            merged[key] = list(dict.fromkeys([*merged[key], *additions]))
        else:
            additions = value if isinstance(value, list) else [value]
            merged[key] = list(dict.fromkeys([merged[key], *additions]))
    return merged
