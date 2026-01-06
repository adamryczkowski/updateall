"""Tests for plugin implementations."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from plugins.apt import AptPlugin
from plugins.flatpak import FlatpakPlugin
from plugins.pipx import PipxPlugin


class TestAptPlugin:
    """Tests for AptPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = AptPlugin()
        assert plugin.name == "apt"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = AptPlugin()
        assert plugin.command == "apt"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = AptPlugin()
        assert "APT" in plugin.description or "apt" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when apt is present."""
        plugin = AptPlugin()
        with patch("shutil.which", return_value="/usr/bin/apt"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when apt is missing."""
        plugin = AptPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_count_updated_packages(self) -> None:
        """Test package counting from apt output."""
        plugin = AptPlugin()
        output = "5 upgraded, 2 newly installed, 0 to remove"
        count = plugin._count_updated_packages(output)
        assert count == 5

    def test_count_updated_packages_fallback(self) -> None:
        """Test package counting fallback using Unpacking lines."""
        plugin = AptPlugin()
        output = """
Unpacking package1 (1.0-1)
Unpacking package2 (2.0-1)
Unpacking package3 (3.0-1)
"""
        count = plugin._count_updated_packages(output)
        assert count == 3


class TestPipxPlugin:
    """Tests for PipxPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = PipxPlugin()
        assert plugin.name == "pipx"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = PipxPlugin()
        assert plugin.command == "pipx"

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when pipx is present."""
        plugin = PipxPlugin()
        with patch("shutil.which", return_value="/usr/local/bin/pipx"):
            result = await plugin.check_available()
        assert result is True

    def test_count_updated_packages(self) -> None:
        """Test package counting from pipx output."""
        plugin = PipxPlugin()
        output = """
upgraded black from 23.0.0 to 24.0.0
upgraded ruff from 0.1.0 to 0.2.0
"""
        count = plugin._count_updated_packages(output)
        assert count == 2


class TestFlatpakPlugin:
    """Tests for FlatpakPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = FlatpakPlugin()
        assert plugin.name == "flatpak"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = FlatpakPlugin()
        assert plugin.command == "flatpak"

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when flatpak is present."""
        plugin = FlatpakPlugin()
        with patch("shutil.which", return_value="/usr/bin/flatpak"):
            result = await plugin.check_available()
        assert result is True

    def test_count_updated_packages(self) -> None:
        """Test package counting from flatpak output."""
        plugin = FlatpakPlugin()
        output = """
Updating app/org.example.App1
Updating app/org.example.App2
"""
        count = plugin._count_updated_packages(output)
        assert count == 2

    def test_count_updated_packages_arrow(self) -> None:
        """Test package counting using arrow pattern."""
        plugin = FlatpakPlugin()
        output = """
org.example.App1 1.0 → 2.0
org.example.App2 3.0 → 4.0
org.example.App3 5.0 → 6.0
"""
        count = plugin._count_updated_packages(output)
        assert count == 3
