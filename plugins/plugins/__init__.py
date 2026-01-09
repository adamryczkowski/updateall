"""Update-All Plugins package.

This package contains plugin implementations for various package managers.
"""

from __future__ import annotations

import os

from plugins.apt import AptPlugin
from plugins.atuin import AtuinPlugin
from plugins.base import BasePlugin, SelfUpdateResult, SelfUpdateStatus
from plugins.calibre import CalibrePlugin
from plugins.cargo import CargoPlugin
from plugins.conda_build import CondaBuildPlugin
from plugins.conda_clean import CondaCleanPlugin
from plugins.conda_packages import CondaPackagesPlugin
from plugins.conda_self import CondaSelfPlugin
from plugins.flatpak import FlatpakPlugin
from plugins.foot import FootPlugin
from plugins.go_packages import GoPackagesPlugin
from plugins.go_runtime import GoRuntimePlugin
from plugins.julia_packages import JuliaPackagesPlugin
from plugins.julia_runtime import JuliaRuntimePlugin
from plugins.lxc import LxcPlugin
from plugins.mock_alpha import MockAlphaPlugin
from plugins.mock_beta import MockBetaPlugin
from plugins.npm import NpmPlugin
from plugins.pihole import PiholePlugin
from plugins.pip import PipPlugin
from plugins.pipx import PipxPlugin
from plugins.poetry import PoetryPlugin
from plugins.r import RPlugin
from plugins.registry import PluginRegistry, get_registry
from plugins.repository import (
    DownloadError,
    InstallationError,
    InstalledPlugin,
    PluginInfo,
    PluginNotFoundError,
    PluginRepository,
    PluginSource,
    RepositoryConfig,
    RepositoryError,
    RepositoryIndex,
)
from plugins.rustup import RustupPlugin
from plugins.signing import (
    PluginSignature,
    PluginSigner,
    PluginVerifier,
    TrustLevel,
    VerificationResult,
    VerificationStatus,
)
from plugins.snap import SnapPlugin
from plugins.spack import SpackPlugin
from plugins.steam import SteamPlugin
from plugins.texlive_packages import TexlivePackagesPlugin
from plugins.texlive_self import TexliveSelfPlugin
from plugins.waterfox import WaterfoxPlugin
from plugins.youtube_dl import YoutubeDlPlugin
from plugins.yt_dlp import YtDlpPlugin

__all__ = [
    "AptPlugin",
    "AtuinPlugin",
    "BasePlugin",
    "CalibrePlugin",
    "CargoPlugin",
    "CondaBuildPlugin",
    "CondaCleanPlugin",
    "CondaPackagesPlugin",
    "CondaSelfPlugin",
    "DownloadError",
    "FlatpakPlugin",
    "FootPlugin",
    "GoPackagesPlugin",
    "GoRuntimePlugin",
    "InstallationError",
    "InstalledPlugin",
    "JuliaPackagesPlugin",
    "JuliaRuntimePlugin",
    "LxcPlugin",
    "MockAlphaPlugin",
    "MockBetaPlugin",
    "NpmPlugin",
    "PiholePlugin",
    "PipPlugin",
    "PipxPlugin",
    "PluginInfo",
    "PluginNotFoundError",
    "PluginRegistry",
    "PluginRepository",
    "PluginSignature",
    "PluginSigner",
    "PluginSource",
    "PluginVerifier",
    "PoetryPlugin",
    "RPlugin",
    "RepositoryConfig",
    "RepositoryError",
    "RepositoryIndex",
    "RustupPlugin",
    "SelfUpdateResult",
    "SelfUpdateStatus",
    "SnapPlugin",
    "SpackPlugin",
    "SteamPlugin",
    "TexlivePackagesPlugin",
    "TexliveSelfPlugin",
    "TrustLevel",
    "VerificationResult",
    "VerificationStatus",
    "WaterfoxPlugin",
    "YoutubeDlPlugin",
    "YtDlpPlugin",
    "get_registry",
    "register_builtin_plugins",
]

# Set this environment variable to "1" to use only mock plugins for debugging
DEBUG_MOCK_PLUGINS_ONLY = os.environ.get("UPDATE_ALL_DEBUG_MOCK_ONLY", "0") == "1"


def register_builtin_plugins(registry: PluginRegistry | None = None) -> PluginRegistry:
    """Register all built-in plugins with the registry.

    If the environment variable UPDATE_ALL_DEBUG_MOCK_ONLY is set to "1",
    only mock plugins will be registered for debugging purposes.

    Args:
        registry: Optional registry to use. Uses global registry if not provided.

    Returns:
        The registry with built-in plugins registered.
    """
    if registry is None:
        registry = get_registry()

    if DEBUG_MOCK_PLUGINS_ONLY:
        # Debug mode: only register mock plugins
        registry.register(MockAlphaPlugin)
        registry.register(MockBetaPlugin)
    else:
        # Normal mode: register all production plugins
        # System package managers
        registry.register(AptPlugin)
        registry.register(FlatpakPlugin)
        registry.register(SnapPlugin)

        # Language package managers
        registry.register(CargoPlugin)
        registry.register(NpmPlugin)
        registry.register(PipPlugin)
        registry.register(PipxPlugin)
        registry.register(PoetryPlugin)
        registry.register(RustupPlugin)

        # Conda ecosystem
        registry.register(CondaSelfPlugin)
        registry.register(CondaPackagesPlugin)
        registry.register(CondaBuildPlugin)
        registry.register(CondaCleanPlugin)

        # Go ecosystem
        registry.register(GoRuntimePlugin)
        registry.register(GoPackagesPlugin)

        # Julia ecosystem
        registry.register(JuliaRuntimePlugin)
        registry.register(JuliaPackagesPlugin)

        # TeX Live
        registry.register(TexliveSelfPlugin)
        registry.register(TexlivePackagesPlugin)

        # Applications
        registry.register(AtuinPlugin)
        registry.register(CalibrePlugin)
        registry.register(FootPlugin)
        registry.register(LxcPlugin)
        registry.register(PiholePlugin)
        registry.register(RPlugin)
        registry.register(SpackPlugin)
        registry.register(SteamPlugin)
        registry.register(WaterfoxPlugin)
        registry.register(YoutubeDlPlugin)
        registry.register(YtDlpPlugin)

        # Mock/Debug plugins (always available for testing)
        registry.register(MockAlphaPlugin)
        registry.register(MockBetaPlugin)

    return registry
