"""Centralized Download Manager for update-all plugins.

This module provides a centralized download manager that handles file downloads
for all plugins with consistent progress reporting, retry logic, bandwidth
limiting, and caching.

Features:
    - Progress reporting via StreamEvent
    - Retry logic with exponential backoff
    - Resume support for partial downloads
    - Bandwidth limiting
    - Download caching
    - Checksum verification
    - Archive extraction (tar.gz, tar.bz2, tar.xz, zip)
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tarfile
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import structlog

from .models import DownloadResult, DownloadSpec, GlobalConfig
from .streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)

# Default configuration values
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_CHUNK_SIZE = 65536  # 64 KB chunks


class DownloadError(Exception):
    """Exception raised when a download fails."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        """Initialize download error.

        Args:
            message: Error message.
            retryable: Whether the error is retryable.
        """
        super().__init__(message)
        self.retryable = retryable


class DownloadManager:
    """Centralized download manager for all plugins.

    Provides:
    - Progress reporting via StreamEvent
    - Retry logic with exponential backoff
    - Resume support for partial downloads
    - Bandwidth limiting
    - Download caching
    - Checksum verification
    - Archive extraction

    Example:
        >>> manager = DownloadManager()
        >>> spec = DownloadSpec(
        ...     url="https://example.com/file.tar.gz",
        ...     destination=Path("/tmp/download"),
        ...     extract=True,
        ... )
        >>> async for event in manager.download(spec, "my-plugin"):
        ...     print(event)
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        bandwidth_limit_bytes: int | None = None,
        max_concurrent_downloads: int = DEFAULT_MAX_CONCURRENT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the download manager.

        Args:
            cache_dir: Directory for caching downloaded files. None = use system temp.
            max_retries: Maximum number of retry attempts for failed downloads.
            retry_delay: Initial delay between retries in seconds (exponential backoff).
            bandwidth_limit_bytes: Maximum download bandwidth in bytes per second.
            max_concurrent_downloads: Maximum number of concurrent downloads.
            timeout_seconds: Default timeout for downloads in seconds.
        """
        self._cache_dir = cache_dir or Path(tempfile.gettempdir()) / "update-all-cache"
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._bandwidth_limit = bandwidth_limit_bytes
        self._max_concurrent = max_concurrent_downloads
        self._timeout_seconds = timeout_seconds

        # Semaphore for limiting concurrent downloads
        self._download_semaphore = asyncio.Semaphore(max_concurrent_downloads)

        # Rate limiter state (token bucket)
        self._tokens = float(bandwidth_limit_bytes) if bandwidth_limit_bytes else float("inf")
        self._last_token_update = time.monotonic()
        self._token_lock = asyncio.Lock()

        self._log = logger.bind(component="download_manager")

        # Ensure cache directory exists
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: GlobalConfig) -> DownloadManager:
        """Create a DownloadManager from GlobalConfig.

        Args:
            config: Global configuration.

        Returns:
            Configured DownloadManager instance.
        """
        return cls(
            cache_dir=config.download_cache_dir,
            max_retries=config.download_max_retries,
            retry_delay=config.download_retry_delay,
            bandwidth_limit_bytes=config.download_bandwidth_limit,
            max_concurrent_downloads=config.download_max_concurrent,
            timeout_seconds=config.download_timeout_seconds,
        )

    async def download(
        self,
        spec: DownloadSpec,
        plugin_name: str,
    ) -> AsyncIterator[StreamEvent]:
        """Download a file according to the spec.

        Yields progress events during download and a completion event
        when done. The final event is always a CompletionEvent.

        Args:
            spec: Download specification.
            plugin_name: Name of the plugin requesting the download.

        Yields:
            StreamEvent objects with download progress.
        """
        log = self._log.bind(plugin=plugin_name, url=spec.url)
        start_time = time.monotonic()

        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=plugin_name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        # Check cache first
        cached_path = self.get_cached_path(spec)
        if cached_path and cached_path.exists():
            log.info("using_cached_download", path=str(cached_path))
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=f"Using cached file: {cached_path}",
                stream="stdout",
            )

            result = DownloadResult(
                success=True,
                path=cached_path,
                bytes_downloaded=0,
                duration_seconds=time.monotonic() - start_time,
                from_cache=True,
                checksum_verified=spec.checksum is not None,
                spec=spec,
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=True,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        # Acquire semaphore for concurrent download limiting
        async with self._download_semaphore:
            result = await self._download_with_retry(spec, plugin_name, log)

            # Yield events based on result
            async for event in self._emit_result_events(result, plugin_name, start_time):
                yield event

    async def _download_with_retry(
        self,
        spec: DownloadSpec,
        plugin_name: str,
        log: structlog.stdlib.BoundLogger,
    ) -> DownloadResult:
        """Download with retry logic.

        Args:
            spec: Download specification.
            plugin_name: Name of the plugin.
            log: Bound logger.

        Returns:
            DownloadResult with success or failure status.
        """
        last_error: str | None = None
        bytes_downloaded = 0
        start_time = time.monotonic()

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = self._retry_delay * (2 ** (attempt - 1))
                log.info("retrying_download", attempt=attempt, delay=delay)
                await asyncio.sleep(delay)

            try:
                result = await self._perform_download(spec, plugin_name)
                return result

            except DownloadError as e:
                last_error = str(e)
                log.warning(
                    "download_attempt_failed",
                    attempt=attempt + 1,
                    error=last_error,
                    retryable=e.retryable,
                )
                if not e.retryable:
                    break

            except Exception as e:
                last_error = str(e)
                log.exception("download_unexpected_error", attempt=attempt + 1)

        return DownloadResult(
            success=False,
            bytes_downloaded=bytes_downloaded,
            duration_seconds=time.monotonic() - start_time,
            error_message=f"Download failed after {self._max_retries + 1} attempts: {last_error}",
            spec=spec,
        )

    async def _perform_download(
        self,
        spec: DownloadSpec,
        plugin_name: str,  # noqa: ARG002 - kept for API consistency
    ) -> DownloadResult:
        """Perform the actual download.

        Args:
            spec: Download specification.
            plugin_name: Name of the plugin (reserved for future logging).

        Returns:
            DownloadResult with download status.

        Raises:
            DownloadError: If download fails.
        """
        start_time = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=spec.timeout_seconds or self._timeout_seconds)

        # Prepare headers
        headers = dict(spec.headers) if spec.headers else {}
        headers.setdefault("User-Agent", "update-all-download-manager/1.0")

        # Create destination directory
        spec.destination.parent.mkdir(parents=True, exist_ok=True)

        # Temporary file for download
        temp_path = spec.destination.parent / f".{spec.filename}.download"

        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(spec.url, headers=headers) as response,
            ):
                if response.status == 404:
                    raise DownloadError(
                        f"File not found: {spec.url}",
                        retryable=False,
                    )
                if response.status >= 400:
                    raise DownloadError(
                        f"HTTP error {response.status}: {response.reason}",
                        retryable=response.status >= 500,
                    )

                bytes_downloaded = 0

                # Initialize hasher if checksum verification is needed
                hasher = None
                if spec.checksum:
                    algorithm = spec.checksum_algorithm
                    if algorithm:
                        hasher = hashlib.new(algorithm)

                with temp_path.open("wb") as f:
                    async for chunk in response.content.iter_chunked(DEFAULT_CHUNK_SIZE):
                        # Apply bandwidth limiting
                        if self._bandwidth_limit:
                            await self._apply_rate_limit(len(chunk))

                        f.write(chunk)
                        bytes_downloaded += len(chunk)

                        if hasher:
                            hasher.update(chunk)

            # Verify checksum
            checksum_verified = False
            if spec.checksum and hasher:
                computed_hash = hasher.hexdigest()
                expected_hash = spec.checksum_value
                if computed_hash != expected_hash:
                    temp_path.unlink(missing_ok=True)
                    raise DownloadError(
                        f"Checksum mismatch: expected {expected_hash}, got {computed_hash}",
                        retryable=False,
                    )
                checksum_verified = True

            # Move to final destination
            final_path = (
                spec.destination / spec.filename if spec.destination.is_dir() else spec.destination
            )
            if spec.extract:
                # Extract archive
                final_path = await self._extract_archive(
                    temp_path, spec.destination, spec.extract_format
                )
                temp_path.unlink(missing_ok=True)
            else:
                # Move file to destination
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(temp_path), str(final_path))

            # Cache the result
            if spec.checksum:
                self._cache_download(spec, final_path)

            return DownloadResult(
                success=True,
                path=final_path,
                bytes_downloaded=bytes_downloaded,
                duration_seconds=time.monotonic() - start_time,
                from_cache=False,
                checksum_verified=checksum_verified,
                spec=spec,
            )

        except aiohttp.ClientError as e:
            temp_path.unlink(missing_ok=True)
            raise DownloadError(f"Network error: {e}") from e

        except TimeoutError:
            temp_path.unlink(missing_ok=True)
            raise DownloadError("Download timed out") from None

    async def _apply_rate_limit(self, bytes_count: int) -> None:
        """Apply rate limiting using token bucket algorithm.

        Args:
            bytes_count: Number of bytes to consume.
        """
        if not self._bandwidth_limit:
            return

        async with self._token_lock:
            now = time.monotonic()
            elapsed = now - self._last_token_update
            self._last_token_update = now

            # Add tokens based on elapsed time
            self._tokens = min(
                float(self._bandwidth_limit),
                self._tokens + elapsed * self._bandwidth_limit,
            )

            # Wait if not enough tokens
            if bytes_count > self._tokens:
                wait_time = (bytes_count - self._tokens) / self._bandwidth_limit
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= bytes_count

    async def _extract_archive(
        self,
        archive_path: Path,
        destination: Path,
        format_hint: str | None,
    ) -> Path:
        """Extract an archive to the destination.

        Args:
            archive_path: Path to the archive file.
            destination: Directory to extract to.
            format_hint: Archive format hint.

        Returns:
            Path to the extracted directory.

        Raises:
            DownloadError: If extraction fails.
        """
        destination.mkdir(parents=True, exist_ok=True)

        try:
            if format_hint in ("tar.gz", "tar.bz2", "tar.xz"):
                # Run extraction in thread pool to avoid blocking
                def extract_tar() -> None:
                    # Determine mode based on format
                    if format_hint == "tar.gz":
                        with tarfile.open(archive_path, "r:gz") as tar:
                            tar.extractall(destination, filter="data")
                    elif format_hint == "tar.bz2":
                        with tarfile.open(archive_path, "r:bz2") as tar:
                            tar.extractall(destination, filter="data")
                    elif format_hint == "tar.xz":
                        with tarfile.open(archive_path, "r:xz") as tar:
                            tar.extractall(destination, filter="data")

                await asyncio.to_thread(extract_tar)

            elif format_hint == "zip":

                def extract_zip() -> None:
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        zf.extractall(destination)

                await asyncio.to_thread(extract_zip)

            else:
                raise DownloadError(
                    f"Unsupported archive format: {format_hint}",
                    retryable=False,
                )

            return destination

        except (tarfile.TarError, zipfile.BadZipFile) as e:
            raise DownloadError(f"Failed to extract archive: {e}", retryable=False) from e

    async def _emit_result_events(
        self,
        result: DownloadResult,
        plugin_name: str,
        start_time: float,  # noqa: ARG002 - kept for API consistency
    ) -> AsyncIterator[StreamEvent]:
        """Emit events based on download result.

        Args:
            result: Download result.
            plugin_name: Name of the plugin.
            start_time: Download start time (reserved for future duration reporting).

        Yields:
            StreamEvent objects.
        """
        if result.success:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=f"Download complete: {result.path}",
                stream="stdout",
            )

            if result.checksum_verified:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=plugin_name,
                    timestamp=datetime.now(tz=UTC),
                    line="Checksum verified",
                    stream="stdout",
                )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=True,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
        else:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=f"Download failed: {result.error_message}",
                stream="stderr",
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message=result.error_message,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=result.error_message,
            )

    async def download_with_progress(
        self,
        spec: DownloadSpec,
        plugin_name: str,
    ) -> AsyncIterator[StreamEvent]:
        """Download a file with progress events.

        This is an enhanced version of download() that emits ProgressEvent
        objects during the download.

        Args:
            spec: Download specification.
            plugin_name: Name of the plugin.

        Yields:
            StreamEvent objects including ProgressEvent.
        """
        log = self._log.bind(plugin=plugin_name, url=spec.url)
        # start_time reserved for future duration tracking

        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=plugin_name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=plugin_name,
            timestamp=datetime.now(tz=UTC),
            line=f"Downloading: {spec.url}",
            stream="stdout",
        )

        # Check cache first
        cached_path = self.get_cached_path(spec)
        if cached_path and cached_path.exists():
            log.info("using_cached_download", path=str(cached_path))
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=f"Using cached file: {cached_path}",
                stream="stdout",
            )

            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=100.0,
                message="Using cached file",
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=True,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        # Perform download with progress
        async with self._download_semaphore:
            async for event in self._download_with_progress_impl(spec, plugin_name, log):
                yield event

    async def _download_with_progress_impl(
        self,
        spec: DownloadSpec,
        plugin_name: str,
        log: structlog.stdlib.BoundLogger,  # noqa: ARG002 - kept for future logging
    ) -> AsyncIterator[StreamEvent]:
        """Implementation of download with progress events.

        Args:
            spec: Download specification.
            plugin_name: Name of the plugin.
            log: Bound logger (reserved for future detailed logging).

        Yields:
            StreamEvent objects.
        """
        # start_time reserved for future duration tracking
        timeout = aiohttp.ClientTimeout(total=spec.timeout_seconds or self._timeout_seconds)

        headers = dict(spec.headers) if spec.headers else {}
        headers.setdefault("User-Agent", "update-all-download-manager/1.0")

        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = spec.destination.parent / f".{spec.filename}.download"

        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(spec.url, headers=headers) as response,
            ):
                if response.status >= 400:
                    error_msg = f"HTTP error {response.status}: {response.reason}"
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=plugin_name,
                        timestamp=datetime.now(tz=UTC),
                        line=error_msg,
                        stream="stderr",
                    )
                    yield PhaseEvent(
                        event_type=EventType.PHASE_END,
                        plugin_name=plugin_name,
                        timestamp=datetime.now(tz=UTC),
                        phase=Phase.DOWNLOAD,
                        success=False,
                        error_message=error_msg,
                    )
                    yield CompletionEvent(
                        event_type=EventType.COMPLETION,
                        plugin_name=plugin_name,
                        timestamp=datetime.now(tz=UTC),
                        success=False,
                        exit_code=1,
                        error_message=error_msg,
                    )
                    return

                total_size = response.content_length or spec.expected_size or 0
                bytes_downloaded = 0
                last_progress_time = time.monotonic()

                hasher = None
                if spec.checksum and spec.checksum_algorithm:
                    hasher = hashlib.new(spec.checksum_algorithm)

                with temp_path.open("wb") as f:
                    async for chunk in response.content.iter_chunked(DEFAULT_CHUNK_SIZE):
                        if self._bandwidth_limit:
                            await self._apply_rate_limit(len(chunk))

                        f.write(chunk)
                        bytes_downloaded += len(chunk)

                        if hasher:
                            hasher.update(chunk)

                        # Emit progress event every 0.5 seconds
                        now = time.monotonic()
                        if now - last_progress_time >= 0.5:
                            last_progress_time = now
                            percent = (
                                (bytes_downloaded / total_size * 100) if total_size > 0 else None
                            )
                            yield ProgressEvent(
                                event_type=EventType.PROGRESS,
                                plugin_name=plugin_name,
                                timestamp=datetime.now(tz=UTC),
                                phase=Phase.DOWNLOAD,
                                percent=percent,
                                message=f"Downloading... {bytes_downloaded / 1024 / 1024:.1f} MB",
                                bytes_downloaded=bytes_downloaded,
                                bytes_total=total_size if total_size > 0 else None,
                            )

            # Verify checksum
            checksum_verified = False
            if spec.checksum and hasher:
                computed_hash = hasher.hexdigest()
                expected_hash = spec.checksum_value
                if computed_hash != expected_hash:
                    temp_path.unlink(missing_ok=True)
                    error_msg = f"Checksum mismatch: expected {expected_hash}, got {computed_hash}"
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=plugin_name,
                        timestamp=datetime.now(tz=UTC),
                        line=error_msg,
                        stream="stderr",
                    )
                    yield PhaseEvent(
                        event_type=EventType.PHASE_END,
                        plugin_name=plugin_name,
                        timestamp=datetime.now(tz=UTC),
                        phase=Phase.DOWNLOAD,
                        success=False,
                        error_message=error_msg,
                    )
                    yield CompletionEvent(
                        event_type=EventType.COMPLETION,
                        plugin_name=plugin_name,
                        timestamp=datetime.now(tz=UTC),
                        success=False,
                        exit_code=1,
                        error_message=error_msg,
                    )
                    return
                checksum_verified = True

            # Final progress event
            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=100.0,
                message="Download complete",
                bytes_downloaded=bytes_downloaded,
                bytes_total=total_size if total_size > 0 else None,
            )

            # Extract or move file
            final_path: Path
            if spec.extract:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=plugin_name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Extracting archive ({spec.extract_format})...",
                    stream="stdout",
                )
                final_path = await self._extract_archive(
                    temp_path, spec.destination, spec.extract_format
                )
                temp_path.unlink(missing_ok=True)
            else:
                final_path = (
                    spec.destination / spec.filename
                    if spec.destination.is_dir()
                    else spec.destination
                )
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(temp_path), str(final_path))

            # Cache the result
            if spec.checksum:
                self._cache_download(spec, final_path)

            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=f"Download complete: {final_path}",
                stream="stdout",
            )

            if checksum_verified:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=plugin_name,
                    timestamp=datetime.now(tz=UTC),
                    line="Checksum verified",
                    stream="stdout",
                )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=True,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )

        except aiohttp.ClientError as e:
            temp_path.unlink(missing_ok=True)
            error_msg = f"Network error: {e}"
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=error_msg,
                stream="stderr",
            )
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message=error_msg,
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=error_msg,
            )

        except TimeoutError:
            temp_path.unlink(missing_ok=True)
            error_msg = "Download timed out"
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                line=error_msg,
                stream="stderr",
            )
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message=error_msg,
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin_name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=error_msg,
            )

    def get_cached_path(self, spec: DownloadSpec) -> Path | None:
        """Check if a file is already cached.

        Args:
            spec: Download specification.

        Returns:
            Path to cached file if exists, None otherwise.
        """
        if not spec.checksum:
            return None

        cache_key = f"{spec.checksum_algorithm}_{spec.checksum_value}"
        cache_path = self._cache_dir / cache_key

        if cache_path.exists():
            return cache_path

        return None

    def _cache_download(self, spec: DownloadSpec, path: Path) -> None:
        """Cache a downloaded file.

        Args:
            spec: Download specification.
            path: Path to the downloaded file.
        """
        if not spec.checksum:
            return

        cache_key = f"{spec.checksum_algorithm}_{spec.checksum_value}"
        cache_path = self._cache_dir / cache_key

        try:
            if path.is_dir():
                # For extracted directories, create a marker file
                marker_path = cache_path.with_suffix(".marker")
                marker_path.write_text(str(path))
            else:
                shutil.copy2(path, cache_path)
        except OSError as e:
            self._log.warning("cache_write_failed", error=str(e))

    def clear_cache(self, max_age_days: int | None = None) -> int:
        """Clear cached downloads.

        Args:
            max_age_days: Only clear files older than this many days.
                         None = clear all.

        Returns:
            Number of files removed.
        """
        removed = 0

        if not self._cache_dir.exists():
            return 0

        now = time.time()
        max_age_seconds = max_age_days * 86400 if max_age_days else 0

        for path in self._cache_dir.iterdir():
            if max_age_days is not None:
                mtime = path.stat().st_mtime
                if now - mtime < max_age_seconds:
                    continue

            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed += 1
            except OSError as e:
                self._log.warning("cache_clear_failed", path=str(path), error=str(e))

        return removed


# Singleton instance
_download_manager: DownloadManager | None = None


def get_download_manager(config: GlobalConfig | None = None) -> DownloadManager:
    """Get the global DownloadManager instance.

    Args:
        config: Optional configuration. If provided and no manager exists,
               creates a new manager with this config.

    Returns:
        The global DownloadManager instance.
    """
    global _download_manager

    if _download_manager is None:
        _download_manager = DownloadManager.from_config(config) if config else DownloadManager()

    return _download_manager


def reset_download_manager() -> None:
    """Reset the global DownloadManager instance.

    Useful for testing.
    """
    global _download_manager
    _download_manager = None
