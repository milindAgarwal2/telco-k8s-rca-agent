"""Validated environment configuration for the specification brain."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when a required setting is absent or internally inconsistent."""


def _optional_text(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", value):
        return None
    return value or None


def _first_text(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = _optional_text(env, name)
        if value is not None:
            return value
    return None


def _positive_int(env: Mapping[str, str], name: str, default: int | None) -> int | None:
    raw = _optional_text(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _project_id(env: Mapping[str, str]) -> str:
    """Return a stable, Graphiti-safe project namespace."""

    configured = _optional_text(env, "SPEC_BRAIN_PROJECT_ID")
    if configured is not None:
        candidate = configured
    else:
        root = _optional_text(env, "SPEC_BRAIN_ROOT")
        candidate = Path(root).resolve().name if root else Path.cwd().resolve().name
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", candidate).strip("-_")
    if not normalized:
        raise ConfigurationError(
            "SPEC_BRAIN_PROJECT_ID must contain a letter, digit, dash, or underscore"
        )
    return normalized.lower()


def _knowledge_plane_id(env: Mapping[str, str], project_id: str) -> str:
    """Return the configured or descriptor-derived federation namespace."""

    configured = _optional_text(env, "SPEC_BRAIN_KNOWLEDGE_PLANE_ID")
    if configured is None:
        root = Path(_optional_text(env, "SPEC_BRAIN_ROOT") or Path.cwd()).resolve()
        descriptor = root / "knowledge-base" / "knowledge-plane.json"
        if descriptor.is_file():
            try:
                payload = json.loads(descriptor.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigurationError(
                    f"invalid knowledge-plane descriptor: {descriptor}"
                ) from exc
            if isinstance(payload, dict):
                value = payload.get("knowledge_plane")
                configured = value.strip() if isinstance(value, str) else None
    candidate = configured or project_id
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", candidate).strip("-_")
    if not normalized:
        raise ConfigurationError(
            "SPEC_BRAIN_KNOWLEDGE_PLANE_ID must contain a letter, digit, "
            "dash, or underscore"
        )
    return normalized.lower()


@dataclass(frozen=True)
class SpecBrainSettings:
    """Settings for exact-graph, semantic-graph, and context operations."""

    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = field(default=None, repr=False)
    project_id: str = "project"
    knowledge_plane_id: str = "project"
    neo4j_kb_database: str = "neo4j"
    neo4j_graphiti_database: str = "neo4j"
    graphiti_group_id: str = "project-main"
    internal_llm_base_url: str | None = None
    internal_llm_model: str | None = None
    internal_llm_token: str | None = field(default=None, repr=False)
    internal_model_auth: str = "bearer-token"
    internal_azure_token_scope: str = "https://ai.azure.com/.default"
    internal_embedding_base_url: str | None = None
    internal_embedding_model: str | None = None
    internal_embedding_dimension: int | None = None
    internal_reranker_base_url: str | None = None
    internal_reranker_model: str | None = None
    max_context_tokens: int | None = None
    max_semantic_results: int = 12
    max_relationship_depth: int = 2

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SpecBrainSettings:
        """Load settings without silently inventing service credentials.

        Args:
            env: Environment mapping. The process environment is used by default.

        Returns:
            A validated settings object. Component-specific required values are
            checked by :meth:`require_exact` and :meth:`require_graphiti`.
        """

        values = os.environ if env is None else env
        reranker_base = _optional_text(values, "INTERNAL_RERANKER_BASE_URL")
        reranker_model = _optional_text(values, "INTERNAL_RERANKER_MODEL")
        model_auth = _optional_text(values, "INTERNAL_MODEL_AUTH") or "bearer-token"
        if model_auth not in {"bearer-token", "azure-identity"}:
            raise ConfigurationError(
                "INTERNAL_MODEL_AUTH must be bearer-token or azure-identity"
            )
        project_id = _project_id(values)
        knowledge_plane_id = _knowledge_plane_id(values, project_id)
        group_id = (
            _optional_text(values, "GRAPHITI_GROUP_ID") or f"{knowledge_plane_id}-main"
        )
        if re.fullmatch(r"[A-Za-z0-9_-]+", group_id) is None:
            raise ConfigurationError(
                "GRAPHITI_GROUP_ID may contain only letters, digits, dashes, "
                "and underscores"
            )
        if bool(reranker_base) != bool(reranker_model):
            raise ConfigurationError(
                "INTERNAL_RERANKER_BASE_URL and INTERNAL_RERANKER_MODEL "
                "must be configured together"
            )
        return cls(
            project_id=project_id,
            knowledge_plane_id=knowledge_plane_id,
            neo4j_uri=_optional_text(values, "NEO4J_URI"),
            neo4j_user=_first_text(values, "NEO4J_USER", "NEO4J_USERNAME"),
            neo4j_password=_optional_text(values, "NEO4J_PASSWORD"),
            neo4j_kb_database=(
                _first_text(values, "NEO4J_KB_DATABASE", "NEO4J_DATABASE") or "neo4j"
            ),
            neo4j_graphiti_database=(
                _first_text(
                    values,
                    "NEO4J_GRAPHITI_DATABASE",
                    "NEO4J_DATABASE",
                )
                or "neo4j"
            ),
            graphiti_group_id=group_id,
            internal_llm_base_url=_optional_text(values, "INTERNAL_LLM_BASE_URL"),
            internal_llm_model=_optional_text(values, "INTERNAL_LLM_MODEL"),
            internal_llm_token=_optional_text(values, "INTERNAL_LLM_TOKEN"),
            internal_model_auth=model_auth,
            internal_azure_token_scope=(
                _optional_text(values, "INTERNAL_AZURE_TOKEN_SCOPE")
                or "https://ai.azure.com/.default"
            ),
            internal_embedding_base_url=_optional_text(
                values, "INTERNAL_EMBEDDING_BASE_URL"
            ),
            internal_embedding_model=_optional_text(values, "INTERNAL_EMBEDDING_MODEL"),
            internal_embedding_dimension=_positive_int(
                values, "INTERNAL_EMBEDDING_DIMENSION", None
            ),
            internal_reranker_base_url=reranker_base,
            internal_reranker_model=reranker_model,
            max_context_tokens=_positive_int(
                values, "SPEC_BRAIN_MAX_CONTEXT_TOKENS", None
            ),
            max_semantic_results=_positive_int(
                values, "SPEC_BRAIN_MAX_SEMANTIC_RESULTS", 12
            )
            or 12,
            max_relationship_depth=_positive_int(
                values, "SPEC_BRAIN_MAX_RELATIONSHIP_DEPTH", 2
            )
            or 2,
        )

    def require_exact(self) -> None:
        """Require all values needed to connect to the exact Neo4j graph."""

        self._require(
            "exact Neo4j graph",
            NEO4J_URI=self.neo4j_uri,
            NEO4J_USER=self.neo4j_user,
            NEO4J_PASSWORD=self.neo4j_password,
            NEO4J_KB_DATABASE=self.neo4j_kb_database,
        )

    def require_graphiti(self) -> None:
        """Require explicit internal services needed by Graphiti."""

        self.require_exact()
        required = {
            "NEO4J_GRAPHITI_DATABASE": self.neo4j_graphiti_database,
            "INTERNAL_LLM_BASE_URL": self.internal_llm_base_url,
            "INTERNAL_LLM_MODEL": self.internal_llm_model,
            "INTERNAL_EMBEDDING_BASE_URL": self.internal_embedding_base_url,
            "INTERNAL_EMBEDDING_MODEL": self.internal_embedding_model,
            "INTERNAL_EMBEDDING_DIMENSION": self.internal_embedding_dimension,
        }
        if self.internal_model_auth == "bearer-token":
            required["INTERNAL_LLM_TOKEN"] = self.internal_llm_token
        else:
            required["INTERNAL_AZURE_TOKEN_SCOPE"] = self.internal_azure_token_scope
        self._require(
            "Graphiti",
            **required,
        )

    def require_query(self) -> None:
        """Require every setting needed to produce a bounded context package."""

        self.require_graphiti()
        self._require(
            "bounded context composition",
            SPEC_BRAIN_MAX_CONTEXT_TOKENS=self.max_context_tokens,
        )

    def redacted_summary(self) -> dict[str, object]:
        """Return configuration state without returning secret values."""

        return {
            "project_id": self.project_id,
            "knowledge_plane_id": self.knowledge_plane_id,
            "neo4j_uri_configured": self.neo4j_uri is not None,
            "neo4j_user_configured": self.neo4j_user is not None,
            "neo4j_password_configured": self.neo4j_password is not None,
            "neo4j_kb_database": self.neo4j_kb_database,
            "neo4j_graphiti_database": self.neo4j_graphiti_database,
            "graphiti_group_id": self.graphiti_group_id,
            "internal_llm_base_url_configured": (
                self.internal_llm_base_url is not None
            ),
            "internal_llm_model": self.internal_llm_model,
            "internal_model_auth": self.internal_model_auth,
            "internal_llm_token_configured": self.internal_llm_token is not None,
            "internal_embedding_base_url_configured": (
                self.internal_embedding_base_url is not None
            ),
            "internal_embedding_model": self.internal_embedding_model,
            "internal_embedding_dimension": self.internal_embedding_dimension,
            "internal_reranker_enabled": (self.internal_reranker_base_url is not None),
            "max_context_tokens": self.max_context_tokens,
            "max_semantic_results": self.max_semantic_results,
            "max_relationship_depth": self.max_relationship_depth,
        }

    @staticmethod
    def _require(component: str, **values: object) -> None:
        missing = [name for name, value in values.items() if value is None]
        if missing:
            names = ", ".join(sorted(missing))
            raise ConfigurationError(f"{component} requires: {names}")
