"""Install a pinned LeanCTX executable in ignored workspace-local AIDE state."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import subprocess
import tarfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError, VerificationError
from .util import safe_join

VERSION = "3.10.2"
RELEASE_URL = "https://github.com/yvgude/lean-ctx/releases/download/v3.10.2/"
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_BINARY_BYTES = 160 * 1024 * 1024

# SHA-256 values published with the upstream v3.10.2 release assets.
ASSETS = {
    ("Windows", "x86_64"): (
        "lean-ctx-x86_64-pc-windows-msvc.zip",
        "74cf6cddaa42650bd29c21acfcb58e7b9d89b62986e4434f9b45130e1caa68f6",
    ),
    ("Linux", "x86_64"): (
        "lean-ctx-x86_64-unknown-linux-gnu.tar.gz",
        "0c723284eb889c359682080878fc56515ae03ff7742b98d7e56fa8a35bbff2fe",
    ),
    ("Linux", "aarch64"): (
        "lean-ctx-aarch64-unknown-linux-gnu.tar.gz",
        "a7d039950b23535ed56fe0772832508ba91f90ee31076dab99524cbb14c1fa16",
    ),
    ("Darwin", "x86_64"): (
        "lean-ctx-x86_64-apple-darwin.tar.gz",
        "ebe13f471247590bb3ca043b05f5f0420f218ba49d9ab492922444df00794289",
    ),
    ("Darwin", "aarch64"): (
        "lean-ctx-aarch64-apple-darwin.tar.gz",
        "a1dac301a77234520729f1451af7959d6bdc1db56856123028398cb06d670615",
    ),
}


@dataclass(frozen=True)
class LeanCtxAsset:
    archive_name: str
    sha256: str
    binary_name: str

    @property
    def url(self) -> str:
        return RELEASE_URL + self.archive_name

    @property
    def archive_relative(self) -> str:
        return ".aide/local/lean-ctx/" + self.archive_name

    @property
    def binary_relative(self) -> str:
        return ".aide/local/lean-ctx/" + self.binary_name

    @property
    def mcp_command(self) -> str:
        return "./" + self.binary_relative


def current_asset() -> LeanCtxAsset:
    """Choose the pinned upstream archive for this machine."""

    machine = platform.machine().lower()
    if machine in {"amd64", "x64"}:
        machine = "x86_64"
    elif machine in {"arm64", "armv8"}:
        machine = "aarch64"
    key = (platform.system(), machine)
    if key not in ASSETS:
        raise ConfigurationError(
            "Extended LeanCTX installation does not support this platform: "
            + "/".join(key)
        )
    name, sha256 = ASSETS[key]
    binary_name = "lean-ctx.exe" if key[0] == "Windows" else "lean-ctx"
    return LeanCtxAsset(name, sha256, binary_name)


def _verified_archive(payload: bytes, asset: LeanCtxAsset) -> bytes:
    if hashlib.sha256(payload).hexdigest() != asset.sha256:
        raise VerificationError(
            "LeanCTX release archive failed the pinned SHA-256 check: "
            + asset.archive_name
        )
    return payload


def _binary_from_archive(payload: bytes, asset: LeanCtxAsset) -> bytes:
    matches: list[bytes] = []
    if asset.archive_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.infolist():
                name = member.filename.replace("\\", "/").split("/")[-1]
                if member.is_dir() or name != asset.binary_name:
                    continue
                if member.file_size > MAX_BINARY_BYTES:
                    raise VerificationError(
                        "LeanCTX executable exceeds the size limit."
                    )
                matches.append(archive.read(member))
    else:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive.getmembers():
                name = member.name.replace("\\", "/").split("/")[-1]
                if not member.isfile() or name != asset.binary_name:
                    continue
                if member.size > MAX_BINARY_BYTES:
                    raise VerificationError(
                        "LeanCTX executable exceeds the size limit."
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise VerificationError("LeanCTX executable could not be read.")
                matches.append(stream.read(MAX_BINARY_BYTES + 1))
    if len(matches) != 1 or not matches[0] or len(matches[0]) > MAX_BINARY_BYTES:
        raise VerificationError(
            "Expected exactly one LeanCTX executable in the release archive."
        )
    return matches[0]


def _cached_archive(root: Path, asset: LeanCtxAsset) -> bytes | None:
    cache = safe_join(root, asset.archive_relative)
    if not cache.is_file() or cache.stat().st_size > MAX_ARCHIVE_BYTES:
        return None
    payload = cache.read_bytes()
    return payload if hashlib.sha256(payload).hexdigest() == asset.sha256 else None


def install_needed(root: Path, asset: LeanCtxAsset) -> bool:
    """Check local integrity without contacting the network."""

    payload = _cached_archive(root, asset)
    binary = safe_join(root, asset.binary_relative)
    if payload is None or not binary.is_file():
        return True
    expected = hashlib.sha256(_binary_from_archive(payload, asset)).hexdigest()
    return hashlib.sha256(binary.read_bytes()).hexdigest() != expected


def prepare_binary(root: Path, asset: LeanCtxAsset) -> tuple[bytes, bytes]:
    """Get a verified archive and executable without mutating the workspace."""

    payload = _cached_archive(root, asset)
    if payload is None:
        local_archive = os.environ.get("AIDE_LEAN_CTX_ARCHIVE")
        if local_archive:
            try:
                path = Path(local_archive).expanduser().resolve(strict=True)
            except OSError as error:
                raise VerificationError(
                    "AIDE_LEAN_CTX_ARCHIVE does not name a readable file."
                ) from error
            if path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise VerificationError(
                    "LeanCTX release archive exceeds the size limit."
                )
            payload = path.read_bytes()
        else:
            request = urllib.request.Request(
                asset.url, headers={"User-Agent": "aide-baseline-lean-ctx"}
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = response.read(MAX_ARCHIVE_BYTES + 1)
            except (OSError, urllib.error.URLError) as error:
                raise VerificationError(
                    "Could not download pinned LeanCTX v3.10.2. Set "
                    "AIDE_LEAN_CTX_ARCHIVE to an approved release archive "
                    "and retry the reviewed Extended apply."
                ) from error
        if len(payload) > MAX_ARCHIVE_BYTES:
            raise VerificationError("LeanCTX release archive exceeds the size limit.")
        _verified_archive(payload, asset)
    try:
        return payload, _binary_from_archive(payload, asset)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise VerificationError("LeanCTX release archive is unreadable.") from error


def verify_binary(path: Path, root: Path) -> None:
    """Confirm the staged executable reports the pinned version."""

    if os.name != "nt":
        path.chmod(path.stat().st_mode | 0o100)
    try:
        result = subprocess.run(
            [str(path), "--version"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError("LeanCTX executable could not be started.") from error
    if result.returncode != 0 or VERSION not in result.stdout + result.stderr:
        raise VerificationError("LeanCTX executable did not report version " + VERSION)
