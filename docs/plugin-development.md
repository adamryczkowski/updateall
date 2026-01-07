# Plugin Development Guide

This guide explains how to create plugins for Update-All. Plugins extend Update-All to support additional package managers and update sources.

## Table of Contents

- [Overview](#overview)
- [Quick Start Tutorial](#quick-start-tutorial)
- [Plugin Architecture](#plugin-architecture)
- [API Reference](#api-reference)
  - [Declarative Command Execution API](#declarative-command-execution-api) *(Recommended)*
  - [Centralized Download Manager API](#centralized-download-manager-api) *(Recommended)*
  - [Version Checking Protocol](#version-checking-protocol) *(Recommended)*
- [Advanced Topics](#advanced-topics)
  - [Plugins Requiring Sudo](#plugins-requiring-sudo)
  - [Multi-Step Updates](#multi-step-updates)
  - [Handling Non-Error Exit Codes](#handling-non-error-exit-codes)
  - [Custom Availability Checks](#custom-availability-checks)
  - [Self-Update Support](#self-update-support-phase-3)
  - [Plugin Dependencies](#plugin-dependencies)
  - [Interactive Mode](#interactive-mode-phase-4)
- [Streaming Output](#streaming-output)
- [External Plugins](#external-plugins)
- [Testing Plugins](#testing-plugins)
- [Publishing Plugins](#publishing-plugins)
- [Configuration Options](#configuration-options)

## Overview

Update-All uses a plugin-based architecture where each package manager (apt, flatpak, pipx, etc.) is implemented as a separate plugin. Plugins are Python classes that inherit from `BasePlugin` and implement a simple interface.

### Key Concepts

- **Plugin**: A Python class that knows how to check for and apply updates for a specific package manager
- **Registry**: The central store where plugins are registered and discovered
- **Orchestrator**: The component that runs plugins in the correct order
- **BasePlugin**: The abstract base class that provides common functionality

### Plugin Lifecycle

1. **Discovery** — Plugins are discovered via entry points or manual registration
2. **Availability Check** — Each plugin checks if its package manager is installed
3. **Update Check** — Plugins check what updates are available
4. **Execution** — Plugins run their update commands
5. **Reporting** — Results are collected and displayed

## Quick Start Tutorial

Let's create a simple plugin for a fictional package manager called "mypkg".

### Step 1: Create the Plugin Class (Declarative API - Recommended)

The recommended way to create plugins is using the **Declarative Command Execution API**. This approach reduces boilerplate and provides automatic streaming, progress tracking, and error handling.

Create a new file `plugins/plugins/mypkg.py`:

```python
"""MyPkg package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MyPkgPlugin(BasePlugin):
    """Plugin for MyPkg package manager.

    Executes:
    1. mypkg update - refresh package lists
    2. mypkg upgrade - upgrade all packages
    """

    @property
    def name(self) -> str:
        """Return the plugin name (unique identifier)."""
        return "mypkg"

    @property
    def command(self) -> str:
        """Return the main command to check availability."""
        return "mypkg"

    @property
    def description(self) -> str:
        """Return a human-readable description."""
        return "MyPkg package manager"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Declare the commands to execute for an update.

        This is the preferred way to implement plugins. The base class
        handles streaming, progress tracking, and error handling automatically.

        Args:
            dry_run: If True, return commands for dry-run mode.

        Returns:
            List of UpdateCommand objects to execute sequentially.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["mypkg", "update", "--dry-run"],
                    description="Check for updates (dry run)",
                )
            ]
        return [
            UpdateCommand(
                cmd=["mypkg", "update"],
                description="Update package lists",
                step_number=1,
                total_steps=2,
                timeout_seconds=150,
            ),
            UpdateCommand(
                cmd=["mypkg", "upgrade", "-y"],
                description="Upgrade packages",
                step_number=2,
                total_steps=2,
            ),
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Legacy API fallback (not used when get_update_commands is implemented)."""
        return "", None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from command output.

        Args:
            output: The combined command output.

        Returns:
            Number of packages that were updated.
        """
        # Look for patterns like "Upgraded: package-name"
        return len(re.findall(r"^Upgraded:\s+", output, re.MULTILINE))
```

### Step 1 (Alternative): Create the Plugin Class (Legacy API)

If you need more control over command execution, you can use the legacy API:

```python
"""MyPkg package manager plugin (legacy API)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MyPkgPlugin(BasePlugin):
    """Plugin for MyPkg package manager."""

    @property
    def name(self) -> str:
        return "mypkg"

    @property
    def command(self) -> str:
        return "mypkg"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the update commands manually.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_parts: list[str] = []

        # Step 1: Update package lists
        return_code, stdout, stderr = await self._run_command(
            ["mypkg", "update"],
            timeout=config.timeout_seconds // 2,
            sudo=False,
        )

        output_parts.append("=== mypkg update ===")
        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"mypkg update failed: {stderr}"

        # Step 2: Upgrade packages
        return_code, stdout, stderr = await self._run_command(
            ["mypkg", "upgrade", "-y"],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output_parts.append("\n=== mypkg upgrade ===")
        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"mypkg upgrade failed: {stderr}"

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        return len(re.findall(r"^Upgraded:\s+", output, re.MULTILINE))
```

### Step 2: Register the Plugin

Add your plugin to `plugins/plugins/__init__.py`:

```python
from plugins.mypkg import MyPkgPlugin

# Add to __all__
__all__ = [
    # ... existing plugins (AptPlugin, CargoPlugin, FlatpakPlugin, etc.) ...
    "MyPkgPlugin",
]

def register_builtin_plugins(registry: PluginRegistry | None = None) -> PluginRegistry:
    """Register all built-in plugins with the registry."""
    if registry is None:
        registry = get_registry()

    # Existing plugins are registered here...
    # registry.register(AptPlugin)
    # registry.register(CargoPlugin)
    # etc.

    # Add your plugin
    registry.register(MyPkgPlugin)

    return registry
```

**Note:** The current built-in plugins include: `AptPlugin`, `CargoPlugin`, `FlatpakPlugin`, `NpmPlugin`, `PipxPlugin`, `RustupPlugin`, and `SnapPlugin`.

### Step 3: Test Your Plugin

Run the plugin to verify it works:

```bash
# Check if the plugin is registered
just run -- plugins list

# Run only your plugin
just run -- run --plugin mypkg --dry-run

# Run with verbose output
just run -- run --plugin mypkg --verbose
```

## Plugin Architecture

### Project Structure

Plugins live in the `plugins/` subproject:

```
plugins/
├── plugins/
│   ├── __init__.py      # Plugin exports and registration
│   ├── base.py          # BasePlugin class
│   ├── registry.py      # Plugin registry
│   ├── apt.py           # APT plugin
│   ├── cargo.py         # Cargo (Rust) plugin
│   ├── flatpak.py       # Flatpak plugin
│   ├── npm.py           # npm plugin
│   ├── pipx.py          # pipx plugin
│   ├── rustup.py        # Rustup plugin
│   ├── snap.py          # Snap plugin
│   └── your_plugin.py   # Your new plugin
├── tests/
│   ├── test_plugins.py
│   └── test_your_plugin.py
├── pyproject.toml
└── justfile
```

### Class Hierarchy

```
UpdatePlugin (ABC)          # Core interface (core/interfaces.py)
    └── BasePlugin          # Common functionality (plugins/base.py)
            ├── AptPlugin
            ├── FlatpakPlugin
            ├── PipxPlugin
            └── YourPlugin
```

### BasePlugin Features

The `BasePlugin` class provides:

- **Availability checking** — Automatically checks if the command exists
- **Command execution** — Async subprocess execution with timeout
- **Structured logging** — Integration with structlog
- **Error handling** — Timeout and exception handling
- **Dry-run support** — Built-in dry-run mode
- **Self-update support** — Optional self-update mechanism (Phase 3)

## API Reference

### Required Properties

Every plugin must implement these properties:

#### `name: str`

Unique identifier for the plugin. Used in configuration and CLI.

```python
@property
def name(self) -> str:
    return "mypkg"
```

#### `command: str`

The main command to check for availability. Used by `check_available()`.

```python
@property
def command(self) -> str:
    return "mypkg"
```

### Optional Properties

#### `description: str`

Human-readable description shown in plugin listings.

```python
@property
def description(self) -> str:
    return "MyPkg package manager for custom packages"
```

Default: `"Update plugin for {name}"`

#### `metadata: PluginMetadata`

Detailed plugin metadata including version, author, and platform support.

```python
@property
def metadata(self) -> PluginMetadata:
    return PluginMetadata(
        name=self.name,
        version="1.0.0",
        description=self.description,
        author="Your Name",
        requires_sudo=True,
        supported_platforms=["linux"],
    )
```

### Method Hierarchy

The plugin system uses a layered architecture:

1. **`execute(dry_run: bool) -> ExecutionResult`** — Public interface defined in `UpdatePlugin`. Called by the orchestrator.
2. **`run_update(config: PluginConfig, dry_run: bool) -> PluginResult`** — Internal method in `BasePlugin` that handles availability checking, dry-run mode, and error handling.
3. **`_execute_update(config: PluginConfig) -> tuple[str, str | None]`** — Abstract method you implement with your actual update logic.

When you extend `BasePlugin`, you only need to implement `_execute_update()`. The base class handles everything else.

### Required Methods

#### `_execute_update(config: PluginConfig) -> tuple[str, str | None]`

The main update logic. Must be implemented by all plugins that extend `BasePlugin`.

**Arguments:**
- `config`: Plugin configuration with timeout, options, etc.

**Returns:**
- Tuple of `(output, error_message)`
- `error_message` should be `None` on success

```python
async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
    return_code, stdout, stderr = await self._run_command(
        ["mypkg", "upgrade"],
        timeout=config.timeout_seconds,
        sudo=False,
    )

    if return_code != 0:
        return stdout, f"Upgrade failed: {stderr}"

    return stdout, None
```

### Optional Methods

#### `_count_updated_packages(output: str) -> int`

Parse command output to count updated packages.

```python
def _count_updated_packages(self, output: str) -> int:
    return len(re.findall(r"Upgraded:\s+\S+", output))
```

Default: Returns `0`

#### `check_available() -> bool`

Check if the package manager is available on the system.

```python
async def check_available(self) -> bool:
    # Default implementation checks if self.command exists
    return shutil.which(self.command) is not None
```

Override for custom availability checks:

```python
async def check_available(self) -> bool:
    # Check for command AND configuration file
    if not shutil.which(self.command):
        return False
    return Path("/etc/mypkg/config").exists()
```

#### `check_updates() -> list[dict[str, Any]]`

Check what updates are available without applying them.

```python
async def check_updates(self) -> list[dict[str, Any]]:
    return_code, stdout, _ = await self._run_command(
        ["mypkg", "list", "--upgradable"],
        timeout=60,
    )

    if return_code != 0:
        return []

    updates = []
    for line in stdout.strip().split("\n"):
        name, version = line.split()
        updates.append({"name": name, "version": version})

    return updates
```

### Helper Methods

#### `_run_command(cmd, timeout, *, check=True, sudo=False) -> tuple[int, str, str]`

Execute a shell command with timeout handling.

**Arguments:**
- `cmd`: Command as a list of strings
- `timeout`: Timeout in seconds
- `check`: Reserved for future use
- `sudo`: Whether to prepend `sudo` to the command

**Returns:**
- Tuple of `(return_code, stdout, stderr)`

**Raises:**
- `TimeoutError`: If command exceeds timeout

```python
# Simple command
return_code, stdout, stderr = await self._run_command(
    ["mypkg", "update"],
    timeout=300,
)

# Command with sudo
return_code, stdout, stderr = await self._run_command(
    ["apt", "upgrade", "-y"],
    timeout=3600,
    sudo=True,
)
```

### Data Models

#### PluginConfig

Configuration passed to plugins during execution.

```python
class PluginConfig(BaseModel):
    name: str                    # Plugin identifier
    enabled: bool = True         # Whether plugin is enabled
    timeout_seconds: int = 300   # Execution timeout
    retry_count: int = 0         # Retries on failure
    requires_sudo: bool = False  # Whether sudo is needed
    dependencies: list[str] = [] # Plugin dependencies
    options: dict[str, Any] = {} # Plugin-specific options
```

#### PluginResult

Result returned from plugin execution.

```python
class PluginResult(BaseModel):
    plugin_name: str              # Plugin identifier
    status: PluginStatus          # SUCCESS, FAILED, SKIPPED, TIMEOUT
    start_time: datetime          # When execution started
    end_time: datetime | None     # When execution ended
    output: str                   # Command output
    error_message: str | None     # Error message if failed
    packages_updated: int         # Count of updated packages
```

#### PluginStatus

Enum of possible execution statuses.

```python
class PluginStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
```

### Declarative Command Execution API

The **Declarative Command Execution API** is the recommended way to implement plugins. Instead of manually implementing `_execute_update_streaming()`, you declare the commands to execute and the base class handles everything automatically.

#### `get_update_commands(dry_run: bool) -> list[UpdateCommand]`

Override this method to use the declarative API. When it returns a non-empty list, the base class uses `_execute_commands_streaming()` instead of `_execute_update_streaming()`.

```python
from core.models import UpdateCommand

def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
    if dry_run:
        return [
            UpdateCommand(
                cmd=["apt", "update", "--dry-run"],
                description="Check for updates (dry run)",
            )
        ]
    return [
        UpdateCommand(
            cmd=["apt", "update"],
            description="Update package lists",
            sudo=True,
            step_number=1,
            total_steps=2,
        ),
        UpdateCommand(
            cmd=["apt", "upgrade", "-y"],
            description="Upgrade packages",
            sudo=True,
            step_number=2,
            total_steps=2,
        ),
    ]
```

#### UpdateCommand

The `UpdateCommand` dataclass defines a single command to execute:

```python
from dataclasses import dataclass
from core.streaming import Phase

@dataclass(frozen=True)
class UpdateCommand:
    # Required
    cmd: list[str]                    # Command and arguments

    # Optional - Display
    description: str = ""             # Human-readable description
    step_name: str | None = None      # Step identifier
    step_number: int | None = None    # Step number (e.g., 1)
    total_steps: int | None = None    # Total steps (e.g., 2)

    # Optional - Execution
    sudo: bool = False                # Prepend sudo
    timeout_seconds: int | None = None # Command timeout (default: 300)
    phase: Phase = Phase.EXECUTE      # Execution phase
    env: dict[str, str] | None = None # Environment variables
    cwd: str | None = None            # Working directory

    # Optional - Error handling
    ignore_exit_codes: tuple[int, ...] = ()  # Exit codes to treat as success
    error_patterns: tuple[str, ...] = ()     # Patterns that indicate failure
    success_patterns: tuple[str, ...] = ()   # Patterns that indicate success
```

#### Benefits of Declarative API

1. **Less boilerplate** — No need to implement streaming logic manually
2. **Automatic headers** — Step progress like `[1/2] Update package lists` is generated
3. **Pattern matching** — Success/error patterns override exit codes
4. **Output collection** — Output is collected for `_count_updated_packages()`
5. **Consistent behavior** — All plugins behave the same way

#### Pattern Matching Priority

When determining command success, patterns are checked in this order:

1. **Error patterns** — If any error pattern matches, command fails
2. **Success patterns** — If any success pattern matches, command succeeds
3. **Ignored exit codes** — If exit code is in `ignore_exit_codes`, command succeeds
4. **Exit code** — Non-zero exit code means failure

Example with patterns:

```python
UpdateCommand(
    cmd=["snap", "refresh"],
    sudo=True,
    # These patterns override exit code
    success_patterns=("All snaps up to date",),
    error_patterns=("FATAL", "CRITICAL"),
    # Exit code 1 is also acceptable
    ignore_exit_codes=(1,),
)
```

#### Fallback to Legacy API

If `get_update_commands()` returns an empty list (the default), the base class falls back to `_execute_update_streaming()` and `_execute_update()`. This ensures backward compatibility with existing plugins.

### Centralized Download Manager API

The **Centralized Download Manager API** is the recommended way to handle file downloads in plugins. Instead of implementing download logic manually, you declare what to download using `DownloadSpec` and the core download manager handles everything automatically.

#### Why Use the Centralized Download Manager?

1. **Automatic retry with exponential backoff** — Failed downloads are retried automatically
2. **Bandwidth limiting** — Configurable rate limiting to avoid saturating network
3. **Download caching** — Files are cached with checksum verification to avoid re-downloading
4. **Archive extraction** — Automatic extraction of tar.gz, tar.bz2, tar.xz, and zip files
5. **Progress reporting** — Real-time progress events for UI display
6. **Checksum verification** — SHA256, SHA512, SHA1, and MD5 checksum support
7. **Consistent behavior** — All plugins handle downloads the same way

#### `get_download_spec(dry_run: bool) -> DownloadSpec | None`

Override this method to specify a single file to download. When it returns a `DownloadSpec`, the base class `download_streaming()` method uses the centralized download manager.

```python
from pathlib import Path
from core.models import DownloadSpec
from plugins.base import BasePlugin


class MyDownloadPlugin(BasePlugin):
    """Plugin that downloads a file from the internet."""

    DOWNLOAD_URL = "https://example.com/releases/latest/myapp.tar.gz"
    INSTALL_PATH = "/opt/myapp"

    @property
    def name(self) -> str:
        return "myapp"

    @property
    def command(self) -> str:
        return "myapp"

    @property
    def supports_download(self) -> bool:
        """Enable separate download phase."""
        return True

    def get_download_spec(self, dry_run: bool = False) -> DownloadSpec | None:
        """Declare the file to download.

        Args:
            dry_run: If True, return None (no download in dry-run mode).

        Returns:
            DownloadSpec describing the file to download, or None.
        """
        if dry_run:
            return None

        return DownloadSpec(
            url=self.DOWNLOAD_URL,
            destination=Path(self.INSTALL_PATH),
            expected_size=50_000_000,  # 50 MB (for progress reporting)
            checksum="sha256:abc123...",  # Optional: verify download
            extract=True,  # Extract the archive after download
            # extract_format is auto-detected from URL (.tar.gz)
        )
```

#### `get_download_specs(dry_run: bool) -> list[DownloadSpec]`

For plugins that need to download multiple files, override this method instead:

```python
def get_download_specs(self, dry_run: bool = False) -> list[DownloadSpec]:
    """Declare multiple files to download.

    Args:
        dry_run: If True, return empty list.

    Returns:
        List of DownloadSpec objects.
    """
    if dry_run:
        return []

    return [
        DownloadSpec(
            url="https://example.com/component-a.tar.gz",
            destination=Path("/opt/myapp/component-a"),
            extract=True,
        ),
        DownloadSpec(
            url="https://example.com/component-b.tar.gz",
            destination=Path("/opt/myapp/component-b"),
            extract=True,
        ),
    ]
```

#### DownloadSpec

The `DownloadSpec` dataclass describes what to download:

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class DownloadSpec:
    # Required
    url: str                              # URL to download from
    destination: Path                     # Where to save (or extract to)

    # Optional - Progress & Verification
    expected_size: int | None = None      # Expected size in bytes
    checksum: str | None = None           # "sha256:abc123..." or "md5:abc123..."

    # Optional - Archive Handling
    extract: bool = False                 # Extract after download
    extract_format: str | None = None     # "tar.gz", "tar.bz2", "zip", "tar.xz"
                                          # (auto-detected from URL if not specified)

    # Optional - Request Configuration
    headers: dict[str, str] = field(default_factory=dict)  # HTTP headers
    timeout_seconds: int | None = None    # Download timeout

    # Optional - Version Checking
    version_url: str | None = None        # URL to check latest version
    version_pattern: str | None = None    # Regex to extract version
```

#### DownloadResult

The download manager returns a `DownloadResult` with details about the download:

```python
@dataclass
class DownloadResult:
    success: bool                         # Whether download succeeded
    path: Path | None = None              # Path to downloaded/extracted file
    bytes_downloaded: int = 0             # Total bytes downloaded
    duration_seconds: float = 0.0         # Time taken
    from_cache: bool = False              # Whether served from cache
    checksum_verified: bool = False       # Whether checksum was verified
    error_message: str | None = None      # Error message if failed
    spec: DownloadSpec | None = None      # Original specification
```

#### Checksum Format

Checksums must be in the format `algorithm:hash`:

```python
# SHA-256 (recommended)
checksum="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# SHA-512
checksum="sha512:cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce..."

# MD5 (not recommended for security, but supported)
checksum="md5:d41d8cd98f00b204e9800998ecf8427e"
```

#### Archive Extraction

When `extract=True`, the download manager automatically extracts archives:

| Format | Extensions | Notes |
|--------|------------|-------|
| `tar.gz` | `.tar.gz`, `.tgz` | Most common for Linux |
| `tar.bz2` | `.tar.bz2`, `.tbz2` | Better compression |
| `tar.xz` | `.tar.xz`, `.txz` | Best compression |
| `zip` | `.zip` | Cross-platform |

The format is auto-detected from the URL extension, or you can specify it explicitly:

```python
DownloadSpec(
    url="https://example.com/file",  # No extension
    destination=Path("/opt/myapp"),
    extract=True,
    extract_format="tar.gz",  # Explicit format
)
```

#### Real-World Example: Waterfox Plugin

Here's how the Waterfox plugin uses the Centralized Download Manager:

```python
"""Waterfox update plugin using Centralized Download Manager."""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.models import DownloadSpec
from plugins.base import BasePlugin


class WaterfoxPlugin(BasePlugin):
    """Plugin for updating Waterfox browser."""

    GITHUB_API_URL = "https://api.github.com/repos/MrAlex94/Waterfox/releases/latest"
    INSTALL_PATH = "/opt/waterfox"

    @property
    def name(self) -> str:
        return "waterfox"

    @property
    def command(self) -> str:
        return "waterfox"

    @property
    def supports_download(self) -> bool:
        return True

    def get_download_spec(self, dry_run: bool = False) -> DownloadSpec | None:
        """Get download specification for Waterfox.

        Returns:
            DownloadSpec for the Waterfox tar.bz2 archive.
        """
        if dry_run:
            return None

        # Get the download URL from GitHub API
        download_url = self._get_download_url()
        if not download_url:
            return None

        return DownloadSpec(
            url=download_url,
            destination=Path(self.INSTALL_PATH),
            extract=True,
            # extract_format auto-detected as "tar.bz2"
            headers={"Accept": "application/octet-stream"},
        )

    def _get_download_url(self) -> str | None:
        """Fetch the download URL from GitHub releases API."""
        # Implementation fetches from GITHUB_API_URL
        # and returns the tar.bz2 asset URL
        ...
```

#### Configuration Options

The download manager can be configured globally in `GlobalConfig`:

```python
from core.models import GlobalConfig

config = GlobalConfig(
    # Cache directory (None = system temp)
    download_cache_dir=Path("/var/cache/update-all"),

    # Retry settings
    download_max_retries=3,           # Max retry attempts
    download_retry_delay=1.0,         # Initial delay (exponential backoff)

    # Bandwidth limiting
    download_bandwidth_limit=None,    # Bytes/sec (None = unlimited)
    download_max_concurrent=2,        # Max parallel downloads

    # Timeout
    download_timeout_seconds=3600,    # Default timeout (1 hour)
)
```

Or in YAML configuration:

```yaml
# config.yaml
global:
  download_cache_dir: /var/cache/update-all
  download_max_retries: 3
  download_retry_delay: 1.0
  download_bandwidth_limit: null  # unlimited
  download_max_concurrent: 2
  download_timeout_seconds: 3600
```

#### Fallback to Manual Downloads

If `get_download_spec()` returns `None` (the default), the base class falls back to the manual `download_streaming()` implementation. This ensures backward compatibility with existing plugins.

### Version Checking Protocol

The **Version Checking Protocol** is the recommended way to implement version checking and update estimation in plugins. This enables:
- Check-only mode (see what needs updating without applying)
- Download size estimation before updates
- Skip plugins that are already up-to-date
- Better progress estimation based on download sizes

#### Why Use the Version Checking Protocol?

1. **Skip unnecessary updates** — Don't run update commands if already up-to-date
2. **Accurate time estimates** — Know download sizes before starting
3. **Check-only mode** — Users can see what would be updated
4. **Better UX** — Show version info in progress display
5. **Resource planning** — Estimate disk space and bandwidth needs

#### Core Methods

The Version Checking Protocol adds four async methods to plugins:

##### `get_installed_version() -> str | None`

Returns the currently installed version, or `None` if not installed.

```python
async def get_installed_version(self) -> str | None:
    """Get the currently installed version.

    Returns:
        Version string (e.g., "1.75.0") or None if not installed.
    """
    if not self.is_available():
        return None

    try:
        process = await asyncio.create_subprocess_exec(
            "myapp",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        if process.returncode == 0:
            # Parse version from output like "myapp version 1.2.3"
            output = stdout.decode().strip()
            match = re.search(r"(\d+\.\d+\.\d+)", output)
            if match:
                return match.group(1)
    except (TimeoutError, OSError):
        pass
    return None
```

##### `get_available_version() -> str | None`

Returns the latest available version, or `None` if cannot determine.

```python
async def get_available_version(self) -> str | None:
    """Get the latest available version.

    Returns:
        Version string or None if cannot determine.
    """
    try:
        # Example: Check GitHub releases API
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tag = data.get("tag_name", "")
                    return tag.lstrip("v")  # Remove "v" prefix
    except (TimeoutError, aiohttp.ClientError, OSError):
        pass
    return None
```

##### `needs_update() -> bool | None`

Returns whether an update is needed, or `None` if cannot determine.

```python
async def needs_update(self) -> bool | None:
    """Check if an update is needed.

    Returns:
        True if update available, False if up-to-date, None if cannot determine.
    """
    installed = await self.get_installed_version()
    available = await self.get_available_version()

    if installed and available:
        # Use the version comparison utility
        from core.version import compare_versions
        return compare_versions(installed, available) < 0

    return None
```

##### `get_update_estimate() -> UpdateEstimate | None`

Returns download size and time estimates, or `None` if no update needed.

```python
from core.models import UpdateEstimate

async def get_update_estimate(self) -> UpdateEstimate | None:
    """Get estimated download size and time.

    Returns:
        UpdateEstimate or None if no update needed.
    """
    needs = await self.needs_update()
    if not needs:
        return None

    # Try to get actual size from API
    download_bytes = 50 * 1024 * 1024  # Default 50MB

    try:
        # Example: Get size from PyPI API
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://pypi.org/pypi/mypackage/json",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for url_info in data.get("urls", []):
                        if url_info.get("packagetype") == "bdist_wheel":
                            download_bytes = url_info.get("size", download_bytes)
                            break
    except (TimeoutError, aiohttp.ClientError, OSError):
        pass

    return UpdateEstimate(
        download_bytes=download_bytes,
        package_count=1,
        packages=["mypackage"],
        estimated_seconds=30,
        confidence=0.8,  # High confidence from API
    )
```

#### UpdateEstimate Dataclass

The `UpdateEstimate` dataclass describes the expected update:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class UpdateEstimate:
    # Size information
    download_bytes: int | None = None      # Total bytes to download
    package_count: int | None = None       # Number of packages

    # Package details (optional)
    packages: list[str] | None = None      # List of package names

    # Time estimation
    estimated_seconds: float | None = None # Estimated time to complete

    # Confidence level (0.0 to 1.0)
    confidence: float = 0.5                # How confident is this estimate
```

#### VersionInfo Dataclass

The `VersionInfo` dataclass aggregates all version information:

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class VersionInfo:
    installed: str | None = None           # Installed version
    available: str | None = None           # Available version
    needs_update: bool | None = None       # Whether update is needed
    check_time: datetime | None = None     # When the check was performed
    error_message: str | None = None       # Error if check failed
    estimate: UpdateEstimate | None = None # Download size estimate
```

#### Version Comparison Utilities

The `core.version` module provides utilities for version comparison:

```python
from core.version import compare_versions, parse_version, needs_update

# Compare two versions
result = compare_versions("1.2.3", "1.3.0")  # Returns -1 (less than)
result = compare_versions("2.0.0", "1.9.9")  # Returns 1 (greater than)
result = compare_versions("1.0.0", "1.0.0")  # Returns 0 (equal)

# Check if update is needed
needs = needs_update("1.2.3", "1.3.0")  # Returns True
needs = needs_update("2.0.0", "1.9.9")  # Returns False

# Parse version for detailed comparison
version = parse_version("1.2.3-beta.1")
print(version.major, version.minor, version.patch)  # 1, 2, 3
```

#### Real-World Example: Waterfox Plugin

Here's how the Waterfox plugin implements the Version Checking Protocol:

```python
"""Waterfox update plugin with Version Checking Protocol."""

from __future__ import annotations

import asyncio
import re

import aiohttp

from core.models import UpdateEstimate
from core.version import compare_versions
from plugins.base import BasePlugin


class WaterfoxPlugin(BasePlugin):
    """Plugin for updating Waterfox browser."""

    GITHUB_API_URL = "https://api.github.com/repos/MrAlex94/Waterfox/releases/latest"

    @property
    def name(self) -> str:
        return "waterfox"

    @property
    def command(self) -> str:
        return "waterfox"

    async def get_installed_version(self) -> str | None:
        """Get installed Waterfox version."""
        try:
            process = await asyncio.create_subprocess_exec(
                "waterfox",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                output = stdout.decode()
                match = re.search(r"(\d+\.\d+\.\d+)", output)
                if match:
                    return match.group(1)
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get latest Waterfox version from GitHub."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Accept": "application/vnd.github.v3+json"}
                async with session.get(
                    self.GITHUB_API_URL,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tag = data.get("tag_name", "")
                        return tag.lstrip("G")  # Remove "G" prefix
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Waterfox needs an update."""
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed and available:
            return compare_versions(installed, available) < 0

        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get download size estimate for Waterfox."""
        needs = await self.needs_update()
        if not needs:
            return None

        # Try to get actual size from GitHub release
        download_bytes = 100 * 1024 * 1024  # Default 100MB

        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Accept": "application/vnd.github.v3+json"}
                async with session.get(
                    self.GITHUB_API_URL,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for asset in data.get("assets", []):
                            if "linux" in asset.get("name", "").lower():
                                download_bytes = asset.get("size", download_bytes)
                                break
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass

        return UpdateEstimate(
            download_bytes=download_bytes,
            package_count=1,
            packages=["waterfox"],
            estimated_seconds=120,
            confidence=0.8,
        )
```

#### Version Sources by Plugin Type

Different plugins use different sources for version information:

| Plugin Type | Installed Version | Available Version |
|-------------|-------------------|-------------------|
| System packages (apt, snap) | Package manager query | Package manager query |
| GitHub releases | `--version` flag | GitHub API |
| PyPI packages | `--version` flag | PyPI JSON API |
| Language runtimes | `--version` flag | Official download page |
| Self-updating tools | `--version` flag | Built-in check command |

#### Confidence Levels

The `confidence` field indicates how reliable the estimate is:

| Confidence | Meaning | Example |
|------------|---------|---------|
| 0.9 - 1.0 | Very high | Exact size from API |
| 0.7 - 0.9 | High | Size from package metadata |
| 0.5 - 0.7 | Medium | Estimate from similar packages |
| 0.3 - 0.5 | Low | Rough estimate |
| 0.0 - 0.3 | Very low | Wild guess |

#### Fallback Behavior

If a plugin doesn't implement the Version Checking Protocol methods, the base class provides sensible defaults:

- `get_installed_version()` → Returns `None`
- `get_available_version()` → Returns `None`
- `needs_update()` → Returns `None` (always run update)
- `get_update_estimate()` → Returns `None` (no size estimate)

This ensures backward compatibility with existing plugins.

## Advanced Topics

### Plugins Requiring Sudo

For plugins that need root privileges:

```python
class AptPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "apt"

    @property
    def command(self) -> str:
        return "apt"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        # Use sudo=True for privileged commands
        return_code, stdout, stderr = await self._run_command(
            ["apt", "update"],
            timeout=config.timeout_seconds,
            sudo=True,  # This prepends "sudo" to the command
        )
        # ...
```

### Multi-Step Updates

Many package managers require multiple steps:

```python
async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
    output_parts: list[str] = []

    # Step 1: Refresh package lists
    return_code, stdout, stderr = await self._run_command(
        ["apt", "update"],
        timeout=config.timeout_seconds // 2,
        sudo=True,
    )
    output_parts.append("=== apt update ===")
    output_parts.append(stdout)

    if return_code != 0:
        return "\n".join(output_parts), f"apt update failed: {stderr}"

    # Step 2: Upgrade packages
    return_code, stdout, stderr = await self._run_command(
        ["apt", "upgrade", "-y"],
        timeout=config.timeout_seconds,
        sudo=True,
    )
    output_parts.append("\n=== apt upgrade ===")
    output_parts.append(stdout)

    if return_code != 0:
        return "\n".join(output_parts), f"apt upgrade failed: {stderr}"

    return "\n".join(output_parts), None
```

### Handling Non-Error Exit Codes

Some commands return non-zero when there's nothing to update:

```python
async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
    return_code, stdout, stderr = await self._run_command(
        ["pipx", "upgrade-all"],
        timeout=config.timeout_seconds,
    )

    output = f"=== pipx upgrade-all ===\n{stdout}"

    if return_code != 0:
        # Check for "nothing to do" conditions
        if "No packages to upgrade" in stderr or "already at latest" in stdout:
            return output, None  # Not an error
        return output, f"pipx upgrade-all failed: {stderr}"

    return output, None
```

### Custom Availability Checks

Override `check_available()` for complex checks:

```python
async def check_available(self) -> bool:
    # Check command exists
    if not shutil.which(self.command):
        return False

    # Check for required configuration
    config_path = Path.home() / ".config" / "mypkg" / "config.yaml"
    if not config_path.exists():
        return False

    # Check command actually works
    try:
        return_code, _, _ = await self._run_command(
            ["mypkg", "--version"],
            timeout=10,
        )
        return return_code == 0
    except Exception:
        return False
```

### Self-Update Support (Phase 3)

Plugins can support self-updating:

```python
class MyPkgPlugin(BasePlugin):
    @property
    def supports_self_update(self) -> bool:
        return True

    @property
    def current_version(self) -> str | None:
        # Return current plugin version
        return "1.0.0"

    async def check_self_update_available(self) -> tuple[bool, str | None]:
        # Check if a new version is available
        # Returns (update_available, new_version)
        return True, "1.1.0"

    async def _perform_self_update(self) -> tuple[bool, str]:
        # Perform the actual update
        # Returns (success, message)
        return True, "Updated to version 1.1.0"
```

### Plugin Dependencies

Specify that your plugin should run after another:

```python
@property
def metadata(self) -> PluginMetadata:
    return PluginMetadata(
        name=self.name,
        dependencies=["apt"],  # Run after apt completes
    )
```

### Interactive Mode (Phase 4)

Plugins can support interactive mode, which runs the update command in a PTY (pseudo-terminal) for full terminal emulation. This enables:
- Interactive prompts (sudo password, confirmations)
- Live progress display with ANSI escape sequences
- Cursor movement and terminal control codes

```python
class MyInteractivePlugin(BasePlugin):
    @property
    def supports_interactive(self) -> bool:
        """Enable interactive mode for this plugin."""
        return True

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Return the command to run in interactive mode.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            return ["/bin/bash", "-c", "mypkg update --dry-run"]
        return ["/bin/bash", "-c", "mypkg update -y"]
```

For multi-step commands, use a shell wrapper:

```python
def get_interactive_command(self, dry_run: bool = False) -> list[str]:
    if dry_run:
        return [
            "/bin/bash", "-c",
            "sudo apt update && sudo apt upgrade --dry-run"
        ]
    return [
        "/bin/bash", "-c",
        "sudo apt update && sudo apt upgrade -y"
    ]
```

## Streaming Output

Update-All supports real-time streaming output from plugins, enabling live progress display in the UI. This section covers how to implement streaming in your plugins.

### Why Streaming?

Without streaming, plugin output is only displayed after execution completes. With streaming:
- Users see output in real-time as commands run
- Progress bars show download and installation progress
- Errors are visible immediately, not after minutes of waiting
- The UI feels responsive even for long-running updates

### Streaming Interface

Python plugins can implement streaming by overriding `execute_streaming()`:

```python
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
)


class MyStreamingPlugin(BasePlugin):
    @property
    def supports_streaming(self) -> bool:
        """Indicate that this plugin supports streaming."""
        return True

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute with streaming output."""
        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        # Run commands with streaming
        async for event in self._run_command_streaming(
            ["mypkg", "upgrade"],
            timeout=300,
        ):
            yield event

        # Emit phase end
        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            success=True,
        )
```

### Event Types

The streaming system uses several event types:

| Event Type | Purpose |
|------------|---------|
| `OutputEvent` | Raw output line (stdout/stderr) |
| `ProgressEvent` | Progress update with percentage |
| `PhaseEvent` | Phase start/end markers |
| `CompletionEvent` | Final completion status |

### Progress Events

Report progress during execution:

```python
yield ProgressEvent(
    event_type=EventType.PROGRESS,
    plugin_name=self.name,
    timestamp=datetime.now(tz=UTC),
    phase=Phase.EXECUTE,
    percent=50.0,
    message="Installing package 5/10...",
    items_completed=5,
    items_total=10,
)
```

For downloads, include byte counts:

```python
yield ProgressEvent(
    event_type=EventType.PROGRESS,
    plugin_name=self.name,
    timestamp=datetime.now(tz=UTC),
    phase=Phase.DOWNLOAD,
    percent=45.5,
    message="Downloading python3.12...",
    bytes_downloaded=15_000_000,
    bytes_total=33_000_000,
)
```

### Download Phase Support

Plugins can support separate download and execute phases:

```python
class MyPlugin(BasePlugin):
    @property
    def supports_download(self) -> bool:
        """Enable separate download phase."""
        return True

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Download updates without installing."""
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        # Download logic here...
        async for event in self._run_download_command_streaming(
            ["mypkg", "download", "--only"],
            timeout=3600,
        ):
            yield event

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            success=True,
        )

    async def estimate_download(self) -> DownloadEstimate | None:
        """Estimate download size before starting."""
        return DownloadEstimate(
            total_bytes=100_000_000,
            package_count=5,
            estimated_seconds=60,
        )
```

### Using `_run_command_streaming()`

The `BasePlugin` class provides a streaming command executor:

```python
async for event in self._run_command_streaming(
    ["mypkg", "upgrade", "-y"],
    timeout=300,
    sudo=True,
    phase=Phase.EXECUTE,
):
    yield event
```

This method:
- Reads stdout and stderr line-by-line
- Parses JSON progress events from stderr (with `PROGRESS:` prefix)
- Handles timeouts gracefully
- Emits a `CompletionEvent` when done

## External Plugins

Update-All supports external executable plugins written in any language (Bash, Python, Go, etc.). External plugins communicate via stdout/stderr using a defined protocol.

### Quick Start

Create an executable script that responds to commands:

```bash
#!/bin/bash
# my-plugin.sh

case "$1" in
    is-applicable)
        # Check if this plugin can run
        command -v my-package-manager &> /dev/null
        exit $?
        ;;
    update)
        echo "Running update..."
        # Your update logic here
        exit 0
        ;;
    *)
        echo "Unknown command: $1" >&2
        exit 1
        ;;
esac
```

### Required Commands

| Command | Description | Exit Code |
|---------|-------------|-----------|
| `is-applicable` | Check if plugin can run | 0=yes, 1=no |
| `update` | Execute updates | 0=success, non-zero=failure |

### Optional Commands

| Command | Description |
|---------|-------------|
| `does-require-sudo` | Check if sudo needed (exit 0=yes, 1=no) |
| `can-separate-download` | Check if download is separate |
| `estimate-update` | Return JSON with size/time estimates |
| `download` | Download updates only |

### Streaming Protocol

External plugins can emit progress events to stderr:

```bash
# Emit progress event
echo 'PROGRESS:{"phase":"execute","percent":50,"message":"Installing..."}' >&2

# Regular output goes to stdout
echo "Installing package..."
```

The `PROGRESS:` prefix tells Update-All to parse the line as a JSON progress event.

### Progress Event Format

```json
{
  "phase": "download|execute|check",
  "percent": 45.5,
  "message": "Downloading package...",
  "bytes_downloaded": 15000000,
  "bytes_total": 33000000,
  "items_completed": 3,
  "items_total": 10
}
```

### Phase Events

Signal phase start/end:

```bash
# Phase start
echo 'PROGRESS:{"type":"phase_start","phase":"download"}' >&2

# ... do work ...

# Phase end
echo 'PROGRESS:{"type":"phase_end","phase":"download","success":true}' >&2
```

### Validating External Plugins

Use the validation tool to check your plugin:

```bash
# Validate plugin
update-all plugins validate ./my-plugin.sh

# Verbose output
update-all plugins validate ./my-plugin.sh --verbose
```

### Example External Plugins

See the `examples/plugins/` directory for complete examples:
- `example-bash-plugin.sh` — Full-featured Bash plugin
- `example-python-plugin.py` — Full-featured Python plugin

### Full Protocol Documentation

For complete protocol details, see [External Plugin Streaming Protocol](external-plugin-streaming-protocol.md).

## Testing Plugins

### Unit Tests

Create tests in `plugins/tests/test_your_plugin.py`:

```python
"""Tests for MyPkg plugin."""

import pytest

from plugins import MyPkgPlugin


class TestMyPkgPlugin:
    """Tests for MyPkgPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = MyPkgPlugin()
        assert plugin.name == "mypkg"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = MyPkgPlugin()
        assert plugin.command == "mypkg"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = MyPkgPlugin()
        assert "mypkg" in plugin.description.lower()

    def test_count_updated_packages(self) -> None:
        """Test package counting."""
        plugin = MyPkgPlugin()
        output = """
        Upgraded: package-a
        Upgraded: package-b
        Already up to date: package-c
        """
        assert plugin._count_updated_packages(output) == 2

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when command is missing."""
        plugin = MyPkgPlugin()
        # This will return False if mypkg is not installed
        available = await plugin.check_available()
        # Assert based on your test environment
        assert isinstance(available, bool)
```

### Running Tests

```bash
# Run all plugin tests
cd plugins
just test

# Run specific test file
poetry run pytest tests/test_your_plugin.py -v

# Run with coverage
just test-cov
```

### Integration Tests

For integration tests that require the actual package manager:

```python
@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("mypkg") is None,
    reason="mypkg not installed"
)
class TestMyPkgPluginIntegration:
    """Integration tests for MyPkgPlugin."""

    @pytest.mark.asyncio
    async def test_check_updates(self) -> None:
        """Test checking for updates."""
        plugin = MyPkgPlugin()
        updates = await plugin.check_updates()
        assert isinstance(updates, list)
```

## Publishing Plugins

### As Part of Update-All

1. Add your plugin to `plugins/plugins/`
2. Register it in `plugins/plugins/__init__.py`
3. Add tests in `plugins/tests/`
4. Submit a pull request

### As a Separate Package

Create a standalone package with an entry point:

```toml
# pyproject.toml
[tool.poetry]
name = "update-all-mypkg"
version = "1.0.0"

[tool.poetry.plugins."update_all.plugins"]
mypkg = "update_all_mypkg:MyPkgPlugin"
```

Users can then install your plugin:

```bash
pip install update-all-mypkg
```

The plugin will be automatically discovered via entry points.

## Examples

### Minimal Plugin

The simplest possible plugin:

```python
from plugins.base import BasePlugin
from core.models import PluginConfig


class MinimalPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "minimal"

    @property
    def command(self) -> str:
        return "echo"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return_code, stdout, stderr = await self._run_command(
            ["echo", "Updated!"],
            timeout=config.timeout_seconds,
        )
        return stdout, None if return_code == 0 else stderr
```

### Complete Plugin with All Features

See [`plugins/plugins/apt.py`](../plugins/plugins/apt.py) for a complete example with:
- Multi-step updates
- Sudo support
- Package counting
- Error handling

## Troubleshooting

### Plugin Not Appearing

1. Check that the plugin is registered in `__init__.py`
2. Verify the plugin class is exported in `__all__`
3. Run `just run -- plugins list` to see registered plugins

### Command Not Found

1. Verify the command exists: `which mypkg`
2. Check `check_available()` returns `True`
3. Ensure the command is in the PATH

### Timeout Errors

1. Increase `timeout_seconds` in configuration
2. Split long operations into multiple commands
3. Use `config.timeout_seconds // 2` for preliminary steps

### Permission Denied

1. Use `sudo=True` in `_run_command()` for privileged operations
2. Ensure the user has sudo access
3. Consider using polkit for GUI environments

## Configuration Options

### Streaming Feature Flag

The `streaming_enabled` configuration option controls whether plugins use streaming output or fall back to batch mode. This is useful for:
- Debugging streaming issues
- Environments where streaming causes problems
- Gradual rollout of streaming features

```yaml
# config.yaml
global:
  streaming_enabled: true  # Default: true
```

In code:

```python
from core.models import GlobalConfig

config = GlobalConfig(streaming_enabled=False)  # Disable streaming

# Check if streaming is enabled
if config.streaming_enabled:
    async for event in plugin.execute_streaming():
        handle_event(event)
else:
    result = await plugin.execute()
    display_result(result)
```

### Monitoring and Metrics

Update-All includes a metrics system for production monitoring. Plugins can integrate with this system to track performance.

#### Using the Metrics Collector

```python
from core.metrics import (
    LatencyTimer,
    MetricsCollector,
    get_metrics_collector,
)

# Get the global metrics collector
collector = get_metrics_collector()

# Track plugin execution
collector.start_plugin_execution("my-plugin")

async for event in plugin.execute_streaming():
    collector.increment_event_count("my-plugin")

    # Track UI update latency
    with LatencyTimer() as timer:
        update_ui(event)
    collector.record_ui_latency(timer.elapsed_ms)

collector.end_plugin_execution("my-plugin")
```

#### Metric Thresholds

The following thresholds are used for alerting:

| Metric | Target | Alert |
|--------|--------|-------|
| Memory per plugin | < 50 MB | > 100 MB |
| UI update latency | < 50 ms | > 200 ms |
| Event queue depth | < 100 | > 500 |
| Test coverage | > 80% | < 70% |

#### Recording Custom Metrics

```python
from core.metrics import MetricValue, MetricLevel

collector.record_metric(MetricValue(
    name="custom_metric",
    value=42.0,
    unit="count",
    level=MetricLevel.OK,
    labels={"plugin": "my-plugin"},
))
```

## Getting Help

- Check existing plugins in `plugins/plugins/` for examples
- Review the [implementation plan](update-all-python-plan.md) for architecture details
- Review the [architecture refinement plan](update-all-architecture-refinement-plan.md) for streaming details
- Open an issue on GitHub for questions
