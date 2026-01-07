# Centralized Download Manager Implementation Plan

**Date:** January 7, 2026
**Status:** Draft
**Proposal Reference:** Proposal 2 from `docs/update-plugins-api-rewrite.md`

## Executive Summary

This document provides a detailed implementation plan for the Centralized Download Manager API (Proposal 2). The goal is to standardize how plugins handle file downloads by introducing a declarative `get_download_spec()` method and a `DownloadSpec` dataclass, enabling the core system to handle downloads with consistent progress reporting, retry logic, bandwidth limiting, and caching.

---

## Table of Contents

1. [Objectives](#objectives)
2. [Current State Analysis](#current-state-analysis)
3. [Proposed Architecture](#proposed-architecture)
4. [Implementation Phases](#implementation-phases)
5. [Test-Driven Development Approach](#test-driven-development-approach)
6. [Plugin Migration Plan](#plugin-migration-plan)
7. [Documentation Updates](#documentation-updates)
8. [Risk Assessment](#risk-assessment)
9. [Timeline](#timeline)

---

## Objectives

### Primary Goals

1. **Standardize download handling** — Move download logic from individual plugins to a centralized download manager
2. **Provide consistent progress reporting** — All downloads report progress in the same format
3. **Enable retry and resume** — Automatic retry on failure with resume support for large files
4. **Support bandwidth limiting** — Control network usage across all plugins
5. **Enable download caching** — Cache downloads for offline updates and faster re-runs

### Secondary Goals

1. Reduce plugin code complexity by 30-50 lines per download-capable plugin
2. Enable download-only mode for pre-downloading updates
3. Provide download size estimation for scheduling decisions
4. Support checksum verification for security

---

## Current State Analysis

### Plugins with Download Functionality

Based on analysis of the repository, the following plugins currently implement their own download logic:

| Plugin | Download Method | Lines of Code | Issues |
|--------|----------------|---------------|--------|
| `waterfox.py` | `urllib.request.urlopen()` | ~50 | No progress, no retry, no resume |
| `go_runtime.py` | Shell script with `curl` | ~40 | No progress in Python, relies on curl |
| `calibre.py` | `wget` subprocess | ~30 | No progress parsing, relies on wget |

### Current Download API

The existing `BasePlugin` class has:

```python
@property
def supports_download(self) -> bool:
    """Check if this plugin supports separate download phase."""
    return False

async def estimate_download(self) -> DownloadEstimate | None:
    """Estimate the download size and time."""
    return None

async def download(self) -> AsyncIterator[StreamEvent]:
    """Download updates without applying them."""
    raise NotImplementedError(...)
```

The `DownloadEstimate` model exists in `core/models.py`:

```python
class DownloadEstimate(BaseModel):
    total_bytes: int | None = None
    package_count: int | None = None
    estimated_seconds: float | None = None
    packages: list[PackageDownload] = Field(default_factory=list)
```

### Gap Analysis

| Feature | Current State | Proposed State |
|---------|--------------|----------------|
| Progress reporting | Plugin-specific | Centralized, consistent |
| Retry logic | None | Configurable retries with backoff |
| Resume support | None | Resume from partial downloads |
| Bandwidth limiting | None | Global bandwidth control |
| Caching | None | Configurable download cache |
| Checksum verification | Manual per-plugin | Automatic with DownloadSpec |

---

## Proposed Architecture

### New Data Models

#### DownloadSpec (New)

```python
# core/models.py

@dataclass(frozen=True)
class DownloadSpec:
    """Specification for files to download.

    This dataclass describes what a plugin needs to download. The core
    download manager handles the actual download with progress reporting,
    retry logic, and caching.

    Attributes:
        url: URL to download from.
        destination: Local path to save the file.
        expected_size: Expected file size in bytes (for progress).
        checksum: Checksum for verification (format: "algorithm:hash").
        extract: Whether to extract the file after download.
        extract_format: Archive format ("tar.gz", "tar.bz2", "zip", "tar.xz").
        headers: Additional HTTP headers for the request.
        timeout_seconds: Download timeout (None = use default).

    Example:
        >>> spec = DownloadSpec(
        ...     url="https://example.com/file.tar.gz",
        ...     destination=Path("/tmp/download"),
        ...     expected_size=100_000_000,
        ...     checksum="sha256:abc123...",
        ...     extract=True,
        ...     extract_format="tar.gz",
        ... )
    """

    url: str
    destination: Path
    expected_size: int | None = None
    checksum: str | None = None  # "sha256:abc123..." or "md5:abc123..."
    extract: bool = False
    extract_format: str | None = None  # "tar.gz", "tar.bz2", "zip", "tar.xz"
    headers: dict[str, str] | None = None
    timeout_seconds: int | None = None

    # For version checking (optional)
    version_url: str | None = None
    version_pattern: str | None = None  # Regex to extract version

    def __post_init__(self) -> None:
        """Validate the download spec."""
        if not self.url:
            raise ValueError("url must be non-empty")
        if self.extract and not self.extract_format:
            # Try to infer format from URL
            url_lower = self.url.lower()
            if url_lower.endswith(".tar.gz") or url_lower.endswith(".tgz"):
                object.__setattr__(self, "extract_format", "tar.gz")
            elif url_lower.endswith(".tar.bz2") or url_lower.endswith(".tbz2"):
                object.__setattr__(self, "extract_format", "tar.bz2")
            elif url_lower.endswith(".tar.xz") or url_lower.endswith(".txz"):
                object.__setattr__(self, "extract_format", "tar.xz")
            elif url_lower.endswith(".zip"):
                object.__setattr__(self, "extract_format", "zip")
```

#### DownloadResult (New)

```python
# core/models.py

@dataclass
class DownloadResult:
    """Result of a download operation.

    Attributes:
        success: Whether the download succeeded.
        path: Path to the downloaded file (or extracted directory).
        bytes_downloaded: Total bytes downloaded.
        duration_seconds: Time taken for download.
        from_cache: Whether the file was served from cache.
        checksum_verified: Whether checksum was verified.
        error_message: Error message if download failed.
    """

    success: bool
    path: Path | None = None
    bytes_downloaded: int = 0
    duration_seconds: float = 0.0
    from_cache: bool = False
    checksum_verified: bool = False
    error_message: str | None = None
```

### DownloadManager Class (New)

```python
# core/download_manager.py

class DownloadManager:
    """Centralized download manager for all plugins.

    Provides:
    - Progress reporting via StreamEvent
    - Retry logic with exponential backoff
    - Resume support for partial downloads
    - Bandwidth limiting
    - Download caching
    - Checksum verification
    - Archive extraction
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        bandwidth_limit_bytes: int | None = None,
        max_concurrent_downloads: int = 2,
    ) -> None:
        """Initialize the download manager."""
        ...

    async def download(
        self,
        spec: DownloadSpec,
        plugin_name: str,
    ) -> AsyncIterator[StreamEvent]:
        """Download a file according to the spec.

        Yields progress events during download and a completion event
        when done. The final event contains the DownloadResult.
        """
        ...

    async def download_batch(
        self,
        specs: list[DownloadSpec],
        plugin_name: str,
    ) -> AsyncIterator[StreamEvent]:
        """Download multiple files with combined progress."""
        ...

    def get_cached_path(self, spec: DownloadSpec) -> Path | None:
        """Check if a file is already cached."""
        ...

    def clear_cache(self, max_age_days: int | None = None) -> int:
        """Clear cached downloads. Returns number of files removed."""
        ...
```

### BasePlugin Changes

```python
# plugins/base.py

class BasePlugin:
    # ... existing methods ...

    def get_download_spec(self) -> DownloadSpec | None:
        """Return download specification if plugin needs to download files.

        Override this method to use the centralized download manager.
        When this method returns a DownloadSpec, the base class will:
        1. Use the DownloadManager to download the file
        2. Handle progress reporting automatically
        3. Verify checksums if provided
        4. Extract archives if requested

        The downloaded file path is passed to get_update_commands() via
        the download_path parameter.

        Returns:
            DownloadSpec if download is needed, None otherwise.

        Example:
            def get_download_spec(self) -> DownloadSpec | None:
                version = self._get_remote_version()
                if not version:
                    return None
                return DownloadSpec(
                    url=f"https://example.com/v{version}.tar.gz",
                    destination=Path("/tmp/myapp-download"),
                    expected_size=100_000_000,
                    checksum=f"sha256:{self._get_checksum(version)}",
                    extract=True,
                )
        """
        return None

    def get_download_specs(self) -> list[DownloadSpec]:
        """Return multiple download specifications.

        Override this for plugins that need to download multiple files.
        Default implementation wraps get_download_spec() in a list.
        """
        spec = self.get_download_spec()
        return [spec] if spec else []

    async def download_streaming(self) -> AsyncIterator[StreamEvent]:
        """Download updates with streaming progress output.

        This method is enhanced to use the centralized DownloadManager
        when get_download_spec() returns a spec.
        """
        # Check for declarative download spec
        specs = self.get_download_specs()

        if specs:
            # Use centralized download manager
            manager = get_download_manager()
            for spec in specs:
                async for event in manager.download(spec, self.name):
                    yield event
        else:
            # Fall back to legacy download() method
            async for event in self.download():
                yield event
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)

#### 1.1 Add DownloadSpec and DownloadResult Models

**Files to modify:**
- `core/core/models.py` — Add `DownloadSpec` and `DownloadResult` dataclasses

**Tasks:**
1. Add `DownloadSpec` dataclass with validation
2. Add `DownloadResult` dataclass
3. Add unit tests for model validation
4. Update `__all__` exports

#### 1.2 Create DownloadManager Class

**Files to create:**
- `core/core/download_manager.py` — New download manager implementation

**Tasks:**
1. Create `DownloadManager` class with basic download functionality
2. Implement progress reporting via `ProgressEvent`
3. Add retry logic with exponential backoff
4. Add checksum verification
5. Add archive extraction support
6. Create singleton accessor `get_download_manager()`

#### 1.3 Add Configuration

**Files to modify:**
- `core/core/models.py` — Add download-related config to `GlobalConfig`

**Tasks:**
1. Add `download_cache_dir` config option
2. Add `download_max_retries` config option
3. Add `download_bandwidth_limit` config option
4. Add `download_max_concurrent` config option

### Phase 2: BasePlugin Integration (Week 2-3)

#### 2.1 Add get_download_spec() Method

**Files to modify:**
- `plugins/plugins/base.py` — Add new methods

**Tasks:**
1. Add `get_download_spec()` method (returns `None` by default)
2. Add `get_download_specs()` method (wraps single spec)
3. Modify `download_streaming()` to use `DownloadManager` when spec is provided
4. Add `_download_path` instance variable to store downloaded file path

#### 2.2 Integrate with Execute Flow

**Files to modify:**
- `plugins/plugins/base.py` — Modify execution flow

**Tasks:**
1. Modify `execute_streaming()` to check for download spec
2. Pass download result to `get_update_commands()` if needed
3. Handle download failures gracefully

### Phase 3: Plugin Migration (Week 3-4)

#### 3.1 Migrate Waterfox Plugin

**Files to modify:**
- `plugins/plugins/waterfox.py`

**Tasks:**
1. Implement `get_download_spec()` returning tarball URL
2. Remove manual download logic from `_execute_update()`
3. Update `get_update_commands()` to use downloaded file
4. Add tests for new implementation

#### 3.2 Migrate Go Runtime Plugin

**Files to modify:**
- `plugins/plugins/go_runtime.py`

**Tasks:**
1. Implement `get_download_spec()` returning Go tarball URL
2. Remove shell script download logic
3. Update installation commands to use downloaded file
4. Add tests for new implementation

#### 3.3 Migrate Calibre Plugin

**Files to modify:**
- `plugins/plugins/calibre.py`

**Tasks:**
1. Implement `get_download_spec()` returning installer script URL
2. Remove wget subprocess call
3. Update installation to use downloaded script
4. Add tests for new implementation

### Phase 4: Advanced Features (Week 4-5)

#### 4.1 Add Resume Support

**Tasks:**
1. Implement HTTP Range header support
2. Track partial downloads in cache
3. Resume from last byte on retry

#### 4.2 Add Bandwidth Limiting

**Tasks:**
1. Implement token bucket rate limiter
2. Apply rate limiting across all concurrent downloads
3. Add configuration for bandwidth limit

#### 4.3 Add Download Caching

**Tasks:**
1. Implement cache directory management
2. Add cache lookup by URL + checksum
3. Add cache expiration and cleanup
4. Add cache statistics

---

## Test-Driven Development Approach

### Testing Strategy

All implementation will follow TDD principles:
1. Write failing tests first
2. Implement minimal code to pass tests
3. Refactor while keeping tests green

### Test Categories

#### Unit Tests

| Test File | Description | Priority |
|-----------|-------------|----------|
| `core/tests/test_download_spec.py` | DownloadSpec validation | P0 |
| `core/tests/test_download_result.py` | DownloadResult dataclass | P0 |
| `core/tests/test_download_manager.py` | DownloadManager core logic | P0 |
| `plugins/tests/test_download_spec_integration.py` | BasePlugin integration | P0 |

#### Integration Tests

| Test File | Description | Priority |
|-----------|-------------|----------|
| `core/tests/test_download_manager_integration.py` | Real HTTP downloads | P1 |
| `plugins/tests/test_waterfox_download.py` | Waterfox plugin migration | P1 |
| `plugins/tests/test_go_runtime_download.py` | Go runtime plugin migration | P1 |
| `plugins/tests/test_calibre_download.py` | Calibre plugin migration | P1 |

### Detailed Test List

#### 1. DownloadSpec Tests (`core/tests/test_download_spec.py`)

```python
class TestDownloadSpec:
    """Tests for DownloadSpec dataclass."""

    def test_create_minimal_spec(self) -> None:
        """Test creating a spec with only required fields."""

    def test_create_full_spec(self) -> None:
        """Test creating a spec with all fields."""

    def test_url_required(self) -> None:
        """Test that empty URL raises ValueError."""

    def test_infer_extract_format_tar_gz(self) -> None:
        """Test automatic format inference for .tar.gz."""

    def test_infer_extract_format_tar_bz2(self) -> None:
        """Test automatic format inference for .tar.bz2."""

    def test_infer_extract_format_zip(self) -> None:
        """Test automatic format inference for .zip."""

    def test_infer_extract_format_tar_xz(self) -> None:
        """Test automatic format inference for .tar.xz."""

    def test_explicit_format_not_overwritten(self) -> None:
        """Test that explicit format is not overwritten by inference."""

    def test_checksum_format_sha256(self) -> None:
        """Test sha256 checksum format."""

    def test_checksum_format_md5(self) -> None:
        """Test md5 checksum format."""

    def test_frozen_dataclass(self) -> None:
        """Test that DownloadSpec is immutable."""
```

#### 2. DownloadResult Tests (`core/tests/test_download_result.py`)

```python
class TestDownloadResult:
    """Tests for DownloadResult dataclass."""

    def test_create_success_result(self) -> None:
        """Test creating a successful result."""

    def test_create_failure_result(self) -> None:
        """Test creating a failed result."""

    def test_from_cache_flag(self) -> None:
        """Test from_cache flag."""

    def test_checksum_verified_flag(self) -> None:
        """Test checksum_verified flag."""
```

#### 3. DownloadManager Tests (`core/tests/test_download_manager.py`)

```python
class TestDownloadManagerInit:
    """Tests for DownloadManager initialization."""

    def test_default_config(self) -> None:
        """Test default configuration values."""

    def test_custom_cache_dir(self) -> None:
        """Test custom cache directory."""

    def test_custom_retry_config(self) -> None:
        """Test custom retry configuration."""

    def test_bandwidth_limit_config(self) -> None:
        """Test bandwidth limit configuration."""


class TestDownloadManagerDownload:
    """Tests for DownloadManager.download() method."""

    @pytest.mark.asyncio
    async def test_download_simple_file(self) -> None:
        """Test downloading a simple file."""

    @pytest.mark.asyncio
    async def test_download_emits_progress_events(self) -> None:
        """Test that download emits progress events."""

    @pytest.mark.asyncio
    async def test_download_emits_completion_event(self) -> None:
        """Test that download emits completion event."""

    @pytest.mark.asyncio
    async def test_download_with_checksum_verification(self) -> None:
        """Test checksum verification on download."""

    @pytest.mark.asyncio
    async def test_download_checksum_mismatch_fails(self) -> None:
        """Test that checksum mismatch causes failure."""

    @pytest.mark.asyncio
    async def test_download_with_extraction_tar_gz(self) -> None:
        """Test extraction of tar.gz archive."""

    @pytest.mark.asyncio
    async def test_download_with_extraction_zip(self) -> None:
        """Test extraction of zip archive."""

    @pytest.mark.asyncio
    async def test_download_timeout(self) -> None:
        """Test download timeout handling."""

    @pytest.mark.asyncio
    async def test_download_network_error(self) -> None:
        """Test network error handling."""


class TestDownloadManagerRetry:
    """Tests for retry logic."""

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self) -> None:
        """Test automatic retry on network error."""

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self) -> None:
        """Test exponential backoff between retries."""

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self) -> None:
        """Test failure after max retries exceeded."""

    @pytest.mark.asyncio
    async def test_no_retry_on_404(self) -> None:
        """Test that 404 errors are not retried."""


class TestDownloadManagerCache:
    """Tests for download caching."""

    def test_cache_lookup_by_url(self) -> None:
        """Test cache lookup by URL."""

    def test_cache_lookup_by_checksum(self) -> None:
        """Test cache lookup by checksum."""

    @pytest.mark.asyncio
    async def test_download_uses_cache(self) -> None:
        """Test that cached files are used."""

    def test_clear_cache_all(self) -> None:
        """Test clearing all cache."""

    def test_clear_cache_by_age(self) -> None:
        """Test clearing cache by age."""


class TestDownloadManagerBandwidth:
    """Tests for bandwidth limiting."""

    @pytest.mark.asyncio
    async def test_bandwidth_limit_applied(self) -> None:
        """Test that bandwidth limit is applied."""

    @pytest.mark.asyncio
    async def test_bandwidth_limit_across_concurrent(self) -> None:
        """Test bandwidth limit across concurrent downloads."""
```

#### 4. BasePlugin Integration Tests (`plugins/tests/test_download_spec_integration.py`)

```python
class TestBasePluginDownloadSpec:
    """Tests for BasePlugin download spec integration."""

    def test_get_download_spec_default_none(self) -> None:
        """Test that get_download_spec returns None by default."""

    def test_get_download_specs_wraps_single(self) -> None:
        """Test that get_download_specs wraps single spec."""

    def test_get_download_specs_empty_when_no_spec(self) -> None:
        """Test that get_download_specs returns empty list when no spec."""


class TestBasePluginDownloadStreaming:
    """Tests for download_streaming with specs."""

    @pytest.mark.asyncio
    async def test_download_streaming_uses_manager(self) -> None:
        """Test that download_streaming uses DownloadManager."""

    @pytest.mark.asyncio
    async def test_download_streaming_falls_back_to_legacy(self) -> None:
        """Test fallback to legacy download() method."""

    @pytest.mark.asyncio
    async def test_download_streaming_emits_phase_events(self) -> None:
        """Test that phase events are emitted."""
```

#### 5. Plugin Migration Tests

##### Waterfox Plugin Tests (`plugins/tests/test_waterfox_download.py`)

```python
class TestWaterfoxDownloadSpec:
    """Tests for Waterfox plugin download spec."""

    def test_get_download_spec_returns_spec(self) -> None:
        """Test that get_download_spec returns a valid spec."""

    def test_download_spec_url_format(self) -> None:
        """Test download URL format."""

    def test_download_spec_extract_enabled(self) -> None:
        """Test that extraction is enabled."""

    def test_download_spec_format_tar_bz2(self) -> None:
        """Test extract format is tar.bz2."""


class TestWaterfoxUpdateWithDownload:
    """Tests for Waterfox update using download spec."""

    @pytest.mark.asyncio
    async def test_update_uses_downloaded_file(self) -> None:
        """Test that update uses the downloaded file."""

    @pytest.mark.asyncio
    async def test_update_commands_reference_download_path(self) -> None:
        """Test that update commands use download path."""
```

##### Go Runtime Plugin Tests (`plugins/tests/test_go_runtime_download.py`)

```python
class TestGoRuntimeDownloadSpec:
    """Tests for Go runtime plugin download spec."""

    def test_get_download_spec_returns_spec(self) -> None:
        """Test that get_download_spec returns a valid spec."""

    def test_download_spec_url_includes_version(self) -> None:
        """Test download URL includes version."""

    def test_download_spec_url_includes_arch(self) -> None:
        """Test download URL includes architecture."""

    def test_download_spec_extract_enabled(self) -> None:
        """Test that extraction is enabled."""
```

##### Calibre Plugin Tests (`plugins/tests/test_calibre_download.py`)

```python
class TestCalibreDownloadSpec:
    """Tests for Calibre plugin download spec."""

    def test_get_download_spec_returns_spec(self) -> None:
        """Test that get_download_spec returns a valid spec."""

    def test_download_spec_url_is_installer(self) -> None:
        """Test download URL is the installer script."""

    def test_download_spec_no_extraction(self) -> None:
        """Test that extraction is disabled (it's a script)."""
```

---

## Plugin Migration Plan

### Migration Priority

| Priority | Plugin | Complexity | Download Size | Notes |
|----------|--------|------------|---------------|-------|
| P0 | `waterfox.py` | Medium | ~100MB | Most complex download logic |
| P0 | `go_runtime.py` | Medium | ~150MB | Shell script download |
| P1 | `calibre.py` | Low | ~100MB | Simple wget call |

### Migration Checklist per Plugin

For each plugin migration:

- [ ] Write tests for `get_download_spec()` method
- [ ] Implement `get_download_spec()` method
- [ ] Write tests for updated `get_update_commands()` method
- [ ] Update `get_update_commands()` to use download path
- [ ] Remove legacy download code from `_execute_update()`
- [ ] Remove legacy download code from `_execute_update_streaming()`
- [ ] Update `supports_download` property if needed
- [ ] Run all tests and verify passing
- [ ] Update plugin docstring

### Waterfox Migration Details

**Before (current implementation):**
```python
async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
    # ... version checking ...

    # Manual download with urllib
    with tempfile.TemporaryDirectory() as tmpdir:
        tarball_path = Path(tmpdir) / f"waterfox-{remote_version}.tar.bz2"
        request = urllib.request.Request(download_url, ...)
        with urllib.request.urlopen(request, timeout=300) as response:
            with tarball_path.open("wb") as f:
                f.write(response.read())

        # Manual extraction
        await self._run_command(["tar", "-xjf", str(tarball_path), ...])

        # Installation
        await self._run_command(["rm", "-rf", self.INSTALL_PATH], sudo=True)
        await self._run_command(["mv", str(extracted_dir), self.INSTALL_PATH], sudo=True)
```

**After (with DownloadSpec):**
```python
def get_download_spec(self) -> DownloadSpec | None:
    remote_version = self.get_remote_version()
    if not remote_version:
        return None

    local_version = self.get_local_version()
    if local_version == remote_version:
        return None  # No download needed

    return DownloadSpec(
        url=self._get_download_url(remote_version),
        destination=Path(f"/tmp/waterfox-{remote_version}"),
        extract=True,
        extract_format="tar.bz2",
    )

def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
    if dry_run:
        return [UpdateCommand(cmd=[self.command, "--version"])]

    # download_path is set by base class after download
    if not hasattr(self, "_download_path") or not self._download_path:
        return []  # No download, nothing to install

    return [
        UpdateCommand(
            cmd=["rm", "-rf", self.INSTALL_PATH],
            sudo=True,
            description="Remove old installation",
            step_number=1,
            total_steps=3,
        ),
        UpdateCommand(
            cmd=["mv", str(self._download_path / "waterfox"), self.INSTALL_PATH],
            sudo=True,
            description="Install new version",
            step_number=2,
            total_steps=3,
        ),
        UpdateCommand(
            cmd=["chown", "-R", "root:root", self.INSTALL_PATH],
            sudo=True,
            description="Set ownership",
            step_number=3,
            total_steps=3,
        ),
    ]
```

### Go Runtime Migration Details

**Before (current implementation):**
```python
update_script = f"""
set -euo pipefail
tmp=$(mktemp -d)
cd "$tmp"
echo "Downloading {download_url}..."
curl -OL "{download_url}"
mkdir -p "{apps_dir}"
rm -f "{apps_dir}/go" 2>/dev/null || true
tar -C "{apps_dir}" -xzf "{release_file}"
mv "{apps_dir}/go" "{apps_dir}/{remote_version}"
ln -sf "{apps_dir}/{remote_version}" "{apps_dir}/go"
cd /
rm -rf "$tmp"
"""
```

**After (with DownloadSpec):**
```python
def get_download_spec(self) -> DownloadSpec | None:
    remote_version = self.get_remote_version()
    if not remote_version:
        return None

    local_version = self.get_local_version()
    if local_version == remote_version:
        return None

    return DownloadSpec(
        url=self._get_download_url(remote_version),
        destination=Path(f"/tmp/go-{remote_version}"),
        extract=True,
        extract_format="tar.gz",
    )

def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
    if dry_run:
        return [UpdateCommand(cmd=["go", "version"])]

    if not hasattr(self, "_download_path") or not self._download_path:
        return []

    apps_dir = str(Path(self.DEFAULT_APPS_DIR).expanduser())
    remote_version = self.get_remote_version()

    return [
        UpdateCommand(
            cmd=["mkdir", "-p", apps_dir],
            description="Create apps directory",
            step_number=1,
            total_steps=4,
        ),
        UpdateCommand(
            cmd=["rm", "-f", f"{apps_dir}/go"],
            description="Remove old symlink",
            step_number=2,
            total_steps=4,
            ignore_exit_codes=(1,),  # OK if doesn't exist
        ),
        UpdateCommand(
            cmd=["mv", str(self._download_path / "go"), f"{apps_dir}/{remote_version}"],
            description="Move to version directory",
            step_number=3,
            total_steps=4,
        ),
        UpdateCommand(
            cmd=["ln", "-sf", f"{apps_dir}/{remote_version}", f"{apps_dir}/go"],
            description="Create symlink",
            step_number=4,
            total_steps=4,
        ),
    ]
```

---

## Documentation Updates

### Files to Update

#### 1. `docs/plugin-development.md`

Add new section: **"Centralized Download Manager"**

```markdown
### Centralized Download Manager

For plugins that need to download files (binaries, tarballs, installers),
use the centralized download manager instead of implementing download logic
manually.

#### Using DownloadSpec

Override `get_download_spec()` to declare what needs to be downloaded:

\`\`\`python
from pathlib import Path
from core.models import DownloadSpec

def get_download_spec(self) -> DownloadSpec | None:
    version = self.get_remote_version()
    if not version:
        return None

    return DownloadSpec(
        url=f"https://example.com/v{version}.tar.gz",
        destination=Path(f"/tmp/myapp-{version}"),
        expected_size=100_000_000,  # Optional: for progress
        checksum=f"sha256:{self._get_checksum(version)}",  # Optional: for verification
        extract=True,
        extract_format="tar.gz",
    )
\`\`\`

#### Benefits

- **Automatic progress reporting** — Download progress is shown in the UI
- **Retry logic** — Failed downloads are automatically retried
- **Resume support** — Large downloads can resume from where they left off
- **Bandwidth limiting** — Downloads respect global bandwidth limits
- **Caching** — Downloaded files are cached for faster re-runs
- **Checksum verification** — Files are verified before use

#### Accessing Downloaded Files

After download, the file path is available via `self._download_path`:

\`\`\`python
def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
    if not self._download_path:
        return []  # No download, skip installation

    return [
        UpdateCommand(
            cmd=["mv", str(self._download_path), "/opt/myapp"],
            sudo=True,
        ),
    ]
\`\`\`

#### DownloadSpec Reference

| Field | Type | Description |
|-------|------|-------------|
| `url` | `str` | URL to download (required) |
| `destination` | `Path` | Local path to save file (required) |
| `expected_size` | `int \| None` | Expected size in bytes |
| `checksum` | `str \| None` | Checksum (format: "sha256:abc...") |
| `extract` | `bool` | Whether to extract archive |
| `extract_format` | `str \| None` | Archive format (tar.gz, zip, etc.) |
| `headers` | `dict \| None` | Additional HTTP headers |
| `timeout_seconds` | `int \| None` | Download timeout |
```

#### 2. Update Existing Sections

- Update "Download Phase Support" section to reference `get_download_spec()`
- Update "Streaming Output" section to mention download progress events
- Add migration note for plugins using legacy download methods

---

## Risk Assessment

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| HTTP library compatibility | Low | Medium | Use aiohttp with fallback to urllib |
| Large file memory issues | Medium | High | Stream to disk, don't load in memory |
| Extraction failures | Low | Medium | Validate archive before extraction |
| Cache corruption | Low | Medium | Use atomic writes, verify checksums |

### Migration Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Breaking existing plugins | Low | High | Keep legacy API, add deprecation warnings |
| Test coverage gaps | Medium | Medium | Require 80%+ coverage for new code |
| Performance regression | Low | Medium | Benchmark before/after migration |

---

## Timeline

### Week 1-2: Core Infrastructure

- [ ] Day 1-2: Write tests for DownloadSpec and DownloadResult
- [ ] Day 3-4: Implement DownloadSpec and DownloadResult
- [ ] Day 5-6: Write tests for DownloadManager basic functionality
- [ ] Day 7-8: Implement DownloadManager basic download
- [ ] Day 9-10: Add progress reporting and completion events

### Week 2-3: BasePlugin Integration

- [ ] Day 11-12: Write tests for BasePlugin integration
- [ ] Day 13-14: Implement get_download_spec() in BasePlugin
- [ ] Day 15-16: Integrate with execute flow
- [ ] Day 17-18: Write integration tests

### Week 3-4: Plugin Migration

- [ ] Day 19-20: Migrate Waterfox plugin
- [ ] Day 21-22: Migrate Go runtime plugin
- [ ] Day 23-24: Migrate Calibre plugin
- [ ] Day 25-26: Integration testing

### Week 4-5: Advanced Features

- [ ] Day 27-28: Add resume support
- [ ] Day 29-30: Add bandwidth limiting
- [ ] Day 31-32: Add caching
- [ ] Day 33-34: Documentation updates
- [ ] Day 35: Final review and cleanup

---

## Success Criteria

### Functional Requirements

- [ ] All download-capable plugins use `get_download_spec()`
- [ ] Progress events are emitted during downloads
- [ ] Checksums are verified when provided
- [ ] Archives are extracted correctly
- [ ] Failed downloads are retried automatically

### Non-Functional Requirements

- [ ] Test coverage ≥ 80% for new code
- [ ] No performance regression (benchmark)
- [ ] Documentation updated
- [ ] All existing tests pass

### Plugin Migration Metrics

| Plugin | Lines Before | Lines After | Reduction |
|--------|-------------|-------------|-----------|
| waterfox.py | ~380 | ~200 | ~47% |
| go_runtime.py | ~460 | ~280 | ~39% |
| calibre.py | ~320 | ~200 | ~37% |

---

## Appendix: API Reference

### DownloadSpec

```python
@dataclass(frozen=True)
class DownloadSpec:
    url: str                           # Required: URL to download
    destination: Path                  # Required: Local save path
    expected_size: int | None = None   # Optional: For progress reporting
    checksum: str | None = None        # Optional: "sha256:..." or "md5:..."
    extract: bool = False              # Optional: Extract after download
    extract_format: str | None = None  # Optional: "tar.gz", "zip", etc.
    headers: dict[str, str] | None = None  # Optional: HTTP headers
    timeout_seconds: int | None = None # Optional: Download timeout
    version_url: str | None = None     # Optional: URL to check version
    version_pattern: str | None = None # Optional: Regex for version
```

### DownloadResult

```python
@dataclass
class DownloadResult:
    success: bool                      # Whether download succeeded
    path: Path | None = None           # Path to downloaded file
    bytes_downloaded: int = 0          # Total bytes downloaded
    duration_seconds: float = 0.0      # Time taken
    from_cache: bool = False           # Whether served from cache
    checksum_verified: bool = False    # Whether checksum was verified
    error_message: str | None = None   # Error message if failed
```

### DownloadManager

```python
class DownloadManager:
    def __init__(
        self,
        cache_dir: Path | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        bandwidth_limit_bytes: int | None = None,
        max_concurrent_downloads: int = 2,
    ) -> None: ...

    async def download(
        self,
        spec: DownloadSpec,
        plugin_name: str,
    ) -> AsyncIterator[StreamEvent]: ...

    async def download_batch(
        self,
        specs: list[DownloadSpec],
        plugin_name: str,
    ) -> AsyncIterator[StreamEvent]: ...

    def get_cached_path(self, spec: DownloadSpec) -> Path | None: ...

    def clear_cache(self, max_age_days: int | None = None) -> int: ...
```

### BasePlugin Methods

```python
class BasePlugin:
    def get_download_spec(self) -> DownloadSpec | None:
        """Return download specification if plugin needs to download files."""
        return None

    def get_download_specs(self) -> list[DownloadSpec]:
        """Return multiple download specifications."""
        spec = self.get_download_spec()
        return [spec] if spec else []
```
