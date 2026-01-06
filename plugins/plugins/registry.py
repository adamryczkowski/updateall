"""Plugin registry for discovering and managing plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from core.interfaces import UpdatePlugin

logger = structlog.get_logger(__name__)


class PluginRegistry:
    """Registry for discovering and managing update plugins.

    Plugins can be registered manually or discovered via entry points.
    """

    def __init__(self) -> None:
        """Initialize an empty plugin registry."""
        self._plugins: dict[str, type[UpdatePlugin]] = {}

    def register(self, plugin_class: type[UpdatePlugin]) -> None:
        """Register a plugin class.

        Args:
            plugin_class: The plugin class to register.
        """
        # Create a temporary instance to get the name
        instance = plugin_class()
        name = instance.name
        self._plugins[name] = plugin_class
        logger.debug("plugin_registered", plugin=name)

    def unregister(self, name: str) -> bool:
        """Unregister a plugin by name.

        Args:
            name: The plugin name to unregister.

        Returns:
            True if the plugin was unregistered, False if not found.
        """
        if name in self._plugins:
            del self._plugins[name]
            logger.debug("plugin_unregistered", plugin=name)
            return True
        return False

    def get(self, name: str) -> UpdatePlugin | None:
        """Get a plugin instance by name.

        Args:
            name: The plugin name.

        Returns:
            A plugin instance, or None if not found.
        """
        plugin_class = self._plugins.get(name)
        if plugin_class:
            return plugin_class()
        return None

    def get_all(self) -> list[UpdatePlugin]:
        """Get instances of all registered plugins.

        Returns:
            List of plugin instances.
        """
        return [cls() for cls in self._plugins.values()]

    def list_names(self) -> list[str]:
        """List all registered plugin names.

        Returns:
            List of plugin names.
        """
        return list(self._plugins.keys())

    def discover_plugins(self) -> int:
        """Discover and register plugins from entry points.

        Uses the 'update_all.plugins' entry point group.

        Returns:
            Number of plugins discovered.
        """
        count = 0

        # Python 3.12+ has the modern entry_points API
        from importlib.metadata import entry_points

        eps = entry_points(group="update_all.plugins")

        for ep in eps:
            try:
                plugin_class = ep.load()
                self.register(plugin_class)
                count += 1
                logger.info("plugin_discovered", plugin=ep.name, module=ep.value)
            except Exception as e:
                logger.error(
                    "plugin_discovery_failed",
                    plugin=ep.name,
                    error=str(e),
                )

        return count


# Global registry instance
_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    """Get the global plugin registry.

    Returns:
        The global PluginRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry
