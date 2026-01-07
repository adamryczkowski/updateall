"""Tests for DownloadManager (Centralized Download Manager - Proposal 2).

This module tests the DownloadManager class which provides centralized
download handling for all plugins.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.download_manager import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT_SECONDS,
    DownloadError,
    DownloadManager,
    get_download_manager,
    reset_download_manager,
)
from core.models import DownloadResult, DownloadSpec, GlobalConfig
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
)


class TestDownloadManagerInit:
    """Tests for DownloadManager initialization."""

    def test_default_config(self) -> None:
        """DM-001: Default configuration values are correct."""
        manager = DownloadManager()

        assert manager._max_retries == DEFAULT_MAX_RETRIES
        assert manager._retry_delay == DEFAULT_RETRY_DELAY
        assert manager._timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert manager._bandwidth_limit is None
        assert manager._max_concurrent == 2

    def test_custom_cache_dir(self) -> None:
        """DM-002: Custom cache directory is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "custom-cache"
            manager = DownloadManager(cache_dir=cache_dir)

            assert manager._cache_dir == cache_dir
            assert cache_dir.exists()

    def test_custom_retry_config(self) -> None:
        """DM-003: Custom retry configuration is used."""
        manager = DownloadManager(
            max_retries=5,
            retry_delay=2.0,
        )

        assert manager._max_retries == 5
        assert manager._retry_delay == 2.0

    def test_bandwidth_limit_config(self) -> None:
        """DM-004: Bandwidth limit configuration is used."""
        manager = DownloadManager(bandwidth_limit_bytes=1_000_000)

        assert manager._bandwidth_limit == 1_000_000

    def test_from_config(self) -> None:
        """DM-005: Create manager from GlobalConfig."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = GlobalConfig(
                download_cache_dir=Path(tmpdir) / "cache",
                download_max_retries=5,
                download_retry_delay=2.0,
                download_bandwidth_limit=500_000,
                download_max_concurrent=4,
                download_timeout_seconds=7200,
            )

            manager = DownloadManager.from_config(config)

            assert manager._cache_dir == config.download_cache_dir
            assert manager._max_retries == 5
            assert manager._retry_delay == 2.0
            assert manager._bandwidth_limit == 500_000
            assert manager._max_concurrent == 4
            assert manager._timeout_seconds == 7200


class TestDownloadManagerSingleton:
    """Tests for DownloadManager singleton pattern."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        reset_download_manager()

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        reset_download_manager()

    def test_get_download_manager_creates_instance(self) -> None:
        """DM-006: get_download_manager creates instance if none exists."""
        manager = get_download_manager()
        assert manager is not None
        assert isinstance(manager, DownloadManager)

    def test_get_download_manager_returns_same_instance(self) -> None:
        """DM-007: get_download_manager returns same instance."""
        manager1 = get_download_manager()
        manager2 = get_download_manager()
        assert manager1 is manager2

    def test_get_download_manager_with_config(self) -> None:
        """DM-008: get_download_manager uses config for new instance."""
        config = GlobalConfig(download_max_retries=10)
        manager = get_download_manager(config)
        assert manager._max_retries == 10

    def test_reset_download_manager(self) -> None:
        """DM-009: reset_download_manager clears singleton."""
        manager1 = get_download_manager()
        reset_download_manager()
        manager2 = get_download_manager()
        assert manager1 is not manager2


class TestDownloadError:
    """Tests for DownloadError exception."""

    def test_download_error_retryable(self) -> None:
        """DE-001: DownloadError with retryable=True."""
        error = DownloadError("Network error", retryable=True)
        assert str(error) == "Network error"
        assert error.retryable is True

    def test_download_error_not_retryable(self) -> None:
        """DE-002: DownloadError with retryable=False."""
        error = DownloadError("File not found", retryable=False)
        assert str(error) == "File not found"
        assert error.retryable is False

    def test_download_error_default_retryable(self) -> None:
        """DE-003: DownloadError defaults to retryable=True."""
        error = DownloadError("Some error")
        assert error.retryable is True


class TestDownloadManagerCache:
    """Tests for download caching."""

    def setup_method(self) -> None:
        """Create temporary directory for tests."""
        self.tmpdir = tempfile.mkdtemp()
        self.cache_dir = Path(self.tmpdir) / "cache"
        self.manager = DownloadManager(cache_dir=self.cache_dir)

    def teardown_method(self) -> None:
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_cached_path_no_checksum(self) -> None:
        """DM-C01: get_cached_path returns None without checksum."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
        )
        result = self.manager.get_cached_path(spec)
        assert result is None

    def test_get_cached_path_not_cached(self) -> None:
        """DM-C02: get_cached_path returns None when not cached."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
            checksum="sha256:abc123",
        )
        result = self.manager.get_cached_path(spec)
        assert result is None

    def test_get_cached_path_cached(self) -> None:
        """DM-C03: get_cached_path returns path when cached."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
            checksum="sha256:abc123",
        )

        # Create cache file
        cache_path = self.cache_dir / "sha256_abc123"
        cache_path.write_text("cached content")

        result = self.manager.get_cached_path(spec)
        assert result == cache_path

    def test_clear_cache_all(self) -> None:
        """DM-C04: clear_cache removes all files."""
        # Create some cache files
        (self.cache_dir / "file1").write_text("content1")
        (self.cache_dir / "file2").write_text("content2")

        removed = self.manager.clear_cache()

        assert removed == 2
        assert not (self.cache_dir / "file1").exists()
        assert not (self.cache_dir / "file2").exists()

    def test_clear_cache_empty(self) -> None:
        """DM-C05: clear_cache handles empty cache."""
        removed = self.manager.clear_cache()
        assert removed == 0


class TestDownloadManagerDownload:
    """Tests for DownloadManager.download() method."""

    def setup_method(self) -> None:
        """Create temporary directory for tests."""
        self.tmpdir = tempfile.mkdtemp()
        self.cache_dir = Path(self.tmpdir) / "cache"
        self.dest_dir = Path(self.tmpdir) / "dest"
        self.dest_dir.mkdir(parents=True)
        self.manager = DownloadManager(cache_dir=self.cache_dir, max_retries=1)

    def teardown_method(self) -> None:
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_download_emits_phase_start(self) -> None:
        """DM-D01: download emits PHASE_START event."""
        spec = DownloadSpec(
            url="https://example.com/file.txt",
            destination=self.dest_dir,
        )

        # Mock aiohttp to avoid actual network request
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.content_length = 100
        mock_response.content.iter_chunked = AsyncMock(
            return_value=AsyncIteratorMock([b"test content"])
        )

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            events = []
            async for event in self.manager.download(spec, "test-plugin"):
                events.append(event)
                if len(events) >= 1:
                    break

        assert len(events) >= 1
        assert isinstance(events[0], PhaseEvent)
        assert events[0].event_type == EventType.PHASE_START
        assert events[0].phase == Phase.DOWNLOAD

    @pytest.mark.asyncio
    async def test_download_uses_cache(self) -> None:
        """DM-D02: download uses cached file when available."""
        spec = DownloadSpec(
            url="https://example.com/file.txt",
            destination=self.dest_dir,
            checksum="sha256:abc123",
        )

        # Create cache file
        cache_path = self.cache_dir / "sha256_abc123"
        cache_path.write_text("cached content")

        events = []
        async for event in self.manager.download(spec, "test-plugin"):
            events.append(event)

        # Should have phase start, output (using cached), phase end, completion
        assert any(isinstance(e, OutputEvent) and "cached" in e.line.lower() for e in events)
        assert any(isinstance(e, CompletionEvent) and e.success for e in events)


class AsyncIteratorMock:
    """Mock async iterator for testing."""

    def __init__(self, items: list) -> None:
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


class TestDownloadManagerExtraction:
    """Tests for archive extraction."""

    def setup_method(self) -> None:
        """Create temporary directory for tests."""
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DownloadManager()

    def teardown_method(self) -> None:
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_extract_tar_gz(self) -> None:
        """DM-E01: Extract tar.gz archive."""
        import tarfile

        # Create a test tar.gz file
        archive_path = Path(self.tmpdir) / "test.tar.gz"
        extract_dir = Path(self.tmpdir) / "extracted"

        # Create archive with a test file
        test_file = Path(self.tmpdir) / "testfile.txt"
        test_file.write_text("test content")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(test_file, arcname="testfile.txt")

        # Extract
        result = await self.manager._extract_archive(archive_path, extract_dir, "tar.gz")

        assert result == extract_dir
        assert (extract_dir / "testfile.txt").exists()
        assert (extract_dir / "testfile.txt").read_text() == "test content"

    @pytest.mark.asyncio
    async def test_extract_zip(self) -> None:
        """DM-E02: Extract zip archive."""
        import zipfile

        # Create a test zip file
        archive_path = Path(self.tmpdir) / "test.zip"
        extract_dir = Path(self.tmpdir) / "extracted"

        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("testfile.txt", "test content")

        # Extract
        result = await self.manager._extract_archive(archive_path, extract_dir, "zip")

        assert result == extract_dir
        assert (extract_dir / "testfile.txt").exists()
        assert (extract_dir / "testfile.txt").read_text() == "test content"

    @pytest.mark.asyncio
    async def test_extract_unsupported_format(self) -> None:
        """DM-E03: Unsupported format raises DownloadError."""
        archive_path = Path(self.tmpdir) / "test.rar"
        archive_path.write_text("fake archive")
        extract_dir = Path(self.tmpdir) / "extracted"

        with pytest.raises(DownloadError, match="Unsupported archive format"):
            await self.manager._extract_archive(archive_path, extract_dir, "rar")


class TestDownloadManagerRateLimit:
    """Tests for bandwidth limiting."""

    def setup_method(self) -> None:
        """Create manager with rate limiting."""
        self.manager = DownloadManager(bandwidth_limit_bytes=1000)

    @pytest.mark.asyncio
    async def test_rate_limit_applied(self) -> None:
        """DM-R01: Rate limiting delays large chunks."""
        import time

        # Reset token state
        self.manager._tokens = 1000
        self.manager._last_token_update = time.monotonic()

        start = time.monotonic()
        # Request more bytes than available tokens
        await self.manager._apply_rate_limit(2000)
        elapsed = time.monotonic() - start

        # Should have waited approximately 1 second (2000 bytes / 1000 bytes per second)
        assert elapsed >= 0.9  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_no_rate_limit_when_disabled(self) -> None:
        """DM-R02: No delay when rate limiting is disabled."""
        import time

        manager = DownloadManager(bandwidth_limit_bytes=None)

        start = time.monotonic()
        await manager._apply_rate_limit(1_000_000)
        elapsed = time.monotonic() - start

        # Should be nearly instant
        assert elapsed < 0.1


class TestDownloadManagerRetry:
    """Tests for retry logic."""

    def setup_method(self) -> None:
        """Create manager with retry settings."""
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DownloadManager(
            cache_dir=Path(self.tmpdir) / "cache",
            max_retries=2,
            retry_delay=0.1,  # Short delay for tests
        )

    def teardown_method(self) -> None:
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self) -> None:
        """DM-RT01: Retry on network error."""
        spec = DownloadSpec(
            url="https://example.com/file.txt",
            destination=Path(self.tmpdir) / "dest",
        )

        call_count = 0

        async def mock_perform_download(*_args: object, **_kwargs: object) -> DownloadResult:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise DownloadError("Network error", retryable=True)
            from core.models import DownloadResult

            return DownloadResult(success=True, path=Path("/tmp/file"))

        with patch.object(self.manager, "_perform_download", mock_perform_download):
            result = await self.manager._download_with_retry(spec, "test-plugin", MagicMock())

        assert call_count == 3
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_retry_on_404(self) -> None:
        """DM-RT02: No retry on 404 error."""
        spec = DownloadSpec(
            url="https://example.com/file.txt",
            destination=Path(self.tmpdir) / "dest",
        )

        call_count = 0

        async def mock_perform_download(*_args: object, **_kwargs: object) -> DownloadResult:
            nonlocal call_count
            call_count += 1
            raise DownloadError("File not found", retryable=False)

        with patch.object(self.manager, "_perform_download", mock_perform_download):
            result = await self.manager._download_with_retry(spec, "test-plugin", MagicMock())

        # Should only try once since error is not retryable
        assert call_count == 1
        assert result.success is False

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self) -> None:
        """DM-RT03: Failure after max retries exceeded."""
        spec = DownloadSpec(
            url="https://example.com/file.txt",
            destination=Path(self.tmpdir) / "dest",
        )

        call_count = 0

        async def mock_perform_download(*_args: object, **_kwargs: object) -> DownloadResult:
            nonlocal call_count
            call_count += 1
            raise DownloadError("Network error", retryable=True)

        with patch.object(self.manager, "_perform_download", mock_perform_download):
            result = await self.manager._download_with_retry(spec, "test-plugin", MagicMock())

        # Should try max_retries + 1 times (initial + retries)
        assert call_count == 3  # 1 initial + 2 retries
        assert result.success is False
        assert "3 attempts" in result.error_message


class TestDownloadManagerConcurrency:
    """Tests for concurrent download limiting."""

    def setup_method(self) -> None:
        """Create manager with concurrency limit."""
        self.manager = DownloadManager(max_concurrent_downloads=2)

    def test_semaphore_initialized(self) -> None:
        """DM-CC01: Semaphore is initialized with correct limit."""
        # The semaphore should allow 2 concurrent downloads
        assert self.manager._download_semaphore._value == 2
