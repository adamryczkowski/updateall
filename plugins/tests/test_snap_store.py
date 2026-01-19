"""Tests for snap_store module - Snap Store API and cache management."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.snap_store import (
    SnapDownloadInfo,
    _decode_chunked,
    _get_architecture,
    cleanup_corrupted_cache_entries,
    is_cache_complete,
    verify_sha3_384,
)


class TestSnapDownloadInfo:
    """Tests for SnapDownloadInfo dataclass."""

    def test_cache_path(self) -> None:
        """Test cache_path property returns correct path."""
        info = SnapDownloadInfo(
            name="firefox",
            snap_id="abc123",
            download_url="https://example.com/firefox.snap",
            sha3_384="deadbeef" * 12,  # 96 hex chars
            size=100_000_000,
            revision=3836,
        )
        assert info.cache_path == Path("/var/lib/snapd/cache") / ("deadbeef" * 12)

    def test_format_size_bytes(self) -> None:
        """Test format_size for bytes."""
        info = SnapDownloadInfo(
            name="test",
            snap_id="id",
            download_url="url",
            sha3_384="a" * 96,
            size=500,
            revision=1,
        )
        assert info.format_size() == "500 B"

    def test_format_size_kilobytes(self) -> None:
        """Test format_size for kilobytes."""
        info = SnapDownloadInfo(
            name="test",
            snap_id="id",
            download_url="url",
            sha3_384="a" * 96,
            size=5 * 1024,
            revision=1,
        )
        assert info.format_size() == "5.0 KB"

    def test_format_size_megabytes(self) -> None:
        """Test format_size for megabytes."""
        info = SnapDownloadInfo(
            name="test",
            snap_id="id",
            download_url="url",
            sha3_384="a" * 96,
            size=150 * 1024 * 1024,
            revision=1,
        )
        assert info.format_size() == "150.0 MB"

    def test_format_size_gigabytes(self) -> None:
        """Test format_size for gigabytes."""
        info = SnapDownloadInfo(
            name="test",
            snap_id="id",
            download_url="url",
            sha3_384="a" * 96,
            size=2 * 1024 * 1024 * 1024,
            revision=1,
        )
        assert info.format_size() == "2.00 GB"


class TestGetArchitecture:
    """Tests for _get_architecture function."""

    def test_x86_64_to_amd64(self) -> None:
        """Test x86_64 is mapped to amd64."""
        with patch("platform.machine", return_value="x86_64"):
            assert _get_architecture() == "amd64"

    def test_aarch64_to_arm64(self) -> None:
        """Test aarch64 is mapped to arm64."""
        with patch("platform.machine", return_value="aarch64"):
            assert _get_architecture() == "arm64"

    def test_armv7l_to_armhf(self) -> None:
        """Test armv7l is mapped to armhf."""
        with patch("platform.machine", return_value="armv7l"):
            assert _get_architecture() == "armhf"

    def test_unknown_passthrough(self) -> None:
        """Test unknown architectures pass through unchanged."""
        with patch("platform.machine", return_value="riscv64"):
            assert _get_architecture() == "riscv64"


class TestDecodeChunked:
    """Tests for _decode_chunked function."""

    def test_simple_chunk(self) -> None:
        """Test decoding a simple chunked response."""
        # "Hello" in chunked encoding
        data = b"5\r\nHello\r\n0\r\n\r\n"
        assert _decode_chunked(data) == b"Hello"

    def test_multiple_chunks(self) -> None:
        """Test decoding multiple chunks."""
        data = b"5\r\nHello\r\n6\r\n World\r\n0\r\n\r\n"
        assert _decode_chunked(data) == b"Hello World"

    def test_empty_response(self) -> None:
        """Test decoding empty chunked response."""
        data = b"0\r\n\r\n"
        assert _decode_chunked(data) == b""


class TestVerifySha3384:
    """Tests for verify_sha3_384 function."""

    def test_valid_hash(self) -> None:
        """Test verification with valid hash."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            content = b"test content for hashing"
            f.write(content)
            f.flush()

            expected_hash = hashlib.sha3_384(content).hexdigest()
            assert verify_sha3_384(Path(f.name), expected_hash) is True

            Path(f.name).unlink()

    def test_invalid_hash(self) -> None:
        """Test verification with invalid hash."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()

            assert verify_sha3_384(Path(f.name), "wrong" * 24) is False

            Path(f.name).unlink()

    def test_missing_file(self) -> None:
        """Test verification with missing file."""
        assert verify_sha3_384(Path("/nonexistent/file"), "a" * 96) is False


class TestCleanupCorruptedCacheEntries:
    """Tests for cleanup_corrupted_cache_entries function."""

    def test_removes_corrupted_entries(self) -> None:
        """Test that corrupted cache entries are removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            # Create a "corrupted" cache file
            test_hash = "a" * 96
            cache_file = cache_dir / test_hash
            cache_file.write_bytes(b"corrupted content")

            info = SnapDownloadInfo(
                name="test-snap",
                snap_id="id",
                download_url="url",
                sha3_384=test_hash,
                size=100,
                revision=1,
            )

            with patch("plugins.snap_store.SNAP_CACHE_DIR", cache_dir):
                removed = cleanup_corrupted_cache_entries([info])

            assert removed == ["test-snap"]
            assert not cache_file.exists()

    def test_keeps_valid_entries(self) -> None:
        """Test that valid cache entries are kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            # Create a valid cache file
            content = b"valid content"
            test_hash = hashlib.sha3_384(content).hexdigest()
            cache_file = cache_dir / test_hash
            cache_file.write_bytes(content)

            info = SnapDownloadInfo(
                name="test-snap",
                snap_id="id",
                download_url="url",
                sha3_384=test_hash,
                size=len(content),
                revision=1,
            )

            with patch("plugins.snap_store.SNAP_CACHE_DIR", cache_dir):
                removed = cleanup_corrupted_cache_entries([info])

            assert removed == []
            assert cache_file.exists()


class TestIsCacheComplete:
    """Tests for is_cache_complete function."""

    def test_all_cached(self) -> None:
        """Test when all snaps are cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            content = b"snap content"
            test_hash = hashlib.sha3_384(content).hexdigest()
            cache_file = cache_dir / test_hash
            cache_file.write_bytes(content)

            info = SnapDownloadInfo(
                name="test-snap",
                snap_id="id",
                download_url="url",
                sha3_384=test_hash,
                size=len(content),
                revision=1,
            )

            with patch("plugins.snap_store.SNAP_CACHE_DIR", cache_dir):
                complete, missing = is_cache_complete([info])

            assert complete is True
            assert missing == []

    def test_some_missing(self) -> None:
        """Test when some snaps are not cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            info = SnapDownloadInfo(
                name="missing-snap",
                snap_id="id",
                download_url="url",
                sha3_384="b" * 96,
                size=100,
                revision=1,
            )

            with patch("plugins.snap_store.SNAP_CACHE_DIR", cache_dir):
                complete, missing = is_cache_complete([info])

            assert complete is False
            assert missing == ["missing-snap"]


class TestGetRefreshCandidates:
    """Tests for get_refresh_candidates function."""

    @pytest.mark.asyncio
    async def test_no_snaps_installed(self) -> None:
        """Test when no snaps are installed."""
        from plugins.snap_store import get_refresh_candidates

        with patch("plugins.snap_store._get_current_snaps_sync", return_value=[]):
            candidates = await get_refresh_candidates()

        assert candidates == []

    @pytest.mark.asyncio
    async def test_parses_store_response(self) -> None:
        """Test parsing of Snap Store API response."""
        from plugins.snap_store import get_refresh_candidates

        mock_snaps = [
            {
                "id": "snap-id-1",
                "name": "firefox",
                "revision": 100,
                "tracking-channel": "latest/stable",
            }
        ]

        mock_response_data = {
            "results": [
                {
                    "result": "refresh",
                    "snap-id": "snap-id-1",
                    "name": "firefox",
                    "snap": {
                        "download": {
                            "url": "https://example.com/firefox.snap",
                            "sha3-384": "a" * 96,
                            "size": 100_000_000,
                        },
                        "revision": 101,
                        "version": "120.0",
                    },
                }
            ]
        }

        # Create proper async context manager mocks
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=mock_response_data)

        # post() returns an async context manager
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        # session is an async context manager, session.post() is a regular method
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        # ClientSession() returns an async context manager
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("plugins.snap_store._get_current_snaps_sync", return_value=mock_snaps),
            patch("aiohttp.ClientSession", return_value=mock_session_cm),
        ):
            candidates = await get_refresh_candidates()

        assert len(candidates) == 1
        assert candidates[0].name == "firefox"
        assert candidates[0].revision == 101
        assert candidates[0].current_revision == 100
        assert candidates[0].version == "120.0"
