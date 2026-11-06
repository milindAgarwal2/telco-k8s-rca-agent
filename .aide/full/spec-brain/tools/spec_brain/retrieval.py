"""Exact Neo4j retrieval seeded by paths and Graphiti semantic facts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tools.spec_brain.config import SpecBrainSettings
from tools.spec_brain.graphiti_loader import SemanticFact
from tools.spec_brain.models import normalize_relative_path, service_stable_id

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{3,}")
_STOP_WORDS = {
    "about",
    "after",
    "before",
    "change",
    "create",
    "design",
    "feature",
    "from",
    "implement",
    "requirements",
    "should",
    "specification",
    "tasks",
    "that",
    "this",
    "update",
    "when",
    "with",
}


class ExactRetrievalError(RuntimeError):
    """Raised when exact retrieval cannot produce usable primary context."""


@dataclass(frozen=True)
class ExactContext:
    """Normalized exact-graph results used by the context composer."""

    primary_context: tuple[dict[str, Any], ...]
    secondary_context: tuple[dict[str, Any], ...]
    module_relationships: tuple[dict[str, Any], ...]
    source_and_test_locations: tuple[dict[str, Any], ...]
    affected_folder_specs: tuple[dict[str, Any], ...]
    service_relationships: tuple[dict[str, Any], ...] = ()


class ExactRetriever:
    """Query the exact graph without allowing semantic facts to become truth."""

    def __init__(
        self,
        settings: SpecBrainSettings,
        driver: Any | None = None,
    ) -> None:
        settings.require_exact()
        self.settings = settings
        self._driver = driver or _create_driver(settings)
        self._owns_driver = driver is None

    def close(self) -> None:
        """Close a Neo4j driver created by this retriever."""

        if self._owns_driver:
            self._driver.close()

    def retrieve(
        self,
        request: str,
        target_paths: Iterable[str] = (),
        semantic_facts: Iterable[SemanticFact] = (),
    ) -> ExactContext:
        """Retrieve primary evidence, exact relationships, and secondary context."""

        normalized_paths = tuple(
            sorted({normalize_relative_path(path) for path in target_paths})
        )
        terms = _search_terms(request, semantic_facts)
        with self._driver.session(database=self.settings.neo4j_kb_database) as session:
            service_relationships, linked_projects = _service_context(
                session, self.settings
            )
            project_ids = (self.settings.project_id, *linked_projects)
            project_prefixes = [f"{project_id}:" for project_id in project_ids]
            project_prefix = f"{self.settings.project_id}:"
            folder_ids = tuple(
                record["stable_id"]
                for record in session.run(
                    _FOLDER_IDS_QUERY,
                    paths=list(normalized_paths),
                    project_prefix=project_prefix,
                )
            )
            primary = _section_results(
                session,
                priority="primary",
                paths=normalized_paths,
                terms=terms,
                limit=max(self.settings.max_semantic_results * 4, 24),
                project_prefix=project_prefix,
                project_prefixes=project_prefixes,
            )
            secondary = _section_results(
                session,
                priority="secondary",
                paths=normalized_paths,
                terms=terms,
                limit=max(self.settings.max_semantic_results * 2, 12),
                project_prefix=project_prefix,
                project_prefixes=project_prefixes,
            )
            relationships = _relationship_results(
                session,
                folder_ids,
                self.settings.max_relationship_depth,
            )
            specs = _affected_specs(session, folder_ids)
        if not primary:
            raise ExactRetrievalError(
                "no primary HLD, LLD, or folder-specification context was found"
            )
        locations = _source_locations(primary)
        return ExactContext(
            primary_context=primary,
            secondary_context=secondary,
            module_relationships=relationships,
            source_and_test_locations=locations,
            affected_folder_specs=specs,
            service_relationships=service_relationships,
        )


_FOLDER_IDS_QUERY = """
UNWIND $paths AS path
MATCH (folder:KB_Folder)
WHERE folder.stable_id STARTS WITH $project_prefix
  AND (path = folder.relative_path
   OR path STARTS WITH folder.relative_path + '/')
WITH path, folder
ORDER BY size(folder.relative_path) DESC
WITH path, collect(folder)[0] AS owner
RETURN DISTINCT owner.stable_id AS stable_id
"""

_SECTIONS_QUERY = """
MATCH (section:KB_Section)
WHERE section.documentation_priority = $priority
  AND coalesce(section.semantic_episode, true) = true
  AND any(prefix IN $project_prefixes
          WHERE section.stable_id STARTS WITH prefix)
WITH section,
     size([
       term IN $terms
       WHERE toLower(coalesce(section.body, '')) CONTAINS term
          OR toLower(coalesce(section.name, '')) CONTAINS term
     ]) AS score,
     section.stable_id STARTS WITH $project_prefix
     AND any(path IN $paths WHERE
       section.relative_path = path
       OR section.relative_path STARTS WITH path + '/'
       OR any(mentioned IN coalesce(section.mentioned_paths, [])
              WHERE mentioned = path OR mentioned STARTS WITH path + '/')
       OR any(test IN coalesce(section.mentioned_tests, [])
              WHERE test = path OR test STARTS WITH path + '/')
     ) AS path_match
WHERE score > 0 OR path_match
RETURN section {.*} AS section, score, path_match
ORDER BY path_match DESC, score DESC, section.relative_path, section.stable_id
LIMIT $limit
"""

_SERVICE_RELATIONSHIPS_QUERY = """
MATCH (service:KB_Service {stable_id: $service_id})
OPTIONAL MATCH (service)-[
  relationship:DEPENDS_ON_SERVICE|PROVIDES_INTERFACE|CONSUMES_INTERFACE|
  PUBLISHES_EVENT|SUBSCRIBES_TO_EVENT
]-(neighbor)
RETURN service {.*} AS service,
       type(relationship) AS relationship_type,
       CASE WHEN relationship IS NULL THEN NULL
            WHEN startNode(relationship) = service THEN 'outbound'
            ELSE 'inbound' END AS direction,
       relationship {.*} AS relationship,
       neighbor {.*} AS neighbor
ORDER BY relationship_type, direction, neighbor.stable_id
"""

_AFFECTED_SPECS_QUERY = """
UNWIND $folder_ids AS folder_id
MATCH (owner:KB_Folder {stable_id: folder_id})
OPTIONAL MATCH (related:KB_Folder)-[:PARENT_OF|DEPENDS_ON]-(owner)
WITH collect(DISTINCT owner) + collect(DISTINCT related) AS folders
UNWIND folders AS folder
WITH DISTINCT folder WHERE folder IS NOT NULL
OPTIONAL MATCH (folder)-[:HAS_SPEC]->(spec:KB_FolderSpec)
RETURN folder {.*} AS folder, spec {.*} AS specification
ORDER BY folder.relative_path
"""


def _section_results(
    session: Any,
    *,
    priority: str,
    paths: tuple[str, ...],
    terms: tuple[str, ...],
    limit: int,
    project_prefix: str,
    project_prefixes: list[str],
) -> tuple[dict[str, Any], ...]:
    records = session.run(
        _SECTIONS_QUERY,
        priority=priority,
        paths=list(paths),
        terms=list(terms),
        limit=limit,
        project_prefix=project_prefix,
        project_prefixes=project_prefixes,
    )
    return tuple(
        {
            **dict(record["section"]),
            "match_score": record["score"],
            "path_match": record["path_match"],
        }
        for record in records
    )


def _service_context(
    session: Any,
    settings: SpecBrainSettings,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    service_id = service_stable_id(
        settings.knowledge_plane_id,
        settings.project_id,
    )
    relationships: list[dict[str, Any]] = []
    linked_projects: set[str] = set()
    for record in session.run(
        _SERVICE_RELATIONSHIPS_QUERY,
        service_id=service_id,
    ):
        relationship_type = record["relationship_type"]
        if relationship_type is None:
            continue
        service = dict(record["service"])
        neighbor = dict(record["neighbor"])
        relationship = dict(record["relationship"])
        relationships.append(
            {
                "service": service,
                "relationship_type": relationship_type,
                "direction": record["direction"],
                "relationship": relationship,
                "neighbor": neighbor,
            }
        )
        neighbor_service = neighbor.get("service_id")
        peer_service = relationship.get("peer_service")
        for candidate in (neighbor_service, peer_service):
            if candidate and candidate != settings.project_id:
                linked_projects.add(str(candidate))
    return tuple(relationships), tuple(sorted(linked_projects))


def _relationship_results(
    session: Any,
    folder_ids: tuple[str, ...],
    depth: int,
) -> tuple[dict[str, Any], ...]:
    if not folder_ids:
        return ()
    query = f"""
UNWIND $folder_ids AS folder_id
MATCH (owner:KB_Folder {{stable_id: folder_id}})
CALL (owner) {{
  OPTIONAL MATCH (parent:KB_Folder)-[:PARENT_OF*1..{depth}]->(owner)
  RETURN collect(DISTINCT parent {{.*}}) AS parents
}}
CALL (owner) {{
  OPTIONAL MATCH (owner)-[:PARENT_OF*1..{depth}]->(child:KB_Folder)
  RETURN collect(DISTINCT child {{.*}}) AS children
}}
CALL (owner) {{
  OPTIONAL MATCH (owner)-[:DEPENDS_ON*1..{depth}]->(dependency:KB_Folder)
  RETURN collect(DISTINCT dependency {{.*}}) AS dependencies
}}
CALL (owner) {{
  OPTIONAL MATCH (consumer:KB_Folder)-[:DEPENDS_ON*1..{depth}]->(owner)
  RETURN collect(DISTINCT consumer {{.*}}) AS consumers
}}
RETURN owner {{.*}} AS owner, parents, children, dependencies, consumers
ORDER BY owner.relative_path
"""
    records = session.run(query, folder_ids=list(folder_ids))
    return tuple(dict(record) for record in records)


def _affected_specs(
    session: Any, folder_ids: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    if not folder_ids:
        return ()
    return tuple(
        {
            "folder": dict(record["folder"]),
            "specification": (
                dict(record["specification"])
                if record["specification"] is not None
                else None
            ),
        }
        for record in session.run(_AFFECTED_SPECS_QUERY, folder_ids=list(folder_ids))
    )


def _source_locations(
    primary: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    locations: dict[tuple[str, str], dict[str, Any]] = {}
    for section in primary:
        for path in section.get("mentioned_paths", []):
            locations[(path, "source")] = {
                "relative_path": path,
                "kind": "source",
                "evidence_section": section.get("stable_id"),
            }
        for path in section.get("mentioned_tests", []):
            locations[(path, "test")] = {
                "relative_path": path,
                "kind": "test",
                "evidence_section": section.get("stable_id"),
            }
    return tuple(locations[key] for key in sorted(locations))


def _search_terms(
    request: str, semantic_facts: Iterable[SemanticFact]
) -> tuple[str, ...]:
    content = [request]
    for fact in semantic_facts:
        content.extend(
            value
            for value in (fact.source_entity, fact.target_entity)
            if value is not None
        )
    terms = {
        match.group(0).lower()
        for value in content
        for match in _WORD_RE.finditer(value)
        if match.group(0).lower() not in _STOP_WORDS
    }
    return tuple(sorted(terms, key=lambda term: (-len(term), term))[:24])


def _create_driver(settings: SpecBrainSettings) -> Any:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise ExactRetrievalError("the Neo4j Python driver is not installed") from exc
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
