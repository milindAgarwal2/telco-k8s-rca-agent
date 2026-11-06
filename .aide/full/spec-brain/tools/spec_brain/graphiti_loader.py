"""Graphiti adapter constrained to approved internal model services."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tools.spec_brain.config import SpecBrainSettings
from tools.spec_brain.models import ManifestEntry, ManifestNode

try:
    from graphiti_core.cross_encoder.client import (
        CrossEncoderClient as _CrossEncoderClient,
    )
except ImportError:

    class _CrossEncoderClient:  # type: ignore[no-redef]
        """Import-safe placeholder until runtime dependency validation."""


EXTRACTION_INSTRUCTIONS = """
Extract only explicitly named repository entities and relationships.
Preserve exact class, function, file, folder, configuration, and test names.
Preserve service, interface, event, and knowledge-plane identifiers exactly.
Link services only when the episode declares their dependency, interface, or event.
Do not infer a runtime call from a static dependency declaration.
Do not convert an optional feature into an enabled deployment feature.
Treat knowledge-base sections as primary design context.
Treat OpenWiki sections as secondary navigation.
Retain uncertainty labels and unresolved questions.
Do not invent a component, interface, data store, queue, configuration, or flow.
""".strip()

ENTITY_TYPE_NAMES = (
    "Component",
    "Program",
    "Interface",
    "DataStore",
    "Configuration",
    "RequestModel",
    "Worker",
    "Test",
    "Specification",
    "Question",
    "Service",
    "Event",
    "KnowledgePlane",
)

EDGE_TYPE_NAMES = (
    "OWNS",
    "DEPENDS_ON",
    "CALLS",
    "PRODUCES",
    "CONSUMES",
    "READS",
    "WRITES",
    "CONFIGURED_BY",
    "VERIFIED_BY",
    "PARTICIPATES_IN",
    "RELATES_TO",
)


class GraphitiDependencyError(RuntimeError):
    """Raised when a pinned Graphiti dependency cannot be imported."""


class GraphitiServiceUnavailable(RuntimeError):
    """Raised before ingestion when an internal dependency is unavailable."""


class GraphitiIngestionError(RuntimeError):
    """Raised when one stable episode cannot be added."""


@dataclass(frozen=True)
class GraphitiEpisode:
    """One stable semantic episode derived from the canonical manifest."""

    stable_id: str
    name: str
    body: str
    source_description: str
    reference_time: datetime
    order: int


@dataclass(frozen=True)
class SemanticFact:
    """Normalized Graphiti fact returned to the exact retriever and composer."""

    stable_id: str
    fact: str
    source_entity: str | None
    target_entity: str | None
    source_types: tuple[str, ...]
    target_types: tuple[str, ...]
    episodes: tuple[str, ...]
    valid_at: str | None
    invalid_at: str | None


@dataclass(frozen=True)
class GraphitiLoadReport:
    """Counts for a resumable sequential episode load."""

    added: int
    skipped: int


class _PassthroughReranker(_CrossEncoderClient):
    """Preserve search order without contacting a reranking service."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        del query
        total = max(len(passages), 1)
        return [
            (passage, (total - index) / total) for index, passage in enumerate(passages)
        ]


class GraphitiRuntime:
    """Lifecycle wrapper around one explicitly configured Graphiti client."""

    def __init__(
        self,
        settings: SpecBrainSettings,
        graphiti: Any,
        service_clients: tuple[Any, ...] = (),
        credential: Any | None = None,
    ) -> None:
        self.settings = settings
        self.graphiti = graphiti
        self.service_clients = service_clients
        self.credential = credential

    @classmethod
    def create(cls, settings: SpecBrainSettings) -> GraphitiRuntime:
        """Create Graphiti without allowing its provider defaults to run."""

        settings.require_graphiti()
        os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
        try:
            from graphiti_core import Graphiti
            from graphiti_core.cross_encoder.openai_reranker_client import (
                OpenAIRerankerClient,
            )
            from graphiti_core.driver.neo4j_driver import Neo4jDriver
            from graphiti_core.embedder.openai import (
                OpenAIEmbedder,
                OpenAIEmbedderConfig,
            )
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_client import OpenAIClient
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise GraphitiDependencyError(
                "the pinned Graphiti runtime dependencies are not installed"
            ) from exc

        authentication, credential = _model_authentication(settings)
        llm_sdk = AsyncOpenAI(
            api_key=authentication,
            base_url=settings.internal_llm_base_url,
        )
        llm_config = LLMConfig(
            api_key=(
                settings.internal_llm_token
                if settings.internal_model_auth == "bearer-token"
                else None
            ),
            model=settings.internal_llm_model,
            small_model=settings.internal_llm_model,
            base_url=settings.internal_llm_base_url,
            temperature=0,
        )
        llm_client = OpenAIClient(config=llm_config, client=llm_sdk)

        embedding_sdk = AsyncOpenAI(
            api_key=authentication,
            base_url=settings.internal_embedding_base_url,
        )
        embedding_config = OpenAIEmbedderConfig(
            api_key=(
                settings.internal_llm_token
                if settings.internal_model_auth == "bearer-token"
                else None
            ),
            base_url=settings.internal_embedding_base_url,
            embedding_model=settings.internal_embedding_model,
            embedding_dim=settings.internal_embedding_dimension,
        )
        embedder = OpenAIEmbedder(
            config=embedding_config,
            client=embedding_sdk,
        )

        if settings.internal_reranker_base_url:
            reranker_sdk = AsyncOpenAI(
                api_key=authentication,
                base_url=settings.internal_reranker_base_url,
            )
            reranker_config = LLMConfig(
                api_key=(
                    settings.internal_llm_token
                    if settings.internal_model_auth == "bearer-token"
                    else None
                ),
                model=settings.internal_reranker_model,
                small_model=settings.internal_reranker_model,
                base_url=settings.internal_reranker_base_url,
                temperature=0,
            )
            cross_encoder: Any = OpenAIRerankerClient(
                config=reranker_config,
                client=reranker_sdk,
            )
        else:
            cross_encoder = _PassthroughReranker()

        graph_driver = Neo4jDriver(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_graphiti_database,
        )
        init_task = getattr(graph_driver, "_init_task", None)
        if init_task is not None:
            init_task.cancel()
            graph_driver._init_task = None
        graphiti = Graphiti(
            graph_driver=graph_driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )
        clients = [llm_sdk, embedding_sdk]
        if settings.internal_reranker_base_url:
            clients.append(reranker_sdk)
        return cls(settings, graphiti, tuple(clients), credential)

    async def check_dependencies(self) -> None:
        """Fail before mutation if Neo4j or an internal model service is down."""

        try:
            await self.graphiti.driver.client.verify_connectivity()
            for client in self.service_clients:
                await client.models.list()
        except Exception as exc:
            raise GraphitiServiceUnavailable(
                "Neo4j or a configured internal model service is unavailable"
            ) from exc

    async def initialize_schema(self) -> None:
        """Create Graphiti-managed indexes without deleting existing data."""

        await self.graphiti.build_indices_and_constraints(delete_existing=False)

    async def add_episodes(
        self, episodes: Iterable[GraphitiEpisode]
    ) -> GraphitiLoadReport:
        """Add episodes sequentially so failures are isolated and resumable."""

        entity_types, edge_types = _graphiti_types()
        added = 0
        skipped = 0
        for episode in sorted(episodes, key=lambda item: (item.order, item.stable_id)):
            try:
                from graphiti_core.nodes import EpisodeType

                if await self._episode_exists(episode.stable_id):
                    skipped += 1
                    continue
                await self.graphiti.add_episode(
                    name=episode.stable_id,
                    episode_body=episode.body,
                    source=EpisodeType.json,
                    source_description=episode.source_description,
                    reference_time=episode.reference_time,
                    group_id=self.settings.graphiti_group_id,
                    entity_types=entity_types,
                    edge_types=edge_types,
                    custom_extraction_instructions=EXTRACTION_INSTRUCTIONS,
                )
                added += 1
            except Exception as exc:
                raise GraphitiIngestionError(
                    f"Graphiti episode failed: {episode.stable_id} "
                    f"({type(exc).__name__}: {exc})"
                ) from exc
        return GraphitiLoadReport(added=added, skipped=skipped)

    async def _episode_exists(self, stable_id: str) -> bool:
        records, _, _ = await self.graphiti.driver.execute_query(
            """
            MATCH (episode:Episodic {group_id: $group_id, name: $name})
            RETURN count(episode) > 0 AS exists
            """,
            group_id=self.settings.graphiti_group_id,
            name=stable_id,
            routing_="r",
        )
        return bool(records and records[0]["exists"])

    async def search(self, request: str) -> tuple[SemanticFact, ...]:
        """Search with the complete change request and enrich endpoint entities."""

        edges = await self.graphiti.search(
            query=request,
            group_ids=[self.settings.graphiti_group_id],
            num_results=self.settings.max_semantic_results,
        )
        entity_ids = sorted(
            {
                entity_id
                for edge in edges
                for entity_id in (edge.source_node_uuid, edge.target_node_uuid)
            }
        )
        entities = await self.graphiti.nodes.entity.get_by_uuids(entity_ids)
        by_id = {entity.uuid: entity for entity in entities}
        facts: list[SemanticFact] = []
        for edge in edges:
            source = by_id.get(edge.source_node_uuid)
            target = by_id.get(edge.target_node_uuid)
            facts.append(
                SemanticFact(
                    stable_id=edge.uuid,
                    fact=edge.fact,
                    source_entity=getattr(source, "name", None),
                    target_entity=getattr(target, "name", None),
                    source_types=tuple(getattr(source, "labels", ()) or ()),
                    target_types=tuple(getattr(target, "labels", ()) or ()),
                    episodes=tuple(edge.episodes or ()),
                    valid_at=_iso_or_none(edge.valid_at),
                    invalid_at=_iso_or_none(edge.invalid_at),
                )
            )
        return tuple(facts)

    async def close(self) -> None:
        """Release Graphiti's Neo4j driver."""

        await self.graphiti.close()
        for client in self.service_clients:
            await client.close()
        if self.credential is not None:
            self.credential.close()


def build_episodes(
    entries: Iterable[ManifestEntry], reference_time: datetime
) -> tuple[GraphitiEpisode, ...]:
    """Build ordered semantic episodes from canonical manifest records."""

    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("reference_time must include a timezone")
    episodes: list[GraphitiEpisode] = []
    for entry in entries:
        if not isinstance(entry, ManifestNode):
            continue
        payload: dict[str, Any]
        if entry.record_type == "claim" and entry.statement:
            order = 5
            payload = {
                "stable_id": entry.stable_id,
                "title": entry.name,
                "artifact_kind": entry.artifact_kind,
                "documentation_priority": entry.documentation_priority,
                "review_status": entry.review_status,
                "page_path": entry.page_path,
                "statement": entry.statement,
            }
        elif (
            entry.record_type == "service"
            and entry.body
            and entry.properties.get("semantic_episode") is True
        ):
            order = 0
            payload = {
                "stable_id": entry.stable_id,
                "title": entry.name,
                "artifact_kind": entry.artifact_kind,
                "documentation_priority": entry.documentation_priority,
                "review_status": entry.review_status,
                "knowledge_plane_id": entry.properties.get("knowledge_plane_id"),
                "service_id": entry.properties.get("service_id"),
                "descriptor_path": entry.properties.get("descriptor_path"),
                "topology": json.loads(entry.body),
            }
        elif (
            entry.record_type == "section"
            and entry.body
            and entry.properties.get("semantic_episode") is True
        ):
            order = _episode_order(entry)
            payload = {
                "stable_id": entry.stable_id,
                "title": entry.name,
                "artifact_kind": entry.artifact_kind,
                "documentation_priority": entry.documentation_priority,
                "review_status": entry.review_status,
                "relative_path": entry.relative_path,
                "heading_path": list(entry.heading_path),
                "body": entry.body,
                "mentioned_paths": list(entry.mentioned_paths),
                "mentioned_tests": list(entry.mentioned_tests),
            }
        else:
            continue
        episodes.append(
            GraphitiEpisode(
                stable_id=entry.stable_id,
                name=entry.name or entry.stable_id,
                body=json.dumps(payload, sort_keys=True, ensure_ascii=False),
                source_description=(
                    "repository specification knowledge; "
                    f"priority={entry.documentation_priority}"
                ),
                reference_time=reference_time,
                order=order,
            )
        )
    return tuple(sorted(episodes, key=lambda item: (item.order, item.stable_id)))


def select_smoke_episodes(
    episodes: Iterable[GraphitiEpisode],
) -> tuple[GraphitiEpisode, ...]:
    """Select one primary and one secondary episode for a bounded smoke test."""

    materialized = tuple(episodes)
    hld = [episode for episode in materialized if episode.order == 1]
    primary_candidates = hld or [
        episode for episode in materialized if episode.order <= 4
    ]
    primary = next(
        (
            episode
            for episode in primary_candidates
            if episode.stable_id.endswith("/1-executive-summary")
        ),
        None,
    )
    if primary is None:
        primary = max(
            primary_candidates,
            key=lambda episode: len(episode.body),
            default=None,
        )
    secondary = next((episode for episode in materialized if episode.order >= 5), None)
    if primary is None or secondary is None:
        raise ValueError("smoke ingestion requires primary and secondary episodes")
    return primary, secondary


def _episode_order(node: ManifestNode) -> int:
    if node.artifact_kind == "HLD":
        return 1
    if node.artifact_kind == "LLD":
        return 2
    if node.artifact_kind == "folder-spec":
        return 3
    if node.artifact_kind == "relationship-map":
        return 4
    return 6


def _graphiti_types() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from pydantic import create_model
    except ImportError as exc:
        raise GraphitiDependencyError("pydantic is required by Graphiti") from exc
    entity_types = {
        name: create_model(
            name,
            repository_evidence=(str | None, None),
            uncertainty=(str | None, None),
        )
        for name in ENTITY_TYPE_NAMES
    }
    edge_types = {
        name: create_model(
            name,
            repository_evidence=(str | None, None),
            uncertainty=(str | None, None),
        )
        for name in EDGE_TYPE_NAMES
    }
    return entity_types, edge_types


def _model_authentication(settings: SpecBrainSettings) -> tuple[Any, Any | None]:
    if settings.internal_model_auth == "bearer-token":
        return settings.internal_llm_token, None
    try:
        from azure.identity import (
            DefaultAzureCredential,
            get_bearer_token_provider,
        )
    except ImportError as exc:
        raise GraphitiDependencyError(
            "azure-identity is required for Entra ID authentication"
        ) from exc
    credential = DefaultAzureCredential()
    provider = get_bearer_token_provider(
        credential, settings.internal_azure_token_scope
    )

    async def async_provider() -> str:
        return provider()

    return async_provider, credential


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
