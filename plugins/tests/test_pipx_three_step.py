"""Tests for pipx three-step upgrade functionality.

These tests cover the three-phase upgrade mechanism:
1. CHECK: Identify outdated main/injected packages in each venv
2. DOWNLOAD: Download main packages to cache (pip includes dependencies)
3. EXECUTE: Install from cache
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from plugins.pipx import (
    DEFAULT_DOWNLOAD_CACHE,
    DEFAULT_PIPX_VENVS,
    OutdatedPackage,
    PipxPlugin,
    VenvMetadata,
)


class TestPipxPluginBasics:
    """Basic plugin property tests."""

    def test_name(self) -> None:
        plugin = PipxPlugin()
        assert plugin.name == "pipx"

    def test_command(self) -> None:
        plugin = PipxPlugin()
        assert plugin.command == "pipx"

    def test_description(self) -> None:
        plugin = PipxPlugin()
        assert "pipx" in plugin.description.lower()

    def test_supports_download(self) -> None:
        plugin = PipxPlugin()
        assert plugin.supports_download is True

    def test_supports_phases(self) -> None:
        plugin = PipxPlugin()
        assert plugin.supports_phases is True

    def test_custom_venvs_dir(self) -> None:
        custom_dir = Path("/custom/venvs")
        plugin = PipxPlugin(venvs_dir=custom_dir)
        assert plugin._venvs_dir == custom_dir

    def test_custom_download_cache(self) -> None:
        custom_cache = Path("/custom/cache")
        plugin = PipxPlugin(download_cache=custom_cache)
        assert plugin._download_cache == custom_cache

    def test_default_paths(self) -> None:
        plugin = PipxPlugin()
        assert plugin._venvs_dir == DEFAULT_PIPX_VENVS
        assert plugin._download_cache == DEFAULT_DOWNLOAD_CACHE


class TestGetInteractiveCommand:
    """Tests for get_interactive_command method."""

    def test_normal_mode(self) -> None:
        plugin = PipxPlugin()
        cmd = plugin.get_interactive_command()
        assert cmd == ["pipx", "upgrade-all"]

    def test_dry_run_mode(self) -> None:
        plugin = PipxPlugin()
        cmd = plugin.get_interactive_command(dry_run=True)
        assert cmd == ["pipx", "list"]


class TestGetPhaseCommands:
    """Tests for get_phase_commands method."""

    def test_returns_all_phases(self) -> None:
        from core.streaming import Phase

        plugin = PipxPlugin()
        commands = plugin.get_phase_commands()

        assert Phase.CHECK in commands
        assert Phase.DOWNLOAD in commands
        assert Phase.EXECUTE in commands

    def test_dry_run_only_check_phase(self) -> None:
        from core.streaming import Phase

        plugin = PipxPlugin()
        commands = plugin.get_phase_commands(dry_run=True)

        assert Phase.CHECK in commands
        # Dry run should not have download/execute phases
        assert Phase.DOWNLOAD not in commands
        assert Phase.EXECUTE not in commands


class TestGetVenvDirs:
    """Tests for _get_venv_dirs method."""

    def test_returns_empty_when_dir_not_exists(self, tmp_path: Path) -> None:
        plugin = PipxPlugin(venvs_dir=tmp_path / "nonexistent")
        assert plugin._get_venv_dirs() == []

    def test_returns_directories_only(self, tmp_path: Path) -> None:
        # Create some venv directories
        (tmp_path / "venv1").mkdir()
        (tmp_path / "venv2").mkdir()
        # Create a file (should be ignored)
        (tmp_path / "somefile.txt").touch()

        plugin = PipxPlugin(venvs_dir=tmp_path)
        venv_dirs = plugin._get_venv_dirs()

        assert len(venv_dirs) == 2
        assert tmp_path / "venv1" in venv_dirs
        assert tmp_path / "venv2" in venv_dirs


class TestGetVenvPython:
    """Tests for _get_venv_python method."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        plugin = PipxPlugin()
        venv_dir = tmp_path / "myvenv"
        python_path = plugin._get_venv_python(venv_dir)

        assert python_path == venv_dir / "bin" / "python"


class TestGetVenvDownloadDir:
    """Tests for _get_venv_download_dir method."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        plugin = PipxPlugin(download_cache=tmp_path)
        download_dir = plugin._get_venv_download_dir("myvenv")

        assert download_dir == tmp_path / "myvenv"


class TestReadVenvMetadata:
    """Tests for _read_venv_metadata method."""

    def test_returns_none_when_file_not_exists(self, tmp_path: Path) -> None:
        plugin = PipxPlugin()
        result = plugin._read_venv_metadata(tmp_path / "nonexistent")
        assert result is None

    def test_parses_main_package(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()

        metadata = {
            "main_package": {
                "package": "requests",
                "package_version": "2.28.0",
            },
            "injected_packages": {},
        }
        (venv_dir / "pipx_metadata.json").write_text(json.dumps(metadata))

        plugin = PipxPlugin()
        result = plugin._read_venv_metadata(venv_dir)

        assert result is not None
        assert result.venv_name == "myvenv"
        assert result.main_package == "requests"
        assert result.main_package_version == "2.28.0"
        assert result.injected_packages == {}

    def test_parses_injected_packages(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()

        metadata = {
            "main_package": {
                "package": "poetry",
                "package_version": "1.5.0",
            },
            "injected_packages": {
                "poetry-plugin-up": {"package_version": "0.9.0"},
                "poetry-plugin-export": {"package_version": "1.4.0"},
            },
        }
        (venv_dir / "pipx_metadata.json").write_text(json.dumps(metadata))

        plugin = PipxPlugin()
        result = plugin._read_venv_metadata(venv_dir)

        assert result is not None
        assert result.main_package == "poetry"
        assert len(result.injected_packages) == 2
        assert result.injected_packages["poetry-plugin-up"] == "0.9.0"
        assert result.injected_packages["poetry-plugin-export"] == "1.4.0"

    def test_handles_invalid_json(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        (venv_dir / "pipx_metadata.json").write_text("not valid json")

        plugin = PipxPlugin()
        result = plugin._read_venv_metadata(venv_dir)
        assert result is None

    def test_returns_none_when_no_main_package(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        (venv_dir / "pipx_metadata.json").write_text(json.dumps({"main_package": {}}))

        plugin = PipxPlugin()
        result = plugin._read_venv_metadata(venv_dir)
        assert result is None


class TestCheckForUpdates:
    """Tests for check_for_updates method."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_venvs(self, tmp_path: Path) -> None:
        plugin = PipxPlugin(venvs_dir=tmp_path / "nonexistent")
        result = await plugin.check_for_updates()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_python_not_found(self, tmp_path: Path) -> None:
        # Create venv directory without python
        (tmp_path / "myvenv").mkdir()

        plugin = PipxPlugin(venvs_dir=tmp_path)
        result = await plugin.check_for_updates()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_metadata_not_found(self, tmp_path: Path) -> None:
        # Create venv with python but no metadata
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        plugin = PipxPlugin(venvs_dir=tmp_path)
        result = await plugin.check_for_updates()
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_to_main_package_only(self, tmp_path: Path) -> None:
        """Only main package updates should be returned, not transitive deps."""
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        # Create metadata with main package "requests"
        metadata = {
            "main_package": {"package": "requests", "package_version": "2.28.0"},
            "injected_packages": {},
        }
        (venv_dir / "pipx_metadata.json").write_text(json.dumps(metadata))

        plugin = PipxPlugin(venvs_dir=tmp_path)

        # pip list --outdated returns both main package and transitive deps
        outdated_json = json.dumps(
            [
                {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},
                {"name": "urllib3", "version": "1.26.0", "latest_version": "2.0.0"},
                {"name": "certifi", "version": "2023.1.1", "latest_version": "2024.1.1"},
            ]
        )

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, outdated_json, "")
            result = await plugin.check_for_updates()

        # Only main package should be returned
        assert len(result) == 1
        assert result[0].package_name == "requests"
        assert result[0].is_main_package is True

    @pytest.mark.asyncio
    async def test_includes_injected_packages(self, tmp_path: Path) -> None:
        """Injected packages should also be tracked for updates."""
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        metadata = {
            "main_package": {"package": "poetry", "package_version": "1.5.0"},
            "injected_packages": {
                "poetry-plugin-up": {"package_version": "0.8.0"},
            },
        }
        (venv_dir / "pipx_metadata.json").write_text(json.dumps(metadata))

        plugin = PipxPlugin(venvs_dir=tmp_path)

        outdated_json = json.dumps(
            [
                {"name": "poetry", "version": "1.5.0", "latest_version": "1.6.0"},
                {"name": "poetry-plugin-up", "version": "0.8.0", "latest_version": "0.9.0"},
                {"name": "tomlkit", "version": "0.11.0", "latest_version": "0.12.0"},
            ]
        )

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, outdated_json, "")
            result = await plugin.check_for_updates()

        # Main + injected packages
        assert len(result) == 2
        pkg_names = {p.package_name for p in result}
        assert "poetry" in pkg_names
        assert "poetry-plugin-up" in pkg_names

        # Check is_main_package flag
        main_pkg = next(p for p in result if p.package_name == "poetry")
        injected_pkg = next(p for p in result if p.package_name == "poetry-plugin-up")
        assert main_pkg.is_main_package is True
        assert injected_pkg.is_main_package is False

    @pytest.mark.asyncio
    async def test_handles_pip_list_failure(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        metadata = {
            "main_package": {"package": "requests", "package_version": "2.28.0"},
            "injected_packages": {},
        }
        (venv_dir / "pipx_metadata.json").write_text(json.dumps(metadata))

        plugin = PipxPlugin(venvs_dir=tmp_path)

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "pip error")
            result = await plugin.check_for_updates()

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        metadata = {
            "main_package": {"package": "requests", "package_version": "2.28.0"},
            "injected_packages": {},
        }
        (venv_dir / "pipx_metadata.json").write_text(json.dumps(metadata))

        plugin = PipxPlugin(venvs_dir=tmp_path)

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "not valid json", "")
            result = await plugin.check_for_updates()

        assert result == []


class TestDownloadUpdates:
    """Tests for download_updates method."""

    @pytest.mark.asyncio
    async def test_returns_success_when_no_packages(self) -> None:
        plugin = PipxPlugin()
        plugin._outdated_packages = []

        success, msg = await plugin.download_updates()

        assert success is True
        assert "No packages to download" in msg

    @pytest.mark.asyncio
    async def test_downloads_packages(self, tmp_path: Path) -> None:
        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)
        plugin._outdated_packages = [
            OutdatedPackage(
                venv_name="myvenv",
                package_name="requests",
                current_version="2.28.0",
                latest_version="2.31.0",
            )
        ]

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "Downloaded requests-2.31.0", "")
            success, msg = await plugin.download_updates()

        assert success is True
        assert "successfully" in msg.lower()
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_download_failure(self, tmp_path: Path) -> None:
        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)
        plugin._outdated_packages = [
            OutdatedPackage(
                venv_name="myvenv",
                package_name="requests",
                current_version="2.28.0",
                latest_version="2.31.0",
            )
        ]

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "Network error")
            success, msg = await plugin.download_updates()

        assert success is False
        assert "Failed to download" in msg


class TestInstallUpdates:
    """Tests for install_updates method."""

    @pytest.mark.asyncio
    async def test_returns_success_when_no_packages(self) -> None:
        plugin = PipxPlugin()
        plugin._outdated_packages = []

        success, msg = await plugin.install_updates()

        assert success is True
        assert "No packages to install" in msg

    @pytest.mark.asyncio
    async def test_installs_packages(self, tmp_path: Path) -> None:
        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        # Create download cache
        download_dir = cache_dir / "myvenv"
        download_dir.mkdir(parents=True)

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)
        plugin._outdated_packages = [
            OutdatedPackage(
                venv_name="myvenv",
                package_name="requests",
                current_version="2.28.0",
                latest_version="2.31.0",
            )
        ]

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "Installed requests-2.31.0", "")
            success, msg = await plugin.install_updates()

        assert success is True
        assert "Successfully installed 1 packages" in msg

    @pytest.mark.asyncio
    async def test_handles_missing_download_dir(self, tmp_path: Path) -> None:
        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)
        plugin._outdated_packages = [
            OutdatedPackage(
                venv_name="myvenv",
                package_name="requests",
                current_version="2.28.0",
                latest_version="2.31.0",
            )
        ]

        success, msg = await plugin.install_updates()

        assert success is False
        assert "Download directory missing" in msg

    @pytest.mark.asyncio
    async def test_handles_install_failure(self, tmp_path: Path) -> None:
        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        # Create download cache
        download_dir = cache_dir / "myvenv"
        download_dir.mkdir(parents=True)

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)
        plugin._outdated_packages = [
            OutdatedPackage(
                venv_name="myvenv",
                package_name="requests",
                current_version="2.28.0",
                latest_version="2.31.0",
            )
        ]

        with patch.object(plugin, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "Installation error")
            success, msg = await plugin.install_updates()

        assert success is False
        assert "Failed to install" in msg


class TestCleanup:
    """Tests for cleanup methods."""

    def test_cleanup_venv_cache(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        venv_cache = cache_dir / "myvenv"
        venv_cache.mkdir(parents=True)
        (venv_cache / "package.whl").touch()

        plugin = PipxPlugin(download_cache=cache_dir)
        plugin._cleanup_venv_cache("myvenv")

        assert not venv_cache.exists()

    def test_cleanup_venv_cache_nonexistent(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        plugin = PipxPlugin(download_cache=cache_dir)

        # Should not raise
        plugin._cleanup_venv_cache("nonexistent")

    def test_cleanup_all_cache(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "venv1").mkdir()
        (cache_dir / "venv2").mkdir()

        plugin = PipxPlugin(download_cache=cache_dir)
        plugin.cleanup_all_cache()

        assert not cache_dir.exists()

    def test_cleanup_all_cache_nonexistent(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "nonexistent"
        plugin = PipxPlugin(download_cache=cache_dir)

        # Should not raise
        plugin.cleanup_all_cache()


class TestCountUpdatedPackages:
    """Tests for _count_updated_packages method."""

    def test_counts_upgraded_pattern(self) -> None:
        plugin = PipxPlugin()
        output = """
        upgraded requests from 2.28.0 to 2.31.0
        upgraded urllib3 from 1.26.0 to 2.0.0
        """
        count = plugin._count_updated_packages(output)
        assert count == 2

    def test_counts_package_upgraded_pattern(self) -> None:
        plugin = PipxPlugin()
        output = """
        Package 'requests' upgraded
        Package 'urllib3' upgraded
        """
        count = plugin._count_updated_packages(output)
        assert count == 2

    def test_returns_zero_for_no_updates(self) -> None:
        plugin = PipxPlugin()
        output = "All packages are up to date"
        count = plugin._count_updated_packages(output)
        assert count == 0


class TestOutdatedPackageDataclass:
    """Tests for OutdatedPackage dataclass."""

    def test_creation(self) -> None:
        pkg = OutdatedPackage(
            venv_name="myvenv",
            package_name="requests",
            current_version="2.28.0",
            latest_version="2.31.0",
        )
        assert pkg.venv_name == "myvenv"
        assert pkg.package_name == "requests"
        assert pkg.current_version == "2.28.0"
        assert pkg.latest_version == "2.31.0"
        assert pkg.is_main_package is True  # Default
        assert pkg.download_size_bytes is None

    def test_with_download_size(self) -> None:
        pkg = OutdatedPackage(
            venv_name="myvenv",
            package_name="requests",
            current_version="2.28.0",
            latest_version="2.31.0",
            download_size_bytes=1024000,
        )
        assert pkg.download_size_bytes == 1024000

    def test_injected_package(self) -> None:
        pkg = OutdatedPackage(
            venv_name="myvenv",
            package_name="poetry-plugin-up",
            current_version="0.8.0",
            latest_version="0.9.0",
            is_main_package=False,
        )
        assert pkg.is_main_package is False


class TestVenvMetadataDataclass:
    """Tests for VenvMetadata dataclass."""

    def test_creation(self) -> None:
        meta = VenvMetadata(
            venv_name="myvenv",
            main_package="requests",
            main_package_version="2.28.0",
        )
        assert meta.venv_name == "myvenv"
        assert meta.main_package == "requests"
        assert meta.main_package_version == "2.28.0"
        assert meta.injected_packages == {}

    def test_with_injected_packages(self) -> None:
        meta = VenvMetadata(
            venv_name="poetry",
            main_package="poetry",
            main_package_version="1.5.0",
            injected_packages={"poetry-plugin-up": "0.9.0"},
        )
        assert meta.injected_packages == {"poetry-plugin-up": "0.9.0"}


class TestExecuteUpdateStreaming:
    """Tests for _execute_update_streaming method."""

    @pytest.mark.asyncio
    async def test_emits_all_phases_when_updates_available(self, tmp_path: Path) -> None:
        from core.streaming import CompletionEvent, EventType, Phase, PhaseEvent

        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)

        # Mock the methods
        with (
            patch.object(
                plugin,
                "check_for_updates",
                new_callable=AsyncMock,
                return_value=[
                    OutdatedPackage(
                        venv_name="myvenv",
                        package_name="requests",
                        current_version="2.28.0",
                        latest_version="2.31.0",
                    )
                ],
            ),
            patch.object(
                plugin,
                "download_updates",
                new_callable=AsyncMock,
                return_value=(True, "Downloaded successfully"),
            ),
            patch.object(
                plugin,
                "install_updates",
                new_callable=AsyncMock,
                return_value=(True, "Installed successfully"),
            ),
        ):
            events = []
            async for event in plugin._execute_update_streaming():
                events.append(event)

        # Check we have phase events for all three phases
        phase_starts = [
            e for e in events if isinstance(e, PhaseEvent) and e.event_type == EventType.PHASE_START
        ]
        phase_ends = [
            e for e in events if isinstance(e, PhaseEvent) and e.event_type == EventType.PHASE_END
        ]

        assert len(phase_starts) == 3
        assert len(phase_ends) == 3

        # Check phases in order
        assert phase_starts[0].phase == Phase.CHECK
        assert phase_starts[1].phase == Phase.DOWNLOAD
        assert phase_starts[2].phase == Phase.EXECUTE

        # Check completion event
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1
        assert completion_events[0].success is True
        assert completion_events[0].packages_updated == 1

    @pytest.mark.asyncio
    async def test_stops_early_when_no_updates(self, tmp_path: Path) -> None:
        from core.streaming import CompletionEvent, Phase, PhaseEvent

        plugin = PipxPlugin(venvs_dir=tmp_path / "nonexistent")

        events = []
        async for event in plugin._execute_update_streaming():
            events.append(event)

        # Should only have CHECK phase
        phase_starts = [e for e in events if isinstance(e, PhaseEvent) and e.phase == Phase.CHECK]
        assert len(phase_starts) >= 1

        # No DOWNLOAD or EXECUTE phases
        download_phases = [
            e for e in events if isinstance(e, PhaseEvent) and e.phase == Phase.DOWNLOAD
        ]
        assert len(download_phases) == 0

        # Completion should be successful
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1
        assert completion_events[0].success is True
        assert completion_events[0].packages_updated == 0

    @pytest.mark.asyncio
    async def test_stops_on_download_failure(self, tmp_path: Path) -> None:
        from core.streaming import CompletionEvent, Phase, PhaseEvent

        venvs_dir = tmp_path / "venvs"
        cache_dir = tmp_path / "cache"
        venv_dir = venvs_dir / "myvenv"
        venv_dir.mkdir(parents=True)
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        plugin = PipxPlugin(venvs_dir=venvs_dir, download_cache=cache_dir)

        with (
            patch.object(
                plugin,
                "check_for_updates",
                new_callable=AsyncMock,
                return_value=[
                    OutdatedPackage(
                        venv_name="myvenv",
                        package_name="requests",
                        current_version="2.28.0",
                        latest_version="2.31.0",
                    )
                ],
            ),
            patch.object(
                plugin,
                "download_updates",
                new_callable=AsyncMock,
                return_value=(False, "Download failed"),
            ),
        ):
            events = []
            async for event in plugin._execute_update_streaming():
                events.append(event)

        # Should have CHECK and DOWNLOAD phases, but not EXECUTE
        execute_phases = [
            e for e in events if isinstance(e, PhaseEvent) and e.phase == Phase.EXECUTE
        ]
        assert len(execute_phases) == 0

        # Completion should be failure
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1
        assert completion_events[0].success is False
        assert "Download failed" in (completion_events[0].error_message or "")
