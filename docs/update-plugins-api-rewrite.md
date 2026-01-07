# Update Plugins API Rewrite Proposal

**Date:** January 7, 2026
**Status:** Draft
**Author:** API Review Team

## Executive Summary

This document analyzes the current update plugin API and proposes improvements to make plugin development easier, less error-prone, and more consistent. The analysis is based on a comprehensive review of 20+ existing plugins and the core API interfaces.

---

## Table of Contents

1. [Current API Overview](#current-api-overview)
2. [Identified Pain Points](#identified-pain-points)
3. [Proposed Changes](#proposed-changes)
4. [Code Examples: Before and After](#code-examples-before-and-after)
5. [Migration Strategy](#migration-strategy)
6. [Appendix: Plugin Analysis Summary](#appendix-plugin-analysis-summary)

---

## Current API Overview

The current plugin system is built around the `UpdatePlugin` abstract base class (in `core/interfaces.py`) and `BasePlugin` implementation (in `plugins/base.py`). Plugins must implement:

### Required Methods/Properties
- `name` (property): Plugin identifier
- `command` (property): Main command used by the plugin
- `check_available()`: Check if the plugin's tool is installed
- `_execute_update(config)`: Execute the actual update

### Optional Methods
- `description` (property): Human-readable description
- `get_interactive_command(dry_run)`: Command for PTY mode
- `_count_updated_packages(output)`: Parse output for package count
- `_execute_update_streaming()`: Streaming version of update
- `supports_download`, `download()`, `estimate_download()`: Download API
- `supports_self_update`, `self_update()`: Self-update mechanism

---

## Identified Pain Points

### Pain Point 1: Repetitive Streaming Boilerplate

**Problem:** Almost every plugin that implements `_execute_update_streaming()` follows the same pattern:

```python
async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
    from datetime import UTC, datetime
    from core.models import PluginConfig
    from core.streaming import CompletionEvent, EventType, OutputEvent

    config = PluginConfig(name=self.name)
    collected_output: list[str] = []

    yield OutputEvent(
        event_type=EventType.OUTPUT,
        plugin_name=self.name,
        timestamp=datetime.now(tz=UTC),
        line="=== some header ===",
        stream="stdout",
    )

    async for event in self._run_command_streaming(
        ["command", "args"],
        timeout=config.timeout_seconds,
        sudo=True,
        phase=Phase.EXECUTE,
    ):
        if isinstance(event, OutputEvent):
            collected_output.append(event.line)
        if isinstance(event, CompletionEvent):
            # Handle completion
            packages_updated = self._count_updated_packages("\n".join(collected_output))
            yield CompletionEvent(...)
            return
        yield event
```

This pattern is repeated in `apt.py`, `pipx.py`, `flatpak.py`, `calibre.py`, `texlive.py`, `spack.py`, `pihole.py`, and many others.

**Impact:**
- 50-100 lines of boilerplate per plugin
- Easy to forget to collect output for package counting
- Inconsistent handling of completion events
- Import statements repeated in every method

---

### Pain Point 2: Inconsistent Version Checking

**Problem:** Many plugins implement their own version checking logic with slight variations:

| Plugin | Method | Pattern |
|--------|--------|---------|
| `waterfox.py` | `get_local_version()`, `get_remote_version()` | HTTP API + subprocess |
| `go.py` | `get_local_version()`, `get_remote_version()` | HTTP API + subprocess |
| `poetry.py` | `get_local_version()` | subprocess only |
| `calibre.py` | `_get_current_version()` | subprocess only |
| `texlive.py` | `get_local_version()` | subprocess only |
| `spack.py` | `get_local_version()`, `_get_git_commit()` | git + subprocess |

**Impact:**
- No standard way to check if updates are available
- No standard way to report "already up-to-date" status
- Plugins cannot participate in "check-only" mode consistently

---

### Pain Point 3: Multi-Step Updates Without Abstraction

**Problem:** Several plugins perform multiple related operations but lack a clean abstraction:

| Plugin | Steps |
|--------|-------|
| `apt.py` | `apt update` → `apt upgrade` |
| `texlive.py` | `tlmgr update --self` → `tlmgr update --all` |
| `conda.py` | Update conda → Update conda-build → Update each environment → Clean cache |
| `go.py` | Download tarball → Extract → Create symlink → Update go packages |
| `waterfox.py` | Check version → Download → Extract → Install |

**Impact:**
- Complex plugins are hard to read and maintain
- No way to report progress per-step
- No way to resume from a failed step
- Difficult to split into separate plugins later

---

### Pain Point 4: Download Logic Reimplemented

**Problem:** Plugins that download files implement their own download logic:

- `waterfox.py`: Uses `urllib.request.urlopen()` with manual file writing
- `go.py`: Uses shell script with `curl`
- `calibre.py`: Uses `wget` subprocess

**Impact:**
- No progress reporting during downloads
- No retry logic
- No bandwidth limiting
- Inconsistent error handling

---

### Pain Point 5: Missing Estimation API

**Problem:** The `estimate_download()` method exists but is not implemented by any plugin. The required CLI API mentions:

- `estimate-update`: Estimate download size and CPU time
- Metrics for historical data and prediction

**Impact:**
- Cannot show estimated time remaining
- Cannot prioritize updates by size
- Cannot implement bandwidth-aware scheduling

---

### Pain Point 6: Sudo Handling Inconsistency

**Problem:** Plugins handle sudo in different ways:

| Plugin | Sudo Handling |
|--------|---------------|
| `apt.py` | `sudo=True` in `_run_command()` |
| `snap.py` | `sudo=True` in `_run_command()` |
| `pipx.py` | `sudo=False` (user-level) |
| `pihole.py` | `sudo=False` (pihole handles internally) |
| `waterfox.py` | `sudo=True` for install steps only |
| `texlive.py` | `sudo=True` for all commands |

**Impact:**
- No way to generate sudoers file entries
- No way to pre-check if sudo is available
- Cannot implement passwordless sudo setup

---

### Pain Point 7: Mutex/Dependency System Not Used

**Problem:** The requirements mention a mutex system for parallel execution, but:

- `PluginConfig` has `dependencies` field but it's not used by plugins
- No mutex declarations in any plugin
- No way to declare per-phase mutexes

**Impact:**
- Cannot safely run plugins in parallel
- Cannot implement resource-aware scheduling

---

### Pain Point 8: Inconsistent Availability Checking

**Problem:** Plugins implement `check_available()` and sometimes `is_available()`:

```python
# Some plugins have both
def is_available(self) -> bool:
    return shutil.which("command") is not None

async def check_available(self) -> bool:
    return self.is_available()

# Others only have check_available()
async def check_available(self) -> bool:
    return shutil.which(self.command) is not None
```

**Impact:**
- Confusion about which method to use
- Sync vs async inconsistency
- Base class already provides `check_available()` based on `command` property

---

## Proposed Changes

### Proposal 1: Declarative Command Execution

**Rationale:** Most plugins just run one or more commands with streaming output. Instead of implementing `_execute_update_streaming()`, plugins should declare their commands.

**New API:**

```python
class BasePlugin:
    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Return list of commands to execute for update.

        Override this instead of _execute_update_streaming() for simple plugins.
        """
        raise NotImplementedError
```

```python
@dataclass
class UpdateCommand:
    """A single command in an update sequence."""

    cmd: list[str]
    description: str = ""
    sudo: bool = False
    timeout_seconds: int | None = None  # None = use default
    phase: Phase = Phase.EXECUTE

    # For multi-step updates
    step_name: str | None = None
    step_number: int | None = None
    total_steps: int | None = None

    # Error handling
    ignore_exit_codes: list[int] = field(default_factory=list)
    error_patterns: list[str] = field(default_factory=list)  # Patterns that indicate error even with exit 0
    success_patterns: list[str] = field(default_factory=list)  # Patterns that indicate success even with non-zero exit
```

**Benefits:**
- 80% of plugins become 10-20 lines instead of 100+
- Automatic streaming, progress reporting, output collection
- Consistent error handling
- Easy to add new features (retry, timeout per-command)

---

### Proposal 2: Centralized Download Manager

**Rationale:** Downloads should be handled by the core system, not individual plugins.

**New API:**

```python
class BasePlugin:
    def get_download_spec(self) -> DownloadSpec | None:
        """Return download specification if plugin needs to download files.

        The core system will handle the actual download with:
        - Progress reporting
        - Retry logic
        - Bandwidth limiting
        - Caching
        """
        return None
```

```python
@dataclass
class DownloadSpec:
    """Specification for files to download."""

    url: str
    destination: Path
    expected_size: int | None = None
    checksum: str | None = None  # "sha256:abc123..."
    extract: bool = False
    extract_format: str | None = None  # "tar.gz", "tar.bz2", "zip"

    # For version checking
    version_url: str | None = None  # URL to check latest version
    version_pattern: str | None = None  # Regex to extract version
```

**Benefits:**
- Consistent download progress reporting
- Automatic retry and resume
- Bandwidth limiting across all plugins
- Download caching for offline updates

---

### Proposal 3: Version Checking Protocol

**Rationale:** Standardize how plugins check for updates.

**New API:**

```python
class BasePlugin:
    async def get_installed_version(self) -> str | None:
        """Get currently installed version. Override for custom logic."""
        # Default: run `{command} --version` and parse
        return None

    async def get_available_version(self) -> str | None:
        """Get latest available version. Override for custom logic."""
        return None

    async def needs_update(self) -> bool:
        """Check if update is needed. Default compares versions."""
        installed = await self.get_installed_version()
        available = await self.get_available_version()
        if not installed or not available:
            return True  # Assume update needed if can't determine
        return installed != available
```

**Benefits:**
- Consistent "check-only" mode
- Can skip plugins that are already up-to-date
- Enables version-based progress reporting

---

### Proposal 4: Step-Based Execution for Complex Plugins

**Rationale:** Complex plugins should be able to declare steps that can be tracked, resumed, and potentially split into separate plugins.

**New API:**

```python
class BasePlugin:
    def get_update_steps(self) -> list[UpdateStep]:
        """Return list of steps for complex updates.

        For simple plugins, override get_update_commands() instead.
        """
        return []
```

```python
@dataclass
class UpdateStep:
    """A logical step in a complex update process."""

    name: str
    description: str

    # Either commands or a custom async function
    commands: list[UpdateCommand] | None = None
    execute_fn: Callable[[], AsyncIterator[StreamEvent]] | None = None

    # Dependencies and mutexes
    depends_on: list[str] = field(default_factory=list)  # Step names
    mutexes: list[str] = field(default_factory=list)

    # Can this step be skipped if already done?
    idempotent: bool = True
    check_fn: Callable[[], bool] | None = None  # Returns True if step already done
```

**Benefits:**
- Clear progress reporting per step
- Resume from failed step
- Easy to split into separate plugins later
- Mutex declarations per step

---

### Proposal 5: Sudo Declaration

**Rationale:** Plugins should declare their sudo requirements upfront.

**New API:**

```python
class BasePlugin:
    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        Used to:
        1. Generate sudoers file entries
        2. Pre-check sudo availability
        3. Prompt for password once at start
        """
        return []

    @property
    def requires_sudo(self) -> bool:
        """Check if any commands require sudo."""
        return len(self.sudo_commands) > 0
```

**Benefits:**
- Can generate sudoers file automatically
- Can prompt for password once at start
- Clear documentation of privilege requirements

---

### Proposal 6: Mutex and Dependency Declaration

**Rationale:** Enable safe parallel execution.

**New API:**

```python
class BasePlugin:
    @property
    def dependencies(self) -> list[str]:
        """Plugin names that must run before this plugin."""
        return []

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Mutexes required for each phase.

        Example:
            {
                Phase.DOWNLOAD: ["network"],
                Phase.EXECUTE: ["apt", "dpkg"],
            }
        """
        return {}
```

**Benefits:**
- Safe parallel execution
- Resource-aware scheduling
- Clear dependency documentation

---

### Proposal 7: Estimation API

**Rationale:** Enable time and size estimation for better UX.

**New API:**

```python
@dataclass
class UpdateEstimate:
    """Estimate for an update operation."""

    download_bytes: int | None = None
    download_seconds: float | None = None
    execute_seconds: float | None = None
    packages_count: int | None = None

    # Confidence interval (for statistical modeling)
    download_seconds_p25: float | None = None
    download_seconds_p75: float | None = None
    execute_seconds_p25: float | None = None
    execute_seconds_p75: float | None = None

class BasePlugin:
    async def estimate_update(self) -> UpdateEstimate | None:
        """Estimate time and size for update.

        The core system will use historical data to improve estimates.
        """
        return None
```

**Benefits:**
- Show estimated time remaining
- Prioritize updates by size
- Historical data improves estimates over time

---

### Proposal 8: Remove Redundant Methods

**Rationale:** Simplify the API by removing redundant methods.

**Changes:**
- Remove `is_available()` - use only `check_available()`
- Remove `_execute_update()` - use only `get_update_commands()` or `get_update_steps()`
- Remove `_execute_update_streaming()` - handled automatically by base class
- Deprecate `run_update()` - use `execute()` instead

---

## Code Examples: Before and After

### Example 1: Simple Package Manager (pipx)

**Before (162 lines):**

```python
class PipxPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "pipx"

    @property
    def command(self) -> str:
        return "pipx"

    @property
    def description(self) -> str:
        return "Python application installer (pipx)"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        if dry_run:
            return ["pipx", "list"]
        return ["pipx", "upgrade-all"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return_code, stdout, stderr = await self._run_command(
            ["pipx", "upgrade-all"],
            timeout=config.timeout_seconds,
            sudo=False,
        )
        output = f"=== pipx upgrade-all ===\n{stdout}"
        if return_code != 0:
            if "No packages to upgrade" in stderr or "already at latest" in stdout:
                return output, None
            return output, f"pipx upgrade-all failed: {stderr}"
        return output, None

    def _count_updated_packages(self, output: str) -> int:
        upgraded_count = len(re.findall(r"upgraded\s+\S+\s+from", output, re.IGNORECASE))
        if upgraded_count == 0:
            upgraded_count = len(re.findall(r"Package\s+'\S+'\s+upgraded", output, re.IGNORECASE))
        return upgraded_count

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        from core.models import PluginConfig
        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== pipx upgrade-all ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            ["pipx", "upgrade-all"],
            timeout=config.timeout_seconds,
            sudo=False,
            phase=Phase.EXECUTE,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            if isinstance(event, CompletionEvent):
                success = event.success
                if not success:
                    output_str = "\n".join(collected_output)
                    if "No packages to upgrade" in output_str or "already at latest" in output_str:
                        success = True
                packages_updated = self._count_updated_packages("\n".join(collected_output))
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=success,
                    exit_code=0 if success else event.exit_code,
                    packages_updated=packages_updated,
                    error_message=None if success else event.error_message,
                )
                return
            yield event
```

**After (25 lines):**

```python
class PipxPlugin(BasePlugin):
    name = "pipx"
    command = "pipx"
    description = "Python application installer (pipx)"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [UpdateCommand(cmd=["pipx", "list"], description="List installed packages")]
        return [
            UpdateCommand(
                cmd=["pipx", "upgrade-all"],
                description="Upgrade all pipx packages",
                success_patterns=["No packages to upgrade", "already at latest"],
            )
        ]

    def count_updated_packages(self, output: str) -> int:
        count = len(re.findall(r"upgraded\s+\S+\s+from", output, re.IGNORECASE))
        if count == 0:
            count = len(re.findall(r"Package\s+'\S+'\s+upgraded", output, re.IGNORECASE))
        return count
```

---

### Example 2: Multi-Step Update (apt)

**Before (223 lines):**

```python
class AptPlugin(BasePlugin):
    # ... 200+ lines of boilerplate ...

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        # Step 1: apt update
        yield OutputEvent(...)
        async for event in self._run_command_streaming(["apt", "update"], ...):
            # ... handle events ...

        # Step 2: apt upgrade
        yield OutputEvent(...)
        async for event in self._run_command_streaming(["apt", "upgrade", "-y"], ...):
            # ... handle events ...
```

**After (30 lines):**

```python
class AptPlugin(BasePlugin):
    name = "apt"
    command = "apt"
    description = "Debian/Ubuntu APT package manager"

    sudo_commands = ["apt"]

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [
                UpdateCommand(cmd=["apt", "update"], sudo=True, step_name="refresh"),
                UpdateCommand(cmd=["apt", "upgrade", "--dry-run"], sudo=True, step_name="check"),
            ]
        return [
            UpdateCommand(
                cmd=["apt", "update"],
                description="Refresh package lists",
                sudo=True,
                step_name="refresh",
                step_number=1,
                total_steps=2,
            ),
            UpdateCommand(
                cmd=["apt", "upgrade", "-y"],
                description="Upgrade packages",
                sudo=True,
                step_name="upgrade",
                step_number=2,
                total_steps=2,
            ),
        ]

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        return {Phase.EXECUTE: ["apt", "dpkg"]}
```

---

### Example 3: Download-Based Update (waterfox)

**Before (383 lines):**

```python
class WaterfoxPlugin(BasePlugin):
    # ... complex download logic with urllib ...

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        # Manual version checking
        local_version = self.get_local_version()
        remote_version = self.get_remote_version()

        # Manual download with urllib
        with tempfile.TemporaryDirectory() as tmpdir:
            tarball_path = Path(tmpdir) / f"waterfox-{remote_version}.tar.bz2"
            request = urllib.request.Request(download_url, ...)
            with urllib.request.urlopen(request, timeout=300) as response:
                with tarball_path.open("wb") as f:
                    f.write(response.read())

            # Manual extraction and installation
            await self._run_command(["tar", "-xjf", ...])
            await self._run_command(["rm", "-rf", ...], sudo=True)
            await self._run_command(["mv", ...], sudo=True)
            await self._run_command(["chown", ...], sudo=True)
```

**After (45 lines):**

```python
class WaterfoxPlugin(BasePlugin):
    name = "waterfox"
    command = "waterfox"
    description = "Update Waterfox browser from GitHub releases"

    GITHUB_API_URL = "https://api.github.com/repos/MrAlex94/Waterfox/releases/latest"
    INSTALL_PATH = "/opt/waterfox"

    sudo_commands = ["rm", "mv", "chown"]

    async def get_available_version(self) -> str | None:
        # Fetch from GitHub API
        ...

    def get_download_spec(self) -> DownloadSpec | None:
        version = self._cached_remote_version
        if not version:
            return None
        return DownloadSpec(
            url=f"https://storage-waterfox.netdna-ssl.com/releases/linux64/installer/waterfox-classic-{version}.en-US.linux-x86_64.tar.bz2",
            destination=Path("/tmp/waterfox-download"),
            extract=True,
            extract_format="tar.bz2",
        )

    def get_update_steps(self) -> list[UpdateStep]:
        return [
            UpdateStep(
                name="install",
                description="Install Waterfox",
                commands=[
                    UpdateCommand(cmd=["rm", "-rf", self.INSTALL_PATH], sudo=True),
                    UpdateCommand(cmd=["mv", "/tmp/waterfox-download/waterfox", self.INSTALL_PATH], sudo=True),
                    UpdateCommand(cmd=["chown", "-R", "root:root", self.INSTALL_PATH], sudo=True),
                ],
            ),
        ]
```

---

## Potential Drawbacks and Trade-offs

### Trade-off 1: Learning Curve

**Drawback:** Plugin authors need to learn new abstractions (`UpdateCommand`, `UpdateStep`, `DownloadSpec`).

**Mitigation:**
- Provide comprehensive documentation with examples
- Keep backward compatibility during transition
- Simple plugins remain simple (just override `get_update_commands()`)

### Trade-off 2: Less Flexibility

**Drawback:** Declarative API may not handle all edge cases.

**Mitigation:**
- Keep `execute_fn` in `UpdateStep` for custom logic
- Allow plugins to override `execute_streaming()` for full control
- Provide escape hatches for complex scenarios

### Trade-off 3: Breaking Changes

**Drawback:** Existing plugins need to be updated.

**Mitigation:**
- Phase 1: Add new API alongside old API
- Phase 2: Deprecate old API with warnings
- Phase 3: Remove old API in next major version

### Trade-off 4: Increased Core Complexity

**Drawback:** More logic in the base class means more potential bugs.

**Mitigation:**
- Comprehensive test coverage
- Gradual rollout with feature flags
- Clear separation of concerns

---

## Migration Strategy

### Phase 1: Add New API (Non-Breaking)

1. Add `UpdateCommand`, `UpdateStep`, `DownloadSpec` dataclasses
2. Add `get_update_commands()`, `get_update_steps()`, `get_download_spec()` methods
3. Update `BasePlugin` to use new methods if available, fall back to old methods
4. Migrate 2-3 simple plugins as proof of concept

### Phase 2: Migrate Plugins

1. Migrate all simple plugins (pipx, snap, flatpak, npm, cargo, rustup)
2. Migrate medium-complexity plugins (apt, texlive, poetry)
3. Migrate complex plugins (conda, go, waterfox, calibre)
4. Add deprecation warnings to old methods

### Phase 3: Remove Old API

1. Remove deprecated methods
2. Update documentation
3. Release as major version

---

## Appendix: Plugin Analysis Summary

| Plugin | Lines | Complexity | Streaming | Download | Multi-Step | Sudo |
|--------|-------|------------|-----------|----------|------------|------|
| apt | 223 | Medium | ✓ | ✗ | ✓ (2) | ✓ |
| pipx | 162 | Low | ✓ | ✗ | ✗ | ✗ |
| flatpak | 162 | Low | ✓ | ✗ | ✗ | ✗ |
| snap | 81 | Low | ✗ | ✗ | ✗ | ✓ |
| cargo | 97 | Low | ✗ | ✗ | ✗ | ✗ |
| npm | 99 | Low | ✗ | ✗ | ✓ (2) | ✗ |
| rustup | 86 | Low | ✗ | ✗ | ✗ | ✗ |
| conda | 446 | High | ✓ | ✗ | ✓ (4+) | ✗ |
| go | 363 | High | ✓ | ✓ | ✓ (5) | ✗ |
| waterfox | 383 | High | ✓ | ✓ | ✓ (4) | ✓ |
| calibre | 323 | Medium | ✓ | ✓ | ✓ (2) | ✓ |
| texlive | 260 | Medium | ✓ | ✗ | ✓ (2) | ✓ |
| spack | 323 | Medium | ✓ | ✗ | ✓ (multi) | ✗ |
| pihole | 211 | Low | ✓ | ✗ | ✗ | ✗ |
| poetry | 224 | Low | ✓ | ✗ | ✗ | ✗ |

### Common Patterns Identified

1. **Simple command execution** (60% of plugins): Just run one command
2. **Multi-step execution** (30% of plugins): Run 2-5 commands in sequence
3. **Download + install** (15% of plugins): Download file, extract, install
4. **Version checking** (40% of plugins): Check local vs remote version
5. **Custom output parsing** (80% of plugins): Count updated packages

### Boilerplate Analysis

| Pattern | Lines per Plugin | Plugins Affected |
|---------|-----------------|------------------|
| Streaming setup | 20-30 | 12 |
| Output collection | 10-15 | 12 |
| Completion handling | 15-25 | 12 |
| Version checking | 20-40 | 8 |
| Download logic | 30-50 | 4 |
| **Total potential savings** | **50-100** | **15+** |

---

## Conclusion

The proposed API changes would:

1. **Reduce plugin code by 60-80%** for simple plugins
2. **Standardize streaming, downloads, and version checking**
3. **Enable new features** (parallel execution, estimation, resume)
4. **Improve maintainability** with less duplicated code
5. **Lower the barrier** for new plugin authors

The migration can be done incrementally with full backward compatibility during the transition period.
