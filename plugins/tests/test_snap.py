"""Tests for Snap plugin with three-step upgrade support."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from plugins.snap import SnapPlugin
from plugins.snap_store import SnapDownloadInfo


class TestSnapPlugin:
    """Tests for SnapPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = SnapPlugin()
        assert plugin.name == "snap"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = SnapPlugin()
        assert plugin.command == "snap"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = SnapPlugin()
        assert "Snap" in plugin.description

    def test_supports_download(self) -> None:
        """Test that plugin supports download phase."""
        plugin = SnapPlugin()
        assert plugin.supports_download is True

    def test_sudo_commands(self) -> None:
        """Test sudo commands declaration."""
        plugin = SnapPlugin()
        assert "/usr/bin/snap" in plugin.sudo_commands

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when snap is present."""
        plugin = SnapPlugin()
        with patch("shutil.which", return_value="/usr/bin/snap"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when snap is missing."""
        plugin = SnapPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_count_updated_packages_refreshed(self) -> None:
        """Test package counting with 'refreshed' pattern."""
        plugin = SnapPlugin()
        output = """
firefox 120.0 from Mozilla refreshed
chromium 119.0 from Canonical refreshed
"""
        count = plugin._count_updated_packages(output)
        assert count == 2

    def test_count_updated_packages_arrow(self) -> None:
        """Test package counting with arrow pattern."""
        plugin = SnapPlugin()
        output = """
firefox (120.0 → 121.0)
chromium (119.0 -> 120.0)
"""
        count = plugin._count_updated_packages(output)
        assert count == 2

    def test_count_updated_packages_no_updates(self) -> None:
        """Test package counting when no updates."""
        plugin = SnapPlugin()
        output = "All snaps up to date."
        count = plugin._count_updated_packages(output)
        assert count == 0

    def test_get_update_commands_dry_run(self) -> None:
        """Test dry run commands."""
        plugin = SnapPlugin()
        commands = plugin.get_update_commands(dry_run=True)
        assert len(commands) == 1
        assert commands[0].cmd == ["snap", "refresh", "--list"]
        assert commands[0].sudo is False

    def test_get_update_commands_normal(self) -> None:
        """Test normal update returns empty (uses streaming)."""
        plugin = SnapPlugin()
        commands = plugin.get_update_commands(dry_run=False)
        assert commands == []


class TestSnapPluginEstimateDownload:
    """Tests for SnapPlugin.estimate_download method."""

    @pytest.mark.asyncio
    async def test_estimate_download_with_candidates(self) -> None:
        """Test download estimation with available updates."""
        plugin = SnapPlugin()

        mock_candidates = [
            SnapDownloadInfo(
                name="firefox",
                snap_id="id1",
                download_url="https://example.com/firefox.snap",
                sha3_384="a" * 96,
                size=100_000_000,
                revision=101,
                version="120.0",
            ),
            SnapDownloadInfo(
                name="chromium",
                snap_id="id2",
                download_url="https://example.com/chromium.snap",
                sha3_384="b" * 96,
                size=50_000_000,
                revision=201,
                version="119.0",
            ),
        ]

        with patch(
            "plugins.snap.get_refresh_candidates",
            new_callable=AsyncMock,
            return_value=mock_candidates,
        ):
            estimate = await plugin.estimate_download()

        assert estimate is not None
        assert estimate.total_bytes == 150_000_000
        assert estimate.package_count == 2
        assert len(estimate.packages) == 2
        assert estimate.packages[0].name == "firefox"
        assert estimate.packages[1].name == "chromium"

    @pytest.mark.asyncio
    async def test_estimate_download_no_updates(self) -> None:
        """Test download estimation when no updates available."""
        plugin = SnapPlugin()

        with patch(
            "plugins.snap.get_refresh_candidates",
            new_callable=AsyncMock,
            return_value=[],
        ):
            estimate = await plugin.estimate_download()

        assert estimate is None

    @pytest.mark.asyncio
    async def test_estimate_download_stores_candidates(self) -> None:
        """Test that estimate_download stores candidates for later use."""
        plugin = SnapPlugin()

        mock_candidates = [
            SnapDownloadInfo(
                name="test",
                snap_id="id",
                download_url="url",
                sha3_384="a" * 96,
                size=1000,
                revision=1,
            ),
        ]

        with patch(
            "plugins.snap.get_refresh_candidates",
            new_callable=AsyncMock,
            return_value=mock_candidates,
        ):
            await plugin.estimate_download()

        assert plugin._candidates == mock_candidates


class TestSnapPluginDownload:
    """Tests for SnapPlugin.download method."""

    @pytest.mark.asyncio
    async def test_download_no_updates(self) -> None:
        """Test download when no updates available."""
        plugin = SnapPlugin()
        plugin._candidates = []

        with patch(
            "plugins.snap.get_refresh_candidates",
            new_callable=AsyncMock,
            return_value=[],
        ):
            events = []
            async for event in plugin.download():
                events.append(event)

        # Should have output and completion events
        assert len(events) >= 2
        assert events[-1].success is True

    @pytest.mark.asyncio
    async def test_download_requires_root(self) -> None:
        """Test download fails without root access."""
        plugin = SnapPlugin()
        plugin._candidates = [
            SnapDownloadInfo(
                name="test",
                snap_id="id",
                download_url="url",
                sha3_384="a" * 96,
                size=1000,
                revision=1,
            ),
        ]

        with patch("os.geteuid", return_value=1000):  # Non-root
            events = []
            async for event in plugin.download():
                events.append(event)

        # Should fail with permission error
        assert events[-1].success is False
        assert "Root" in (events[-1].error_message or "")
