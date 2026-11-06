"""Validated configuration for the specification evidence server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aide_architecture_mcp.config import ArchitectureSettings
from aide_knowledge_mcp.config import ConfigurationError, Settings


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _required_directory(root: Path, variable: str, default: str) -> Path:
    configured = Path(os.getenv(variable, default)).expanduser()
    candidate = configured if configured.is_absolute() else root / configured
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ConfigurationError(f"{variable} must resolve inside the repository")
    if resolved.exists() and not resolved.is_dir():
        raise ConfigurationError(f"{variable} must identify a directory: {resolved}")
    return resolved


def _optional_directory(root: Path, variable: str, default: str) -> Path:
    configured = Path(os.getenv(variable, default)).expanduser()
    candidate = configured if configured.is_absolute() else root / configured
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ConfigurationError(f"{variable} must resolve inside the repository")
    if resolved == root:
        raise ConfigurationError(f"{variable} must be a repository subdirectory")
    if resolved.exists() and not resolved.is_dir():
        raise ConfigurationError(f"{variable} must identify a directory")
    return resolved


@dataclass(frozen=True)
class SpecSettings:
    """Repository boundaries and limits for specification assistance."""

    architecture: ArchitectureSettings
    story_directory: Path
    max_story_bytes: int = 2_000_000
    max_read_lines: int = 1_000
    max_document_chars: int = 200_000

    @property
    def repository_root(self) -> Path:
        """Return the shared repository root."""
        return self.architecture.knowledge.repository_root

    @classmethod
    def from_environment(cls) -> SpecSettings:
        """Build a repository-bound configuration from environment variables."""
        inferred_root = Path(__file__).resolve().parents[3]
        root = Path(os.getenv("AIDE_SPEC_ROOT", str(inferred_root))).expanduser()
        root = root.resolve()
        if not root.is_dir():
            raise ConfigurationError(f"AIDE_SPEC_ROOT directory does not exist: {root}")

        max_context_chars = _bounded_int(
            "AIDE_SPEC_MAX_CONTEXT_CHARS",
            50_000,
            2_000,
            150_000,
        )
        knowledge = Settings(
            repository_root=root,
            primary_directory=_required_directory(
                root,
                "AIDE_SPEC_PRIMARY_DIR",
                "knowledge-base",
            ),
            secondary_directory=_required_directory(
                root,
                "AIDE_SPEC_SECONDARY_DIR",
                "openwiki",
            ),
            max_file_bytes=_bounded_int(
                "AIDE_SPEC_MAX_FILE_BYTES",
                4_000_000,
                1_024,
                20_000_000,
            ),
            max_section_chars=_bounded_int(
                "AIDE_SPEC_MAX_SECTION_CHARS",
                12_000,
                1_000,
                100_000,
            ),
            max_excerpt_chars=_bounded_int(
                "AIDE_SPEC_MAX_EXCERPT_CHARS",
                1_800,
                200,
                10_000,
            ),
            max_read_lines=_bounded_int(
                "AIDE_SPEC_MAX_KNOWLEDGE_READ_LINES",
                600,
                10,
                2_000,
            ),
            max_context_chars=max_context_chars,
        )
        return cls(
            architecture=ArchitectureSettings(knowledge=knowledge),
            story_directory=_optional_directory(
                root,
                "AIDE_SPEC_STORY_DIR",
                "jira",
            ),
            max_story_bytes=_bounded_int(
                "AIDE_SPEC_MAX_STORY_BYTES",
                2_000_000,
                1_024,
                10_000_000,
            ),
            max_read_lines=_bounded_int(
                "AIDE_SPEC_MAX_READ_LINES",
                1_000,
                10,
                5_000,
            ),
            max_document_chars=_bounded_int(
                "AIDE_SPEC_MAX_DOCUMENT_CHARS",
                200_000,
                2_000,
                1_000_000,
            ),
        )
