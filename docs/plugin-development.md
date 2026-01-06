# Plugin Development Guide

This guide explains how to create plugins for Update-All. Plugins extend Update-All to support additional package managers and update sources.

## Table of Contents

- [Overview](#overview)
- [Quick Start Tutorial](#quick-start-tutorial)
- [Plugin Architecture](#plugin-architecture)
- [API Reference](#api-reference)
- [Advanced Topics](#advanced-topics)
- [Testing Plugins](#testing-plugins)
- [Publishing Plugins](#publishing-plugins)

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

### Step 1: Create the Plugin Class

Create a new file `plugins/plugins/mypkg.py`:

```python
"""MyPkg package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

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

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the update commands.

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
        """Count updated packages from command output.

        Args:
            output: The combined command output.

        Returns:
            Number of packages that were updated.
        """
        # Look for patterns like "Upgraded: package-name"
        return len(re.findall(r"^Upgraded:\s+", output, re.MULTILINE))
```

### Step 2: Register the Plugin

Add your plugin to `plugins/plugins/__init__.py`:

```python
from plugins.mypkg import MyPkgPlugin

# Add to __all__
__all__ = [
    # ... existing plugins ...
    "MyPkgPlugin",
]

def register_builtin_plugins(registry: PluginRegistry | None = None) -> PluginRegistry:
    # ... existing registrations ...
    registry.register(MyPkgPlugin)
    return registry
```

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
│   ├── flatpak.py       # Flatpak plugin
│   ├── pipx.py          # pipx plugin
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

### Required Methods

#### `_execute_update(config: PluginConfig) -> tuple[str, str | None]`

The main update logic. Must be implemented by all plugins.

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

## Getting Help

- Check existing plugins in `plugins/plugins/` for examples
- Review the [implementation plan](update-all-python-plan.md) for architecture details
- Open an issue on GitHub for questions
