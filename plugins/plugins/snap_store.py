"""Snap Store API client and cache management for three-step upgrades.

This module provides functionality to:
1. Query the Snap Store API for refresh candidates with download URLs
2. Download snap files to the snapd cache directory
3. Verify and clean up corrupted cache entries

The three-step upgrade process:
- CHECK: Query Snap Store API for available updates with download info
- DOWNLOAD: Pre-download snap files to /var/lib/snapd/cache/<sha3-384>
- INSTALL: Run `snap refresh` which uses cached files if available

Cache mechanism (from snapd source code analysis):
- Cache files are stored as /var/lib/snapd/cache/<sha3-384-hex>
- When snapd needs a snap, it checks if the SHA3-384 hash exists in cache
- If found, it creates a hard link to the target path (no download needed)
- If not found or hash mismatch, it downloads normally

Security:
- SHA3-384 ensures integrity - snapd will reject tampered files
- Cache directory is root-owned with 0700 permissions
- Snap assertions are still verified during installation
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

SNAP_CACHE_DIR = Path("/var/lib/snapd/cache")
SNAP_STORE_API = "https://api.snapcraft.io/v2/snaps/refresh"
SNAPD_SOCKET = "/run/snapd.socket"
CHUNK_SIZE = 65536


@dataclass(frozen=True)
class SnapDownloadInfo:
    """Information needed to download a snap from the store."""

    name: str
    snap_id: str
    download_url: str
    sha3_384: str
    size: int
    revision: int
    current_revision: int | None = None
    version: str | None = None

    @property
    def cache_path(self) -> Path:
        return SNAP_CACHE_DIR / self.sha3_384

    def format_size(self) -> str:
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        elif self.size < 1024 * 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f} MB"
        else:
            return f"{self.size / (1024 * 1024 * 1024):.2f} GB"


def _get_architecture() -> str:
    """Get system architecture in snap format."""
    arch = platform.machine()
    return {
        "x86_64": "amd64",
        "aarch64": "arm64",
        "armv7l": "armhf",
    }.get(arch, arch)


def _get_current_snaps_sync() -> list[dict[str, Any]]:
    """Get current snap info from snapd socket API (synchronous)."""
    log = logger.bind(function="_get_current_snaps_sync")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)

    try:
        sock.connect(SNAPD_SOCKET)

        request = (
            "GET /v2/snaps HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        if b"\r\n\r\n" not in response:
            log.warning("invalid_response", reason="no header separator")
            return []

        _, body = response.split(b"\r\n\r\n", 1)

        # Handle chunked transfer encoding
        decoded_body = _decode_chunked(body) if b"Transfer-Encoding: chunked" in response else body

        data = json.loads(decoded_body)
        if data.get("type") == "sync":
            return data.get("result", [])

        log.warning("unexpected_response_type", type=data.get("type"))
        return []

    except (OSError, json.JSONDecodeError) as e:
        log.warning("snapd_socket_error", error=str(e))
        return []
    finally:
        sock.close()


def _decode_chunked(data: bytes) -> bytes:
    """Decode HTTP chunked transfer encoding."""
    result = []
    pos = 0

    while pos < len(data):
        # Find the chunk size line
        end_of_size = data.find(b"\r\n", pos)
        if end_of_size == -1:
            break

        size_str = data[pos:end_of_size].decode("ascii").strip()
        if not size_str:
            pos = end_of_size + 2
            continue

        try:
            chunk_size = int(size_str, 16)
        except ValueError:
            break

        if chunk_size == 0:
            break

        chunk_start = end_of_size + 2
        chunk_end = chunk_start + chunk_size
        result.append(data[chunk_start:chunk_end])
        pos = chunk_end + 2

    return b"".join(result)


async def get_refresh_candidates() -> list[SnapDownloadInfo]:
    """Query Snap Store API for refresh candidates with download URLs.

    Returns:
        List of SnapDownloadInfo for snaps that have updates available.
    """
    log = logger.bind(function="get_refresh_candidates")

    current_snaps = _get_current_snaps_sync()

    if not current_snaps:
        log.info("no_snaps_installed")
        return []

    log.info("checking_refresh_candidates", snap_count=len(current_snaps))

    context = []
    actions = []

    for snap in current_snaps:
        snap_id = snap.get("id")
        if not snap_id:
            continue

        # Build epoch structure
        epoch = snap.get("epoch", {})
        if isinstance(epoch, dict):
            epoch_read = epoch.get("read", [0])
            epoch_write = epoch.get("write", [0])
        else:
            epoch_read = [0]
            epoch_write = [0]

        context.append(
            {
                "snap-id": snap_id,
                "instance-key": snap_id,
                "revision": snap.get("revision", 0),
                "tracking-channel": snap.get("tracking-channel", "latest/stable"),
                "epoch": {"read": epoch_read, "write": epoch_write},
            }
        )
        actions.append(
            {
                "action": "refresh",
                "instance-key": snap_id,
                "snap-id": snap_id,
            }
        )

    headers = {
        "Content-Type": "application/json",
        "Snap-Device-Series": "16",
        "Snap-Device-Architecture": _get_architecture(),
    }

    payload = {
        "context": context,
        "actions": actions,
        "fields": ["download", "revision", "version", "name"],
    }

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                SNAP_STORE_API,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response,
        ):
            response.raise_for_status()
            data = await response.json()

    except aiohttp.ClientError as e:
        log.error("snap_store_api_error", error=str(e))
        return []

    # Build lookup for current revisions
    current_revisions = {
        snap.get("id"): snap.get("revision") for snap in current_snaps if snap.get("id")
    }

    candidates = []
    for result in data.get("results", []):
        if result.get("result") != "refresh":
            continue

        snap_data = result.get("snap", {})
        download = snap_data.get("download", {})

        if not download.get("url"):
            continue

        snap_id = result.get("snap-id", "")
        candidates.append(
            SnapDownloadInfo(
                name=result.get("name", ""),
                snap_id=snap_id,
                download_url=download["url"],
                sha3_384=download["sha3-384"],
                size=download["size"],
                revision=snap_data.get("revision", 0),
                current_revision=current_revisions.get(snap_id),
                version=snap_data.get("version"),
            )
        )

    log.info("refresh_candidates_found", count=len(candidates))
    return candidates


def verify_sha3_384(path: Path, expected_hash: str) -> bool:
    """Verify SHA3-384 hash of a file."""
    hasher = hashlib.sha3_384()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                hasher.update(chunk)
        return hasher.hexdigest() == expected_hash
    except OSError:
        return False


async def download_snap_to_cache(
    info: SnapDownloadInfo,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """Download a snap file to the snapd cache.

    If the file already exists in cache with correct hash, returns immediately.
    Downloads to a temporary file first, verifies hash, then moves atomically.

    Args:
        info: Download information from Snap Store API.
        progress_callback: Optional callback(bytes_downloaded, total_bytes).

    Returns:
        Path to the cached file.

    Raises:
        PermissionError: If not running as root.
        ValueError: If SHA3-384 hash doesn't match.
        aiohttp.ClientError: On download failure.
    """
    log = logger.bind(snap=info.name, revision=info.revision)
    cache_path = info.cache_path

    # Check if already in cache with valid hash
    if cache_path.exists():
        if verify_sha3_384(cache_path, info.sha3_384):
            log.info("cache_hit", path=str(cache_path))
            cache_path.touch()  # Update mtime to prevent cleanup
            return cache_path
        else:
            log.warning("removing_corrupted_cache", path=str(cache_path))
            cache_path.unlink()

    # Ensure cache directory exists with correct permissions
    if not SNAP_CACHE_DIR.exists():
        SNAP_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    log.info("downloading_snap", url=info.download_url[:80], size=info.format_size())

    # Download to temporary file first
    fd, tmp_path_str = tempfile.mkstemp(dir=SNAP_CACHE_DIR, prefix=".download-")
    tmp_path = Path(tmp_path_str)

    try:
        hasher = hashlib.sha3_384()
        bytes_downloaded = 0

        async with (
            aiohttp.ClientSession() as session,
            session.get(
                info.download_url,
                timeout=aiohttp.ClientTimeout(total=3600),
            ) as response,
        ):
            response.raise_for_status()

            async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                os.write(fd, chunk)
                hasher.update(chunk)
                bytes_downloaded += len(chunk)

                if progress_callback:
                    progress_callback(bytes_downloaded, info.size)

        os.close(fd)
        fd = -1

        # Verify hash before moving to cache
        actual_hash = hasher.hexdigest()
        if actual_hash != info.sha3_384:
            raise ValueError(
                f"Hash mismatch for {info.name}: "
                f"expected {info.sha3_384[:16]}..., got {actual_hash[:16]}..."
            )

        # Atomic move to final location
        tmp_path.rename(cache_path)
        log.info("download_complete", path=str(cache_path))

        return cache_path

    except Exception:
        # Clean up on failure
        if fd >= 0:
            os.close(fd)
        tmp_path.unlink(missing_ok=True)
        raise


def cleanup_corrupted_cache_entries(candidates: list[SnapDownloadInfo]) -> list[str]:
    """Verify and remove any corrupted cache entries.

    Call this before running `snap refresh` to ensure snapd doesn't
    repeatedly fail on corrupted cache files.

    Args:
        candidates: List of snap download info to check.

    Returns:
        List of snap names whose cache entries were removed.
    """
    log = logger.bind(function="cleanup_corrupted_cache_entries")
    removed = []

    for info in candidates:
        cache_path = info.cache_path

        if cache_path.exists() and not verify_sha3_384(cache_path, info.sha3_384):
            log.warning("removing_corrupted_cache", snap=info.name, path=str(cache_path))
            try:
                cache_path.unlink()
                removed.append(info.name)
            except OSError as e:
                log.error("cache_removal_failed", snap=info.name, error=str(e))

    return removed


def is_cache_complete(candidates: list[SnapDownloadInfo]) -> tuple[bool, list[str]]:
    """Check if all candidates are already cached with valid hashes.

    Args:
        candidates: List of snap download info to check.

    Returns:
        Tuple of (all_cached, missing_names).
    """
    missing = []

    for info in candidates:
        cache_path = info.cache_path
        if not cache_path.exists() or not verify_sha3_384(cache_path, info.sha3_384):
            missing.append(info.name)

    return len(missing) == 0, missing
