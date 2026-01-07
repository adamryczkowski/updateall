# Sudo Declaration Implementation Plan

**Date:** January 7, 2026
**Status:** Draft
**Proposal:** Proposal 5 - Sudo Declaration
**Author:** Implementation Team

## Executive Summary

This document provides a detailed implementation plan for Proposal 5 (Sudo Declaration) from the Update Plugins API Rewrite proposal. The goal is to add a standardized way for plugins to declare their sudo requirements upfront, enabling:

1. Automatic sudoers file generation
2. Pre-checking sudo availability before execution
3. Prompting for password once at start
4. Clear documentation of privilege requirements

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Proposed API](#proposed-api)
3. [Implementation Phases](#implementation-phases)
4. [Test-Driven Development Approach](#test-driven-development-approach)
5. [Test Cases](#test-cases)
6. [Plugin Migration Plan](#plugin-migration-plan)
7. [Documentation Updates](#documentation-updates)
8. [Risk Analysis](#risk-analysis)
9. [Timeline](#timeline)

---

## Current State Analysis

### How Sudo is Currently Handled

Currently, sudo handling is scattered across the codebase:

1. **In `BasePlugin._run_command()`** ([`plugins/plugins/base.py:319`](../plugins/plugins/base.py:319)):
   - The `sudo` parameter prepends `sudo` to commands
   - No upfront declaration of which commands need sudo

2. **In `UpdateCommand` dataclass** ([`core/core/models.py`](../core/core/models.py)):
   - Each command has a `sudo: bool` field
   - Sudo requirements are embedded in command definitions

3. **In individual plugins**:
   - Each plugin decides per-command whether to use sudo
   - No central registry of sudo requirements

4. **In `ui/ui/sudo.py`** ([`ui/ui/sudo.py`](../ui/ui/sudo.py)):
   - `SudoKeepAlive` class keeps sudo credentials alive
   - `check_sudo_status()` checks if sudo is cached
   - `ensure_sudo_authenticated()` prompts for password

### Current Plugin Sudo Usage

| Plugin | Sudo Usage | Commands Requiring Sudo |
|--------|------------|-------------------------|
| `apt.py` | Yes | `apt update`, `apt upgrade` |
| `snap.py` | Yes | `snap refresh` |
| `texlive_self.py` | Yes | `tlmgr update --self` |
| `texlive_packages.py` | Yes | `tlmgr update --all` |
| `calibre.py` | Yes | `sh /tmp/calibre-installer.sh` |
| `waterfox.py` | Yes | `rm`, `mv`, `chown` for installation |
| `flatpak.py` | No | User-level flatpak |
| `pipx.py` | No | User-level pipx |
| `cargo.py` | No | User-level cargo |
| `rustup.py` | No | User-level rustup |
| `pihole.py` | No | pihole handles sudo internally |
| `go_runtime.py` | No | User-level installation |
| `lxc.py` | No | Uses SSH, not local sudo |

### Problems with Current Approach

1. **No upfront knowledge**: Cannot determine sudo requirements before execution
2. **Cannot generate sudoers**: No list of commands that need passwordless sudo
3. **Multiple password prompts**: Each sudo command may prompt separately
4. **No pre-validation**: Cannot check if user has sudo access before starting

---

## Proposed API

### New Properties in `BasePlugin`

```python
class BasePlugin(UpdatePlugin):
    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        Used to:
        1. Generate sudoers file entries
        2. Pre-check sudo availability
        3. Prompt for password once at start

        Returns:
            List of command paths (e.g., ["/usr/bin/apt", "/usr/bin/snap"])
        """
        return []

    @property
    def requires_sudo(self) -> bool:
        """Check if any commands require sudo.

        Returns:
            True if sudo_commands is non-empty.
        """
        return len(self.sudo_commands) > 0
```

### New Data Models

```python
@dataclass(frozen=True)
class SudoRequirement:
    """Sudo requirement for a plugin."""

    plugin_name: str
    commands: list[str]  # Full paths to commands requiring sudo
    reason: str = ""  # Optional explanation

@dataclass
class SudoersEntry:
    """Entry for sudoers file generation."""

    user: str
    host: str = "ALL"
    runas: str = "ALL"
    commands: list[str] = field(default_factory=list)
    nopasswd: bool = True

    def to_sudoers_line(self) -> str:
        """Generate sudoers file line."""
        tag = "NOPASSWD: " if self.nopasswd else ""
        cmds = ", ".join(self.commands)
        return f"{self.user} {self.host}=({self.runas}) {tag}{cmds}"
```

### New Utility Functions

```python
# In core/core/sudo.py (new file)

async def collect_sudo_requirements(
    plugins: list[UpdatePlugin],
) -> list[SudoRequirement]:
    """Collect sudo requirements from all plugins.

    Args:
        plugins: List of plugins to check.

    Returns:
        List of SudoRequirement objects for plugins that need sudo.
    """
    ...

def generate_sudoers_entries(
    requirements: list[SudoRequirement],
    user: str,
) -> list[SudoersEntry]:
    """Generate sudoers entries for the given requirements.

    Args:
        requirements: Sudo requirements from plugins.
        user: Username for sudoers entries.

    Returns:
        List of SudoersEntry objects.
    """
    ...

async def validate_sudo_access(
    requirements: list[SudoRequirement],
) -> dict[str, bool]:
    """Validate that the user has sudo access for all required commands.

    Args:
        requirements: Sudo requirements to validate.

    Returns:
        Dict mapping plugin names to whether sudo access is available.
    """
    ...
```

---

## Implementation Phases

### Phase 1: Core API (Non-Breaking)

**Goal:** Add the new `sudo_commands` property to `BasePlugin` without breaking existing plugins.

**Tasks:**

1. Add `sudo_commands` property with default empty list
2. Add `requires_sudo` computed property
3. Add `SudoRequirement` and `SudoersEntry` dataclasses
4. Create `core/core/sudo.py` with utility functions
5. Add comprehensive tests

**Files to modify:**
- `plugins/plugins/base.py` - Add properties
- `core/core/models.py` - Add dataclasses
- `core/core/sudo.py` - New file with utilities
- `core/tests/test_sudo.py` - New test file

### Phase 2: Integration with Existing Infrastructure

**Goal:** Integrate sudo declaration with existing sudo handling in UI.

**Tasks:**

1. Update `ui/ui/sudo.py` to use plugin sudo declarations
2. Add pre-execution sudo validation
3. Add sudoers file generation command
4. Update orchestrator to check sudo requirements

**Files to modify:**
- `ui/ui/sudo.py` - Integrate with plugin declarations
- `core/core/orchestrator.py` - Add sudo pre-check
- `cli/cli/main.py` - Add sudoers generation command

### Phase 3: Plugin Migration

**Goal:** Migrate all eligible plugins to use the new sudo declaration API.

**Tasks:**

1. Migrate plugins that use sudo (apt, snap, texlive, calibre, waterfox)
2. Update tests for migrated plugins
3. Add deprecation warnings for plugins not using the new API

**Files to modify:**
- `plugins/plugins/apt.py`
- `plugins/plugins/snap.py`
- `plugins/plugins/texlive_self.py`
- `plugins/plugins/texlive_packages.py`
- `plugins/plugins/calibre.py`
- `plugins/plugins/waterfox.py`

### Phase 4: Documentation and Cleanup

**Goal:** Update documentation and finalize the implementation.

**Tasks:**

1. Update `docs/plugin-development.md` with sudo declaration guide
2. Add examples to example plugins
3. Update external plugin protocol documentation
4. Add migration guide for existing plugins

**Files to modify:**
- `docs/plugin-development.md`
- `examples/plugins/example-bash-plugin.sh`
- `examples/plugins/example-python-plugin.py`
- `docs/external-plugin-streaming-protocol.md`

---

## Test-Driven Development Approach

Following TDD principles, tests will be written before implementation. The test structure follows the existing project conventions.

### Test File Structure

```
core/tests/
├── test_sudo.py              # New: Core sudo utilities
├── test_sudo_integration.py  # New: Integration tests

plugins/tests/
├── test_sudo_declaration.py  # New: Plugin sudo declaration tests
├── test_plugins.py           # Update: Add sudo property tests

ui/tests/
├── test_sudo.py              # Update: Add integration tests
```

### Test Categories

1. **Unit Tests**: Test individual functions in isolation
2. **Integration Tests**: Test interaction between components
3. **Plugin Tests**: Test sudo declaration in plugins
4. **CLI Tests**: Test sudoers generation command

---

## Test Cases

### Unit Tests for `core/core/sudo.py`

```python
# core/tests/test_sudo.py

class TestSudoRequirement:
    """Tests for SudoRequirement dataclass."""

    def test_create_sudo_requirement(self) -> None:
        """Test creating a SudoRequirement."""
        req = SudoRequirement(
            plugin_name="apt",
            commands=["/usr/bin/apt"],
            reason="Package management",
        )
        assert req.plugin_name == "apt"
        assert req.commands == ["/usr/bin/apt"]
        assert req.reason == "Package management"

    def test_sudo_requirement_immutable(self) -> None:
        """Test that SudoRequirement is immutable (frozen)."""
        req = SudoRequirement(plugin_name="apt", commands=["/usr/bin/apt"])
        with pytest.raises(FrozenInstanceError):
            req.plugin_name = "snap"

    def test_sudo_requirement_empty_commands(self) -> None:
        """Test SudoRequirement with empty commands list."""
        req = SudoRequirement(plugin_name="test", commands=[])
        assert req.commands == []


class TestSudoersEntry:
    """Tests for SudoersEntry dataclass."""

    def test_to_sudoers_line_nopasswd(self) -> None:
        """Test generating sudoers line with NOPASSWD."""
        entry = SudoersEntry(
            user="adam",
            commands=["/usr/bin/apt", "/usr/bin/snap"],
            nopasswd=True,
        )
        line = entry.to_sudoers_line()
        assert line == "adam ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/snap"

    def test_to_sudoers_line_with_password(self) -> None:
        """Test generating sudoers line without NOPASSWD."""
        entry = SudoersEntry(
            user="adam",
            commands=["/usr/bin/apt"],
            nopasswd=False,
        )
        line = entry.to_sudoers_line()
        assert line == "adam ALL=(ALL) /usr/bin/apt"

    def test_to_sudoers_line_custom_host(self) -> None:
        """Test generating sudoers line with custom host."""
        entry = SudoersEntry(
            user="adam",
            host="localhost",
            commands=["/usr/bin/apt"],
        )
        line = entry.to_sudoers_line()
        assert "localhost" in line

    def test_to_sudoers_line_custom_runas(self) -> None:
        """Test generating sudoers line with custom runas."""
        entry = SudoersEntry(
            user="adam",
            runas="root",
            commands=["/usr/bin/apt"],
        )
        line = entry.to_sudoers_line()
        assert "(root)" in line


class TestCollectSudoRequirements:
    """Tests for collect_sudo_requirements function."""

    @pytest.mark.asyncio
    async def test_collect_from_plugins_with_sudo(self) -> None:
        """Test collecting requirements from plugins that need sudo."""
        # Create mock plugins
        plugin1 = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])
        plugin2 = MockPlugin(name="snap", sudo_commands=["/usr/bin/snap"])

        requirements = await collect_sudo_requirements([plugin1, plugin2])

        assert len(requirements) == 2
        assert requirements[0].plugin_name == "apt"
        assert requirements[1].plugin_name == "snap"

    @pytest.mark.asyncio
    async def test_collect_from_plugins_without_sudo(self) -> None:
        """Test collecting requirements from plugins that don't need sudo."""
        plugin = MockPlugin(name="pipx", sudo_commands=[])

        requirements = await collect_sudo_requirements([plugin])

        assert len(requirements) == 0

    @pytest.mark.asyncio
    async def test_collect_mixed_plugins(self) -> None:
        """Test collecting requirements from mixed plugins."""
        plugin1 = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])
        plugin2 = MockPlugin(name="pipx", sudo_commands=[])
        plugin3 = MockPlugin(name="snap", sudo_commands=["/usr/bin/snap"])

        requirements = await collect_sudo_requirements([plugin1, plugin2, plugin3])

        assert len(requirements) == 2
        plugin_names = [r.plugin_name for r in requirements]
        assert "apt" in plugin_names
        assert "snap" in plugin_names
        assert "pipx" not in plugin_names


class TestGenerateSudoersEntries:
    """Tests for generate_sudoers_entries function."""

    def test_generate_single_plugin(self) -> None:
        """Test generating sudoers for single plugin."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=["/usr/bin/apt"]),
        ]

        entries = generate_sudoers_entries(requirements, user="adam")

        assert len(entries) == 1
        assert entries[0].user == "adam"
        assert "/usr/bin/apt" in entries[0].commands

    def test_generate_multiple_plugins(self) -> None:
        """Test generating sudoers for multiple plugins."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=["/usr/bin/apt"]),
            SudoRequirement(plugin_name="snap", commands=["/usr/bin/snap"]),
        ]

        entries = generate_sudoers_entries(requirements, user="adam")

        # Should consolidate into single entry or multiple
        all_commands = []
        for entry in entries:
            all_commands.extend(entry.commands)
        assert "/usr/bin/apt" in all_commands
        assert "/usr/bin/snap" in all_commands

    def test_generate_deduplicates_commands(self) -> None:
        """Test that duplicate commands are deduplicated."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=["/usr/bin/apt"]),
            SudoRequirement(plugin_name="apt-extra", commands=["/usr/bin/apt"]),
        ]

        entries = generate_sudoers_entries(requirements, user="adam")

        all_commands = []
        for entry in entries:
            all_commands.extend(entry.commands)
        assert all_commands.count("/usr/bin/apt") == 1


class TestValidateSudoAccess:
    """Tests for validate_sudo_access function."""

    @pytest.mark.asyncio
    async def test_validate_with_cached_credentials(self) -> None:
        """Test validation when sudo credentials are cached."""
        # This test requires mocking subprocess
        requirements = [
            SudoRequirement(plugin_name="apt", commands=["/usr/bin/apt"]),
        ]

        # Mock sudo -l to return success
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_process

            result = await validate_sudo_access(requirements)

            assert result["apt"] is True

    @pytest.mark.asyncio
    async def test_validate_without_sudo_access(self) -> None:
        """Test validation when sudo access is denied."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=["/usr/bin/apt"]),
        ]

        # Mock sudo -l to return failure
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"not allowed")
            mock_exec.return_value = mock_process

            result = await validate_sudo_access(requirements)

            assert result["apt"] is False
```

### Unit Tests for `BasePlugin` Sudo Properties

```python
# plugins/tests/test_sudo_declaration.py

class TestBasePluginSudoProperties:
    """Tests for BasePlugin sudo declaration properties."""

    def test_sudo_commands_default_empty(self) -> None:
        """Test that sudo_commands defaults to empty list."""
        plugin = MinimalPlugin()
        assert plugin.sudo_commands == []

    def test_requires_sudo_false_when_no_commands(self) -> None:
        """Test requires_sudo is False when sudo_commands is empty."""
        plugin = MinimalPlugin()
        assert plugin.requires_sudo is False

    def test_requires_sudo_true_when_has_commands(self) -> None:
        """Test requires_sudo is True when sudo_commands is non-empty."""
        plugin = SudoPlugin()  # Plugin with sudo_commands
        assert plugin.requires_sudo is True

    def test_sudo_commands_returns_list(self) -> None:
        """Test that sudo_commands always returns a list."""
        plugin = MinimalPlugin()
        result = plugin.sudo_commands
        assert isinstance(result, list)


class TestAptPluginSudoDeclaration:
    """Tests for AptPlugin sudo declaration."""

    def test_apt_requires_sudo(self) -> None:
        """Test that AptPlugin requires sudo."""
        plugin = AptPlugin()
        assert plugin.requires_sudo is True

    def test_apt_sudo_commands_includes_apt(self) -> None:
        """Test that AptPlugin declares apt command."""
        plugin = AptPlugin()
        assert "/usr/bin/apt" in plugin.sudo_commands or "apt" in plugin.sudo_commands

    def test_apt_sudo_commands_is_list(self) -> None:
        """Test that AptPlugin.sudo_commands is a list."""
        plugin = AptPlugin()
        assert isinstance(plugin.sudo_commands, list)


class TestSnapPluginSudoDeclaration:
    """Tests for SnapPlugin sudo declaration."""

    def test_snap_requires_sudo(self) -> None:
        """Test that SnapPlugin requires sudo."""
        plugin = SnapPlugin()
        assert plugin.requires_sudo is True

    def test_snap_sudo_commands_includes_snap(self) -> None:
        """Test that SnapPlugin declares snap command."""
        plugin = SnapPlugin()
        assert "/usr/bin/snap" in plugin.sudo_commands or "snap" in plugin.sudo_commands


class TestPipxPluginSudoDeclaration:
    """Tests for PipxPlugin sudo declaration (no sudo needed)."""

    def test_pipx_does_not_require_sudo(self) -> None:
        """Test that PipxPlugin does not require sudo."""
        plugin = PipxPlugin()
        assert plugin.requires_sudo is False

    def test_pipx_sudo_commands_empty(self) -> None:
        """Test that PipxPlugin has empty sudo_commands."""
        plugin = PipxPlugin()
        assert plugin.sudo_commands == []


class TestWaterfoxPluginSudoDeclaration:
    """Tests for WaterfoxPlugin sudo declaration."""

    def test_waterfox_requires_sudo(self) -> None:
        """Test that WaterfoxPlugin requires sudo."""
        plugin = WaterfoxPlugin()
        assert plugin.requires_sudo is True

    def test_waterfox_sudo_commands_includes_install_commands(self) -> None:
        """Test that WaterfoxPlugin declares installation commands."""
        plugin = WaterfoxPlugin()
        # Should include rm, mv, chown for installation
        sudo_cmds = plugin.sudo_commands
        assert len(sudo_cmds) > 0
```

### Integration Tests

```python
# core/tests/test_sudo_integration.py

class TestSudoIntegration:
    """Integration tests for sudo declaration system."""

    @pytest.mark.asyncio
    async def test_orchestrator_checks_sudo_before_execution(self) -> None:
        """Test that orchestrator validates sudo before running plugins."""
        # Create plugins with sudo requirements
        plugins = [AptPlugin(), PipxPlugin()]

        # Mock sudo validation
        with patch("core.sudo.validate_sudo_access") as mock_validate:
            mock_validate.return_value = {"apt": True}

            # Run orchestrator
            orchestrator = Orchestrator(plugins)
            await orchestrator.pre_execute_checks()

            # Verify sudo was validated
            mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_sudo_keepalive_started_for_sudo_plugins(self) -> None:
        """Test that SudoKeepAlive is started when sudo plugins are present."""
        plugins = [AptPlugin()]

        with patch("ui.sudo.SudoKeepAlive") as mock_keepalive:
            mock_instance = AsyncMock()
            mock_keepalive.return_value = mock_instance

            # Run with sudo plugins
            runner = PluginRunner(plugins)
            await runner.run()

            # Verify keepalive was started
            mock_instance.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_sudo_keepalive_for_non_sudo_plugins(self) -> None:
        """Test that SudoKeepAlive is not started when no sudo is needed."""
        plugins = [PipxPlugin(), CargoPlugin()]

        with patch("ui.sudo.SudoKeepAlive") as mock_keepalive:
            runner = PluginRunner(plugins)
            await runner.run()

            # Verify keepalive was not started
            mock_keepalive.assert_not_called()


class TestSudoersGeneration:
    """Integration tests for sudoers file generation."""

    def test_generate_sudoers_file_content(self) -> None:
        """Test generating complete sudoers file content."""
        plugins = [AptPlugin(), SnapPlugin()]

        content = generate_sudoers_file(plugins, user="adam")

        assert "adam" in content
        assert "NOPASSWD" in content
        assert "apt" in content.lower()
        assert "snap" in content.lower()

    def test_sudoers_file_has_header_comment(self) -> None:
        """Test that generated sudoers file has header comment."""
        plugins = [AptPlugin()]

        content = generate_sudoers_file(plugins, user="adam")

        assert "# Generated by update-all" in content
        assert "# Do not edit manually" in content

    def test_sudoers_file_valid_syntax(self) -> None:
        """Test that generated sudoers file has valid syntax."""
        plugins = [AptPlugin(), SnapPlugin()]

        content = generate_sudoers_file(plugins, user="adam")

        # Each non-comment line should match sudoers format
        for line in content.split("\n"):
            if line.strip() and not line.startswith("#"):
                # Basic format check: user host=(runas) commands
                assert "=" in line
                assert "(" in line
                assert ")" in line
```

### CLI Tests

```python
# cli/tests/test_sudoers_command.py

class TestSudoersCommand:
    """Tests for sudoers generation CLI command."""

    def test_sudoers_command_generates_output(self) -> None:
        """Test that sudoers command generates output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sudoers", "generate"])

        assert result.exit_code == 0
        assert "NOPASSWD" in result.output

    def test_sudoers_command_with_user_option(self) -> None:
        """Test sudoers command with custom user."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sudoers", "generate", "--user", "testuser"])

        assert result.exit_code == 0
        assert "testuser" in result.output

    def test_sudoers_command_with_output_file(self) -> None:
        """Test sudoers command with output file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            runner = CliRunner()
            result = runner.invoke(cli, ["sudoers", "generate", "--output", f.name])

            assert result.exit_code == 0
            content = Path(f.name).read_text()
            assert "NOPASSWD" in content

    def test_sudoers_validate_command(self) -> None:
        """Test sudoers validate command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sudoers", "validate"])

        assert result.exit_code in (0, 1)  # 0 if valid, 1 if not

    def test_sudoers_list_command(self) -> None:
        """Test listing plugins that require sudo."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sudoers", "list"])

        assert result.exit_code == 0
        assert "apt" in result.output.lower()
```

### External Plugin Tests

```python
# plugins/tests/test_external_plugin_sudo.py

class TestExternalPluginSudo:
    """Tests for external plugin sudo declaration."""

    def test_external_plugin_does_require_sudo(self) -> None:
        """Test external plugin that requires sudo."""
        # Create a mock external plugin script
        script = """#!/bin/bash
        case "$1" in
            does-require-sudo)
                exit 0  # Yes, requires sudo
                ;;
            sudo-programs-paths)
                echo "/usr/bin/apt"
                echo "/usr/bin/dpkg"
                exit 0
                ;;
        esac
        """

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            f.flush()
            os.chmod(f.name, 0o755)

            plugin = ExternalPlugin(f.name)
            assert plugin.requires_sudo is True
            assert "/usr/bin/apt" in plugin.sudo_commands

    def test_external_plugin_does_not_require_sudo(self) -> None:
        """Test external plugin that does not require sudo."""
        script = """#!/bin/bash
        case "$1" in
            does-require-sudo)
                exit 1  # No, does not require sudo
                ;;
        esac
        """

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            f.flush()
            os.chmod(f.name, 0o755)

            plugin = ExternalPlugin(f.name)
            assert plugin.requires_sudo is False
```

---

## Plugin Migration Plan

### Migration Order

Plugins will be migrated in order of complexity and sudo usage:

1. **Simple sudo plugins** (single command):
   - `snap.py` - Only uses `snap refresh`
   - `texlive_self.py` - Only uses `tlmgr update --self`
   - `texlive_packages.py` - Only uses `tlmgr update --all`

2. **Multi-command sudo plugins**:
   - `apt.py` - Uses `apt update` and `apt upgrade`

3. **Complex sudo plugins** (installation commands):
   - `calibre.py` - Uses installer script with sudo
   - `waterfox.py` - Uses `rm`, `mv`, `chown` for installation

4. **Non-sudo plugins** (verification only):
   - `pipx.py`, `flatpak.py`, `cargo.py`, `rustup.py`, etc.

### Migration Template

For each plugin, the migration involves:

```python
# Before (current state)
class AptPlugin(BasePlugin):
    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        return [
            UpdateCommand(
                cmd=["apt", "update"],
                sudo=True,  # Sudo specified per-command
                ...
            ),
        ]

# After (with sudo declaration)
class AptPlugin(BasePlugin):
    @property
    def sudo_commands(self) -> list[str]:
        """Commands that require sudo for APT updates."""
        return ["/usr/bin/apt"]

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        return [
            UpdateCommand(
                cmd=["apt", "update"],
                sudo=True,  # Still needed for execution
                ...
            ),
        ]
```

### Specific Plugin Migrations

#### `apt.py`

```python
@property
def sudo_commands(self) -> list[str]:
    """Commands that require sudo for APT updates."""
    return ["/usr/bin/apt"]
```

#### `snap.py`

```python
@property
def sudo_commands(self) -> list[str]:
    """Commands that require sudo for Snap updates."""
    return ["/usr/bin/snap"]
```

#### `texlive_self.py` and `texlive_packages.py`

```python
@property
def sudo_commands(self) -> list[str]:
    """Commands that require sudo for TeX Live updates."""
    import shutil
    tlmgr_path = shutil.which("tlmgr")
    return [tlmgr_path] if tlmgr_path else ["/usr/bin/tlmgr"]
```

#### `calibre.py`

```python
@property
def sudo_commands(self) -> list[str]:
    """Commands that require sudo for Calibre installation."""
    return ["/bin/sh"]  # Installer script runs with sudo
```

#### `waterfox.py`

```python
@property
def sudo_commands(self) -> list[str]:
    """Commands that require sudo for Waterfox installation."""
    return ["/bin/rm", "/bin/mv", "/bin/chown"]
```

---

## Documentation Updates

### Updates to `docs/plugin-development.md`

Add a new section "Sudo Declaration" after "Plugins Requiring Sudo":

```markdown
### Sudo Declaration

Plugins that require sudo privileges should declare their requirements upfront
using the `sudo_commands` property. This enables:

1. **Sudoers file generation** — Automatically generate passwordless sudo entries
2. **Pre-execution validation** — Check sudo access before starting updates
3. **Single password prompt** — Prompt for password once at the start
4. **Clear documentation** — Document privilege requirements

#### Declaring Sudo Requirements

Override the `sudo_commands` property to return a list of command paths:

```python
class MyPlugin(BasePlugin):
    @property
    def sudo_commands(self) -> list[str]:
        """Commands that require sudo.

        Returns:
            List of full paths to commands requiring sudo.
        """
        return ["/usr/bin/apt", "/usr/bin/dpkg"]
```

#### Best Practices

1. **Use full paths** — Always use full paths (e.g., `/usr/bin/apt` not `apt`)
2. **Minimal privileges** — Only declare commands that actually need sudo
3. **Document reasons** — Add comments explaining why sudo is needed

#### Checking Sudo Requirements

Use the `requires_sudo` property to check if a plugin needs sudo:

```python
plugin = AptPlugin()
if plugin.requires_sudo:
    print(f"Plugin requires sudo for: {plugin.sudo_commands}")
```

#### Generating Sudoers Entries

Use the CLI to generate sudoers entries for all plugins:

```bash
# Generate sudoers entries
update-all sudoers generate

# Generate for specific user
update-all sudoers generate --user myuser

# Write to file
update-all sudoers generate --output /etc/sudoers.d/update-all
```

#### Example: Complete Plugin with Sudo

```python
class MyPackageManagerPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "mypkg"

    @property
    def command(self) -> str:
        return "mypkg"

    @property
    def sudo_commands(self) -> list[str]:
        """Commands requiring sudo for package management."""
        return ["/usr/bin/mypkg"]

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [UpdateCommand(cmd=["mypkg", "check"], sudo=False)]
        return [
            UpdateCommand(
                cmd=["mypkg", "update"],
                sudo=True,
                description="Update packages",
            ),
        ]
```
```

### Updates to External Plugin Protocol

Add to `docs/external-plugin-streaming-protocol.md`:

```markdown
### Sudo Declaration Commands

External plugins can declare sudo requirements using these commands:

#### `does-require-sudo`

Check if the plugin requires sudo privileges.

```bash
./my-plugin.sh does-require-sudo
# Exit 0 = requires sudo
# Exit 1 = does not require sudo
```

#### `sudo-programs-paths`

Return full paths of programs that need sudo, one per line.

```bash
./my-plugin.sh sudo-programs-paths
# Output:
# /usr/bin/apt
# /usr/bin/dpkg
# Exit 0 = success
# Exit 1 = error
```

#### Example Implementation

```bash
#!/bin/bash

case "$1" in
    does-require-sudo)
        exit 0  # Yes, we need sudo
        ;;
    sudo-programs-paths)
        echo "/usr/bin/apt"
        echo "/usr/bin/dpkg"
        exit 0
        ;;
    # ... other commands ...
esac
```
```

---

## Risk Analysis

### Risk 1: Breaking Existing Plugins

**Risk:** Adding new required properties could break existing plugins.

**Mitigation:**
- `sudo_commands` returns empty list by default
- `requires_sudo` is computed from `sudo_commands`
- No changes to existing plugin behavior

### Risk 2: Incorrect Sudo Declarations

**Risk:** Plugins may declare incorrect sudo requirements.

**Mitigation:**
- Validation function to check declared commands exist
- Warning if declared command doesn't match actual usage
- Integration tests verify declarations match behavior

### Risk 3: Security Concerns with Sudoers Generation

**Risk:** Generated sudoers entries could be insecure.

**Mitigation:**
- Only generate NOPASSWD for specific commands, not ALL
- Validate command paths are absolute
- Add security warnings in documentation
- Require explicit user confirmation for sudoers changes

### Risk 4: Path Differences Across Systems

**Risk:** Command paths may differ across Linux distributions.

**Mitigation:**
- Use `shutil.which()` to find actual command paths
- Support both hardcoded and dynamic path resolution
- Document path requirements

---

## Timeline

### Week 1: Phase 1 - Core API

- Day 1-2: Write tests for `SudoRequirement`, `SudoersEntry`
- Day 3-4: Implement dataclasses and utility functions
- Day 5: Write tests for `BasePlugin` sudo properties

### Week 2: Phase 2 - Integration

- Day 1-2: Write integration tests
- Day 3-4: Integrate with orchestrator and UI
- Day 5: Add CLI commands

### Week 3: Phase 3 - Plugin Migration

- Day 1-2: Migrate simple plugins (snap, texlive)
- Day 3-4: Migrate complex plugins (apt, calibre, waterfox)
- Day 5: Update plugin tests

### Week 4: Phase 4 - Documentation

- Day 1-2: Update plugin-development.md
- Day 3: Update external plugin protocol
- Day 4-5: Final testing and review

---

## Appendix: File Changes Summary

### New Files

| File | Description |
|------|-------------|
| `core/core/sudo.py` | Sudo utilities (collect, generate, validate) |
| `core/tests/test_sudo.py` | Unit tests for sudo utilities |
| `core/tests/test_sudo_integration.py` | Integration tests |
| `plugins/tests/test_sudo_declaration.py` | Plugin sudo declaration tests |
| `cli/tests/test_sudoers_command.py` | CLI command tests |

### Modified Files

| File | Changes |
|------|---------|
| `plugins/plugins/base.py` | Add `sudo_commands`, `requires_sudo` properties |
| `plugins/plugins/apt.py` | Add `sudo_commands` property |
| `plugins/plugins/snap.py` | Add `sudo_commands` property |
| `plugins/plugins/texlive_self.py` | Add `sudo_commands` property |
| `plugins/plugins/texlive_packages.py` | Add `sudo_commands` property |
| `plugins/plugins/calibre.py` | Add `sudo_commands` property |
| `plugins/plugins/waterfox.py` | Add `sudo_commands` property |
| `core/core/models.py` | Add `SudoRequirement`, `SudoersEntry` |
| `core/core/orchestrator.py` | Add sudo pre-check |
| `ui/ui/sudo.py` | Integrate with plugin declarations |
| `cli/cli/main.py` | Add sudoers commands |
| `docs/plugin-development.md` | Add sudo declaration section |
| `docs/external-plugin-streaming-protocol.md` | Add sudo commands |

---

## Conclusion

This implementation plan provides a comprehensive approach to adding sudo declaration support to the Update-All plugin system. The TDD approach ensures that all functionality is thoroughly tested before implementation, and the phased rollout minimizes risk of breaking existing plugins.

Key benefits of this implementation:

1. **Backward compatible** — Existing plugins continue to work unchanged
2. **Opt-in adoption** — Plugins can migrate at their own pace
3. **Security focused** — Sudoers generation uses minimal privileges
4. **Well documented** — Clear guidance for plugin authors
5. **Thoroughly tested** — Comprehensive test coverage
