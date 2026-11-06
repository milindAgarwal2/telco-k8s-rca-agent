"""Filesystem, hashing, Git, and process primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ConfigurationError, SafetyError

REPARSE_POINT = 0x400
DEFAULT_EXCLUDES = {
    ".git",
    ".aide/local",
    ".venv",
    "node_modules",
    "build",
    "dist",
    "target",
}

WINDOWS_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.35, 0.5, 0.5, 0.5)


def utc_now() -> str:
    """Return a stable UTC timestamp."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    """Serialize JSON deterministically."""

    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def read_json(path: Path) -> Any:
    """Read JSON with a path-specific error."""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Required JSON file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read valid JSON from {path}: {exc}") from exc


def sha256_bytes(content: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a regular file without following an unsafe replacement."""

    if not path.is_file() or path.is_symlink():
        raise SafetyError(f"Expected a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_value(value: Any) -> str:
    """Hash a JSON-compatible value."""

    return sha256_bytes(canonical_json(value))


def normalize_relative(value: str) -> str:
    """Normalize and validate a portable repository-relative path."""

    if not isinstance(value, str) or not value.strip():
        raise SafetyError("A non-empty relative path is required.")
    raw = value.replace("\\", "/")
    if "\x00" in raw or re.match(r"^[A-Za-z]:", raw) or raw.startswith("/"):
        raise SafetyError(f"Absolute or invalid path is not allowed: {value}")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SafetyError(f"Path traversal or ambiguous path is not allowed: {value}")
    return path.as_posix()


def is_reparse_point(path: Path) -> bool:
    """Return whether a path is a Windows reparse point or a symlink."""

    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & REPARSE_POINT)


def safe_join(root: Path, relative: str, *, allow_leaf_missing: bool = True) -> Path:
    """Resolve an owned target while rejecting traversal and reparse parents."""

    normalized = normalize_relative(relative)
    root = root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.exists() and is_reparse_point(current):
            raise SafetyError(f"Refusing path through symlink or junction: {current}")
    if candidate.exists():
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SafetyError(f"Target escapes repository root: {candidate}") from exc
    elif not allow_leaf_missing:
        raise SafetyError(f"Required target does not exist: {candidate}")
    return candidate


def find_git_root(start: Path) -> Path:
    """Resolve the Git worktree root without invoking a shell."""

    start = start.resolve(strict=True)
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError(f"Cannot execute Git preflight: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ConfigurationError(f"Target is not a Git worktree: {start}: {detail}")
    root = Path(result.stdout.strip()).resolve(strict=True)
    if is_reparse_point(root):
        raise SafetyError(f"Git root must not be a symlink or junction: {root}")
    return root


def git_revision(root: Path) -> str:
    """Return the current immutable Git commit identifier."""

    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise ConfigurationError(
            f"Cannot resolve HEAD for {root}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def git_changed_paths(root: Path) -> list[str]:
    """Return changed and untracked paths without altering the worktree."""

    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        ],
        check=False,
        capture_output=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise ConfigurationError("Cannot inspect Git worktree status.")
    paths: list[str] = []
    entries = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    for entry in entries:
        if not entry:
            continue
        body = entry[3:] if len(entry) >= 4 else entry
        if " -> " in body:
            body = body.split(" -> ", 1)[1]
        paths.append(body.replace("\\", "/"))
    return sorted(set(paths))


def iter_repository_files(root: Path) -> Iterable[tuple[str, Path]]:
    """Yield regular files without following links or common generated trees."""

    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root).as_posix()
        kept_names = []
        for name in names:
            child = directory_path / name
            rel = child.relative_to(root).as_posix()
            if (
                name == ".git"
                or rel == ".aide/local"
                or name
                in {
                    ".venv",
                    "node_modules",
                    "build",
                    "dist",
                    "target",
                }
            ):
                continue
            if is_reparse_point(child):
                continue
            kept_names.append(name)
        names[:] = kept_names
        for name in files:
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if relative_directory.startswith(".aide/local"):
                continue
            yield rel, path


def fingerprint_paths(root: Path, relative_paths: Iterable[str]) -> str:
    """Hash path names and contents for a stable artifact fingerprint."""

    digest = hashlib.sha256()
    for relative in sorted({normalize_relative(path) for path in relative_paths}):
        path = safe_join(root, relative, allow_leaf_missing=False)
        if not path.is_file():
            raise SafetyError(f"Fingerprint target is not a file: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def repository_snapshot(root: Path) -> dict[str, str]:
    """Capture a deterministic repository file snapshot for scope checks."""

    snapshot: dict[str, str] = {}
    for relative, path in iter_repository_files(root):
        snapshot[relative] = sha256_file(path)
    return snapshot


def atomic_write(path: Path, content: bytes) -> None:
    """Replace one file atomically in its directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _replace_with_retry(source: Path, destination: Path) -> None:
    """Replace a file, tolerating brief Windows scanner or indexer locks."""

    for delay in (*WINDOWS_REPLACE_RETRY_DELAYS, None):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def command_exists(executable: str) -> bool:
    """Check an executable without running it."""

    return shutil.which(executable) is not None


def redact(value: Any) -> Any:
    """Recursively redact values whose keys indicate credentials."""

    sensitive = re.compile(r"token|secret|password|credential|api[_-]?key", re.I)
    if isinstance(value, dict):
        return {
            key: "<redacted>" if sensitive.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class FileTransaction:
    """Rollback local file writes if an installer operation fails."""

    def __init__(self) -> None:
        self._originals: dict[Path, bytes | None] = {}
        self._order: list[Path] = []

    def write(self, path: Path, content: bytes) -> None:
        """Write a file after capturing its original bytes once."""

        if path.exists() and is_reparse_point(path):
            raise SafetyError(f"Refusing to replace symlink or junction: {path}")
        if path not in self._originals:
            self._originals[path] = path.read_bytes() if path.exists() else None
            self._order.append(path)
        atomic_write(path, content)

    def remove(self, path: Path) -> None:
        """Remove an owned regular file while retaining rollback bytes."""

        if path.exists() and is_reparse_point(path):
            raise SafetyError(f"Refusing to remove symlink or junction: {path}")
        if path not in self._originals:
            self._originals[path] = path.read_bytes() if path.exists() else None
            self._order.append(path)
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise SafetyError(f"Refusing to remove non-regular file: {path}")
            path.unlink()

    def rollback(self) -> None:
        """Restore files in reverse order."""

        for path in reversed(self._order):
            original = self._originals[path]
            if original is None:
                if path.exists() and path.is_file() and not path.is_symlink():
                    path.unlink()
            else:
                atomic_write(path, original)


def ensure_python_supported() -> None:
    """Require the standard-library baseline runtime."""

    import sys

    if sys.version_info < (3, 11):  # noqa: UP036
        raise ConfigurationError("AIDE baseline requires Python 3.11 or newer.")
