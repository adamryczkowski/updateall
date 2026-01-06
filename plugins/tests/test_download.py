"""Tests for Download API functionality (Phase 2).

This module tests the download interface methods in BasePlugin and UpdatePlugin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from core.models import DownloadEstimate, PackageDownload, PluginConfig
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
)
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class MockDownloadPlugin(BasePlugin):
    """Mock plugin for testing download functionality."""

    @property
    def name(self) -> str:
        return "mock-download"

    @property
    def command(self) -> str:
        return "echo"

    @property
    def supports_download(self) -> bool:
        return True

    async def _execute_update(
        self,
        config: PluginConfig,  # noqa: ARG002
    ) -> tuple[str, str | None]:
        return "Update completed", None

    async def estimate_download(self) -> DownloadEstimate | None:
        return DownloadEstimate(
            total_bytes=100_000_000,
            package_count=5,
            estimated_seconds=30.0,
            packages=[
                PackageDownload(name="pkg1", version="1.0", size_bytes=20_000_000),
                PackageDownload(name="pkg2", version="2.0", size_bytes=30_000_000),
                PackageDownload(name="pkg3", version="3.0", size_bytes=50_000_000),
            ],
        )

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Simulate download with progress events."""
        # Emit progress events
        for i in range(5):
            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=(i + 1) * 20,
                message=f"Downloading package {i + 1}/5...",
                bytes_downloaded=(i + 1) * 20_000_000,
                bytes_total=100_000_000,
                items_completed=i + 1,
                items_total=5,
            )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
        )


class MockNoDownloadPlugin(BasePlugin):
    """Mock plugin that does not support download."""

    @property
    def name(self) -> str:
        return "mock-no-download"

    @property
    def command(self) -> str:
        return "echo"

    async def _execute_update(
        self,
        config: PluginConfig,  # noqa: ARG002
    ) -> tuple[str, str | None]:
        return "Update completed", None


class TestBasePluginDownloadDefaults:
    """Tests for BasePlugin download default behavior."""

    def test_supports_download_default_false(self) -> None:
        """Test that supports_download defaults to False."""
        plugin = MockNoDownloadPlugin()
        assert plugin.supports_download is False

    @pytest.mark.asyncio
    async def test_estimate_download_default_none(self) -> None:
        """Test that estimate_download defaults to None."""
        plugin = MockNoDownloadPlugin()
        result = await plugin.estimate_download()
        assert result is None

    @pytest.mark.asyncio
    async def test_download_raises_not_implemented(self) -> None:
        """Test that download raises NotImplementedError by default."""
        plugin = MockNoDownloadPlugin()
        with pytest.raises(NotImplementedError, match="does not support separate download"):
            async for _ in plugin.download():
                pass


class TestMockDownloadPlugin:
    """Tests for MockDownloadPlugin with download support."""

    def test_supports_download_true(self) -> None:
        """Test that supports_download returns True."""
        plugin = MockDownloadPlugin()
        assert plugin.supports_download is True

    @pytest.mark.asyncio
    async def test_estimate_download(self) -> None:
        """Test download estimation."""
        plugin = MockDownloadPlugin()
        estimate = await plugin.estimate_download()

        assert estimate is not None
        assert estimate.total_bytes == 100_000_000
        assert estimate.package_count == 5
        assert estimate.estimated_seconds == 30.0
        assert len(estimate.packages) == 3
        assert estimate.packages[0].name == "pkg1"

    @pytest.mark.asyncio
    async def test_download_yields_progress_events(self) -> None:
        """Test that download yields progress events."""
        plugin = MockDownloadPlugin()

        events = []
        async for event in plugin.download():
            events.append(event)

        # Should have 5 progress events + 1 completion event
        assert len(events) == 6

        # Check progress events
        progress_events = [e for e in events if isinstance(e, ProgressEvent)]
        assert len(progress_events) == 5

        # Check first progress event
        first_progress = progress_events[0]
        assert first_progress.phase == Phase.DOWNLOAD
        assert first_progress.percent == 20
        assert first_progress.bytes_downloaded == 20_000_000
        assert first_progress.bytes_total == 100_000_000

        # Check last progress event
        last_progress = progress_events[-1]
        assert last_progress.percent == 100
        assert last_progress.items_completed == 5
        assert last_progress.items_total == 5

        # Check completion event
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1
        assert completion_events[0].success is True

    @pytest.mark.asyncio
    async def test_download_streaming(self) -> None:
        """Test download_streaming wrapper method."""
        plugin = MockDownloadPlugin()

        with patch("shutil.which", return_value="/usr/bin/echo"):
            events = []
            async for event in plugin.download_streaming():
                events.append(event)

        # Should have phase start, progress events, completion, phase end
        phase_events = [e for e in events if isinstance(e, PhaseEvent)]
        assert len(phase_events) >= 2

        # Check phase start
        phase_start = [e for e in phase_events if e.event_type == EventType.PHASE_START]
        assert len(phase_start) == 1
        assert phase_start[0].phase == Phase.DOWNLOAD

        # Check phase end
        phase_end = [e for e in phase_events if e.event_type == EventType.PHASE_END]
        assert len(phase_end) == 1
        assert phase_end[0].phase == Phase.DOWNLOAD
        assert phase_end[0].success is True


class TestDownloadStreamingNoSupport:
    """Tests for download_streaming when plugin doesn't support download."""

    @pytest.mark.asyncio
    async def test_download_streaming_emits_error(self) -> None:
        """Test that download_streaming emits error when not supported."""
        plugin = MockNoDownloadPlugin()

        events = []
        async for event in plugin.download_streaming():
            events.append(event)

        # Should have output event with error message and completion event
        output_events = [e for e in events if isinstance(e, OutputEvent)]
        assert len(output_events) >= 1
        assert "does not support separate download" in output_events[0].line

        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1
        assert completion_events[0].success is False


class TestExecuteAfterDownload:
    """Tests for execute_after_download method."""

    @pytest.mark.asyncio
    async def test_execute_after_download_delegates_to_execute_streaming(self) -> None:
        """Test that execute_after_download delegates to execute_streaming."""
        plugin = MockDownloadPlugin()

        with patch("shutil.which", return_value="/usr/bin/echo"):
            events = []
            async for event in plugin.execute_after_download(dry_run=True):
                events.append(event)

        # Should have phase events for EXECUTE phase
        phase_events = [e for e in events if isinstance(e, PhaseEvent)]
        execute_phases = [e for e in phase_events if e.phase == Phase.EXECUTE]
        assert len(execute_phases) >= 1
