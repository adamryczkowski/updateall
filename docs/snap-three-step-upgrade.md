# Snap Three-Step Upgrade Implementation

## Executive Summary

This document describes how to implement a three-step upgrade process for Snap packages (check → download → install), similar to APT's workflow. While snap doesn't natively expose a download-only CLI option, we leverage snapd's internal cache mechanism to achieve true separation of download and install phases.

**Key Benefit**: Snap downloads are usually very large. This approach allows downloading during cheap internet windows even if electricity for updates may be expensive later.

**Safety Guarantee**: Since snapd verifies SHA3-384 hashes of cached files, if we download wrong content, snapd will reject it and re-download. This makes the approach safe to attempt.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Three-Step Workflow                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase 1: CHECK                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Query Snap Store API for refresh candidates             │   │
│  │ → Returns: name, snap-id, download URL, SHA3-384, size  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Phase 2: DOWNLOAD                                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Download snap files to /var/lib/snapd/cache/<sha3-384>  │   │
│  │ → Verify SHA3-384 hash during download                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Phase 3: INSTALL                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Run `snap refresh`                                      │   │
│  │ → snapd finds files in cache, creates hard links        │   │
│  │ → No download needed, only installation                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Source Code Analysis

All implementation details are based on analysis of the snapd source code (cloned to `ref/snapd`).

### Key Discoveries

| Component | Source File | Details |
|-----------|-------------|---------|
| Download info structure | [`snap/info.go:1092`](../ref/snapd/snap/info.go:1092) | `DownloadInfo{DownloadURL, Size, Sha3_384}` |
| Store API response | [`store/details_v2.go:74`](../ref/snapd/store/details_v2.go:74) | `storeDownload{URL, Size, Sha3_384}` |
| Cache manager | [`store/cache.go:100`](../ref/snapd/store/cache.go:100) | `CacheManager` uses SHA3-384 as cache key |
| Cache directory | [`dirs/dirs.go:575`](../ref/snapd/dirs/dirs.go:575) | `/var/lib/snapd/cache` |
| Snap blob directory | [`dirs/dirs.go:367`](../ref/snapd/dirs/dirs.go:367) | `/var/lib/snapd/snaps` |
| Store action API | [`store/store_action.go:237`](../ref/snapd/store/store_action.go:237) | `SnapAction()` for refresh queries |

### Cache Mechanism

From [`store/cache.go:144-157`](../ref/snapd/store/cache.go:144):

```go
func (cm *CacheManager) Get(cacheKey, targetPath string) bool {
    // Creates hard link from cache to target path
    if err := os.Link(cm.path(cacheKey), targetPath); err != nil && !errors.Is(err, os.ErrExist) {
        return false
    }
    logger.Debugf("using cache for %s", targetPath)
    // Updates mtime to prevent cleanup
    now := time.Now()
    _ = os.Chtimes(targetPath, now, now)
    return true
}
```

**How it works**:
1. Cache files are stored as `/var/lib/snapd/cache/<sha3-384-hex>`
2. When snapd needs a snap, it checks if the SHA3-384 hash exists in cache
3. If found, it creates a hard link to the target path (no download needed)
4. If not found or hash mismatch, it downloads normally

---

## Phase 1: Check (Get Refresh Candidates)

**Goal**: Get list of upgradable snaps with download URLs, sizes, and SHA3-384 hashes.

### Snap Store API

The snapd socket API at `/v2/find?select=refresh` returns refresh candidates but **does NOT include download URLs** (only `download-size`). To get download URLs, we must query the Snap Store API directly.

**API Endpoint**: `POST https://api.snapcraft.io/v2/snaps/refresh`

**Required Headers**:
```
Content-Type: application/json
Snap-Device-Series: 16
Snap-Device-Architecture: amd64
```

**Request Format**:
```json
{
  "context": [
    {
      "snap-id": "<snap-id>",
      "instance-key": "<snap-id>",
      "revision": <current-revision>,
      "tracking-channel": "latest/stable",
      "epoch": {"read": [0], "write": [0]}
    }
  ],
  "actions": [
    {
      "action": "refresh",
      "instance-key": "<snap-id>",
      "snap-id": "<snap-id>"
    }
  ],
  "fields": ["download", "revision", "version", "name"]
}
```

**Response Format**:
```json
{
  "results": [
    {
      "result": "refresh",
      "instance-key": "<snap-id>",
      "snap-id": "<snap-id>",
      "name": "firefox",
      "snap": {
        "download": {
          "url": "https://api.snapcraft.io/api/v1/snaps/download/...",
          "sha3-384": "abc123...",
          "size": 283115520
        },
        "revision": 3836,
        "version": "120.0"
      }
    }
  ]
}
```

### Getting Current Snap Info

To build the request, first get current snap info from snapd:

```bash
# Via snapd socket API
curl --unix-socket /run/snapd.socket http://localhost/v2/snaps
```

---

## Phase 2: Download (Pre-Download to Cache)

**Goal**: Download snap files to `/var/lib/snapd/cache/<sha3-384>` so snapd finds them during refresh.

### Cache Details

| Property | Value |
|----------|-------|
| Location | `/var/lib/snapd/cache` |
| File naming | `<sha3-384-hex>` (96 characters) |
| Permissions | Directory: `0700`, owned by root |
| Mechanism | Hard links to `/var/lib/snapd/snaps/<name>_<rev>.snap` |

### Implementation

```python
#!/usr/bin/env python3
"""
Snap Pre-Download Module for updateall.

Downloads snap packages to the snapd cache directory for later installation.
Requires root access to write to /var/lib/snapd/cache.
"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import NamedTuple

import httpx  # or requests

SNAP_CACHE_DIR = Path("/var/lib/snapd/cache")
SNAP_STORE_API = "https://api.snapcraft.io/v2/snaps/refresh"


class SnapDownloadInfo(NamedTuple):
    """Information needed to download a snap."""
    name: str
    snap_id: str
    download_url: str
    sha3_384: str
    size: int
    revision: int


async def download_snap_to_cache(
    info: SnapDownloadInfo,
    progress_callback=None
) -> Path:
    """
    Download a snap file to the snapd cache.

    Args:
        info: Download information from Snap Store API
        progress_callback: Optional callback(bytes_downloaded, total_bytes)

    Returns:
        Path to the cached file

    Raises:
        PermissionError: If not running as root
        ValueError: If SHA3-384 hash doesn't match
        httpx.HTTPError: On download failure
    """
    cache_path = SNAP_CACHE_DIR / info.sha3_384

    # Check if already in cache
    if cache_path.exists():
        # Verify hash of existing file
        if _verify_sha3_384(cache_path, info.sha3_384):
            # Update mtime to prevent cleanup
            cache_path.touch()
            return cache_path
        else:
            # Corrupted cache entry, remove it
            cache_path.unlink()

    # Ensure cache directory exists with correct permissions
    SNAP_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Download to temporary file first, then move atomically
    with tempfile.NamedTemporaryFile(
        dir=SNAP_CACHE_DIR,
        delete=False,
        prefix=".download-"
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)

        try:
            hasher = hashlib.sha3_384()
            bytes_downloaded = 0

            async with httpx.AsyncClient() as client:
                async with client.stream("GET", info.download_url) as response:
                    response.raise_for_status()

                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        tmp_file.write(chunk)
                        hasher.update(chunk)
                        bytes_downloaded += len(chunk)

                        if progress_callback:
                            progress_callback(bytes_downloaded, info.size)

            # Verify hash
            actual_hash = hasher.hexdigest()
            if actual_hash != info.sha3_384:
                raise ValueError(
                    f"Hash mismatch for {info.name}: "
                    f"expected {info.sha3_384[:16]}..., "
                    f"got {actual_hash[:16]}..."
                )

            # Atomic move to final location
            tmp_path.rename(cache_path)

            return cache_path

        except Exception:
            # Clean up on failure
            tmp_path.unlink(missing_ok=True)
            raise


def _verify_sha3_384(path: Path, expected_hash: str) -> bool:
    """Verify SHA3-384 hash of a file."""
    hasher = hashlib.sha3_384()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest() == expected_hash


async def get_refresh_candidates() -> list[SnapDownloadInfo]:
    """
    Query Snap Store API for refresh candidates with download URLs.

    Returns:
        List of SnapDownloadInfo for snaps that have updates available
    """
    # First, get current snap info from snapd
    current_snaps = await _get_current_snaps()

    if not current_snaps:
        return []

    # Build request for Snap Store API
    context = []
    actions = []

    for snap in current_snaps:
        context.append({
            "snap-id": snap["snap-id"],
            "instance-key": snap["snap-id"],
            "revision": snap["revision"],
            "tracking-channel": snap.get("tracking-channel", "latest/stable"),
            "epoch": snap.get("epoch", {"read": [0], "write": [0]})
        })
        actions.append({
            "action": "refresh",
            "instance-key": snap["snap-id"],
            "snap-id": snap["snap-id"]
        })

    # Query Snap Store
    headers = {
        "Content-Type": "application/json",
        "Snap-Device-Series": "16",
        "Snap-Device-Architecture": _get_architecture()
    }

    payload = {
        "context": context,
        "actions": actions,
        "fields": ["download", "revision", "version", "name"]
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            SNAP_STORE_API,
            json=payload,
            headers=headers,
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()

    # Parse results
    candidates = []
    for result in data.get("results", []):
        if result.get("result") != "refresh":
            continue

        snap_data = result.get("snap", {})
        download = snap_data.get("download", {})

        if not download.get("url"):
            continue

        candidates.append(SnapDownloadInfo(
            name=result.get("name", ""),
            snap_id=result.get("snap-id", ""),
            download_url=download["url"],
            sha3_384=download["sha3-384"],
            size=download["size"],
            revision=snap_data.get("revision", 0)
        ))

    return candidates


async def _get_current_snaps() -> list[dict]:
    """Get current snap info from snapd socket API."""
    import socket
    import json

    # Connect to snapd socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect("/run/snapd.socket")

    try:
        request = (
            "GET /v2/snaps HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Accept: application/json\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())

        # Read response (simplified - real implementation needs proper HTTP parsing)
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\r\n\r\n" in response:
                # Find JSON body
                _, body = response.split(b"\r\n\r\n", 1)
                # Handle chunked encoding if present
                if b"\r\n" in body:
                    # Simple chunked handling
                    parts = body.split(b"\r\n")
                    body = b"".join(parts[1::2])
                try:
                    data = json.loads(body)
                    if data.get("type") == "sync":
                        return data.get("result", [])
                except json.JSONDecodeError:
                    continue
    finally:
        sock.close()

    return []


def _get_architecture() -> str:
    """Get system architecture in snap format."""
    import platform
    arch = platform.machine()
    return {
        "x86_64": "amd64",
        "aarch64": "arm64",
        "armv7l": "armhf",
    }.get(arch, arch)
```

---

## Phase 3: Install (Refresh from Cache)

**Goal**: Run `snap refresh` which will find pre-downloaded files in cache.

### How It Works

1. `snap refresh` triggers snapd to check for updates
2. For each update, snapd calls `CacheManager.Get(sha3_384, targetPath)`
3. If file exists in cache with matching hash, snapd creates a hard link (no download needed)
4. If file doesn't exist or hash doesn't match, snapd downloads normally

### Command

```bash
sudo snap refresh
```

### Verification

```bash
# Check snapd logs to confirm cache was used
journalctl -u snapd | grep "using cache"
```

---

## Complete Plugin Implementation

```python
class SnapPlugin:
    """Snap plugin with three-step upgrade support via cache pre-download."""

    async def check(self) -> CheckResult:
        """Get refresh candidates with download sizes."""
        candidates = await get_refresh_candidates()

        return CheckResult(
            count=len(candidates),
            download_size=sum(c.size for c in candidates),
            packages=[
                PackageInfo(
                    name=c.name,
                    current_version=None,  # Would need additional query
                    new_version=f"rev{c.revision}",
                    download_size=c.size
                )
                for c in candidates
            ],
            # Store for download phase
            _candidates=candidates
        )

    async def download(self, candidates: list[SnapDownloadInfo]) -> DownloadResult:
        """Pre-download snaps to cache."""
        if os.geteuid() != 0:
            return DownloadResult(
                status="error",
                message="Root access required to write to snap cache"
            )

        downloaded = []
        failed = []

        for candidate in candidates:
            try:
                await download_snap_to_cache(candidate)
                downloaded.append(candidate.name)
            except Exception as e:
                failed.append((candidate.name, str(e)))

        return DownloadResult(
            status="success" if not failed else "partial",
            downloaded=downloaded,
            failed=failed,
            message=f"Downloaded {len(downloaded)}/{len(candidates)} snaps to cache"
        )

    async def install(self) -> InstallResult:
        """Run snap refresh (uses cached files if available)."""
        result = await self._run_command(["snap", "refresh"])
        return InstallResult(
            success=result.returncode == 0,
            output=result.stdout
        )
```

---

## Error Handling: What Happens When Cache Files Are Rejected

### Scenario: Corrupted or Invalid Cache File

If we place a file in the cache that doesn't match the expected SHA3-384 hash, here's what happens:

**From [`store/store_download.go:209-212`](../ref/snapd/store/store_download.go:209)**:
```go
if s.cacher.Get(downloadInfo.Sha3_384, targetPath) {
    logger.Debugf("Cache hit for SHA3_384 …%.5s.", downloadInfo.Sha3_384)
    return nil
}
```

**From [`store/store_download.go:267-297`](../ref/snapd/store/store_download.go:267)**:
```go
// After download/cache-hit, verify hash
actualSha3 := fmt.Sprintf("%x", h.Sum(nil))
if downloadInfo.Sha3_384 != actualSha3 {
    err = HashError{name, actualSha3, downloadInfo.Sha3_384}
}

// If hash error, truncate and re-download
if _, ok := err.(HashError); ok {
    logger.Debugf("Hashsum error on download: %v", err.Error())
    logger.Debugf("Truncating and trying again from scratch.")
    err = w.Truncate(0)
    // ... re-download from scratch
}
```

### Key Finding: Snapd Does NOT Remove Corrupted Cache Entries

When there's a hash mismatch:
1. Snapd detects the hash mismatch after linking from cache
2. Snapd truncates the **target file** and re-downloads from the store
3. **The corrupted cache file is NOT removed** - it remains in place
4. Next time, snapd will try the corrupted cache file again (and fail again)

### Our Responsibility: Clean Up Failed Downloads

Since snapd doesn't clean up corrupted cache entries, **we must remove them ourselves** if our download fails hash verification.

**Updated Implementation** (replaces the earlier `download_snap_to_cache` function):

```python
async def download_snap_to_cache(
    info: SnapDownloadInfo,
    progress_callback=None
) -> Path:
    """
    Download a snap file to the snapd cache.

    IMPORTANT: If hash verification fails, we MUST remove the corrupted file
    from the cache. Snapd will not clean it up, and it will cause repeated
    failures on every refresh attempt.
    """
    cache_path = SNAP_CACHE_DIR / info.sha3_384

    # Check if already in cache
    if cache_path.exists():
        # Verify hash of existing file
        if _verify_sha3_384(cache_path, info.sha3_384):
            # Update mtime to prevent cleanup
            cache_path.touch()
            return cache_path
        else:
            # CRITICAL: Remove corrupted cache entry
            # Snapd will NOT do this for us!
            logger.warning(
                f"Removing corrupted cache entry for {info.name}: "
                f"hash mismatch in {cache_path}"
            )
            cache_path.unlink()

    # Ensure cache directory exists with correct permissions
    SNAP_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Download to temporary file first, then move atomically
    with tempfile.NamedTemporaryFile(
        dir=SNAP_CACHE_DIR,
        delete=False,
        prefix=".download-"
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)

        try:
            hasher = hashlib.sha3_384()
            bytes_downloaded = 0

            async with httpx.AsyncClient() as client:
                async with client.stream("GET", info.download_url) as response:
                    response.raise_for_status()

                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        tmp_file.write(chunk)
                        hasher.update(chunk)
                        bytes_downloaded += len(chunk)

                        if progress_callback:
                            progress_callback(bytes_downloaded, info.size)

            # Verify hash BEFORE moving to cache
            actual_hash = hasher.hexdigest()
            if actual_hash != info.sha3_384:
                # DO NOT put corrupted file in cache!
                raise ValueError(
                    f"Hash mismatch for {info.name}: "
                    f"expected {info.sha3_384[:16]}..., "
                    f"got {actual_hash[:16]}..."
                )

            # Hash verified - safe to move to cache
            tmp_path.rename(cache_path)

            return cache_path

        except Exception:
            # Clean up temporary file on ANY failure
            tmp_path.unlink(missing_ok=True)
            raise


def cleanup_corrupted_cache_entries(candidates: list[SnapDownloadInfo]) -> list[str]:
    """
    Verify and remove any corrupted cache entries.

    Call this before running `snap refresh` to ensure snapd doesn't
    repeatedly fail on corrupted cache files.

    Returns:
        List of snap names whose cache entries were removed
    """
    removed = []

    for info in candidates:
        cache_path = SNAP_CACHE_DIR / info.sha3_384

        if cache_path.exists():
            if not _verify_sha3_384(cache_path, info.sha3_384):
                logger.warning(
                    f"Removing corrupted cache entry for {info.name}"
                )
                cache_path.unlink()
                removed.append(info.name)

    return removed
```

### Updated Plugin Install Method

```python
class SnapPlugin:
    async def install(self) -> InstallResult:
        """Run snap refresh (uses cached files if available)."""

        # IMPORTANT: Clean up any corrupted cache entries first
        # Otherwise snapd will fail repeatedly on them
        if hasattr(self, '_candidates'):
            removed = cleanup_corrupted_cache_entries(self._candidates)
            if removed:
                logger.info(f"Removed corrupted cache entries: {removed}")

        result = await self._run_command(["snap", "refresh"])
        return InstallResult(
            success=result.returncode == 0,
            output=result.stdout
        )
```

### Summary: Error Handling Responsibilities

| Scenario | Snapd Behavior | Our Responsibility |
|----------|----------------|-------------------|
| Cache hit, hash matches | Uses cached file | None |
| Cache hit, hash mismatch | Re-downloads, **leaves corrupted file** | Remove corrupted file |
| Cache miss | Downloads normally | None |
| Our download fails hash check | N/A (file not in cache) | Don't put file in cache |
| Our download network error | N/A | Clean up temp file |

---

## Cache Cleanup Considerations

From [`store/cache.go:39-57`](../ref/snapd/store/cache.go:39):

```go
var DefaultCachePolicyClassic = CachePolicy{
    MaxItems: 5,           // at most 5 unreferenced items
    MaxAge: 30 * 24 * time.Hour,  // 30 days max age
    // No size limit on classic systems
}
```

**Key insight**: Files with `nlink > 1` (hard-linked elsewhere) are NOT candidates for cleanup. Our pre-downloaded files will have `nlink == 1` until `snap refresh` links them.

**Mitigation strategies**:
- Download close to when refresh will happen
- Touch files to update mtime if refresh is delayed
- Accept that snapd may clean up old pre-downloads (they'll just be re-downloaded)

---

## Security Considerations

1. **Hash Verification**: SHA3-384 ensures integrity - snapd will reject tampered files
2. **Root Required**: Cache directory is root-owned with 0700 permissions
3. **No Signature Bypass**: Snap assertions are still verified during installation
4. **Store API**: Uses HTTPS, same as snapd itself

---

## Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Requires root | Cannot pre-download as regular user | Run download phase with sudo |
| Cache cleanup | Files may be cleaned up before refresh | Download close to refresh time |
| Delta updates | Downloads full snaps, not deltas | Accept larger downloads |
| Internal behavior | Relies on cache mechanism | Verified from source code, safe due to hash verification |

---

## Comparison: APT vs Snap

| Feature | APT | Snap (with this implementation) |
|---------|-----|--------------------------------|
| Check with size | `apt update` + `apt upgrade -s` | Snap Store API query |
| Download only | `apt upgrade --download-only` | Pre-download to cache |
| Install from cache | `apt upgrade --no-download` | `snap refresh` (uses cache) |
| Cache location | `/var/cache/apt/archives` | `/var/lib/snapd/cache` |
| Cache key | Filename | SHA3-384 hash |
| Verification | GPG signatures | SHA3-384 + assertions |

---

## Source Code References

All findings are based on analysis of the snapd source code cloned to `ref/snapd`:

| File | Key Information |
|------|-----------------|
| [`daemon/api_find.go:259`](../ref/snapd/daemon/api_find.go:259) | DownloadSize returned in API response |
| [`dirs/dirs.go:367`](../ref/snapd/dirs/dirs.go:367) | SnapBlobDir = /var/lib/snapd/snaps |
| [`dirs/dirs.go:575`](../ref/snapd/dirs/dirs.go:575) | SnapDownloadCacheDir = /var/lib/snapd/cache |
| [`store/cache.go:100-200`](../ref/snapd/store/cache.go:100) | CacheManager uses SHA3-384 as cache key |
| [`store/cache.go:144-157`](../ref/snapd/store/cache.go:144) | Cache Get() creates hard links |
| [`store/cache.go:160-186`](../ref/snapd/store/cache.go:160) | Cache Put() with 0700 permissions |
| [`store/store_download.go:197-312`](../ref/snapd/store/store_download.go:197) | Download mechanism with cache integration |
| [`store/store_action.go:237`](../ref/snapd/store/store_action.go:237) | SnapAction API for refresh queries |
| [`store/details_v2.go:74-79`](../ref/snapd/store/details_v2.go:74) | storeDownload struct with URL, Size, Sha3_384 |
| [`overlord/snapstate/handlers.go:894-973`](../ref/snapd/overlord/snapstate/handlers.go:894) | Internal pre-download mechanism |
