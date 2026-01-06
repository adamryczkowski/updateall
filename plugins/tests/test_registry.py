"""Tests for plugin registry."""

from __future__ import annotations

from plugins.apt import AptPlugin
from plugins.pipx import PipxPlugin
from plugins.registry import PluginRegistry, get_registry


class TestPluginRegistry:
    """Tests for PluginRegistry."""

    def test_register_plugin(self) -> None:
        """Test registering a plugin."""
        registry = PluginRegistry()
        registry.register(AptPlugin)

        assert "apt" in registry.list_names()

    def test_unregister_plugin(self) -> None:
        """Test unregistering a plugin."""
        registry = PluginRegistry()
        registry.register(AptPlugin)

        result = registry.unregister("apt")

        assert result is True
        assert "apt" not in registry.list_names()

    def test_unregister_nonexistent(self) -> None:
        """Test unregistering a non-existent plugin."""
        registry = PluginRegistry()

        result = registry.unregister("nonexistent")

        assert result is False

    def test_get_plugin(self) -> None:
        """Test getting a plugin by name."""
        registry = PluginRegistry()
        registry.register(AptPlugin)

        plugin = registry.get("apt")

        assert plugin is not None
        assert plugin.name == "apt"

    def test_get_nonexistent_plugin(self) -> None:
        """Test getting a non-existent plugin."""
        registry = PluginRegistry()

        plugin = registry.get("nonexistent")

        assert plugin is None

    def test_get_all_plugins(self) -> None:
        """Test getting all registered plugins."""
        registry = PluginRegistry()
        registry.register(AptPlugin)
        registry.register(PipxPlugin)

        plugins = registry.get_all()

        assert len(plugins) == 2
        names = {p.name for p in plugins}
        assert names == {"apt", "pipx"}

    def test_list_names(self) -> None:
        """Test listing plugin names."""
        registry = PluginRegistry()
        registry.register(AptPlugin)
        registry.register(PipxPlugin)

        names = registry.list_names()

        assert set(names) == {"apt", "pipx"}


class TestGetRegistry:
    """Tests for get_registry function."""

    def test_returns_registry(self) -> None:
        """Test that get_registry returns a PluginRegistry."""
        registry = get_registry()
        assert isinstance(registry, PluginRegistry)

    def test_returns_same_instance(self) -> None:
        """Test that get_registry returns the same instance."""
        registry1 = get_registry()
        registry2 = get_registry()
        assert registry1 is registry2
