"""Validated architecture-server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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


def _source_directory(root: Path, variable: str, default: str) -> Path:
    configured = Path(os.getenv(variable, default)).expanduser()
    candidate = configured if configured.is_absolute() else root / configured
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ConfigurationError(f"{variable} must resolve inside the repository")
    if resolved.exists() and not resolved.is_dir():
        raise ConfigurationError(f"{variable} must identify a directory: {resolved}")
    return resolved


@dataclass(frozen=True)
class ArchitectureSettings:
    """Architecture-specific wrapper around the shared knowledge settings."""

    knowledge: Settings

    @classmethod
    def from_environment(cls) -> ArchitectureSettings:
        """Build repository-bound architecture settings from the environment."""
        inferred_root = Path(__file__).resolve().parents[3]
        root = (
            Path(os.getenv("AIDE_ARCHITECTURE_ROOT", str(inferred_root)))
            .expanduser()
            .resolve()
        )
        if not root.is_dir():
            raise ConfigurationError(
                f"AIDE_ARCHITECTURE_ROOT directory does not exist: {root}"
            )
        max_context_chars = _bounded_int(
            "AIDE_ARCHITECTURE_MAX_CONTEXT_CHARS",
            40_000,
            2_000,
            120_000,
        )
        knowledge = Settings(
            repository_root=root,
            primary_directory=_source_directory(
                root,
                "AIDE_ARCHITECTURE_PRIMARY_DIR",
                "knowledge-base",
            ),
            secondary_directory=_source_directory(
                root,
                "AIDE_ARCHITECTURE_SECONDARY_DIR",
                "openwiki",
            ),
            max_file_bytes=_bounded_int(
                "AIDE_ARCHITECTURE_MAX_FILE_BYTES",
                4_000_000,
                1_024,
                20_000_000,
            ),
            max_section_chars=_bounded_int(
                "AIDE_ARCHITECTURE_MAX_SECTION_CHARS",
                12_000,
                1_000,
                100_000,
            ),
            max_excerpt_chars=_bounded_int(
                "AIDE_ARCHITECTURE_MAX_EXCERPT_CHARS",
                1_800,
                200,
                10_000,
            ),
            max_read_lines=_bounded_int(
                "AIDE_ARCHITECTURE_MAX_READ_LINES",
                500,
                10,
                2_000,
            ),
            max_context_chars=max_context_chars,
        )
        return cls(knowledge=knowledge)
