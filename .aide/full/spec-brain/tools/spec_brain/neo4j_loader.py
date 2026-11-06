"""Idempotent additive loader for the exact Neo4j repository graph."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.spec_brain.config import SpecBrainSettings
from tools.spec_brain.models import (
    NODE_LABELS,
    RELATIONSHIP_TYPES,
    ManifestEntry,
    ManifestNode,
    ManifestRelationship,
    decode_jsonl,
)


class Neo4jDependencyError(RuntimeError):
    """Raised when the optional Neo4j driver is unavailable."""


@dataclass(frozen=True)
class LoadReport:
    """Summary of an exact-graph load attempt."""

    nodes: int
    relationships: int
    batches: int


class ExactGraphLoader:
    """Load canonical manifest records into a designated Neo4j database."""

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
        """Close a driver created by this loader."""

        if self._owns_driver:
            self._driver.close()

    def check_connectivity(self) -> None:
        """Verify the configured Neo4j service and target database."""

        self._driver.verify_connectivity()
        with self._driver.session(database=self.settings.neo4j_kb_database) as session:
            session.run("RETURN 1 AS ready").consume()

    def initialize_schema(self) -> None:
        """Create stable-ID uniqueness constraints for exact-graph labels."""

        labels = sorted({label for values in NODE_LABELS.values() for label in values})
        with self._driver.session(database=self.settings.neo4j_kb_database) as session:
            for label in labels:
                constraint_name = f"{label.lower()}_stable_id"
                query = (
                    f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.stable_id IS UNIQUE"
                )
                session.run(query).consume()

    def load(
        self, entries: Iterable[ManifestEntry], batch_size: int = 500
    ) -> LoadReport:
        """Upsert nodes and relationships without deleting existing graph data."""

        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        materialized = tuple(entries)
        nodes = tuple(
            entry for entry in materialized if isinstance(entry, ManifestNode)
        )
        relationships = tuple(
            entry for entry in materialized if isinstance(entry, ManifestRelationship)
        )
        node_labels = {node.stable_id: node.labels[0] for node in nodes}
        for relationship in relationships:
            if relationship.source_id not in node_labels:
                raise ValueError(
                    f"relationship source is absent: {relationship.source_id}"
                )
            if relationship.target_id not in node_labels:
                raise ValueError(
                    f"relationship target is absent: {relationship.target_id}"
                )

        grouped_nodes: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            grouped_nodes[node.labels].append(_node_row(node))
        grouped_relationships: dict[tuple[str, str, str], list[dict[str, Any]]] = (
            defaultdict(list)
        )
        for relationship in relationships:
            key = (
                relationship.relationship_type,
                node_labels[relationship.source_id],
                node_labels[relationship.target_id],
            )
            grouped_relationships[key].append(_relationship_row(relationship))

        batches = 0
        with self._driver.session(database=self.settings.neo4j_kb_database) as session:
            for labels, rows in sorted(grouped_nodes.items()):
                label_expression = ":".join(labels)
                query = (
                    f"UNWIND $rows AS row "
                    f"MERGE (n:{label_expression} {{stable_id: row.stable_id}}) "
                    "SET n += row.properties"
                )
                for batch in _batches(rows, batch_size):
                    session.run(query, rows=batch).consume()
                    batches += 1
            for key, rows in sorted(grouped_relationships.items()):
                relationship_type, source_label, target_label = key
                if relationship_type not in RELATIONSHIP_TYPES:
                    raise ValueError(
                        f"unsupported relationship type: {relationship_type}"
                    )
                query = (
                    f"UNWIND $rows AS row "
                    f"MATCH (source:{source_label} {{stable_id: row.source_id}}) "
                    f"MATCH (target:{target_label} {{stable_id: row.target_id}}) "
                    f"MERGE (source)-[r:{relationship_type} "
                    "{stable_id: row.stable_id}]->(target) "
                    "SET r += row.properties"
                )
                for batch in _batches(rows, batch_size):
                    session.run(query, rows=batch).consume()
                    batches += 1
        return LoadReport(len(nodes), len(relationships), batches)


def load_manifest_file(path: Path) -> tuple[ManifestEntry, ...]:
    """Read and validate a canonical JSON Lines manifest file."""

    if not path.is_file():
        raise ValueError(f"manifest does not exist: {path}")
    return decode_jsonl(path.read_text(encoding="utf-8"))


def _create_driver(settings: SpecBrainSettings) -> Any:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise Neo4jDependencyError(
            "the Neo4j Python driver is not installed in the active environment"
        ) from exc
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def _node_row(node: ManifestNode) -> dict[str, Any]:
    properties = node.to_dict()
    properties.pop("record_type", None)
    properties.pop("labels", None)
    stable_id = properties.pop("stable_id")
    properties["stable_id"] = stable_id
    return {"stable_id": stable_id, "properties": _neo4j_properties(properties)}


def _relationship_row(relationship: ManifestRelationship) -> dict[str, Any]:
    return {
        "stable_id": relationship.stable_id,
        "source_id": relationship.source_id,
        "target_id": relationship.target_id,
        "properties": _neo4j_properties(
            {"stable_id": relationship.stable_id, **relationship.properties}
        ),
    }


def _neo4j_properties(properties: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in properties.items():
        if value is None:
            continue
        if isinstance(value, dict):
            result[key] = json.dumps(value, sort_keys=True, ensure_ascii=False)
        elif isinstance(value, tuple):
            result[key] = list(value)
        elif isinstance(value, list) and any(
            isinstance(item, (dict, list, tuple)) for item in value
        ):
            result[key] = json.dumps(value, sort_keys=True, ensure_ascii=False)
        else:
            result[key] = value
    return result


def _batches(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
