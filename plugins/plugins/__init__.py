"""Update-All Plugins package.

This package contains plugin implementations for various package managers.
"""

from __future__ import annotations

import os

from plugins.apt import AptPlugin
from plugins.base import BasePlugin, SelfUpdateResult, SelfUpdateStatus
from plugins.cargo import CargoPlugin
from plugins.flatpak import FlatpakPlugin
from plugins.mock_alpha import MockAlphaPlugin
from plugins.mock_beta import MockBetaPlugin
from plugins.npm import NpmPlugin
from plugins.pipx import PipxPlugin
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

__all__ = [
    "AptPlugin",
    "BasePlugin",
    "CargoPlugin",
    "DownloadError",
    "FlatpakPlugin",
    "InstallationError",
    "InstalledPlugin",
    "MockAlphaPlugin",
    "MockBetaPlugin",
    "NpmPlugin",
    "PipxPlugin",
    "PluginInfo",
    "PluginNotFoundError",
    "PluginRegistry",
    "PluginRepository",
    "PluginSignature",
    "PluginSigner",
    "PluginSource",
    "PluginVerifier",
    "RepositoryConfig",
    "RepositoryError",
    "RepositoryIndex",
    "RustupPlugin",
    "SelfUpdateResult",
    "SelfUpdateStatus",
    "SnapPlugin",
    "TrustLevel",
    "VerificationResult",
    "VerificationStatus",
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
        registry.register(AptPlugin)
        registry.register(CargoPlugin)
        registry.register(FlatpakPlugin)
        registry.register(NpmPlugin)
        registry.register(PipxPlugin)
        registry.register(RustupPlugin)
        registry.register(SnapPlugin)

    return registry
