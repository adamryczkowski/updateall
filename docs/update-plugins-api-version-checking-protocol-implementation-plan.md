# Version Checking Protocol Implementation Plan

**Date:** January 7, 2026
**Status:** Draft
**Proposal Reference:** Proposal 3 from `docs/update-plugins-api-rewrite.md`

## Executive Summary

This document provides a detailed implementation plan for the Version Checking Protocol (Proposal 3) from the Update Plugins API Rewrite proposal. The protocol standardizes how plugins check for updates by introducing four new methods:

- `get_installed_version()` - Get currently installed version
- `get_available_version()` - Get latest available version
- `needs_update()` - Check if update is needed by comparing versions
- `get_update_estimate()` - Get estimated download size and package count (optional)

This implementation follows a Test-Driven Development (TDD) approach and includes migration plans for all eligible plugins.

---

## Table of Contents

1. [Goals and Benefits](#goals-and-benefits)
2. [Current State Analysis](#current-state-analysis)
3. [API Design](#api-design)
4. [Implementation Phases](#implementation-phases)
5. [Test Plan (TDD Approach)](#test-plan-tdd-approach)
6. [Plugin Migration Plan](#plugin-migration-plan)
7. [Download Size Estimation Research](#download-size-estimation-research)
8. [Documentation Updates](#documentation-updates)
9. [Risk Analysis](#risk-analysis)
10. [Timeline](#timeline)

---

## Goals and Benefits

### Primary Goals

1. **Standardize version checking** across all plugins
2. **Enable "check-only" mode** to see what updates are available without applying them
3. **Skip up-to-date plugins** to reduce unnecessary work
4. **Provide version-based progress reporting** for better UX
5. **Support the `estimate-update` CLI command** from the plugin CLI API requirements

### Expected Benefits

| Benefit | Description |
|---------|-------------|
| Consistent UX | All plugins report versions the same way |
| Faster updates | Skip plugins that are already up-to-date |
| Better estimates | Version info enables better time/size predictions |
| Check-only mode | Users can see what would be updated before running |
| Integration with stats | Historical version data for trend analysis |

---

## Current State Analysis

### Plugins with Existing Version Checking

The following plugins already implement version checking methods (but inconsistently):

| Plugin | Local Version Method | Remote Version Method | Needs Update Method |
|--------|---------------------|----------------------|---------------------|
| `waterfox.py` | `get_local_version()` | `get_remote_version()` | `needs_update()` |
| `go_runtime.py` | `get_local_version()` | `get_remote_version()` | `needs_update()` |
| `poetry.py` | `get_local_version()` | ❌ | ❌ |
| `calibre.py` | `_get_current_version()` | ❌ | ❌ |
| `texlive_self.py` | `get_local_version()` | ❌ | ❌ |
| `spack.py` | `get_local_version()` + `_get_git_commit()` | ❌ | ❌ |

### Plugins Without Version Checking

These plugins could benefit from version checking but don't implement it:

| Plugin | Version Check Feasibility | Notes |
|--------|--------------------------|-------|
| `apt.py` | Medium | Can use `apt list --upgradable` |
| `pipx.py` | Low | No single version, multiple packages |
| `flatpak.py` | Low | No single version, multiple apps |
| `snap.py` | Low | No single version, multiple snaps |
| `cargo.py` | Low | No single version, multiple crates |
| `rustup.py` | High | `rustup check` provides version info |
| `npm.py` | Low | No single version, multiple packages |
| `conda_*.py` | Medium | Conda has version info |
| `julia_*.py` | High | Julia has version commands |
| `pihole.py` | High | Pi-hole has version API |
| `yt_dlp.py` | High | `yt-dlp --version` + PyPI API |
| `youtube_dl.py` | High | Similar to yt-dlp |

### Version Checking Patterns Identified

1. **Subprocess + Regex** - Run `command --version` and parse output
2. **HTTP API** - Fetch version from GitHub API or package registry
3. **Git-based** - Compare git commits for source-installed tools
4. **Package manager query** - Use package manager's own query commands

---

## API Design

### New Methods in `BasePlugin`

```python
class BasePlugin(UpdatePlugin):
    """Base class for all update plugins."""

    async def get_installed_version(self) -> str | None:
        """Get the currently installed version.

        Override this method to provide version information for the
        managed software. The default implementation attempts to run
        `{command} --version` and parse the output.

        Returns:
            Version string (e.g., "1.2.3") or None if:
            - Software is not installed
            - Version cannot be determined
            - Version checking is not supported

        Example:
            async def get_installed_version(self) -> str | None:
                if not await self.check_available():
                    return None
                code, stdout, _ = await self._run_command(
                    ["myapp", "--version"], timeout=10
                )
                if code == 0:
                    match = re.search(r"(\d+\.\d+\.\d+)", stdout)
                    return match.group(1) if match else None
                return None
        """
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available version.

        Override this method to check for the latest version from
        the upstream source (e.g., GitHub releases, package registry).

        Returns:
            Version string (e.g., "1.3.0") or None if:
            - Version cannot be determined
            - Network is unavailable
            - Version checking is not supported

        Example:
            async def get_available_version(self) -> str | None:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(self.VERSION_URL) as resp:
                            data = await resp.json()
                            return data.get("tag_name", "").lstrip("v")
                except Exception:
                    return None
        """
        return None

    async def needs_update(self) -> bool | None:
        """Check if an update is needed.

        Compares installed version with available version to determine
        if an update should be performed.

        Returns:
            - True: Update is available
            - False: Already up-to-date
            - None: Cannot determine (version check not supported or failed)

        The default implementation compares versions from
        get_installed_version() and get_available_version().
        Override for custom comparison logic (e.g., semantic versioning).

        Example:
            async def needs_update(self) -> bool | None:
                installed = await self.get_installed_version()
                available = await self.get_available_version()
                if not installed or not available:
                    return None  # Cannot determine
                return version.parse(installed) < version.parse(available)
        """
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed is None or available is None:
            return None  # Cannot determine

        # Simple string comparison (override for semantic versioning)
        return installed != available

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size and package count for the update.

        Override this method to provide download size estimates. This is
        particularly useful for package managers like apt, flatpak, and snap
        that can report download sizes before performing updates.

        Returns:
            UpdateEstimate with download_bytes, package_count, etc., or None
            if estimation is not supported or no update is needed.

        Example (apt):
            async def get_update_estimate(self) -> UpdateEstimate | None:
                # Run apt-get upgrade --dry-run to get download size
                code, stdout, _ = await self._run_command(
                    ["apt-get", "upgrade", "--dry-run"],
                    timeout=60,
                    sudo=True,
                )
                if code != 0:
                    return None

                # Parse output for download size and package count
                # Example: "Need to get 150 MB of archives"
                size_match = re.search(r"Need to get ([\d.]+)\s*(\w+)", stdout)
                count_match = re.search(r"(\d+)\s+upgraded", stdout)

                download_bytes = None
                if size_match:
                    size, unit = size_match.groups()
                    multipliers = {"B": 1, "kB": 1024, "MB": 1024**2, "GB": 1024**3}
                    download_bytes = int(float(size) * multipliers.get(unit, 1))

                package_count = int(count_match.group(1)) if count_match else None

                return UpdateEstimate(
                    download_bytes=download_bytes,
                    package_count=package_count,
                )
        """
        return None

    @property
    def supports_version_check(self) -> bool:
        """Check if this plugin supports version checking.

        Returns True if the plugin has implemented version checking
        by overriding get_installed_version() or get_available_version().

        Returns:
            True if version checking is supported, False otherwise.
        """
        # Check if methods are overridden from BasePlugin
        return (
            type(self).get_installed_version is not BasePlugin.get_installed_version
            or type(self).get_available_version is not BasePlugin.get_available_version
        )

    @property
    def supports_update_estimate(self) -> bool:
        """Check if this plugin supports update estimation.

        Returns True if the plugin has implemented get_update_estimate().

        Returns:
            True if update estimation is supported, False otherwise.
        """
        return type(self).get_update_estimate is not BasePlugin.get_update_estimate
```

### New Data Models

```python
# In core/models.py

@dataclass(frozen=True)
class UpdateEstimate:
    """Estimated resource requirements for an update.

    This dataclass provides information about the expected download size,
    package count, and estimated time for an update. This enables:
    - Showing users how much bandwidth an update will require
    - Estimating total update time across all plugins
    - Making informed decisions about when to run updates
    """

    # Download information
    download_bytes: int | None = None
    download_bytes_formatted: str | None = None  # e.g., "150 MB"

    # Package information
    package_count: int | None = None
    packages: list[str] | None = None  # List of package names

    # Time estimates (based on historical data or heuristics)
    estimated_seconds: float | None = None

    # Confidence level (0.0 - 1.0)
    confidence: float | None = None

    @property
    def has_download_info(self) -> bool:
        """Check if download size information is available."""
        return self.download_bytes is not None

    def format_download_size(self) -> str:
        """Format download size in human-readable format."""
        if self.download_bytes is None:
            return "Unknown"
        if self.download_bytes < 1024:
            return f"{self.download_bytes} B"
        elif self.download_bytes < 1024 * 1024:
            return f"{self.download_bytes / 1024:.1f} KB"
        elif self.download_bytes < 1024 * 1024 * 1024:
            return f"{self.download_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{self.download_bytes / (1024 * 1024 * 1024):.2f} GB"


@dataclass(frozen=True)
class VersionInfo:
    """Version information for a plugin."""

    installed: str | None = None
    available: str | None = None
    needs_update: bool | None = None
    check_time: datetime | None = None
    error_message: str | None = None

    # Update estimate (optional, for plugins that support it)
    estimate: UpdateEstimate | None = None

    @property
    def is_up_to_date(self) -> bool | None:
        """Check if the software is up-to-date."""
        if self.needs_update is None:
            return None
        return not self.needs_update

    @property
    def version_change(self) -> str | None:
        """Get version change string (e.g., '1.2.3 -> 1.3.0')."""
        if self.installed and self.available and self.needs_update:
            return f"{self.installed} -> {self.available}"
        return None

    @property
    def download_size(self) -> str | None:
        """Get formatted download size if available."""
        if self.estimate and self.estimate.has_download_info:
            return self.estimate.format_download_size()
        return None
```

### Integration with UpdatePlugin Interface

```python
# In core/interfaces.py

class UpdatePlugin(ABC):
    """Abstract base class for update plugins."""

    # ... existing methods ...

    async def get_version_info(self) -> VersionInfo:
        """Get complete version information.

        This method aggregates version checking results into a
        single VersionInfo object for easy consumption. If the plugin
        supports update estimation and an update is needed, it will
        also include download size and package count information.

        Returns:
            VersionInfo with installed, available, needs_update, and
            optionally estimate fields.
        """
        from datetime import UTC, datetime
        from .models import VersionInfo

        try:
            installed = await self.get_installed_version()
            available = await self.get_available_version()
            needs_update = await self.needs_update()

            # Get update estimate if supported and update is needed
            estimate = None
            if needs_update and self.supports_update_estimate:
                estimate = await self.get_update_estimate()

            return VersionInfo(
                installed=installed,
                available=available,
                needs_update=needs_update,
                check_time=datetime.now(tz=UTC),
                estimate=estimate,
            )
        except Exception as e:
            return VersionInfo(
                check_time=datetime.now(tz=UTC),
                error_message=str(e),
            )

    async def get_installed_version(self) -> str | None:
        """Get the currently installed version."""
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available version."""
        return None

    async def needs_update(self) -> bool | None:
        """Check if an update is needed."""
        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size and package count."""
        return None

    @property
    def supports_update_estimate(self) -> bool:
        """Check if this plugin supports update estimation."""
        return False
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)

**Goal:** Add version checking methods to base classes and core models.

#### Tasks

1. **Add `VersionInfo` dataclass to `core/models.py`**
   - Fields: `installed`, `available`, `needs_update`, `check_time`, `error_message`
   - Properties: `is_up_to_date`, `version_change`

2. **Add abstract methods to `core/interfaces.py`**
   - `get_installed_version()` with default return `None`
   - `get_available_version()` with default return `None`
   - `needs_update()` with default implementation
   - `get_version_info()` aggregation method

3. **Implement base methods in `plugins/base.py`**
   - Default `needs_update()` comparing versions
   - `supports_version_check` property
   - Helper method `_parse_version_output()` for common patterns

4. **Add version comparison utilities**
   - Create `core/version.py` with version parsing and comparison
   - Support semantic versioning (major.minor.patch)
   - Support date-based versions (YYYY.MM.DD)
   - Support git commit hashes

#### Deliverables

- [ ] `core/models.py` updated with `VersionInfo`
- [ ] `core/interfaces.py` updated with version methods
- [ ] `plugins/base.py` updated with default implementations
- [ ] `core/version.py` created with version utilities
- [ ] Unit tests for all new code

---

### Phase 2: Plugin Migration - High Priority (Week 2)

**Goal:** Migrate plugins that already have version checking logic.

#### Plugins to Migrate

| Plugin | Current Methods | Migration Effort |
|--------|----------------|------------------|
| `waterfox.py` | `get_local_version()`, `get_remote_version()`, `needs_update()` | Low - rename methods |
| `go_runtime.py` | `get_local_version()`, `get_remote_version()`, `needs_update()` | Low - rename methods |
| `poetry.py` | `get_local_version()` | Medium - add remote check |
| `calibre.py` | `_get_current_version()` | Medium - rename + add remote |
| `texlive_self.py` | `get_local_version()` | Medium - add remote check |
| `spack.py` | `get_local_version()`, `_get_git_commit()` | Medium - git-based remote |

#### Migration Steps per Plugin

1. Rename existing methods to match new API
2. Make methods `async` if not already
3. Add `get_available_version()` if missing
4. Update `needs_update()` to use new comparison logic
5. Add tests for version checking
6. Update plugin docstring

#### Deliverables

- [ ] 6 plugins migrated to new API
- [ ] Tests for each migrated plugin
- [ ] Backward compatibility maintained

---

### Phase 3: Plugin Migration - Medium Priority (Week 3)

**Goal:** Add version checking to plugins where it's feasible.

#### Plugins to Enhance

| Plugin | Version Source | Implementation Notes |
|--------|---------------|---------------------|
| `rustup.py` | `rustup check` | Parse output for version info |
| `pihole.py` | Pi-hole API | HTTP request to local API |
| `yt_dlp.py` | `yt-dlp --version` + PyPI | Compare with PyPI latest |
| `youtube_dl.py` | Similar to yt-dlp | PyPI version check |
| `julia_runtime.py` | `julia --version` + releases | GitHub releases API |
| `julia_packages.py` | `Pkg.status()` | Parse package versions |

#### Deliverables

- [ ] 6 additional plugins with version checking
- [ ] Tests for each enhanced plugin
- [ ] Documentation for version check patterns

---

### Phase 4: Integration and CLI (Week 4)

**Goal:** Integrate version checking into the CLI and orchestrator.

#### Tasks

1. **Add `check` command to CLI**
   ```bash
   update-all check              # Check all plugins for updates
   update-all check --plugin apt # Check specific plugin
   update-all check --json       # Output as JSON
   ```

2. **Update orchestrator to use version checking**
   - Skip plugins where `needs_update()` returns `False`
   - Show version info in progress display
   - Log version changes in statistics

3. **Add version info to streaming events**
   - New `VersionCheckEvent` type
   - Emit before update execution
   - Include in completion summary

4. **Update statistics collection**
   - Track version changes over time
   - Store version history per plugin
   - Enable trend analysis

#### Deliverables

- [ ] `check` CLI command implemented
- [ ] Orchestrator integration complete
- [ ] Streaming events updated
- [ ] Statistics integration complete

---

## Test Plan (TDD Approach)

### Test Categories

Following TDD principles, tests should be written **before** implementation.

### Unit Tests

#### 1. VersionInfo Model Tests (`core/tests/test_models.py`)

```python
class TestVersionInfo:
    """Tests for VersionInfo dataclass."""

    def test_version_info_creation(self) -> None:
        """Test creating VersionInfo with all fields."""
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
        )
        assert info.installed == "1.2.3"
        assert info.available == "1.3.0"
        assert info.needs_update is True

    def test_version_info_defaults(self) -> None:
        """Test VersionInfo default values."""
        info = VersionInfo()
        assert info.installed is None
        assert info.available is None
        assert info.needs_update is None
        assert info.check_time is None
        assert info.error_message is None

    def test_is_up_to_date_true(self) -> None:
        """Test is_up_to_date when no update needed."""
        info = VersionInfo(needs_update=False)
        assert info.is_up_to_date is True

    def test_is_up_to_date_false(self) -> None:
        """Test is_up_to_date when update needed."""
        info = VersionInfo(needs_update=True)
        assert info.is_up_to_date is False

    def test_is_up_to_date_none(self) -> None:
        """Test is_up_to_date when cannot determine."""
        info = VersionInfo(needs_update=None)
        assert info.is_up_to_date is None

    def test_version_change_string(self) -> None:
        """Test version_change property."""
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
        )
        assert info.version_change == "1.2.3 -> 1.3.0"

    def test_version_change_none_when_up_to_date(self) -> None:
        """Test version_change is None when up-to-date."""
        info = VersionInfo(
            installed="1.3.0",
            available="1.3.0",
            needs_update=False,
        )
        assert info.version_change is None

    def test_version_change_none_when_missing_versions(self) -> None:
        """Test version_change is None when versions missing."""
        info = VersionInfo(needs_update=True)
        assert info.version_change is None

    def test_version_info_with_estimate(self) -> None:
        """Test VersionInfo with UpdateEstimate."""
        estimate = UpdateEstimate(download_bytes=157286400, package_count=15)
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
            estimate=estimate,
        )
        assert info.estimate is not None
        assert info.download_size == "150.0 MB"

    def test_download_size_none_without_estimate(self) -> None:
        """Test download_size is None when no estimate."""
        info = VersionInfo(needs_update=True)
        assert info.download_size is None


class TestUpdateEstimate:
    """Tests for UpdateEstimate dataclass."""

    def test_update_estimate_creation(self) -> None:
        """Test creating UpdateEstimate with all fields."""
        estimate = UpdateEstimate(
            download_bytes=157286400,
            package_count=15,
            packages=["pkg1", "pkg2"],
            estimated_seconds=120.5,
            confidence=0.85,
        )
        assert estimate.download_bytes == 157286400
        assert estimate.package_count == 15
        assert estimate.packages == ["pkg1", "pkg2"]
        assert estimate.estimated_seconds == 120.5
        assert estimate.confidence == 0.85

    def test_update_estimate_defaults(self) -> None:
        """Test UpdateEstimate default values."""
        estimate = UpdateEstimate()
        assert estimate.download_bytes is None
        assert estimate.package_count is None
        assert estimate.packages is None
        assert estimate.estimated_seconds is None
        assert estimate.confidence is None

    def test_has_download_info_true(self) -> None:
        """Test has_download_info when download_bytes is set."""
        estimate = UpdateEstimate(download_bytes=1024)
        assert estimate.has_download_info is True

    def test_has_download_info_false(self) -> None:
        """Test has_download_info when download_bytes is None."""
        estimate = UpdateEstimate()
        assert estimate.has_download_info is False

    def test_format_download_size_bytes(self) -> None:
        """Test formatting small sizes in bytes."""
        estimate = UpdateEstimate(download_bytes=512)
        assert estimate.format_download_size() == "512 B"

    def test_format_download_size_kilobytes(self) -> None:
        """Test formatting sizes in kilobytes."""
        estimate = UpdateEstimate(download_bytes=2048)
        assert estimate.format_download_size() == "2.0 KB"

    def test_format_download_size_megabytes(self) -> None:
        """Test formatting sizes in megabytes."""
        estimate = UpdateEstimate(download_bytes=157286400)
        assert estimate.format_download_size() == "150.0 MB"

    def test_format_download_size_gigabytes(self) -> None:
        """Test formatting sizes in gigabytes."""
        estimate = UpdateEstimate(download_bytes=2147483648)
        assert estimate.format_download_size() == "2.00 GB"

    def test_format_download_size_unknown(self) -> None:
        """Test formatting when download_bytes is None."""
        estimate = UpdateEstimate()
        assert estimate.format_download_size() == "Unknown"
```

#### 2. Version Comparison Tests (`core/tests/test_version.py`)

```python
class TestVersionComparison:
    """Tests for version comparison utilities."""

    def test_parse_semantic_version(self) -> None:
        """Test parsing semantic version strings."""
        assert parse_version("1.2.3") == (1, 2, 3)
        assert parse_version("v1.2.3") == (1, 2, 3)
        assert parse_version("1.2") == (1, 2, 0)
        assert parse_version("1") == (1, 0, 0)

    def test_parse_date_version(self) -> None:
        """Test parsing date-based versions."""
        assert parse_version("2024.01.15") == (2024, 1, 15)
        assert parse_version("2024.1.5") == (2024, 1, 5)

    def test_compare_versions_less_than(self) -> None:
        """Test version comparison: less than."""
        assert compare_versions("1.2.3", "1.3.0") < 0
        assert compare_versions("1.2.3", "2.0.0") < 0
        assert compare_versions("1.2.3", "1.2.4") < 0

    def test_compare_versions_equal(self) -> None:
        """Test version comparison: equal."""
        assert compare_versions("1.2.3", "1.2.3") == 0
        assert compare_versions("v1.2.3", "1.2.3") == 0

    def test_compare_versions_greater_than(self) -> None:
        """Test version comparison: greater than."""
        assert compare_versions("1.3.0", "1.2.3") > 0
        assert compare_versions("2.0.0", "1.2.3") > 0

    def test_compare_versions_with_prerelease(self) -> None:
        """Test version comparison with prerelease tags."""
        assert compare_versions("1.2.3-alpha", "1.2.3") < 0
        assert compare_versions("1.2.3-beta", "1.2.3-alpha") > 0
        assert compare_versions("1.2.3-rc1", "1.2.3-beta") > 0

    def test_needs_update_simple(self) -> None:
        """Test needs_update with simple versions."""
        assert needs_update("1.2.3", "1.3.0") is True
        assert needs_update("1.3.0", "1.3.0") is False
        assert needs_update("1.3.0", "1.2.3") is False

    def test_needs_update_with_none(self) -> None:
        """Test needs_update with None values."""
        assert needs_update(None, "1.3.0") is None
        assert needs_update("1.2.3", None) is None
        assert needs_update(None, None) is None
```

#### 3. BasePlugin Version Methods Tests (`plugins/tests/test_version_checking.py`)

```python
class TestBasePluginVersionMethods:
    """Tests for BasePlugin version checking methods."""

    @pytest.mark.asyncio
    async def test_get_installed_version_default(self) -> None:
        """Test default get_installed_version returns None."""
        plugin = MinimalTestPlugin()
        assert await plugin.get_installed_version() is None

    @pytest.mark.asyncio
    async def test_get_available_version_default(self) -> None:
        """Test default get_available_version returns None."""
        plugin = MinimalTestPlugin()
        assert await plugin.get_available_version() is None

    @pytest.mark.asyncio
    async def test_needs_update_default_with_no_versions(self) -> None:
        """Test needs_update returns None when versions unavailable."""
        plugin = MinimalTestPlugin()
        assert await plugin.needs_update() is None

    @pytest.mark.asyncio
    async def test_needs_update_with_versions(self) -> None:
        """Test needs_update compares versions correctly."""
        plugin = VersionedTestPlugin(
            installed_version="1.2.3",
            available_version="1.3.0",
        )
        assert await plugin.needs_update() is True

    @pytest.mark.asyncio
    async def test_needs_update_when_up_to_date(self) -> None:
        """Test needs_update returns False when up-to-date."""
        plugin = VersionedTestPlugin(
            installed_version="1.3.0",
            available_version="1.3.0",
        )
        assert await plugin.needs_update() is False

    @pytest.mark.asyncio
    async def test_get_version_info_aggregation(self) -> None:
        """Test get_version_info aggregates all version data."""
        plugin = VersionedTestPlugin(
            installed_version="1.2.3",
            available_version="1.3.0",
        )
        info = await plugin.get_version_info()
        assert info.installed == "1.2.3"
        assert info.available == "1.3.0"
        assert info.needs_update is True
        assert info.check_time is not None

    @pytest.mark.asyncio
    async def test_get_version_info_handles_errors(self) -> None:
        """Test get_version_info captures errors."""
        plugin = ErroringVersionPlugin()
        info = await plugin.get_version_info()
        assert info.error_message is not None

    def test_supports_version_check_false_by_default(self) -> None:
        """Test supports_version_check is False for base plugin."""
        plugin = MinimalTestPlugin()
        assert plugin.supports_version_check is False

    def test_supports_version_check_true_when_overridden(self) -> None:
        """Test supports_version_check is True when methods overridden."""
        plugin = VersionedTestPlugin()
        assert plugin.supports_version_check is True

    @pytest.mark.asyncio
    async def test_get_update_estimate_default(self) -> None:
        """Test default get_update_estimate returns None."""
        plugin = MinimalTestPlugin()
        assert await plugin.get_update_estimate() is None

    def test_supports_update_estimate_false_by_default(self) -> None:
        """Test supports_update_estimate is False for base plugin."""
        plugin = MinimalTestPlugin()
        assert plugin.supports_update_estimate is False

    def test_supports_update_estimate_true_when_overridden(self) -> None:
        """Test supports_update_estimate is True when method overridden."""
        plugin = EstimatingTestPlugin()
        assert plugin.supports_update_estimate is True

    @pytest.mark.asyncio
    async def test_get_update_estimate_returns_estimate(self) -> None:
        """Test get_update_estimate returns UpdateEstimate."""
        plugin = EstimatingTestPlugin(
            download_bytes=157286400,
            package_count=15,
        )
        estimate = await plugin.get_update_estimate()
        assert estimate is not None
        assert estimate.download_bytes == 157286400
        assert estimate.package_count == 15

    @pytest.mark.asyncio
    async def test_get_version_info_includes_estimate(self) -> None:
        """Test get_version_info includes estimate when update needed."""
        plugin = EstimatingTestPlugin(
            installed_version="1.2.3",
            available_version="1.3.0",
            download_bytes=157286400,
            package_count=15,
        )
        info = await plugin.get_version_info()
        assert info.needs_update is True
        assert info.estimate is not None
        assert info.download_size == "150.0 MB"

    @pytest.mark.asyncio
    async def test_get_version_info_no_estimate_when_up_to_date(self) -> None:
        """Test get_version_info skips estimate when up-to-date."""
        plugin = EstimatingTestPlugin(
            installed_version="1.3.0",
            available_version="1.3.0",
            download_bytes=157286400,
        )
        info = await plugin.get_version_info()
        assert info.needs_update is False
        assert info.estimate is None  # Not fetched when up-to-date
```

#### 4. Plugin-Specific Version Tests

```python
class TestWaterfoxVersionChecking:
    """Tests for Waterfox plugin version checking."""

    @pytest.mark.asyncio
    async def test_get_installed_version_parses_output(self) -> None:
        """Test parsing waterfox --version output."""
        plugin = WaterfoxPlugin()
        # Mock subprocess to return known output
        with patch_subprocess("Mozilla Waterfox 6.0.18"):
            version = await plugin.get_installed_version()
            assert version == "6.0.18"

    @pytest.mark.asyncio
    async def test_get_installed_version_not_installed(self) -> None:
        """Test get_installed_version when not installed."""
        plugin = WaterfoxPlugin()
        with patch_which(None):
            version = await plugin.get_installed_version()
            assert version is None

    @pytest.mark.asyncio
    async def test_get_available_version_from_github(self) -> None:
        """Test fetching version from GitHub API."""
        plugin = WaterfoxPlugin()
        with patch_http_response({"tag_name": "6.0.19"}):
            version = await plugin.get_available_version()
            assert version == "6.0.19"

    @pytest.mark.asyncio
    async def test_get_available_version_network_error(self) -> None:
        """Test handling network errors gracefully."""
        plugin = WaterfoxPlugin()
        with patch_http_error():
            version = await plugin.get_available_version()
            assert version is None

    @pytest.mark.asyncio
    async def test_needs_update_true(self) -> None:
        """Test needs_update when update available."""
        plugin = WaterfoxPlugin()
        with patch_versions(installed="6.0.18", available="6.0.19"):
            assert await plugin.needs_update() is True

    @pytest.mark.asyncio
    async def test_needs_update_false(self) -> None:
        """Test needs_update when up-to-date."""
        plugin = WaterfoxPlugin()
        with patch_versions(installed="6.0.19", available="6.0.19"):
            assert await plugin.needs_update() is False


class TestGoRuntimeVersionChecking:
    """Tests for Go runtime plugin version checking."""

    @pytest.mark.asyncio
    async def test_get_installed_version_parses_output(self) -> None:
        """Test parsing go version output."""
        plugin = GoRuntimePlugin()
        with patch_subprocess("go version go1.21.5 linux/amd64"):
            version = await plugin.get_installed_version()
            assert version == "go1.21.5"

    @pytest.mark.asyncio
    async def test_get_available_version_from_golang_org(self) -> None:
        """Test fetching version from golang.org."""
        plugin = GoRuntimePlugin()
        with patch_http_response("go1.22.0\ntime 2024-01-01"):
            version = await plugin.get_available_version()
            assert version == "go1.22.0"


class TestPoetryVersionChecking:
    """Tests for Poetry plugin version checking."""

    @pytest.mark.asyncio
    async def test_get_installed_version_parses_output(self) -> None:
        """Test parsing poetry --version output."""
        plugin = PoetryPlugin()
        with patch_subprocess("Poetry (version 1.8.0)"):
            version = await plugin.get_installed_version()
            assert version == "1.8.0"

    @pytest.mark.asyncio
    async def test_get_available_version_from_pypi(self) -> None:
        """Test fetching version from PyPI."""
        plugin = PoetryPlugin()
        with patch_pypi_response("poetry", "1.8.1"):
            version = await plugin.get_available_version()
            assert version == "1.8.1"
```

### Integration Tests

#### 5. CLI Integration Tests (`cli/tests/test_check_command.py`)

```python
class TestCheckCommand:
    """Integration tests for the check command."""

    @pytest.mark.asyncio
    async def test_check_all_plugins(self) -> None:
        """Test checking all plugins for updates."""
        result = await run_cli(["check"])
        assert result.exit_code == 0
        assert "Checking for updates" in result.output

    @pytest.mark.asyncio
    async def test_check_specific_plugin(self) -> None:
        """Test checking a specific plugin."""
        result = await run_cli(["check", "--plugin", "waterfox"])
        assert result.exit_code == 0
        assert "waterfox" in result.output

    @pytest.mark.asyncio
    async def test_check_json_output(self) -> None:
        """Test JSON output format."""
        result = await run_cli(["check", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "plugins" in data

    @pytest.mark.asyncio
    async def test_check_skips_unavailable_plugins(self) -> None:
        """Test that unavailable plugins are skipped."""
        result = await run_cli(["check"])
        # Should not error on unavailable plugins
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_check_shows_version_changes(self) -> None:
        """Test that version changes are displayed."""
        result = await run_cli(["check", "--plugin", "waterfox"])
        # Should show version info if available
        assert "version" in result.output.lower() or "up-to-date" in result.output.lower()
```

#### 6. Orchestrator Integration Tests (`core/tests/test_orchestrator_version_check.py`)

```python
class TestOrchestratorVersionCheck:
    """Tests for orchestrator version checking integration."""

    @pytest.mark.asyncio
    async def test_skip_up_to_date_plugins(self) -> None:
        """Test that up-to-date plugins are skipped."""
        orchestrator = Orchestrator()
        plugin = VersionedTestPlugin(
            installed_version="1.3.0",
            available_version="1.3.0",
        )
        result = await orchestrator.run_plugin(plugin, skip_if_up_to_date=True)
        assert result.status == PluginStatus.SKIPPED
        assert "up-to-date" in result.output.lower()

    @pytest.mark.asyncio
    async def test_run_plugins_needing_update(self) -> None:
        """Test that plugins needing update are executed."""
        orchestrator = Orchestrator()
        plugin = VersionedTestPlugin(
            installed_version="1.2.3",
            available_version="1.3.0",
        )
        result = await orchestrator.run_plugin(plugin, skip_if_up_to_date=True)
        assert result.status != PluginStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_run_plugins_without_version_check(self) -> None:
        """Test that plugins without version check are always run."""
        orchestrator = Orchestrator()
        plugin = MinimalTestPlugin()  # No version checking
        result = await orchestrator.run_plugin(plugin, skip_if_up_to_date=True)
        assert result.status != PluginStatus.SKIPPED
```

### Test Fixtures and Helpers

```python
# plugins/tests/conftest.py

@pytest.fixture
def minimal_test_plugin() -> MinimalTestPlugin:
    """Create a minimal test plugin."""
    return MinimalTestPlugin()


@pytest.fixture
def versioned_test_plugin() -> VersionedTestPlugin:
    """Create a test plugin with version checking."""
    return VersionedTestPlugin(
        installed_version="1.2.3",
        available_version="1.3.0",
    )


class MinimalTestPlugin(BasePlugin):
    """Minimal plugin for testing."""

    @property
    def name(self) -> str:
        return "test-minimal"

    @property
    def command(self) -> str:
        return "echo"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return "Updated", None


class VersionedTestPlugin(BasePlugin):
    """Test plugin with version checking."""

    def __init__(
        self,
        installed_version: str = "1.0.0",
        available_version: str = "1.1.0",
    ) -> None:
        self._installed = installed_version
        self._available = available_version

    @property
    def name(self) -> str:
        return "test-versioned"

    @property
    def command(self) -> str:
        return "echo"

    async def get_installed_version(self) -> str | None:
        return self._installed

    async def get_available_version(self) -> str | None:
        return self._available

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return "Updated", None


class ErroringVersionPlugin(BasePlugin):
    """Test plugin that errors during version check."""

    @property
    def name(self) -> str:
        return "test-error"

    @property
    def command(self) -> str:
        return "echo"

    async def get_installed_version(self) -> str | None:
        raise RuntimeError("Version check failed")

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return "Updated", None


class EstimatingTestPlugin(BasePlugin):
    """Test plugin with version checking and update estimation."""

    def __init__(
        self,
        installed_version: str = "1.0.0",
        available_version: str = "1.1.0",
        download_bytes: int | None = None,
        package_count: int | None = None,
    ) -> None:
        self._installed = installed_version
        self._available = available_version
        self._download_bytes = download_bytes
        self._package_count = package_count

    @property
    def name(self) -> str:
        return "test-estimating"

    @property
    def command(self) -> str:
        return "echo"

    async def get_installed_version(self) -> str | None:
        return self._installed

    async def get_available_version(self) -> str | None:
        return self._available

    async def get_update_estimate(self) -> UpdateEstimate | None:
        if self._download_bytes is None and self._package_count is None:
            return None
        return UpdateEstimate(
            download_bytes=self._download_bytes,
            package_count=self._package_count,
        )

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return "Updated", None


@contextmanager
def patch_subprocess(output: str, returncode: int = 0):
    """Patch subprocess to return specific output."""
    with patch("subprocess.run") as mock:
        mock.return_value = MagicMock(
            stdout=output,
            stderr="",
            returncode=returncode,
        )
        yield mock


@contextmanager
def patch_which(path: str | None):
    """Patch shutil.which to return specific path."""
    with patch("shutil.which", return_value=path):
        yield


@contextmanager
def patch_http_response(data: dict | str):
    """Patch HTTP requests to return specific data."""
    with patch("urllib.request.urlopen") as mock:
        response = MagicMock()
        if isinstance(data, dict):
            response.read.return_value = json.dumps(data).encode()
        else:
            response.read.return_value = data.encode()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        mock.return_value = response
        yield mock


@contextmanager
def patch_http_error():
    """Patch HTTP requests to raise an error."""
    with patch("urllib.request.urlopen") as mock:
        mock.side_effect = urllib.error.URLError("Network error")
        yield mock


@contextmanager
def patch_versions(installed: str, available: str):
    """Patch version methods to return specific versions."""
    with patch.object(
        WaterfoxPlugin, "get_local_version", return_value=installed
    ), patch.object(
        WaterfoxPlugin, "get_remote_version", return_value=available
    ):
        yield
```

### Test Summary

| Category | Test File | Test Count |
|----------|-----------|------------|
| VersionInfo Model | `core/tests/test_models.py` | 10 |
| UpdateEstimate Model | `core/tests/test_models.py` | 9 |
| Version Comparison | `core/tests/test_version.py` | 10 |
| BasePlugin Methods | `plugins/tests/test_version_checking.py` | 15 |
| Waterfox Plugin | `plugins/tests/test_waterfox_version.py` | 6 |
| Go Runtime Plugin | `plugins/tests/test_go_runtime_version.py` | 4 |
| Poetry Plugin | `plugins/tests/test_poetry_version.py` | 4 |
| CLI Check Command | `cli/tests/test_check_command.py` | 5 |
| Orchestrator Integration | `core/tests/test_orchestrator_version_check.py` | 3 |
| **Total** | | **66** |

---

## Plugin Migration Plan

### Migration Priority

#### Priority 1: Already Have Version Checking (Week 2)

| Plugin | Migration Steps | Estimated Effort |
|--------|----------------|------------------|
| `waterfox.py` | Rename `get_local_version()` → `get_installed_version()`, `get_remote_version()` → `get_available_version()`, make async | 2 hours |
| `go_runtime.py` | Same as waterfox | 2 hours |
| `poetry.py` | Rename method, add PyPI version check | 3 hours |
| `calibre.py` | Rename `_get_current_version()`, add version check | 3 hours |
| `texlive_self.py` | Rename method, add CTAN version check | 3 hours |
| `spack.py` | Adapt git-based version checking | 3 hours |

#### Priority 2: Easy to Add (Week 3)

| Plugin | Version Source | Estimated Effort |
|--------|---------------|------------------|
| `rustup.py` | Parse `rustup check` output | 2 hours |
| `pihole.py` | Pi-hole local API | 2 hours |
| `yt_dlp.py` | `--version` + PyPI | 2 hours |
| `youtube_dl.py` | Same as yt-dlp | 1 hour |
| `julia_runtime.py` | `--version` + GitHub releases | 3 hours |
| `atuin.py` | `--version` + GitHub releases | 2 hours |

#### Priority 3: Package Managers with Download Estimates (Optional)

These plugins manage multiple packages, so single-version checking is less applicable.
However, they can provide valuable **download size estimates** via `get_update_estimate()`:

| Plugin | Version Check | Download Estimate | Notes |
|--------|--------------|-------------------|-------|
| `apt.py` | `has_updates()` | ✅ Yes | `apt-get upgrade --dry-run` reports size |
| `flatpak.py` | `has_updates()` | ✅ Yes | `flatpak update --no-deploy` reports size |
| `snap.py` | `has_updates()` | ⚠️ Limited | `snap refresh --list` has limited info |
| `pipx.py` | `has_updates()` | ❌ No | No size info available |
| `npm.py` | `has_updates()` | ❌ No | No size info available |
| `cargo.py` | `has_updates()` | ❌ No | No size info available |

For these plugins, we implement:
1. `has_updates() -> bool | None` - Returns `True` if any packages have updates
2. `get_update_estimate() -> UpdateEstimate | None` - Returns download size and package count (where supported)

This enables the UI to show messages like:
- "apt: 15 packages to update (150 MB download)"
- "flatpak: 3 apps to update (450 MB download)"

### Migration Template

```python
# Before migration (example: poetry.py)
class PoetryPlugin(BasePlugin):
    def get_local_version(self) -> str | None:
        """Get the currently installed Poetry version."""
        if not self.is_available():
            return None
        try:
            result = subprocess.run(
                ["poetry", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output
                ...
        except Exception:
            pass
        return None


# After migration
class PoetryPlugin(BasePlugin):
    PYPI_URL = "https://pypi.org/pypi/poetry/json"

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Poetry version."""
        if not await self.check_available():
            return None
        try:
            code, stdout, _ = await self._run_command(
                ["poetry", "--version"],
                timeout=10,
            )
            if code == 0:
                match = re.search(r"version\s+(\d+\.\d+\.\d+)", stdout)
                return match.group(1) if match else None
        except Exception:
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest Poetry version from PyPI."""
        try:
            request = urllib.request.Request(
                self.PYPI_URL,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode())
                return data.get("info", {}).get("version")
        except Exception:
            return None
```

---

## Download Size Estimation Research

This section documents the research findings for implementing `get_update_estimate()` across all plugins.
Each plugin's method for obtaining download size information is documented with implementation examples.

### Summary Table

| Plugin | Estimation Method | Reliability | Implementation Complexity |
|--------|------------------|-------------|---------------------------|
| `apt.py` | `apt-get upgrade --print-uris` | ✅ High | Low |
| `flatpak.py` | `flatpak remote-info --show-size` | ✅ High | Medium |
| `snap.py` | `snap refresh --list` | ⚠️ Medium | Low |
| `pipx.py` | PyPI JSON API | ✅ High | Medium |
| `pip.py` | PyPI JSON API | ✅ High | Medium |
| `poetry.py` | PyPI JSON API | ✅ High | Medium |
| `npm.py` | npm Registry API | ✅ High | Medium |
| `cargo.py` | Crates.io API | ✅ High | Medium |
| `rustup.py` | HEAD request to manifest | ⚠️ Medium | High |
| `go_runtime.py` | Go downloads JSON API | ✅ High | Low |
| `waterfox.py` | GitHub Releases API | ✅ High | Low |
| `calibre.py` | GitHub Releases API | ✅ High | Low |
| `atuin.py` | GitHub Releases API | ✅ High | Low |
| `yt_dlp.py` | PyPI JSON API | ✅ High | Low |
| `youtube_dl.py` | PyPI JSON API | ✅ High | Low |
| `julia_runtime.py` | GitHub Releases API | ✅ High | Low |
| `julia_packages.py` | Julia Registry API | ⚠️ Medium | High |
| `texlive_self.py` | CTAN/tlmgr | ⚠️ Medium | High |
| `texlive_packages.py` | CTAN/tlmgr | ⚠️ Medium | High |
| `spack.py` | Git-based (no size) | ❌ None | N/A |
| `pihole.py` | Pi-hole API | ⚠️ Medium | Medium |
| `foot.py` | Source build (no size) | ❌ None | N/A |
| `steam.py` | Steam API | ⚠️ Medium | High |
| `lxc.py` | LXC image server | ⚠️ Medium | Medium |
| `r.py` | CRAN API | ⚠️ Medium | Medium |
| `conda_*.py` | Conda API | ✅ High | Medium |

### Detailed Implementation Guide

#### 1. apt.py - APT Package Manager

**Method:** `apt-get upgrade --print-uris`

**Research Finding:** The `--print-uris` flag outputs download URLs with size information in the third column (bytes).

**Example Output:**
```
'http://archive.ubuntu.com/ubuntu/pool/main/b/bash/bash_5.1-6ubuntu1.1_amd64.deb' bash_5.1-6ubuntu1.1_amd64.deb 775124 SHA256:...
'http://archive.ubuntu.com/ubuntu/pool/main/c/coreutils/coreutils_8.32-4.1ubuntu1.2_amd64.deb' coreutils_8.32-4.1ubuntu1.2_amd64.deb 1234567 SHA256:...
```

**Implementation:**
```python
async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for apt updates."""
    code, stdout, _ = await self._run_command(
        ["apt-get", "upgrade", "--print-uris", "-y"],
        timeout=120,
        sudo=True,
    )
    if code != 0:
        return None

    # Parse output: 'URL' filename size hash
    total_bytes = 0
    package_count = 0
    packages = []

    for line in stdout.strip().split("\n"):
        if line.startswith("'http"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    total_bytes += int(parts[2])
                    package_count += 1
                    # Extract package name from filename
                    filename = parts[1]
                    pkg_name = filename.split("_")[0]
                    packages.append(pkg_name)
                except (ValueError, IndexError):
                    continue

    if package_count == 0:
        return None

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=package_count,
        packages=packages[:20],  # Limit to first 20 for display
    )
```

**Sources:**
- apt-get man page: `--print-uris` flag documentation
- Tested on Ubuntu 24.04 LTS

---

#### 2. flatpak.py - Flatpak Applications

**Method:** `flatpak remote-info --show-size` or `flatpak update --no-deploy`

**Research Finding:** Flatpak provides size information via `remote-info --show-size` for individual apps, or `flatpak update --no-deploy` for a dry-run that shows total download size.

**Example Output (update --no-deploy):**
```
Looking for updates…
        ID                                     Branch         Op   Remote          Download
 1. [✓] org.gnome.Platform                    44             u    flathub         234.5 MB / 456.7 MB
 2. [✓] org.mozilla.firefox                   stable         u    flathub          89.2 MB / 178.4 MB
```

**Implementation:**
```python
async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for flatpak updates."""
    code, stdout, _ = await self._run_command(
        ["flatpak", "update", "--no-deploy", "-y"],
        timeout=120,
    )
    if code != 0:
        return None

    total_bytes = 0
    package_count = 0
    packages = []

    # Parse lines with download size (e.g., "234.5 MB / 456.7 MB")
    for line in stdout.split("\n"):
        # Match pattern: app_id ... XX.X MB / YY.Y MB
        match = re.search(
            r"(\S+)\s+\S+\s+[ui]\s+\S+\s+([\d.]+)\s*(KB|MB|GB)\s*/",
            line
        )
        if match:
            app_id = match.group(1)
            size = float(match.group(2))
            unit = match.group(3)

            multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}
            total_bytes += int(size * multipliers.get(unit, 1))
            package_count += 1
            packages.append(app_id)

    if package_count == 0:
        return None

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=package_count,
        packages=packages,
    )
```

**Sources:**
- flatpak man page: `--no-deploy` and `--show-size` flags
- https://docs.flatpak.org/en/latest/flatpak-command-reference.html

---

#### 3. snap.py - Snap Packages

**Method:** `snap refresh --list`

**Research Finding:** The `snap refresh --list` command shows available updates with a Size column.

**Example Output:**
```
Name           Version          Rev    Size   Publisher    Notes
firefox        120.0-1          3252   184MB  mozilla✓     -
chromium       120.0.6099.71    2691   156MB  nicholasd    -
```

**Implementation:**
```python
async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for snap updates."""
    code, stdout, _ = await self._run_command(
        ["snap", "refresh", "--list"],
        timeout=60,
    )
    if code != 0:
        return None

    total_bytes = 0
    package_count = 0
    packages = []

    lines = stdout.strip().split("\n")
    if len(lines) < 2:  # Header + at least one package
        return None

    for line in lines[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 4:
            name = parts[0]
            size_str = parts[3]

            # Parse size (e.g., "184MB", "1.2GB")
            match = re.match(r"([\d.]+)(KB|MB|GB)", size_str)
            if match:
                size = float(match.group(1))
                unit = match.group(2)
                multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}
                total_bytes += int(size * multipliers.get(unit, 1))
                package_count += 1
                packages.append(name)

    if package_count == 0:
        return None

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=package_count,
        packages=packages,
    )
```

**Sources:**
- snap man page
- Tested on Ubuntu 24.04 LTS

---

#### 4. pipx.py / pip.py / poetry.py - Python Packages (PyPI)

**Method:** PyPI JSON API at `https://pypi.org/pypi/{package}/json`

**Research Finding:** PyPI provides package size information in the JSON API response under `.urls[].size` for each distribution file.

**Example API Response:**
```json
{
  "info": {"name": "requests", "version": "2.31.0"},
  "urls": [
    {
      "filename": "requests-2.31.0-py3-none-any.whl",
      "size": 62574,
      "packagetype": "bdist_wheel"
    },
    {
      "filename": "requests-2.31.0.tar.gz",
      "size": 110346,
      "packagetype": "sdist"
    }
  ]
}
```

**Implementation (pipx example):**
```python
PYPI_API = "https://pypi.org/pypi/{package}/json"

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for pipx updates."""
    # First, get list of outdated packages
    code, stdout, _ = await self._run_command(
        ["pipx", "list", "--json"],
        timeout=60,
    )
    if code != 0:
        return None

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    total_bytes = 0
    package_count = 0
    packages = []

    for venv_name, venv_info in data.get("venvs", {}).items():
        pkg_name = venv_info.get("metadata", {}).get("main_package", {}).get("package")
        if not pkg_name:
            continue

        # Fetch size from PyPI
        try:
            request = urllib.request.Request(
                self.PYPI_API.format(package=pkg_name),
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                pkg_data = json.loads(response.read().decode())

                # Get wheel size (preferred) or sdist size
                for url_info in pkg_data.get("urls", []):
                    if url_info.get("packagetype") == "bdist_wheel":
                        total_bytes += url_info.get("size", 0)
                        package_count += 1
                        packages.append(pkg_name)
                        break
                else:
                    # Fallback to sdist
                    for url_info in pkg_data.get("urls", []):
                        if url_info.get("packagetype") == "sdist":
                            total_bytes += url_info.get("size", 0)
                            package_count += 1
                            packages.append(pkg_name)
                            break
        except Exception:
            continue

    if package_count == 0:
        return None

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=package_count,
        packages=packages,
    )
```

**Sources:**
- PyPI JSON API documentation: https://warehouse.pypa.io/api-reference/json.html
- Tested with requests, poetry, and other packages

---

#### 5. npm.py - Node.js Packages

**Method:** npm Registry API at `https://registry.npmjs.org/{package}/latest`

**Research Finding:** The npm registry provides package size in `.dist.unpackedSize` (uncompressed) and tarball size can be obtained via HEAD request.

**Example API Response:**
```json
{
  "name": "express",
  "version": "4.18.2",
  "dist": {
    "tarball": "https://registry.npmjs.org/express/-/express-4.18.2.tgz",
    "unpackedSize": 214771,
    "fileCount": 57
  }
}
```

**Implementation:**
```python
NPM_REGISTRY = "https://registry.npmjs.org/{package}/latest"

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for npm global updates."""
    # Get list of outdated global packages
    code, stdout, _ = await self._run_command(
        ["npm", "outdated", "-g", "--json"],
        timeout=60,
    )
    # npm outdated returns exit code 1 if there are outdated packages
    if code not in (0, 1):
        return None

    try:
        outdated = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        return None

    total_bytes = 0
    package_count = 0
    packages = []

    for pkg_name, info in outdated.items():
        wanted_version = info.get("wanted")
        if not wanted_version:
            continue

        # Fetch size from npm registry
        try:
            request = urllib.request.Request(
                self.NPM_REGISTRY.format(package=pkg_name),
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                pkg_data = json.loads(response.read().decode())
                size = pkg_data.get("dist", {}).get("unpackedSize", 0)
                if size:
                    total_bytes += size
                    package_count += 1
                    packages.append(pkg_name)
        except Exception:
            continue

    if package_count == 0:
        return None

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=package_count,
        packages=packages,
    )
```

**Sources:**
- npm Registry API: https://github.com/npm/registry/blob/master/docs/REGISTRY-API.md
- Tested with express, typescript, and other packages

---

#### 6. cargo.py - Rust Crates

**Method:** Crates.io API at `https://crates.io/api/v1/crates/{crate}`

**Research Finding:** Crates.io provides crate size in `.versions[0].crate_size` (compressed size in bytes). Note: Requires User-Agent header.

**Example API Response:**
```json
{
  "crate": {"name": "serde", "max_version": "1.0.193"},
  "versions": [
    {
      "num": "1.0.193",
      "crate_size": 77821,
      "downloads": 12345678
    }
  ]
}
```

**Implementation:**
```python
CRATES_API = "https://crates.io/api/v1/crates/{crate}"

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for cargo updates."""
    # Get list of outdated crates
    code, stdout, _ = await self._run_command(
        ["cargo", "install", "--list"],
        timeout=60,
    )
    if code != 0:
        return None

    # Parse installed crates
    installed_crates = []
    for line in stdout.split("\n"):
        if line and not line.startswith(" "):
            # Format: "crate_name v1.2.3:"
            match = re.match(r"(\S+)\s+v([\d.]+)", line)
            if match:
                installed_crates.append((match.group(1), match.group(2)))

    total_bytes = 0
    package_count = 0
    packages = []

    for crate_name, installed_version in installed_crates:
        try:
            request = urllib.request.Request(
                self.CRATES_API.format(crate=crate_name),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "update-all/1.0",  # Required by crates.io
                },
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
                latest = data.get("crate", {}).get("max_version")
                if latest and latest != installed_version:
                    # Get size of latest version
                    for ver in data.get("versions", []):
                        if ver.get("num") == latest:
                            size = ver.get("crate_size", 0)
                            if size:
                                total_bytes += size
                                package_count += 1
                                packages.append(crate_name)
                            break
        except Exception:
            continue

    if package_count == 0:
        return None

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=package_count,
        packages=packages,
    )
```

**Sources:**
- Crates.io API documentation: https://crates.io/policies
- Note: Requires User-Agent header per crates.io policy

---

#### 7. go_runtime.py - Go Runtime

**Method:** Go downloads JSON API at `https://go.dev/dl/?mode=json`

**Research Finding:** The Go downloads page provides a JSON API with file sizes for each release.

**Example API Response:**
```json
[
  {
    "version": "go1.21.5",
    "stable": true,
    "files": [
      {
        "filename": "go1.21.5.linux-amd64.tar.gz",
        "os": "linux",
        "arch": "amd64",
        "size": 66561424,
        "sha256": "..."
      }
    ]
  }
]
```

**Implementation:**
```python
GO_DOWNLOADS_API = "https://go.dev/dl/?mode=json"

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for Go runtime update."""
    # Check if update is needed
    if not await self.needs_update():
        return None

    available = await self.get_available_version()
    if not available:
        return None

    try:
        request = urllib.request.Request(
            self.GO_DOWNLOADS_API,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            releases = json.loads(response.read().decode())

            for release in releases:
                if release.get("version") == available:
                    # Find the appropriate file for this system
                    for file_info in release.get("files", []):
                        if (
                            file_info.get("os") == "linux"
                            and file_info.get("arch") == "amd64"
                            and file_info.get("filename", "").endswith(".tar.gz")
                        ):
                            return UpdateEstimate(
                                download_bytes=file_info.get("size"),
                                package_count=1,
                                packages=[available],
                            )
    except Exception:
        pass

    return None
```

**Sources:**
- Go downloads page: https://go.dev/dl/
- JSON API: https://go.dev/dl/?mode=json

---

#### 8. GitHub Releases (waterfox.py, calibre.py, atuin.py, julia_runtime.py)

**Method:** GitHub Releases API at `https://api.github.com/repos/{owner}/{repo}/releases/latest`

**Research Finding:** GitHub provides asset sizes in `.assets[].size` for each release asset.

**Example API Response:**
```json
{
  "tag_name": "v6.0.19",
  "assets": [
    {
      "name": "waterfox-6.0.19.tar.bz2",
      "size": 89456123,
      "browser_download_url": "https://github.com/..."
    }
  ]
}
```

**Implementation (generic for GitHub releases):**
```python
GITHUB_RELEASES_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size from GitHub releases."""
    if not await self.needs_update():
        return None

    try:
        request = urllib.request.Request(
            self.GITHUB_RELEASES_API.format(owner=self.OWNER, repo=self.REPO),
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "update-all/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.loads(response.read().decode())

            # Find the appropriate asset for this system
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                if self._is_matching_asset(name):
                    return UpdateEstimate(
                        download_bytes=asset.get("size"),
                        package_count=1,
                        packages=[release.get("tag_name", "").lstrip("v")],
                    )
    except Exception:
        pass

    return None

def _is_matching_asset(self, name: str) -> bool:
    """Check if asset name matches this system."""
    # Override in subclass for specific matching logic
    return "linux" in name.lower() and "x86_64" in name.lower()
```

**Plugin-Specific Asset Matching:**

| Plugin | Asset Pattern |
|--------|--------------|
| `waterfox.py` | `waterfox-*.tar.bz2` containing `linux` |
| `calibre.py` | `calibre-*.txz` containing `x86_64` |
| `atuin.py` | `atuin-*.tar.gz` containing `linux` and `gnu` |
| `julia_runtime.py` | `julia-*.tar.gz` containing `linux` and `x86_64` |

**Sources:**
- GitHub REST API: https://docs.github.com/en/rest/releases/releases

---

#### 9. rustup.py - Rust Toolchain

**Method:** HEAD request to manifest URLs for Content-Length

**Research Finding:** Rustup doesn't provide size information in `rustup check`. The manifest files don't include sizes. The only reliable method is to make HEAD requests to the actual download URLs.

**Implementation:**
```python
RUST_DIST_URL = "https://static.rust-lang.org/dist"

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for rustup update."""
    # Get update info from rustup check
    code, stdout, _ = await self._run_command(
        ["rustup", "check"],
        timeout=60,
    )
    if code != 0 or "Update available" not in stdout:
        return None

    # Parse the new version from output
    # Example: "stable - Update available : 1.74.0 (current: 1.73.0)"
    match = re.search(r"Update available\s*:\s*([\d.]+)", stdout)
    if not match:
        return None

    new_version = match.group(1)

    # Construct download URL and get size via HEAD request
    # Example: https://static.rust-lang.org/dist/rust-1.74.0-x86_64-unknown-linux-gnu.tar.gz
    url = f"{self.RUST_DIST_URL}/rust-{new_version}-x86_64-unknown-linux-gnu.tar.gz"

    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=30) as response:
            size = response.headers.get("Content-Length")
            if size:
                return UpdateEstimate(
                    download_bytes=int(size),
                    package_count=1,
                    packages=[f"rust-{new_version}"],
                )
    except Exception:
        pass

    return None
```

**Sources:**
- Rust distribution server: https://static.rust-lang.org/dist/
- rustup source code analysis

---

#### 10. conda_*.py - Conda Packages

**Method:** Conda API or `conda update --dry-run --json`

**Research Finding:** Conda provides detailed package information including size via `conda update --dry-run --json`.

**Example Output:**
```json
{
  "actions": {
    "FETCH": [
      {"name": "numpy", "version": "1.26.2", "size": 7654321},
      {"name": "pandas", "version": "2.1.3", "size": 12345678}
    ]
  }
}
```

**Implementation:**
```python
async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size for conda updates."""
    code, stdout, _ = await self._run_command(
        ["conda", "update", "--all", "--dry-run", "--json"],
        timeout=120,
    )
    if code != 0:
        return None

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    fetch_actions = data.get("actions", {}).get("FETCH", [])
    if not fetch_actions:
        return None

    total_bytes = sum(pkg.get("size", 0) for pkg in fetch_actions)
    packages = [pkg.get("name") for pkg in fetch_actions if pkg.get("name")]

    return UpdateEstimate(
        download_bytes=total_bytes,
        package_count=len(fetch_actions),
        packages=packages[:20],
    )
```

**Sources:**
- Conda documentation: https://docs.conda.io/projects/conda/en/latest/commands/update.html
- `--json` flag provides machine-readable output

---

#### 11. Plugins Without Download Size Estimation

The following plugins cannot provide reliable download size estimates:

| Plugin | Reason |
|--------|--------|
| `spack.py` | Git-based installation, no pre-download size info |
| `foot.py` | Source build from git, size depends on build |
| `texlive_*.py` | CTAN/tlmgr doesn't expose sizes easily |
| `steam.py` | Steam client handles downloads internally |

For these plugins, `get_update_estimate()` should return `None` or an estimate with only `package_count` (no `download_bytes`).

---

## Documentation Updates

### Updates to `docs/plugin-development.md`

Add a new section after "API Reference":

```markdown
### Version Checking API

The Version Checking API enables plugins to report version information and
determine if updates are available. This enables:

- **Check-only mode**: See what updates are available without applying them
- **Skip up-to-date plugins**: Reduce unnecessary work
- **Version-based progress**: Show version changes in the UI

#### `get_installed_version() -> str | None`

Get the currently installed version of the managed software.

```python
async def get_installed_version(self) -> str | None:
    """Get the currently installed version.

    Returns:
        Version string (e.g., "1.2.3") or None if not installed.
    """
    if not await self.check_available():
        return None

    code, stdout, _ = await self._run_command(
        ["myapp", "--version"],
        timeout=10,
    )
    if code == 0:
        match = re.search(r"(\d+\.\d+\.\d+)", stdout)
        return match.group(1) if match else None
    return None
```

#### `get_available_version() -> str | None`

Get the latest available version from the upstream source.

```python
async def get_available_version(self) -> str | None:
    """Get the latest available version.

    Returns:
        Version string or None if cannot determine.
    """
    try:
        # Example: Fetch from GitHub releases API
        request = urllib.request.Request(
            "https://api.github.com/repos/owner/repo/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
            return data.get("tag_name", "").lstrip("v")
    except Exception:
        return None
```

#### `needs_update() -> bool | None`

Check if an update is needed by comparing versions.

```python
async def needs_update(self) -> bool | None:
    """Check if an update is needed.

    Returns:
        - True: Update is available
        - False: Already up-to-date
        - None: Cannot determine
    """
    installed = await self.get_installed_version()
    available = await self.get_available_version()

    if not installed or not available:
        return None

    # Use semantic version comparison
    from packaging import version
    return version.parse(installed) < version.parse(available)
```

#### `get_version_info() -> VersionInfo`

Get complete version information in a single call.

```python
info = await plugin.get_version_info()
print(f"Installed: {info.installed}")
print(f"Available: {info.available}")
print(f"Needs update: {info.needs_update}")
if info.version_change:
    print(f"Change: {info.version_change}")
if info.download_size:
    print(f"Download size: {info.download_size}")
```

#### `get_update_estimate() -> UpdateEstimate | None` (Optional)

Get estimated download size and package count for pending updates. This is
particularly useful for package managers that can report download sizes before
performing updates.

```python
async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size and package count.

    Returns:
        UpdateEstimate with download_bytes, package_count, etc.,
        or None if estimation is not supported.
    """
    # Example: apt plugin
    code, stdout, _ = await self._run_command(
        ["apt-get", "upgrade", "--dry-run"],
        timeout=60,
        sudo=True,
    )
    if code != 0:
        return None

    # Parse "Need to get 150 MB of archives"
    size_match = re.search(r"Need to get ([\d.]+)\s*(\w+)", stdout)
    count_match = re.search(r"(\d+)\s+upgraded", stdout)

    download_bytes = None
    if size_match:
        size, unit = size_match.groups()
        multipliers = {"B": 1, "kB": 1024, "MB": 1024**2, "GB": 1024**3}
        download_bytes = int(float(size) * multipliers.get(unit, 1))

    return UpdateEstimate(
        download_bytes=download_bytes,
        package_count=int(count_match.group(1)) if count_match else None,
    )
```

#### Plugins with Download Estimate Support

The following plugins can provide download size estimates:

| Plugin | Estimate Source | Notes |
|--------|----------------|-------|
| `apt.py` | `apt-get upgrade --dry-run` | Reports download size and package count |
| `flatpak.py` | `flatpak update --no-deploy` | Reports download size per app |
| `snap.py` | `snap refresh --list` | Limited size info available |

#### Version Sources

Common sources for version information:

| Source | Example | Use Case |
|--------|---------|----------|
| Command output | `myapp --version` | Most CLI tools |
| GitHub Releases | `api.github.com/repos/.../releases/latest` | GitHub-hosted projects |
| PyPI | `pypi.org/pypi/package/json` | Python packages |
| npm Registry | `registry.npmjs.org/package` | Node.js packages |
| Crates.io | `crates.io/api/v1/crates/package` | Rust crates |
| Git commits | `git rev-parse HEAD` | Source-installed tools |
```

---

## Risk Analysis

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Network failures during version check | High | Low | Return `None`, don't block updates |
| Version parsing errors | Medium | Low | Robust regex, fallback to string comparison |
| Rate limiting on APIs | Medium | Medium | Cache results, respect rate limits |
| Breaking existing plugins | Low | High | Backward compatible defaults |
| Performance impact | Medium | Medium | Async methods, timeout limits |

### Mitigation Strategies

1. **Network Failures**
   - All version check methods return `None` on error
   - Updates proceed if version check fails
   - Log warnings but don't fail

2. **Version Parsing**
   - Support multiple version formats
   - Fall back to string comparison
   - Provide utility functions for common patterns

3. **Rate Limiting**
   - Cache version check results (configurable TTL)
   - Batch API requests where possible
   - Respect `Retry-After` headers

4. **Backward Compatibility**
   - Default implementations return `None`
   - Existing plugins continue to work unchanged
   - Gradual migration, not big-bang

---

## Timeline

### Week 1: Core Infrastructure

| Day | Task |
|-----|------|
| Mon | Write tests for `VersionInfo` model |
| Mon | Implement `VersionInfo` dataclass |
| Tue | Write tests for version comparison utilities |
| Tue | Implement `core/version.py` |
| Wed | Write tests for `BasePlugin` version methods |
| Wed | Implement version methods in `BasePlugin` |
| Thu | Write tests for `UpdatePlugin` interface |
| Thu | Update `core/interfaces.py` |
| Fri | Integration testing, bug fixes |

### Week 2: Priority 1 Plugin Migration

| Day | Task |
|-----|------|
| Mon | Migrate `waterfox.py` with tests |
| Mon | Migrate `go_runtime.py` with tests |
| Tue | Migrate `poetry.py` with tests |
| Wed | Migrate `calibre.py` with tests |
| Thu | Migrate `texlive_self.py` with tests |
| Thu | Migrate `spack.py` with tests |
| Fri | Integration testing, bug fixes |

### Week 3: Priority 2 Plugin Migration

| Day | Task |
|-----|------|
| Mon | Migrate `rustup.py` with tests |
| Mon | Migrate `pihole.py` with tests |
| Tue | Migrate `yt_dlp.py` with tests |
| Tue | Migrate `youtube_dl.py` with tests |
| Wed | Migrate `julia_runtime.py` with tests |
| Wed | Migrate `atuin.py` with tests |
| Thu | Additional plugins as time permits |
| Fri | Integration testing, bug fixes |

### Week 4: CLI and Integration

| Day | Task |
|-----|------|
| Mon | Write tests for `check` CLI command |
| Mon | Implement `check` command |
| Tue | Write tests for orchestrator integration |
| Tue | Implement orchestrator skip logic |
| Wed | Update streaming events |
| Wed | Update statistics collection |
| Thu | Update documentation |
| Fri | Final testing, release preparation |

---

## Success Criteria

### Functional Requirements

- [ ] All version checking methods implemented in `BasePlugin`
- [ ] `VersionInfo` model created and tested
- [ ] Version comparison utilities created and tested
- [ ] At least 12 plugins migrated to new API
- [ ] `check` CLI command implemented
- [ ] Orchestrator skips up-to-date plugins
- [ ] Documentation updated

### Quality Requirements

- [ ] 100% test coverage for new code
- [ ] All existing tests pass
- [ ] No breaking changes to existing plugins
- [ ] Performance: version check < 5 seconds per plugin
- [ ] Graceful handling of network failures

### Documentation Requirements

- [ ] `docs/plugin-development.md` updated with Version Checking API
- [ ] Migration guide for plugin authors
- [ ] API reference documentation
- [ ] Example implementations

---

## Appendix: Related Requirements

This implementation supports the following requirements from the update-all solution:

### Plugin CLI API Commands

| Command | Supported By |
|---------|--------------|
| `is-applicable` | `check_available()` (existing) |
| `estimate-update` | `get_version_info()` + `needs_update()` |

### Features Enabled

- **Quick if nothing to update**: Skip plugins where `needs_update()` returns `False`
- **Check for updates without performing them**: `check` CLI command
- **Estimated time remaining**: Version info enables better predictions
- **Nice visual output**: Version change display (`1.2.3 -> 1.3.0`)
- **Download size estimation**: Show bandwidth requirements before updating (e.g., "150 MB download")
- **Package count display**: Show number of packages to update (e.g., "15 packages")
- **Informed update decisions**: Users can decide when to run updates based on download size
