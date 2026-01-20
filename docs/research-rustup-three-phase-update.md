# Research: Splitting Rustup Update into Three Phases

**Date:** 2026-01-20
**Author:** Research conducted via source code analysis and web research
**Sources:**
- Official rustup repository: https://github.com/rust-lang/rustup (cloned to `ref/rustup/`)
- The rustup book: https://rust-lang.github.io/rustup/
- Rust distribution manifests: https://static.rust-lang.org/dist/channel-rust-stable.toml

## Executive Summary

The goal is to split the rustup/cargo updater into three distinct phases:
1. **CHECK**: Determine if updates are available and calculate download size
2. **DOWNLOAD**: Download components without installing
3. **INSTALL**: Install previously downloaded components

**Current Status:** Rustup (v1.28.2) does NOT natively support separating download and install phases. The `rustup update` command performs download and installation in an interleaved manner.

## Current Rustup Architecture

### Available Commands

| Command | Purpose | Separates Download/Install? |
|---------|---------|----------------------------|
| `rustup check` | Check for available updates | N/A (no download) |
| `rustup update` | Download and install updates | No - interleaved |
| `rustup toolchain install` | Install specific toolchain | No - interleaved |
| `rustup self update` | Update rustup itself | No - interleaved |

### Phase 1: CHECK - Current Implementation

The `rustup check` command is already implemented and provides:

```bash
$ rustup check
stable-x86_64-unknown-linux-gnu - Up to date : 1.92.0 (ded5c06cf 2025-12-08)
rustup - Up to date : 1.28.2
```

**What it does:**
- Fetches the manifest from `static.rust-lang.org/dist/channel-rust-{channel}.toml`
- Compares installed version with available version
- Reports "Up to date" or "Update available: X.Y.Z -> A.B.C"

**Limitation:** Does NOT report download size.

### Download Size Information

The Rust distribution manifest (`channel-rust-stable.toml`) structure:

```toml
[pkg.cargo.target.x86_64-unknown-linux-gnu]
available = true
url = "https://static.rust-lang.org/dist/2025-12-11/cargo-1.92.0-x86_64-unknown-linux-gnu.tar.gz"
hash = "..."
xz_url = "https://static.rust-lang.org/dist/2025-12-11/cargo-1.92.0-x86_64-unknown-linux-gnu.tar.xz"
xz_hash = "..."
```

**Critical Finding:** The manifest does NOT include file sizes. To get download sizes, HTTP HEAD requests must be made to each URL to retrieve the `Content-Length` header.

### Phase 2 & 3: DOWNLOAD and INSTALL - Current Implementation

Currently, rustup's update process works as follows (from source code analysis):

1. **Fetch manifest** - Download and parse the channel manifest
2. **Calculate changes** - Determine which components need updating
3. **For each component:**
   - Download the component tarball
   - Verify checksum
   - Unpack and install
   - Move to next component

The download and install are **interleaved per component**, not separated.

## Proposed Implementation Strategy

### Option A: Leverage Existing Download Cache (Recommended)

Rustup already caches downloaded files in `~/.rustup/downloads/` keyed by hash. We can exploit this:

```python
# Phase 1: CHECK
async def check_rustup_updates() -> tuple[bool, list[str], int]:
    """
    Returns: (has_updates, component_list, estimated_download_size_bytes)
    """
    # Run: rustup check
    # Parse output for "Update available" lines
    # For download size: fetch manifest, make HEAD requests for each component URL
    pass

# Phase 2: DOWNLOAD (workaround)
async def download_rustup_updates() -> bool:
    """
    Download components without installing.

    WORKAROUND: There's no native --download-only flag.
    Strategy: Start `rustup update`, monitor for download completion,
    then interrupt before installation begins.

    Alternative: Manually download files to ~/.rustup/downloads/{hash}
    """
    pass

# Phase 3: INSTALL
async def install_rustup_updates() -> bool:
    """
    Install previously downloaded components.

    If downloads are cached, `rustup update` will skip download phase
    and proceed directly to installation.
    """
    # Run: rustup update
    # Downloads will be skipped if already in cache
    pass
```

### Option B: Manual Download Implementation

Implement our own download phase by:

1. Parsing the manifest to get component URLs
2. Downloading files to `~/.rustup/downloads/{hash}`
3. Running `rustup update` which will use cached files

```python
import aiohttp
import hashlib
from pathlib import Path

RUSTUP_DOWNLOADS = Path.home() / ".rustup" / "downloads"

async def download_component(url: str, expected_hash: str) -> Path:
    """Download a component to rustup's cache directory."""
    target = RUSTUP_DOWNLOADS / expected_hash
    if target.exists():
        # Verify existing file
        if verify_hash(target, expected_hash):
            return target
        target.unlink()

    # Download with progress tracking
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            hasher = hashlib.sha256()

            partial = target.with_suffix('.partial')
            with open(partial, 'wb') as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)
                    hasher.update(chunk)

            if hasher.hexdigest() != expected_hash:
                partial.unlink()
                raise ValueError("Checksum mismatch")

            partial.rename(target)
            return target
```

### Option C: Request Feature from Rustup Team

File a feature request for `rustup update --download-only` flag. Related issues exist:
- https://github.com/rust-lang/rustup/issues/4109 - Update order improvements
- https://github.com/rust-lang/rustup/issues/4448 - Download recovery support

## Implementation for updateall Plugin

Given the constraints, here's the recommended implementation:

### Step 1: Enhanced Check Phase

```python
async def check_phase(self) -> tuple[bool, str, int]:
    """
    Check for rustup updates and estimate download size.

    Returns:
        (has_updates, version_info, download_size_bytes)
    """
    # Run rustup check
    returncode, stdout, stderr = await self._run_command(
        ["rustup", "check"],
        timeout=30,
    )

    has_updates = "Update available" in stdout

    if not has_updates:
        return False, stdout, 0

    # Get download size by fetching manifest and making HEAD requests
    download_size = await self._estimate_download_size()

    return True, stdout, download_size

async def _estimate_download_size(self) -> int:
    """Estimate total download size from manifest."""
    # This requires:
    # 1. Determining which channel(s) are installed
    # 2. Fetching the manifest
    # 3. Identifying which components need updating
    # 4. Making HEAD requests to get Content-Length
    #
    # This is complex and may not be worth implementing
    # Consider returning 0 or a rough estimate
    return 0
```

### Step 2: Download Phase (Best Effort)

Since rustup doesn't support download-only, we have two options:

**Option A: Skip separate download phase**
```python
def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
    if dry_run:
        return {Phase.CHECK: ["rustup", "check"]}

    return {
        Phase.CHECK: ["rustup", "check"],
        # No separate DOWNLOAD phase - rustup doesn't support it
        Phase.EXECUTE: ["rustup", "update"],
    }
```

**Option B: Pre-download components manually**
```python
async def download_phase(self) -> bool:
    """
    Pre-download rustup components to cache.

    This is a best-effort implementation that downloads
    components to ~/.rustup/downloads/ so that the subsequent
    update phase can use cached files.
    """
    # Implementation would require:
    # 1. Parse manifest
    # 2. Identify components to update
    # 3. Download each to cache
    # This is complex and fragile
    pass
```

### Step 3: Install Phase

```python
async def install_phase(self) -> tuple[str, str | None]:
    """
    Install rustup updates.

    If downloads were pre-cached, this will be fast.
    Otherwise, it will download and install.
    """
    returncode, stdout, stderr = await self._run_command(
        ["rustup", "update"],
        timeout=600,  # 10 minutes for large updates
    )

    if returncode != 0:
        return stdout, f"rustup update failed: {stderr}"

    return stdout, None
```

## Recommendations

### For Immediate Implementation

1. **Use existing `rustup check`** for the CHECK phase
2. **Skip separate DOWNLOAD phase** - rustup doesn't support it natively
3. **Use `rustup update`** for the EXECUTE phase

```python
def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
    """Get commands for each execution phase."""
    if dry_run:
        return {Phase.CHECK: ["rustup", "check"]}

    return {
        Phase.CHECK: ["rustup", "check"],
        Phase.EXECUTE: ["rustup", "update", "--no-self-update"],
    }
```

### For Future Enhancement

1. **File a feature request** with rustup team for `--download-only` flag
2. **Implement manual download** if separate phases are critical
3. **Add download size estimation** via manifest parsing + HEAD requests

## Technical Details from Source Code Analysis

### Key Files in rustup Source

| File | Purpose |
|------|---------|
| `src/cli/rustup_mode.rs` | CLI command definitions and handlers |
| `src/dist/download.rs` | Download management with caching |
| `src/dist/manifest.rs` | Manifest parsing (no size field) |
| `src/dist/manifestation.rs` | Installation logic |

### Download Cache Location

```
~/.rustup/downloads/{sha256_hash}
~/.rustup/downloads/{sha256_hash}.partial  # In-progress downloads
```

### Manifest URLs

```
https://static.rust-lang.org/dist/channel-rust-stable.toml
https://static.rust-lang.org/dist/channel-rust-beta.toml
https://static.rust-lang.org/dist/channel-rust-nightly.toml
```

## Conclusion

**Rustup does not currently support separating download and install phases.** The recommended approach for the updateall plugin is to:

1. Use `rustup check` for the CHECK phase
2. Skip the DOWNLOAD phase (or implement manual pre-caching if critical)
3. Use `rustup update` for the EXECUTE phase

The download size requirement cannot be easily satisfied without making additional HTTP HEAD requests, as the manifest does not include file sizes.

## References

- Rustup source code: `ref/rustup/` (shallow clone)
- Rustup book: https://rust-lang.github.io/rustup/
- Distribution manifest format: https://forge.rust-lang.org/infra/channel-layout.html
- Related GitHub issues:
  - #4109: Update order improvements
  - #4448: Download recovery support
