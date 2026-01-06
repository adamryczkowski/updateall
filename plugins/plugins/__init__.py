"""Update-All Plugins package.

This package contains plugin implementations for various package managers.
"""

from plugins.apt import AptPlugin
from plugins.base import BasePlugin, SelfUpdateResult, SelfUpdateStatus
from plugins.cargo import CargoPlugin
from plugins.flatpak import FlatpakPlugin
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


def register_builtin_plugins(registry: PluginRegistry | None = None) -> PluginRegistry:
    """Register all built-in plugins with the registry.

    Args:
        registry: Optional registry to use. Uses global registry if not provided.

    Returns:
        The registry with built-in plugins registered.
    """
    if registry is None:
        registry = get_registry()

    # Register built-in plugins (in alphabetical order)
    registry.register(AptPlugin)
    registry.register(CargoPlugin)
    registry.register(FlatpakPlugin)
    registry.register(NpmPlugin)
    registry.register(PipxPlugin)
    registry.register(RustupPlugin)
    registry.register(SnapPlugin)

    return registry
