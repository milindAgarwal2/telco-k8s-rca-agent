"""Read-only repository profile discovery and project mapping."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .util import iter_repository_files, normalize_relative


@dataclass(frozen=True)
class Profile:
    """A composable repository profile discovered from file names only."""

    name: str
    markers: tuple[str, ...]
    evidence: tuple[str, ...] = field(default_factory=tuple)


PROFILE_MARKERS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "*.py"),
    "java": (
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle*",
        "*.java",
    ),
    "go": ("go.mod", "go.work", "*.go"),
    "kotlin": ("build.gradle.kts", "settings.gradle.kts", "*.kt", "*.kts"),
    "php": ("composer.json", "*.php"),
    "rust": ("Cargo.toml", "Cargo.lock", "*.rs"),
    "angular": ("angular.json", "*.component.ts", "*.module.ts"),
    "bash": ("*.sh",),
    "ansible": (
        "ansible.cfg",
        "playbook*.yml",
        "playbook*.yaml",
        "roles/*/tasks/*.yml",
    ),
    "postman": ("*.postman_collection.json", "postman/*.json"),
    "kubernetes": (
        "kustomization.yaml",
        "kustomization.yml",
        "Chart.yaml",
        "manifests/*.yaml",
    ),
    "gitops": (".flux.yaml", "clusters/*", "environments/*", "gitops/*"),
    "fluxcd": (
        "clusters/*/flux-system/*",
        "**/gotk-components.yaml",
        "**/gotk-sync.yaml",
    ),
}


def _matches(relative: str, marker: str) -> bool:
    """Match a portable path against a profile marker."""

    return fnmatch.fnmatch(relative, marker) or fnmatch.fnmatch(
        Path(relative).name, marker
    )


def detect_profiles(root: Path) -> dict[str, Any]:
    """Inspect names only; never import, execute, or parse project code."""

    root = root.resolve(strict=True)
    evidence: dict[str, list[str]] = {name: [] for name in PROFILE_MARKERS}
    modules: dict[str, set[str]] = {}
    for relative, _path in iter_repository_files(root):
        if relative.startswith((".aide/", ".kiro/")):
            continue
        for name, markers in PROFILE_MARKERS.items():
            if any(_matches(relative, marker) for marker in markers):
                evidence[name].append(relative)
                module = relative.split("/", 1)[0] if "/" in relative else "."
                modules.setdefault(module, set()).add(name)
    selected = sorted(name for name, paths in evidence.items() if paths)
    if len(selected) > 1:
        selected.append("mixed")
    return {
        "profiles": selected,
        "evidence": {
            name: sorted(paths)[:25] for name, paths in evidence.items() if paths
        },
        "modules": [
            {"path": path, "profiles": sorted(names)}
            for path, names in sorted(modules.items())
        ],
        "method": "filename-and-directory-markers-only",
        "executed_repository_code": False,
    }


def load_profile(path: Path) -> dict[str, Any]:
    """Load and minimally validate a profile descriptor."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid profile descriptor {path}: {exc}") from exc
    if value.get("schema_version") != 1 or not value.get("name"):
        raise ConfigurationError(f"Unsupported profile descriptor: {path}")
    for mapping in value.get("module_mappings", []):
        normalize_relative(mapping["path"])
    return value
