"""Tests for mutex and dependency declaration API.

This module tests the Proposal 6 implementation: Mutex and Dependency Declaration.
"""

from __future__ import annotations

from core.streaming import Phase

# =============================================================================
# Test Fixtures - Mock Plugins for Testing
# =============================================================================


class MockPluginBase:
    """Base mock plugin for testing."""

    @property
    def name(self) -> str:
        return "mock-plugin"

    @property
    def command(self) -> str:
        return "mock"


class MockPluginWithDependencies(MockPluginBase):
    """Mock plugin with dependencies declared."""

    @property
    def dependencies(self) -> list[str]:
        return ["apt", "snap"]


class MockPluginWithSingleDependency(MockPluginBase):
    """Mock plugin with a single dependency."""

    @property
    def dependencies(self) -> list[str]:
        return ["conda-self"]


class MockPluginWithMutexes(MockPluginBase):
    """Mock plugin with mutexes declared."""

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        return {
            Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"],
        }


class MockPluginWithMultiPhaseMutexes(MockPluginBase):
    """Mock plugin with mutexes for multiple phases."""

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        return {
            Phase.DOWNLOAD: ["system:network"],
            Phase.EXECUTE: ["pkgmgr:apt"],
        }


class MockPluginWithOverlappingMutexes(MockPluginBase):
    """Mock plugin with overlapping mutexes across phases."""

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        return {
            Phase.DOWNLOAD: ["system:network", "pkgmgr:apt"],
            Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"],
        }


# =============================================================================
# Tests for dependencies Property
# =============================================================================


class TestDependenciesProperty:
    """Tests for the dependencies property."""

    def test_default_dependencies_empty(self) -> None:
        """Test that default dependencies is an empty list."""
        from plugins.base import BasePlugin

        # Create a minimal concrete implementation
        class MinimalPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "minimal"

            @property
            def command(self) -> str:
                return "minimal"

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = MinimalPlugin()
        assert plugin.dependencies == []

    def test_dependencies_returns_list(self) -> None:
        """Test that dependencies returns a list of strings."""
        from plugins.base import BasePlugin

        class PluginWithDeps(BasePlugin):
            @property
            def name(self) -> str:
                return "with-deps"

            @property
            def command(self) -> str:
                return "withdeps"

            @property
            def dependencies(self) -> list[str]:
                return ["apt", "snap"]

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = PluginWithDeps()
        deps = plugin.dependencies
        assert isinstance(deps, list)
        assert all(isinstance(d, str) for d in deps)

    def test_dependencies_can_be_overridden(self) -> None:
        """Test that subclasses can override dependencies."""
        from plugins.base import BasePlugin

        class PluginWithOverride(BasePlugin):
            @property
            def name(self) -> str:
                return "override"

            @property
            def command(self) -> str:
                return "override"

            @property
            def dependencies(self) -> list[str]:
                return ["custom-dep"]

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = PluginWithOverride()
        assert plugin.dependencies == ["custom-dep"]

    def test_dependencies_with_single_dependency(self) -> None:
        """Test plugin with a single dependency."""
        from plugins.base import BasePlugin

        class SingleDepPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "single-dep"

            @property
            def command(self) -> str:
                return "singledep"

            @property
            def dependencies(self) -> list[str]:
                return ["conda-self"]

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = SingleDepPlugin()
        assert len(plugin.dependencies) == 1
        assert plugin.dependencies[0] == "conda-self"

    def test_dependencies_with_multiple_dependencies(self) -> None:
        """Test plugin with multiple dependencies."""
        from plugins.base import BasePlugin

        class MultiDepPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "multi-dep"

            @property
            def command(self) -> str:
                return "multidep"

            @property
            def dependencies(self) -> list[str]:
                return ["apt", "snap", "flatpak"]

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = MultiDepPlugin()
        assert len(plugin.dependencies) == 3
        assert "apt" in plugin.dependencies
        assert "snap" in plugin.dependencies
        assert "flatpak" in plugin.dependencies


# =============================================================================
# Tests for mutexes Property
# =============================================================================


class TestMutexesProperty:
    """Tests for the mutexes property."""

    def test_default_mutexes_empty(self) -> None:
        """Test that default mutexes is an empty dict."""
        from plugins.base import BasePlugin

        class MinimalPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "minimal"

            @property
            def command(self) -> str:
                return "minimal"

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = MinimalPlugin()
        assert plugin.mutexes == {}

    def test_mutexes_returns_dict(self) -> None:
        """Test that mutexes returns a dict mapping Phase to list."""
        from plugins.base import BasePlugin

        class PluginWithMutexes(BasePlugin):
            @property
            def name(self) -> str:
                return "with-mutexes"

            @property
            def command(self) -> str:
                return "withmutexes"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {Phase.EXECUTE: ["pkgmgr:apt"]}

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = PluginWithMutexes()
        mutexes = plugin.mutexes
        assert isinstance(mutexes, dict)
        assert Phase.EXECUTE in mutexes
        assert isinstance(mutexes[Phase.EXECUTE], list)

    def test_mutexes_can_be_overridden(self) -> None:
        """Test that subclasses can override mutexes."""
        from plugins.base import BasePlugin

        class PluginWithOverride(BasePlugin):
            @property
            def name(self) -> str:
                return "override"

            @property
            def command(self) -> str:
                return "override"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {Phase.EXECUTE: ["custom:mutex"]}

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = PluginWithOverride()
        assert plugin.mutexes == {Phase.EXECUTE: ["custom:mutex"]}

    def test_mutexes_for_single_phase(self) -> None:
        """Test plugin with mutexes for a single phase."""
        from plugins.base import BasePlugin

        class SinglePhasePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "single-phase"

            @property
            def command(self) -> str:
                return "singlephase"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"]}

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = SinglePhasePlugin()
        assert len(plugin.mutexes) == 1
        assert Phase.EXECUTE in plugin.mutexes
        assert len(plugin.mutexes[Phase.EXECUTE]) == 2

    def test_mutexes_for_multiple_phases(self) -> None:
        """Test plugin with mutexes for multiple phases."""
        from plugins.base import BasePlugin

        class MultiPhasePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "multi-phase"

            @property
            def command(self) -> str:
                return "multiphase"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {
                    Phase.DOWNLOAD: ["system:network"],
                    Phase.EXECUTE: ["pkgmgr:apt"],
                }

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = MultiPhasePlugin()
        assert len(plugin.mutexes) == 2
        assert Phase.DOWNLOAD in plugin.mutexes
        assert Phase.EXECUTE in plugin.mutexes
        assert plugin.mutexes[Phase.DOWNLOAD] == ["system:network"]
        assert plugin.mutexes[Phase.EXECUTE] == ["pkgmgr:apt"]

    def test_mutexes_with_standard_mutex_names(self) -> None:
        """Test using StandardMutexes constants."""
        from core.mutex import StandardMutexes
        from plugins.base import BasePlugin

        class StandardMutexPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "standard-mutex"

            @property
            def command(self) -> str:
                return "standardmutex"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {
                    Phase.EXECUTE: [
                        StandardMutexes.APT_LOCK,
                        StandardMutexes.DPKG_LOCK,
                    ],
                }

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = StandardMutexPlugin()
        assert "pkgmgr:apt" in plugin.mutexes[Phase.EXECUTE]
        assert "pkgmgr:dpkg" in plugin.mutexes[Phase.EXECUTE]


# =============================================================================
# Tests for all_mutexes Property
# =============================================================================


class TestAllMutexesProperty:
    """Tests for the all_mutexes convenience property."""

    def test_all_mutexes_empty_when_no_mutexes(self) -> None:
        """Test all_mutexes returns empty list when no mutexes declared."""
        from plugins.base import BasePlugin

        class NoMutexPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "no-mutex"

            @property
            def command(self) -> str:
                return "nomutex"

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = NoMutexPlugin()
        assert plugin.all_mutexes == []

    def test_all_mutexes_single_phase(self) -> None:
        """Test all_mutexes with single phase."""
        from plugins.base import BasePlugin

        class SinglePhasePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "single-phase"

            @property
            def command(self) -> str:
                return "singlephase"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"]}

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = SinglePhasePlugin()
        all_mutexes = plugin.all_mutexes
        assert len(all_mutexes) == 2
        assert "pkgmgr:apt" in all_mutexes
        assert "pkgmgr:dpkg" in all_mutexes

    def test_all_mutexes_multiple_phases(self) -> None:
        """Test all_mutexes combines mutexes from all phases."""
        from plugins.base import BasePlugin

        class MultiPhasePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "multi-phase"

            @property
            def command(self) -> str:
                return "multiphase"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {
                    Phase.DOWNLOAD: ["system:network"],
                    Phase.EXECUTE: ["pkgmgr:apt"],
                }

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = MultiPhasePlugin()
        all_mutexes = plugin.all_mutexes
        assert len(all_mutexes) == 2
        assert "system:network" in all_mutexes
        assert "pkgmgr:apt" in all_mutexes

    def test_all_mutexes_deduplicates(self) -> None:
        """Test all_mutexes removes duplicates across phases."""
        from plugins.base import BasePlugin

        class OverlappingPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "overlapping"

            @property
            def command(self) -> str:
                return "overlapping"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {
                    Phase.DOWNLOAD: ["system:network", "pkgmgr:apt"],
                    Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"],
                }

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = OverlappingPlugin()
        all_mutexes = plugin.all_mutexes
        # Should have 3 unique mutexes, not 4
        assert len(all_mutexes) == 3
        assert "system:network" in all_mutexes
        assert "pkgmgr:apt" in all_mutexes
        assert "pkgmgr:dpkg" in all_mutexes

    def test_all_mutexes_sorted(self) -> None:
        """Test all_mutexes returns sorted list."""
        from plugins.base import BasePlugin

        class UnsortedPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "unsorted"

            @property
            def command(self) -> str:
                return "unsorted"

            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {
                    Phase.EXECUTE: ["z:last", "a:first", "m:middle"],
                }

            async def _execute_update(self, _config):  # type: ignore[override]
                return "", None

        plugin = UnsortedPlugin()
        all_mutexes = plugin.all_mutexes
        assert all_mutexes == ["a:first", "m:middle", "z:last"]
