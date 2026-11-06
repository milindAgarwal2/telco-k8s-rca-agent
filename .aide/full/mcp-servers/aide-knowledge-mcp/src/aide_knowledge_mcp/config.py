"""Validated runtime configuration for the knowledge server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when a configured knowledge boundary is unsafe or unavailable."""


def _bounded_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
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


def _resolve_source(root: Path, name: str, default: str) -> Path:
    configured = Path(os.getenv(name, default)).expanduser()
    candidate = configured if configured.is_absolute() else root / configured
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ConfigurationError(f"{name} must resolve inside AIDE_KNOWLEDGE_ROOT")
    if resolved.exists() and not resolved.is_dir():
        raise ConfigurationError(f"{name} must identify a directory: {resolved}")
    return resolved


@dataclass(frozen=True)
class Settings:
    """Immutable source boundaries and response limits."""

    repository_root: Path
    primary_directory: Path
    secondary_directory: Path
    max_file_bytes: int = 4_000_000
    max_section_chars: int = 12_000
    max_excerpt_chars: int = 1_600
    max_read_lines: int = 400
    max_context_chars: int = 30_000

    @classmethod
    def from_environment(cls) -> Settings:
        """Load and validate configuration from environment variables."""
        inferred_root = Path(__file__).resolve().parents[3]
        root = (
            Path(os.getenv("AIDE_KNOWLEDGE_ROOT", str(inferred_root)))
            .expanduser()
            .resolve()
        )
        if not root.is_dir():
            raise ConfigurationError(
                f"AIDE_KNOWLEDGE_ROOT directory does not exist: {root}"
            )

        return cls(
            repository_root=root,
            primary_directory=_resolve_source(
                root,
                "AIDE_KNOWLEDGE_PRIMARY_DIR",
                "knowledge-base",
            ),
            secondary_directory=_resolve_source(
                root,
                "AIDE_KNOWLEDGE_SECONDARY_DIR",
                "openwiki",
            ),
            max_file_bytes=_bounded_int(
                "AIDE_KNOWLEDGE_MAX_FILE_BYTES",
                4_000_000,
                1_024,
                20_000_000,
            ),
            max_section_chars=_bounded_int(
                "AIDE_KNOWLEDGE_MAX_SECTION_CHARS",
                12_000,
                1_000,
                100_000,
            ),
            max_excerpt_chars=_bounded_int(
                "AIDE_KNOWLEDGE_MAX_EXCERPT_CHARS",
                1_600,
                200,
                10_000,
            ),
            max_read_lines=_bounded_int(
                "AIDE_KNOWLEDGE_MAX_READ_LINES",
                400,
                10,
                2_000,
            ),
            max_context_chars=_bounded_int(
                "AIDE_KNOWLEDGE_MAX_CONTEXT_CHARS",
                30_000,
                2_000,
                100_000,
            ),
        )
