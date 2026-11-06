from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "policy_version": "1.0",
    "scanner": {
        "exclude_directories": [
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "dist",
            "build",
            "target",
            ".idea",
            ".vscode",
            "__pycache__",
        ],
        "source_evidence": True,
        "max_source_files": 5000,
    },
    "catalog": {
        "mode": "file",
        "path": "config/sample-scss-catalog.json",
        "timeout_seconds": 20,
        "verify_tls": True,
        "maven_coordinate_fallback": True,
    },
    "job": {
        "heartbeat_interval_seconds": 5,
        "stale_after_seconds": 120,
        "estimated_seconds_per_item": 2.0,
        "estimated_report_overhead_seconds": 5.0,
        "projection_list_limit": 100,
    },
    "policy": {
        "approved_statuses": ["approved", "available", "active", "green"],
        "warning_statuses": ["conditional", "amber", "maintenance"],
        "review_statuses": ["review", "yellow", "unknown"],
        "denied_statuses": [
            "denied",
            "prohibited",
            "unavailable",
            "deprecated",
            "eol",
            "red",
        ],
        "unknown_component_status": "red",
        "unknown_version_status": "yellow",
        "catalog_error_status": "grey",
        "whitelisted_component_patterns": [
            "docker.artifactory.rosetta*",
            "docker.artifactory.rosetta.ericssondevops.com/*",
        ],
    },
}


def load_config(path: str | Path | None) -> dict[str, Any]:
    config = _deep_copy(DEFAULT_CONFIG)
    if path is None:
        return config

    config_path = Path(path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        loaded = json.loads(text)
    elif config_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "YAML configuration requires PyYAML; use JSON or install PyYAML."
            ) from exc
        loaded = yaml.safe_load(text)
    else:
        raise ValueError("Configuration must be JSON or YAML.")

    if not isinstance(loaded, dict):
        raise ValueError("Configuration root must be an object.")
    _deep_merge(config, loaded)
    config["_config_directory"] = str(config_path.parent)
    return config


def resolve_config_path(config: dict[str, Any], value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    config_directory = config.get("_config_directory")
    if config_directory:
        return (Path(config_directory) / candidate).resolve()
    return candidate.resolve()


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))
