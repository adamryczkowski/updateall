"""Tests for sudo declaration and management utilities.

This module tests the sudo utilities defined in core/core/sudo.py,
including SudoRequirement, SudoersEntry, and utility functions.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

import pytest

from core.sudo import (
    SudoersEntry,
    SudoRequirement,
    collect_sudo_requirements,
    generate_sudoers_entries,
    generate_sudoers_file,
    resolve_command_path,
    validate_command_paths,
    validate_sudo_access,
)

# =============================================================================
# Mock Plugin Classes for Testing
# =============================================================================


class MockPlugin:
    """Mock plugin for testing sudo requirements."""

    def __init__(
        self,
        name: str = "mock",
        sudo_commands: list[str] | None = None,
    ) -> None:
        self._name = name
        self._sudo_commands = sudo_commands or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def sudo_commands(self) -> list[str]:
        return self._sudo_commands


class MockPluginWithoutSudo:
    """Mock plugin without sudo_commands attribute."""

    def __init__(self, name: str = "no-sudo") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name


# =============================================================================
# Tests for SudoRequirement
# =============================================================================


class TestSudoRequirement:
    """Tests for SudoRequirement dataclass."""

    def test_create_sudo_requirement(self) -> None:
        """Test creating a SudoRequirement with all fields."""
        req = SudoRequirement(
            plugin_name="apt",
            commands=("/usr/bin/apt",),
            reason="Package management",
        )
        assert req.plugin_name == "apt"
        assert req.commands == ("/usr/bin/apt",)
        assert req.reason == "Package management"

    def test_create_sudo_requirement_minimal(self) -> None:
        """Test creating a SudoRequirement with minimal fields."""
        req = SudoRequirement(
            plugin_name="snap",
            commands=("/usr/bin/snap",),
        )
        assert req.plugin_name == "snap"
        assert req.commands == ("/usr/bin/snap",)
        assert req.reason == ""

    def test_sudo_requirement_immutable(self) -> None:
        """Test that SudoRequirement is immutable (frozen)."""
        req = SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",))
        with pytest.raises(FrozenInstanceError):
            req.plugin_name = "snap"  # type: ignore[misc]

    def test_sudo_requirement_empty_commands(self) -> None:
        """Test SudoRequirement with empty commands tuple."""
        req = SudoRequirement(plugin_name="test", commands=())
        assert req.commands == ()

    def test_sudo_requirement_multiple_commands(self) -> None:
        """Test SudoRequirement with multiple commands."""
        req = SudoRequirement(
            plugin_name="waterfox",
            commands=("/bin/rm", "/bin/mv", "/bin/chown"),
        )
        assert len(req.commands) == 3
        assert "/bin/rm" in req.commands
        assert "/bin/mv" in req.commands
        assert "/bin/chown" in req.commands

    def test_sudo_requirement_empty_plugin_name_raises(self) -> None:
        """Test that empty plugin_name raises ValueError."""
        with pytest.raises(ValueError, match="plugin_name cannot be empty"):
            SudoRequirement(plugin_name="", commands=("/usr/bin/apt",))

    def test_sudo_requirement_list_converted_to_tuple(self) -> None:
        """Test that list commands are converted to tuple."""
        req = SudoRequirement(
            plugin_name="apt",
            commands=["/usr/bin/apt", "/usr/bin/dpkg"],  # type: ignore[arg-type]
        )
        assert isinstance(req.commands, tuple)
        assert req.commands == ("/usr/bin/apt", "/usr/bin/dpkg")


# =============================================================================
# Tests for SudoersEntry
# =============================================================================


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
        assert "NOPASSWD" not in line

    def test_to_sudoers_line_custom_host(self) -> None:
        """Test generating sudoers line with custom host."""
        entry = SudoersEntry(
            user="adam",
            host="localhost",
            commands=["/usr/bin/apt"],
        )
        line = entry.to_sudoers_line()
        assert "localhost" in line
        assert line == "adam localhost=(ALL) NOPASSWD: /usr/bin/apt"

    def test_to_sudoers_line_custom_runas(self) -> None:
        """Test generating sudoers line with custom runas."""
        entry = SudoersEntry(
            user="adam",
            runas="root",
            commands=["/usr/bin/apt"],
        )
        line = entry.to_sudoers_line()
        assert "(root)" in line
        assert line == "adam ALL=(root) NOPASSWD: /usr/bin/apt"

    def test_to_sudoers_line_single_command(self) -> None:
        """Test generating sudoers line with single command."""
        entry = SudoersEntry(
            user="testuser",
            commands=["/usr/bin/apt"],
        )
        line = entry.to_sudoers_line()
        assert line == "testuser ALL=(ALL) NOPASSWD: /usr/bin/apt"

    def test_to_sudoers_line_empty_commands_raises(self) -> None:
        """Test that empty commands raises ValueError."""
        entry = SudoersEntry(user="adam", commands=[])
        with pytest.raises(ValueError, match="Cannot generate sudoers line without commands"):
            entry.to_sudoers_line()

    def test_sudoers_entry_default_values(self) -> None:
        """Test SudoersEntry default values."""
        entry = SudoersEntry(user="adam")
        assert entry.host == "ALL"
        assert entry.runas == "ALL"
        assert entry.commands == []
        assert entry.nopasswd is True
        assert entry.comment == ""

    def test_sudoers_entry_with_comment(self) -> None:
        """Test SudoersEntry with comment."""
        entry = SudoersEntry(
            user="adam",
            commands=["/usr/bin/apt"],
            comment="APT package manager",
        )
        assert entry.comment == "APT package manager"
        # Comment is not included in the line itself
        line = entry.to_sudoers_line()
        assert "APT package manager" not in line


# =============================================================================
# Tests for collect_sudo_requirements
# =============================================================================


class TestCollectSudoRequirements:
    """Tests for collect_sudo_requirements function."""

    @pytest.mark.asyncio
    async def test_collect_from_plugins_with_sudo(self) -> None:
        """Test collecting requirements from plugins that need sudo."""
        plugin1 = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])
        plugin2 = MockPlugin(name="snap", sudo_commands=["/usr/bin/snap"])

        requirements = await collect_sudo_requirements([plugin1, plugin2])

        assert len(requirements) == 2
        assert requirements[0].plugin_name == "apt"
        assert requirements[0].commands == ("/usr/bin/apt",)
        assert requirements[1].plugin_name == "snap"
        assert requirements[1].commands == ("/usr/bin/snap",)

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

    @pytest.mark.asyncio
    async def test_collect_empty_plugins_list(self) -> None:
        """Test collecting from empty plugins list."""
        requirements = await collect_sudo_requirements([])

        assert len(requirements) == 0

    @pytest.mark.asyncio
    async def test_collect_plugin_without_sudo_commands_attribute(self) -> None:
        """Test collecting from plugin without sudo_commands attribute."""
        plugin = MockPluginWithoutSudo(name="no-sudo")

        requirements = await collect_sudo_requirements([plugin])  # type: ignore[list-item]

        assert len(requirements) == 0

    @pytest.mark.asyncio
    async def test_collect_multiple_commands_per_plugin(self) -> None:
        """Test collecting plugin with multiple sudo commands."""
        plugin = MockPlugin(
            name="waterfox",
            sudo_commands=["/bin/rm", "/bin/mv", "/bin/chown"],
        )

        requirements = await collect_sudo_requirements([plugin])

        assert len(requirements) == 1
        assert requirements[0].plugin_name == "waterfox"
        assert len(requirements[0].commands) == 3


# =============================================================================
# Tests for generate_sudoers_entries
# =============================================================================


class TestGenerateSudoersEntries:
    """Tests for generate_sudoers_entries function."""

    def test_generate_single_plugin(self) -> None:
        """Test generating sudoers for single plugin."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
        ]

        entries = generate_sudoers_entries(requirements, user="adam")

        assert len(entries) == 1
        assert entries[0].user == "adam"
        assert "/usr/bin/apt" in entries[0].commands

    def test_generate_multiple_plugins_consolidated(self) -> None:
        """Test generating sudoers for multiple plugins (consolidated)."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
            SudoRequirement(plugin_name="snap", commands=("/usr/bin/snap",)),
        ]

        entries = generate_sudoers_entries(requirements, user="adam", consolidate=True)

        # Should consolidate into single entry
        assert len(entries) == 1
        assert "/usr/bin/apt" in entries[0].commands
        assert "/usr/bin/snap" in entries[0].commands

    def test_generate_multiple_plugins_not_consolidated(self) -> None:
        """Test generating sudoers for multiple plugins (not consolidated)."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
            SudoRequirement(plugin_name="snap", commands=("/usr/bin/snap",)),
        ]

        entries = generate_sudoers_entries(requirements, user="adam", consolidate=False)

        # Should create separate entries
        assert len(entries) == 2

    def test_generate_deduplicates_commands(self) -> None:
        """Test that duplicate commands are deduplicated."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
            SudoRequirement(plugin_name="apt-extra", commands=("/usr/bin/apt",)),
        ]

        entries = generate_sudoers_entries(requirements, user="adam", consolidate=True)

        assert len(entries) == 1
        # Should only have one /usr/bin/apt
        assert entries[0].commands.count("/usr/bin/apt") == 1

    def test_generate_empty_requirements(self) -> None:
        """Test generating sudoers for empty requirements."""
        entries = generate_sudoers_entries([], user="adam")

        assert len(entries) == 0

    def test_generate_uses_current_user_by_default(self) -> None:
        """Test that current user is used by default."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
        ]

        with patch("core.sudo.getpass.getuser", return_value="testuser"):
            entries = generate_sudoers_entries(requirements)

        assert len(entries) == 1
        assert entries[0].user == "testuser"

    def test_generate_sorts_commands(self) -> None:
        """Test that commands are sorted in consolidated output."""
        requirements = [
            SudoRequirement(plugin_name="z-plugin", commands=("/usr/bin/zzz",)),
            SudoRequirement(plugin_name="a-plugin", commands=("/usr/bin/aaa",)),
        ]

        entries = generate_sudoers_entries(requirements, user="adam", consolidate=True)

        assert entries[0].commands == ["/usr/bin/aaa", "/usr/bin/zzz"]


# =============================================================================
# Tests for validate_sudo_access
# =============================================================================


class TestValidateSudoAccess:
    """Tests for validate_sudo_access function."""

    @pytest.mark.asyncio
    async def test_validate_as_root(self) -> None:
        """Test validation when running as root."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
        ]

        with patch("os.geteuid", return_value=0):
            result = await validate_sudo_access(requirements)

        assert result["apt"] is True

    @pytest.mark.asyncio
    async def test_validate_sudo_not_available(self) -> None:
        """Test validation when sudo is not available."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
        ]

        with (
            patch("os.geteuid", return_value=1000),
            patch("shutil.which", return_value=None),
        ):
            result = await validate_sudo_access(requirements)

        assert result["apt"] is False

    @pytest.mark.asyncio
    async def test_validate_with_cached_credentials(self) -> None:
        """Test validation when sudo credentials are cached."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
        ]

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("os.geteuid", return_value=1000),
            patch("shutil.which", return_value="/usr/bin/sudo"),
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
        ):
            result = await validate_sudo_access(requirements)

        assert result["apt"] is True

    @pytest.mark.asyncio
    async def test_validate_without_sudo_access(self) -> None:
        """Test validation when sudo access is denied."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
        ]

        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"not allowed"))

        with (
            patch("os.geteuid", return_value=1000),
            patch("shutil.which", return_value="/usr/bin/sudo"),
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
        ):
            result = await validate_sudo_access(requirements)

        assert result["apt"] is False

    @pytest.mark.asyncio
    async def test_validate_multiple_plugins(self) -> None:
        """Test validation with multiple plugins."""
        requirements = [
            SudoRequirement(plugin_name="apt", commands=("/usr/bin/apt",)),
            SudoRequirement(plugin_name="snap", commands=("/usr/bin/snap",)),
        ]

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("os.geteuid", return_value=1000),
            patch("shutil.which", return_value="/usr/bin/sudo"),
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
        ):
            result = await validate_sudo_access(requirements)

        assert result["apt"] is True
        assert result["snap"] is True

    @pytest.mark.asyncio
    async def test_validate_empty_requirements(self) -> None:
        """Test validation with empty requirements."""
        result = await validate_sudo_access([])

        assert result == {}


# =============================================================================
# Tests for generate_sudoers_file
# =============================================================================


class TestGenerateSudoersFile:
    """Tests for generate_sudoers_file function."""

    def test_generate_sudoers_file_content(self) -> None:
        """Test generating complete sudoers file content."""
        plugin1 = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])
        plugin2 = MockPlugin(name="snap", sudo_commands=["/usr/bin/snap"])

        content = generate_sudoers_file([plugin1, plugin2], user="adam")

        assert "adam" in content
        assert "NOPASSWD" in content
        assert "/usr/bin/apt" in content
        assert "/usr/bin/snap" in content

    def test_sudoers_file_has_header_comment(self) -> None:
        """Test that generated sudoers file has header comment."""
        plugin = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])

        content = generate_sudoers_file([plugin], user="adam")

        assert "# Generated by update-all" in content
        assert "# Do not edit manually" in content

    def test_sudoers_file_without_header(self) -> None:
        """Test generating sudoers file without header."""
        plugin = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])

        content = generate_sudoers_file([plugin], user="adam", include_header=False)

        assert "# Generated by update-all" not in content
        assert "adam" in content

    def test_sudoers_file_no_plugins_with_sudo(self) -> None:
        """Test generating sudoers file when no plugins need sudo."""
        plugin = MockPlugin(name="pipx", sudo_commands=[])

        content = generate_sudoers_file([plugin], user="adam")

        assert "# No plugins require sudo" in content

    def test_sudoers_file_uses_current_user_by_default(self) -> None:
        """Test that current user is used by default."""
        plugin = MockPlugin(name="apt", sudo_commands=["/usr/bin/apt"])

        with patch("core.sudo.getpass.getuser", return_value="testuser"):
            content = generate_sudoers_file([plugin])

        assert "testuser" in content


# =============================================================================
# Tests for resolve_command_path
# =============================================================================


class TestResolveCommandPath:
    """Tests for resolve_command_path function."""

    def test_resolve_absolute_path_exists(self) -> None:
        """Test resolving absolute path that exists."""
        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("os.access", return_value=True),
        ):
            result = resolve_command_path("/usr/bin/apt")

        assert result == "/usr/bin/apt"

    def test_resolve_absolute_path_not_exists(self) -> None:
        """Test resolving absolute path that doesn't exist."""
        with patch("pathlib.Path.is_file", return_value=False):
            result = resolve_command_path("/usr/bin/nonexistent")

        assert result is None

    def test_resolve_command_name(self) -> None:
        """Test resolving command name using which."""
        with patch("shutil.which", return_value="/usr/bin/apt"):
            result = resolve_command_path("apt")

        assert result == "/usr/bin/apt"

    def test_resolve_command_name_not_found(self) -> None:
        """Test resolving command name that doesn't exist."""
        with patch("shutil.which", return_value=None):
            result = resolve_command_path("nonexistent")

        assert result is None


# =============================================================================
# Tests for validate_command_paths
# =============================================================================


class TestValidateCommandPaths:
    """Tests for validate_command_paths function."""

    def test_validate_all_found(self) -> None:
        """Test validating commands that all exist."""
        with patch("shutil.which", side_effect=["/usr/bin/apt", "/usr/bin/snap"]):
            result = validate_command_paths(["apt", "snap"])

        assert result["apt"] == "/usr/bin/apt"
        assert result["snap"] == "/usr/bin/snap"

    def test_validate_some_not_found(self) -> None:
        """Test validating commands where some don't exist."""
        with patch("shutil.which", side_effect=["/usr/bin/apt", None]):
            result = validate_command_paths(["apt", "nonexistent"])

        assert result["apt"] == "/usr/bin/apt"
        assert result["nonexistent"] is None

    def test_validate_empty_list(self) -> None:
        """Test validating empty command list."""
        result = validate_command_paths([])

        assert result == {}
