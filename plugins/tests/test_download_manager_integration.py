"""Tests for Centralized Download Manager integration with BasePlugin.

This module tests the get_download_spec() method and the integration
of BasePlugin.download_streaming() with the DownloadManager.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from core.models import DownloadSpec, PluginConfig
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


class MockPluginWithDownloadSpec(BasePlugin):
    """Mock plugin that provides a DownloadSpec."""

    @property
    def name(self) -> str:
        return "mock-download-spec"

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

    async def get_download_spec(self) -> DownloadSpec | None:
        """Return a DownloadSpec for testing."""
        return DownloadSpec(
            url="https://example.com/test-file.tar.gz",
            destination=Path("/tmp/test-file.tar.gz"),
            checksum="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
            extract=True,
        )


class MockPluginNoDownloadSpec(BasePlugin):
    """Mock plugin that does not provide a DownloadSpec."""

    @property
    def name(self) -> str:
        return "mock-no-download-spec"

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

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Legacy download implementation."""
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Legacy download in progress...",
            stream="stdout",
        )
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
        )


class MockPluginWithMultipleDownloads(BasePlugin):
    """Mock plugin that provides multiple DownloadSpecs."""

    @property
    def name(self) -> str:
        return "mock-multi-download"

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

    async def get_download_specs(self) -> list[DownloadSpec]:
        """Return multiple DownloadSpecs for testing."""
        return [
            DownloadSpec(
                url="https://example.com/file1.tar.gz",
                destination=Path("/tmp/file1.tar.gz"),
            ),
            DownloadSpec(
                url="https://example.com/file2.zip",
                destination=Path("/tmp/file2.zip"),
            ),
        ]


class TestGetDownloadSpec:
    """Tests for get_download_spec() method."""

    @pytest.mark.asyncio
    async def test_get_download_spec_returns_none_by_default(self) -> None:
        """Test that get_download_spec returns None by default."""
        plugin = MockPluginNoDownloadSpec()
        result = await plugin.get_download_spec()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_spec_returns_spec(self) -> None:
        """Test that get_download_spec returns a DownloadSpec when overridden."""
        plugin = MockPluginWithDownloadSpec()
        result = await plugin.get_download_spec()

        assert result is not None
        assert isinstance(result, DownloadSpec)
        assert result.url == "https://example.com/test-file.tar.gz"
        assert result.destination == Path("/tmp/test-file.tar.gz")
        assert (
            result.checksum
            == "sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234"
        )
        assert result.extract is True

    @pytest.mark.asyncio
    async def test_get_download_spec_archive_format_inferred(self) -> None:
        """Test that archive format is inferred from URL."""
        plugin = MockPluginWithDownloadSpec()
        result = await plugin.get_download_spec()

        assert result is not None
        assert result.extract_format == "tar.gz"


class TestGetDownloadSpecs:
    """Tests for get_download_specs() method (multiple downloads)."""

    @pytest.mark.asyncio
    async def test_get_download_specs_returns_empty_by_default(self) -> None:
        """Test that get_download_specs returns empty list by default."""
        plugin = MockPluginNoDownloadSpec()
        result = await plugin.get_download_specs()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_download_specs_returns_list(self) -> None:
        """Test that get_download_specs returns a list when overridden."""
        plugin = MockPluginWithMultipleDownloads()
        result = await plugin.get_download_specs()

        assert len(result) == 2
        assert result[0].url == "https://example.com/file1.tar.gz"
        assert result[1].url == "https://example.com/file2.zip"


class TestDownloadStreamingWithDownloadManager:
    """Tests for download_streaming() integration with DownloadManager."""

    @pytest.mark.asyncio
    async def test_download_streaming_uses_download_manager_when_spec_provided(
        self,
    ) -> None:
        """Test that download_streaming uses DownloadManager when get_download_spec returns a spec."""
        plugin = MockPluginWithDownloadSpec()

        # Mock the DownloadManager
        mock_download_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.bytes_downloaded = 1000000
        mock_result.duration_seconds = 5.0
        mock_result.path = Path("/tmp/test-file.tar.gz")

        async def mock_download_streaming(
            *_args: object, **_kwargs: object
        ) -> AsyncIterator[StreamEvent]:
            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=plugin.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=50,
                message="Downloading...",
                bytes_downloaded=500000,
                bytes_total=1000000,
            )
            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=plugin.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=100,
                message="Download complete",
                bytes_downloaded=1000000,
                bytes_total=1000000,
            )

        mock_download_manager.download_streaming = mock_download_streaming

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
            patch(
                "plugins.base.get_download_manager",
                return_value=mock_download_manager,
            ),
        ):
            events = []
            async for event in plugin.download_streaming():
                events.append(event)

        # Should have phase events and progress events
        phase_events = [e for e in events if isinstance(e, PhaseEvent)]
        progress_events = [e for e in events if isinstance(e, ProgressEvent)]

        # Check phase start
        phase_start = [e for e in phase_events if e.event_type == EventType.PHASE_START]
        assert len(phase_start) == 1
        assert phase_start[0].phase == Phase.DOWNLOAD

        # Check progress events from DownloadManager
        assert len(progress_events) >= 2

    @pytest.mark.asyncio
    async def test_download_streaming_falls_back_to_legacy_when_no_spec(self) -> None:
        """Test that download_streaming falls back to legacy download() when no spec."""
        plugin = MockPluginNoDownloadSpec()

        with patch("shutil.which", return_value="/usr/bin/echo"):
            events = []
            async for event in plugin.download_streaming():
                events.append(event)

        # Should have output from legacy download
        output_events = [e for e in events if isinstance(e, OutputEvent)]
        assert any("Legacy download" in e.line for e in output_events)

    @pytest.mark.asyncio
    async def test_download_streaming_handles_download_manager_error(self) -> None:
        """Test that download_streaming handles DownloadManager errors gracefully."""
        plugin = MockPluginWithDownloadSpec()

        # Mock the DownloadManager to raise an error
        mock_download_manager = MagicMock()

        async def mock_download_streaming_error(
            *_args: object, **_kwargs: object
        ) -> AsyncIterator[StreamEvent]:
            yield PhaseEvent(
                event_type=EventType.PHASE_START,
                plugin_name=plugin.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
            )
            raise ConnectionError("Network error")

        mock_download_manager.download_streaming = mock_download_streaming_error

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
            patch(
                "plugins.base.get_download_manager",
                return_value=mock_download_manager,
            ),
        ):
            events = []
            async for event in plugin.download_streaming():
                events.append(event)

        # Should have a completion event with failure
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) >= 1
        assert completion_events[-1].success is False


class TestDownloadStreamingWithMultipleSpecs:
    """Tests for download_streaming() with multiple DownloadSpecs."""

    @pytest.mark.asyncio
    async def test_download_streaming_handles_multiple_specs(self) -> None:
        """Test that download_streaming handles multiple DownloadSpecs."""
        plugin = MockPluginWithMultipleDownloads()

        # Mock the DownloadManager
        mock_download_manager = MagicMock()
        download_count = 0

        async def mock_download_streaming(
            *_args: object, **_kwargs: object
        ) -> AsyncIterator[StreamEvent]:
            nonlocal download_count
            download_count += 1
            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=plugin.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=100,
                message=f"Download {download_count} complete",
                bytes_downloaded=1000000,
                bytes_total=1000000,
            )

        mock_download_manager.download_streaming = mock_download_streaming

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
            patch(
                "plugins.base.get_download_manager",
                return_value=mock_download_manager,
            ),
        ):
            events = []
            async for event in plugin.download_streaming():
                events.append(event)

        # Should have progress events for both downloads
        progress_events = [e for e in events if isinstance(e, ProgressEvent)]
        assert len(progress_events) >= 2


class TestDownloadManagerCaching:
    """Tests for DownloadManager caching integration."""

    @pytest.mark.asyncio
    async def test_download_streaming_uses_cache_when_available(self) -> None:
        """Test that download_streaming uses cached files when available."""
        plugin = MockPluginWithDownloadSpec()

        # Mock the DownloadManager with cache hit
        mock_download_manager = MagicMock()
        mock_download_manager.get_cached_path.return_value = Path("/tmp/cached-file.tar.gz")

        async def mock_download_streaming_cached(
            *_args: object, **_kwargs: object
        ) -> AsyncIterator[StreamEvent]:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin.name,
                timestamp=datetime.now(tz=UTC),
                line="Using cached file",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )

        mock_download_manager.download_streaming = mock_download_streaming_cached

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
            patch(
                "plugins.base.get_download_manager",
                return_value=mock_download_manager,
            ),
        ):
            events = []
            async for event in plugin.download_streaming():
                events.append(event)

        # Should complete successfully with cache
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) >= 1
        assert completion_events[-1].success is True
