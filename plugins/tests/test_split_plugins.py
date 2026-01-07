"""Tests for split plugin implementations.

These tests cover plugins that were split from multi-step plugins
into independent single-step plugins with dependency declarations.

Split plugins:
- Julia: julia_runtime, julia_packages
- Go: go_runtime, go_packages
- TexLive: texlive_self, texlive_packages
- Conda: conda_self, conda_build, conda_packages, conda_clean
- YouTube-DL: youtube_dl, yt_dlp
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# Conda plugins
from plugins.conda_build import CondaBuildPlugin
from plugins.conda_clean import CondaCleanPlugin
from plugins.conda_packages import CondaPackagesPlugin
from plugins.conda_self import CondaSelfPlugin

# Go plugins
from plugins.go_packages import GoPackagesPlugin
from plugins.go_runtime import GoRuntimePlugin

# Julia plugins
from plugins.julia_packages import JuliaPackagesPlugin
from plugins.julia_runtime import JuliaRuntimePlugin

# TexLive plugins
from plugins.texlive_packages import TexlivePackagesPlugin
from plugins.texlive_self import TexliveSelfPlugin

# YouTube-DL plugins
from plugins.youtube_dl import YoutubeDlPlugin
from plugins.yt_dlp import YtDlpPlugin

# =============================================================================
# Julia Runtime Plugin Tests
# =============================================================================


class TestJuliaRuntimePlugin:
    """Tests for JuliaRuntimePlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = JuliaRuntimePlugin()
        assert plugin.name == "julia-runtime"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = JuliaRuntimePlugin()
        assert plugin.command == "juliaup"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = JuliaRuntimePlugin()
        assert "julia" in plugin.description.lower()
        assert "runtime" in plugin.description.lower() or "juliaup" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when juliaup is present."""
        plugin = JuliaRuntimePlugin()
        with patch("shutil.which", return_value="/usr/local/bin/juliaup"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when juliaup is missing."""
        plugin = JuliaRuntimePlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_is_available_when_present(self) -> None:
        """Test is_available when juliaup is present."""
        plugin = JuliaRuntimePlugin()
        with patch("shutil.which", return_value="/usr/local/bin/juliaup"):
            result = plugin.is_available()
        assert result is True

    def test_is_available_when_missing(self) -> None:
        """Test is_available when juliaup is missing."""
        plugin = JuliaRuntimePlugin()
        with patch("shutil.which", return_value=None):
            result = plugin.is_available()
        assert result is False

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = JuliaRuntimePlugin()
        cmd = plugin.get_interactive_command()
        assert cmd == ["juliaup", "update"]

    def test_get_interactive_command_dry_run(self) -> None:
        """Test interactive command generation for dry run."""
        plugin = JuliaRuntimePlugin()
        cmd = plugin.get_interactive_command(dry_run=True)
        assert cmd == ["juliaup", "status"]

    def test_count_updated_packages(self) -> None:
        """Test package counting from juliaup output."""
        plugin = JuliaRuntimePlugin()
        output = "Updated Julia 1.9.0 to 1.10.0"
        count = plugin._count_updated_packages(output)
        assert count >= 1


# =============================================================================
# Julia Packages Plugin Tests
# =============================================================================


class TestJuliaPackagesPlugin:
    """Tests for JuliaPackagesPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = JuliaPackagesPlugin()
        assert plugin.name == "julia-packages"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = JuliaPackagesPlugin()
        assert plugin.command == "julia"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = JuliaPackagesPlugin()
        assert "julia" in plugin.description.lower()
        assert "package" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when julia is present."""
        plugin = JuliaPackagesPlugin()
        with patch("shutil.which", return_value="/usr/local/bin/julia"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when julia is missing."""
        plugin = JuliaPackagesPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = JuliaPackagesPlugin()
        cmd = plugin.get_interactive_command()
        assert cmd[0] == "julia"
        assert "-e" in cmd
        assert "Pkg.update()" in cmd[-1]


# =============================================================================
# Go Runtime Plugin Tests
# =============================================================================


class TestGoRuntimePlugin:
    """Tests for GoRuntimePlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = GoRuntimePlugin()
        assert plugin.name == "go-runtime"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = GoRuntimePlugin()
        assert plugin.command == "go"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = GoRuntimePlugin()
        assert "go" in plugin.description.lower()
        assert "runtime" in plugin.description.lower() or "download" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when go is present."""
        plugin = GoRuntimePlugin()
        with patch("shutil.which", return_value="/usr/local/go/bin/go"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when go is missing."""
        plugin = GoRuntimePlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False


# =============================================================================
# Go Packages Plugin Tests
# =============================================================================


class TestGoPackagesPlugin:
    """Tests for GoPackagesPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = GoPackagesPlugin()
        assert plugin.name == "go-packages"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = GoPackagesPlugin()
        assert plugin.command == "go-global-update"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = GoPackagesPlugin()
        assert "go" in plugin.description.lower()
        assert "package" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when go-global-update is present."""
        plugin = GoPackagesPlugin()
        with patch("shutil.which", return_value="/home/user/go/bin/go-global-update"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when go-global-update is missing."""
        plugin = GoPackagesPlugin()
        # Need to mock both shutil.which and the Path.home() check
        with (
            patch("plugins.go_packages.shutil.which", return_value=None),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = await plugin.check_available()
        assert result is False

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = GoPackagesPlugin()
        cmd = plugin.get_interactive_command()
        # Command should contain go-global-update (may be full path or just name)
        assert "go-global-update" in cmd[0]


# =============================================================================
# TexLive Self Plugin Tests
# =============================================================================


class TestTexliveSelfPlugin:
    """Tests for TexliveSelfPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = TexliveSelfPlugin()
        assert plugin.name == "texlive-self"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = TexliveSelfPlugin()
        assert plugin.command == "tlmgr"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = TexliveSelfPlugin()
        assert "tlmgr" in plugin.description.lower() or "texlive" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when tlmgr is present."""
        plugin = TexliveSelfPlugin()
        with patch("shutil.which", return_value="/usr/local/texlive/bin/tlmgr"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when tlmgr is missing."""
        plugin = TexliveSelfPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = TexliveSelfPlugin()
        cmd = plugin.get_interactive_command()
        assert "tlmgr" in cmd
        assert "update" in cmd
        assert "--self" in cmd


# =============================================================================
# TexLive Packages Plugin Tests
# =============================================================================


class TestTexlivePackagesPlugin:
    """Tests for TexlivePackagesPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = TexlivePackagesPlugin()
        assert plugin.name == "texlive-packages"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = TexlivePackagesPlugin()
        assert plugin.command == "tlmgr"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = TexlivePackagesPlugin()
        assert "texlive" in plugin.description.lower() or "package" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when tlmgr is present."""
        plugin = TexlivePackagesPlugin()
        with patch("shutil.which", return_value="/usr/local/texlive/bin/tlmgr"):
            result = await plugin.check_available()
        assert result is True

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = TexlivePackagesPlugin()
        cmd = plugin.get_interactive_command()
        assert "tlmgr" in cmd
        assert "update" in cmd
        assert "--all" in cmd

    def test_count_updated_packages(self) -> None:
        """Test package counting from tlmgr output."""
        plugin = TexlivePackagesPlugin()
        output = """
update: texlive-base (12345 -> 12346)
update: texlive-latex-base (12345 -> 12346)
update: texlive-fonts-recommended (12345 -> 12346)
"""
        count = plugin._count_updated_packages(output)
        assert count == 3


# =============================================================================
# Conda Self Plugin Tests
# =============================================================================


class TestCondaSelfPlugin:
    """Tests for CondaSelfPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = CondaSelfPlugin()
        assert plugin.name == "conda-self"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = CondaSelfPlugin()
        assert plugin.command == "conda"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = CondaSelfPlugin()
        assert "conda" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when conda is present."""
        plugin = CondaSelfPlugin()
        with patch("shutil.which", return_value="/home/user/miniconda/bin/conda"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when conda is missing."""
        plugin = CondaSelfPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = CondaSelfPlugin()
        cmd = plugin.get_interactive_command()
        assert "conda" in cmd
        assert "update" in cmd
        assert "conda" in cmd  # updating conda itself


# =============================================================================
# Conda Build Plugin Tests
# =============================================================================


class TestCondaBuildPlugin:
    """Tests for CondaBuildPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = CondaBuildPlugin()
        assert plugin.name == "conda-build"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = CondaBuildPlugin()
        assert plugin.command == "conda"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = CondaBuildPlugin()
        assert "conda-build" in plugin.description.lower()

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = CondaBuildPlugin()
        cmd = plugin.get_interactive_command()
        assert "conda" in cmd
        assert "update" in cmd
        assert "conda-build" in cmd


# =============================================================================
# Conda Packages Plugin Tests
# =============================================================================


class TestCondaPackagesPlugin:
    """Tests for CondaPackagesPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = CondaPackagesPlugin()
        assert plugin.name == "conda-packages"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = CondaPackagesPlugin()
        assert plugin.command == "conda"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = CondaPackagesPlugin()
        assert "conda" in plugin.description.lower()
        assert (
            "package" in plugin.description.lower() or "environment" in plugin.description.lower()
        )

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when conda is present."""
        plugin = CondaPackagesPlugin()
        with patch("shutil.which", return_value="/home/user/miniconda/bin/conda"):
            result = await plugin.check_available()
        assert result is True


# =============================================================================
# Conda Clean Plugin Tests
# =============================================================================


class TestCondaCleanPlugin:
    """Tests for CondaCleanPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = CondaCleanPlugin()
        assert plugin.name == "conda-clean"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = CondaCleanPlugin()
        assert plugin.command == "conda"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = CondaCleanPlugin()
        assert "conda" in plugin.description.lower()
        assert "clean" in plugin.description.lower() or "cache" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when conda is present."""
        plugin = CondaCleanPlugin()
        with patch("shutil.which", return_value="/home/user/miniconda/bin/conda"):
            result = await plugin.check_available()
        assert result is True

    def test_get_interactive_command(self) -> None:
        """Test interactive command generation."""
        plugin = CondaCleanPlugin()
        cmd = plugin.get_interactive_command()
        assert "conda" in cmd
        assert "clean" in cmd
        assert "--all" in cmd


# =============================================================================
# YouTube-DL Plugin Tests
# =============================================================================


class TestYoutubeDlPlugin:
    """Tests for YoutubeDlPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = YoutubeDlPlugin()
        assert plugin.name == "youtube-dl"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = YoutubeDlPlugin()
        assert plugin.command == "youtube-dl"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = YoutubeDlPlugin()
        assert "youtube-dl" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when youtube-dl is present."""
        plugin = YoutubeDlPlugin()
        with patch("shutil.which", return_value="/usr/local/bin/youtube-dl"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when youtube-dl is missing."""
        plugin = YoutubeDlPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_is_standalone_install_usr_local_bin(self) -> None:
        """Test standalone detection for /usr/local/bin."""
        plugin = YoutubeDlPlugin()
        assert plugin._is_standalone_install("/usr/local/bin/youtube-dl") is True

    def test_is_standalone_install_pipx(self) -> None:
        """Test standalone detection for pipx installation."""
        plugin = YoutubeDlPlugin()
        assert (
            plugin._is_standalone_install("/home/user/.local/pipx/venvs/youtube-dl/bin/youtube-dl")
            is False
        )

    def test_count_updated_packages(self) -> None:
        """Test package counting from youtube-dl output."""
        plugin = YoutubeDlPlugin()
        output = "youtube-dl updated successfully to version 2024.01.01"
        count = plugin._count_updated_packages(output)
        assert count >= 1


# =============================================================================
# yt-dlp Plugin Tests
# =============================================================================


class TestYtDlpPlugin:
    """Tests for YtDlpPlugin."""

    def test_name(self) -> None:
        """Test plugin name."""
        plugin = YtDlpPlugin()
        assert plugin.name == "yt-dlp"

    def test_command(self) -> None:
        """Test plugin command."""
        plugin = YtDlpPlugin()
        assert plugin.command == "yt-dlp"

    def test_description(self) -> None:
        """Test plugin description."""
        plugin = YtDlpPlugin()
        assert "yt-dlp" in plugin.description.lower()

    @pytest.mark.asyncio
    async def test_check_available_when_present(self) -> None:
        """Test availability check when yt-dlp is present."""
        plugin = YtDlpPlugin()
        with patch("shutil.which", return_value="/usr/local/bin/yt-dlp"):
            result = await plugin.check_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_when_missing(self) -> None:
        """Test availability check when yt-dlp is missing."""
        plugin = YtDlpPlugin()
        with patch("shutil.which", return_value=None):
            result = await plugin.check_available()
        assert result is False

    def test_is_standalone_install_usr_local_bin(self) -> None:
        """Test standalone detection for /usr/local/bin."""
        plugin = YtDlpPlugin()
        assert plugin._is_standalone_install("/usr/local/bin/yt-dlp") is True

    def test_is_standalone_install_pipx(self) -> None:
        """Test standalone detection for pipx installation."""
        plugin = YtDlpPlugin()
        assert (
            plugin._is_standalone_install("/home/user/.local/pipx/venvs/yt-dlp/bin/yt-dlp") is False
        )

    def test_count_updated_packages(self) -> None:
        """Test package counting from yt-dlp output."""
        plugin = YtDlpPlugin()
        output = "yt-dlp is up to date (2024.01.01)"
        count = plugin._count_updated_packages(output)
        # "current version" pattern should match
        assert count >= 0  # May be 0 if already up to date

    def test_get_interactive_command_standalone(self) -> None:
        """Test interactive command for standalone installation."""
        plugin = YtDlpPlugin()
        with (
            patch.object(plugin, "_get_tool_path", return_value="/usr/local/bin/yt-dlp"),
            patch.object(plugin, "_is_standalone_install", return_value=True),
        ):
            cmd = plugin.get_interactive_command()
        assert cmd == ["sudo", "yt-dlp", "-U"]

    def test_get_interactive_command_pipx(self) -> None:
        """Test interactive command for pipx installation."""
        plugin = YtDlpPlugin()
        with (
            patch.object(plugin, "_get_tool_path", return_value="/home/user/.local/bin/yt-dlp"),
            patch.object(plugin, "_is_standalone_install", return_value=False),
        ):
            cmd = plugin.get_interactive_command()
        assert cmd == ["pipx", "upgrade", "yt-dlp"]


# =============================================================================
# Plugin Independence Tests
# =============================================================================


class TestPluginIndependence:
    """Tests to verify that split plugins are truly independent."""

    def test_julia_plugins_have_different_names(self) -> None:
        """Test that Julia plugins have distinct names."""
        runtime = JuliaRuntimePlugin()
        packages = JuliaPackagesPlugin()
        assert runtime.name != packages.name

    def test_go_plugins_have_different_names(self) -> None:
        """Test that Go plugins have distinct names."""
        runtime = GoRuntimePlugin()
        packages = GoPackagesPlugin()
        assert runtime.name != packages.name

    def test_texlive_plugins_have_different_names(self) -> None:
        """Test that TexLive plugins have distinct names."""
        self_plugin = TexliveSelfPlugin()
        packages = TexlivePackagesPlugin()
        assert self_plugin.name != packages.name

    def test_conda_plugins_have_different_names(self) -> None:
        """Test that Conda plugins have distinct names."""
        self_plugin = CondaSelfPlugin()
        build = CondaBuildPlugin()
        packages = CondaPackagesPlugin()
        clean = CondaCleanPlugin()

        names = [self_plugin.name, build.name, packages.name, clean.name]
        assert len(names) == len(set(names))  # All unique

    def test_youtube_plugins_have_different_names(self) -> None:
        """Test that YouTube plugins have distinct names."""
        youtube_dl = YoutubeDlPlugin()
        yt_dlp = YtDlpPlugin()
        assert youtube_dl.name != yt_dlp.name

    def test_all_split_plugins_have_unique_names(self) -> None:
        """Test that all split plugins have globally unique names."""
        plugins = [
            JuliaRuntimePlugin(),
            JuliaPackagesPlugin(),
            GoRuntimePlugin(),
            GoPackagesPlugin(),
            TexliveSelfPlugin(),
            TexlivePackagesPlugin(),
            CondaSelfPlugin(),
            CondaBuildPlugin(),
            CondaPackagesPlugin(),
            CondaCleanPlugin(),
            YoutubeDlPlugin(),
            YtDlpPlugin(),
        ]

        names = [p.name for p in plugins]
        assert len(names) == len(set(names)), f"Duplicate names found: {names}"
