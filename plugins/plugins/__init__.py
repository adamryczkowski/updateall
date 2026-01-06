"""Update-All Plugins package.

This package contains plugin implementations for various package managers.
"""

from plugins.apt import AptPlugin
from plugins.base import BasePlugin
from plugins.flatpak import FlatpakPlugin
from plugins.pipx import PipxPlugin
from plugins.registry import PluginRegistry, get_registry

__all__ = [
    "AptPlugin",
    "BasePlugin",
    "FlatpakPlugin",
    "PipxPlugin",
    "PluginRegistry",
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

    # Register built-in plugins
    registry.register(AptPlugin)
    registry.register(PipxPlugin)
    registry.register(FlatpakPlugin)

    return registry
