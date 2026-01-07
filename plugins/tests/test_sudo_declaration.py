"""Tests for plugin sudo declaration properties.

This module tests the sudo_commands and requires_sudo properties
added to BasePlugin as part of Proposal 5 (Sudo Declaration).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plugins.apt import AptPlugin
from plugins.base import BasePlugin
from plugins.calibre import CalibrePlugin
from plugins.cargo import CargoPlugin
from plugins.flatpak import FlatpakPlugin
from plugins.pipx import PipxPlugin
from plugins.rustup import RustupPlugin
from plugins.snap import SnapPlugin
from plugins.texlive_packages import TexlivePackagesPlugin
from plugins.texlive_self import TexliveSelfPlugin
from plugins.waterfox import WaterfoxPlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


# =============================================================================
# Mock Plugin for Testing Base Behavior
# =============================================================================


class MinimalPlugin(BasePlugin):
    """Minimal plugin for testing base behavior."""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def command(self) -> str:
        return "echo"

    async def _execute_update(self, _config: PluginConfig) -> tuple[str, str | None]:
        return "Updated", None


class SudoPlugin(BasePlugin):
    """Plugin with sudo commands for testing."""

    @property
    def name(self) -> str:
        return "sudo-test"

    @property
    def command(self) -> str:
        return "echo"

    @property
    def sudo_commands(self) -> list[str]:
        return ["/usr/bin/apt", "/usr/bin/dpkg"]

    async def _execute_update(self, _config: PluginConfig) -> tuple[str, str | None]:
        return "Updated", None


# =============================================================================
# Tests for BasePlugin Sudo Properties
# =============================================================================


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
        plugin = SudoPlugin()
        assert plugin.requires_sudo is True

    def test_sudo_commands_returns_list(self) -> None:
        """Test that sudo_commands always returns a list."""
        plugin = MinimalPlugin()
        result = plugin.sudo_commands
        assert isinstance(result, list)

    def test_sudo_commands_with_override(self) -> None:
        """Test that overridden sudo_commands returns correct values."""
        plugin = SudoPlugin()
        assert plugin.sudo_commands == ["/usr/bin/apt", "/usr/bin/dpkg"]

    def test_requires_sudo_computed_from_sudo_commands(self) -> None:
        """Test that requires_sudo is computed from sudo_commands."""
        plugin = SudoPlugin()
        # requires_sudo should be True because sudo_commands is non-empty
        assert plugin.requires_sudo is True
        assert len(plugin.sudo_commands) > 0


# =============================================================================
# Tests for Plugins Without Sudo (Verification)
# =============================================================================


class TestPluginsWithoutSudo:
    """Tests for plugins that should not require sudo."""

    def test_pipx_does_not_require_sudo(self) -> None:
        """Test that PipxPlugin does not require sudo."""
        plugin = PipxPlugin()
        assert plugin.requires_sudo is False

    def test_pipx_sudo_commands_empty(self) -> None:
        """Test that PipxPlugin has empty sudo_commands."""
        plugin = PipxPlugin()
        assert plugin.sudo_commands == []

    def test_flatpak_does_not_require_sudo(self) -> None:
        """Test that FlatpakPlugin does not require sudo."""
        plugin = FlatpakPlugin()
        assert plugin.requires_sudo is False

    def test_flatpak_sudo_commands_empty(self) -> None:
        """Test that FlatpakPlugin has empty sudo_commands."""
        plugin = FlatpakPlugin()
        assert plugin.sudo_commands == []

    def test_cargo_does_not_require_sudo(self) -> None:
        """Test that CargoPlugin does not require sudo."""
        plugin = CargoPlugin()
        assert plugin.requires_sudo is False

    def test_cargo_sudo_commands_empty(self) -> None:
        """Test that CargoPlugin has empty sudo_commands."""
        plugin = CargoPlugin()
        assert plugin.sudo_commands == []

    def test_rustup_does_not_require_sudo(self) -> None:
        """Test that RustupPlugin does not require sudo."""
        plugin = RustupPlugin()
        assert plugin.requires_sudo is False

    def test_rustup_sudo_commands_empty(self) -> None:
        """Test that RustupPlugin has empty sudo_commands."""
        plugin = RustupPlugin()
        assert plugin.sudo_commands == []


# =============================================================================
# Tests for Plugins With Sudo (After Migration)
# These tests will pass after the plugins are migrated
# =============================================================================


class TestAptPluginSudoDeclaration:
    """Tests for AptPlugin sudo declaration."""

    def test_apt_requires_sudo(self) -> None:
        """Test that AptPlugin requires sudo."""
        plugin = AptPlugin()
        assert plugin.requires_sudo is True

    def test_apt_sudo_commands_includes_apt(self) -> None:
        """Test that AptPlugin declares apt command."""
        plugin = AptPlugin()
        # Check for apt in any form (full path or command name)
        sudo_cmds = plugin.sudo_commands
        assert any("apt" in cmd for cmd in sudo_cmds)

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
        sudo_cmds = plugin.sudo_commands
        assert any("snap" in cmd for cmd in sudo_cmds)


class TestTexliveSelfPluginSudoDeclaration:
    """Tests for TexliveSelfPlugin sudo declaration."""

    def test_texlive_self_requires_sudo(self) -> None:
        """Test that TexliveSelfPlugin requires sudo."""
        plugin = TexliveSelfPlugin()
        assert plugin.requires_sudo is True

    def test_texlive_self_sudo_commands_includes_tlmgr(self) -> None:
        """Test that TexliveSelfPlugin declares tlmgr command."""
        plugin = TexliveSelfPlugin()
        sudo_cmds = plugin.sudo_commands
        assert any("tlmgr" in cmd for cmd in sudo_cmds)


class TestTexlivePackagesPluginSudoDeclaration:
    """Tests for TexlivePackagesPlugin sudo declaration."""

    def test_texlive_packages_requires_sudo(self) -> None:
        """Test that TexlivePackagesPlugin requires sudo."""
        plugin = TexlivePackagesPlugin()
        assert plugin.requires_sudo is True

    def test_texlive_packages_sudo_commands_includes_tlmgr(self) -> None:
        """Test that TexlivePackagesPlugin declares tlmgr command."""
        plugin = TexlivePackagesPlugin()
        sudo_cmds = plugin.sudo_commands
        assert any("tlmgr" in cmd for cmd in sudo_cmds)


class TestCalibrePluginSudoDeclaration:
    """Tests for CalibrePlugin sudo declaration."""

    def test_calibre_requires_sudo(self) -> None:
        """Test that CalibrePlugin requires sudo."""
        plugin = CalibrePlugin()
        assert plugin.requires_sudo is True

    def test_calibre_sudo_commands_not_empty(self) -> None:
        """Test that CalibrePlugin has non-empty sudo_commands."""
        plugin = CalibrePlugin()
        assert len(plugin.sudo_commands) > 0


class TestWaterfoxPluginSudoDeclaration:
    """Tests for WaterfoxPlugin sudo declaration."""

    def test_waterfox_requires_sudo(self) -> None:
        """Test that WaterfoxPlugin requires sudo."""
        plugin = WaterfoxPlugin()
        assert plugin.requires_sudo is True

    def test_waterfox_sudo_commands_includes_install_commands(self) -> None:
        """Test that WaterfoxPlugin declares installation commands."""
        plugin = WaterfoxPlugin()
        sudo_cmds = plugin.sudo_commands
        assert len(sudo_cmds) > 0
        # Should include commands like rm, mv, chown
        cmd_names = [cmd.split("/")[-1] for cmd in sudo_cmds]
        assert any(name in ["rm", "mv", "chown"] for name in cmd_names)
