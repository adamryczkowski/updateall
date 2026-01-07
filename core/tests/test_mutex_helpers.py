"""Tests for mutex helper functions (Proposal 6).

These tests verify the helper functions for collecting mutexes and
dependencies from plugin instances.
"""

from __future__ import annotations

from unittest.mock import Mock

from core.mutex import (
    StandardMutexes,
    build_dependency_graph,
    collect_plugin_dependencies,
    collect_plugin_mutexes,
    validate_dependencies,
)
from core.streaming import Phase


class TestStandardMutexes:
    """Tests for StandardMutexes class."""

    def test_apt_lock_constant(self) -> None:
        """Test APT_LOCK constant value."""
        assert StandardMutexes.APT_LOCK == "pkgmgr:apt"

    def test_dpkg_lock_constant(self) -> None:
        """Test DPKG_LOCK constant value."""
        assert StandardMutexes.DPKG_LOCK == "pkgmgr:dpkg"

    def test_snap_lock_constant(self) -> None:
        """Test SNAP_LOCK constant value."""
        assert StandardMutexes.SNAP_LOCK == "pkgmgr:snap"

    def test_conda_lock_constant(self) -> None:
        """Test CONDA_LOCK constant value (Proposal 6 addition)."""
        assert StandardMutexes.CONDA_LOCK == "pkgmgr:conda"

    def test_texlive_lock_constant(self) -> None:
        """Test TEXLIVE_LOCK constant value (Proposal 6 addition)."""
        assert StandardMutexes.TEXLIVE_LOCK == "pkgmgr:texlive"

    def test_mise_lock_constant(self) -> None:
        """Test MISE_LOCK constant value (Proposal 6 addition)."""
        assert StandardMutexes.MISE_LOCK == "pkgmgr:mise"

    def test_waterfox_lock_constant(self) -> None:
        """Test WATERFOX_LOCK constant value (Proposal 6 addition)."""
        assert StandardMutexes.WATERFOX_LOCK == "app:waterfox"

    def test_calibre_lock_constant(self) -> None:
        """Test CALIBRE_LOCK constant value (Proposal 6 addition)."""
        assert StandardMutexes.CALIBRE_LOCK == "app:calibre"

    def test_network_constant(self) -> None:
        """Test NETWORK constant value."""
        assert StandardMutexes.NETWORK == "system:network"

    def test_all_mutexes_returns_list(self) -> None:
        """Test all_mutexes() returns a list."""
        result = StandardMutexes.all_mutexes()
        assert isinstance(result, list)

    def test_all_mutexes_contains_apt_lock(self) -> None:
        """Test all_mutexes() includes APT_LOCK."""
        result = StandardMutexes.all_mutexes()
        assert StandardMutexes.APT_LOCK in result

    def test_all_mutexes_is_sorted(self) -> None:
        """Test all_mutexes() returns sorted list."""
        result = StandardMutexes.all_mutexes()
        assert result == sorted(result)

    def test_all_mutexes_no_duplicates(self) -> None:
        """Test all_mutexes() has no duplicates."""
        result = StandardMutexes.all_mutexes()
        assert len(result) == len(set(result))


class TestCollectPluginMutexes:
    """Tests for collect_plugin_mutexes() function."""

    def _create_mock_plugin(
        self,
        name: str,
        mutexes: dict[Phase, list[str]] | None = None,
    ) -> Mock:
        """Create a mock plugin with specified mutexes."""
        plugin = Mock()
        plugin.name = name
        plugin.mutexes = mutexes or {}
        return plugin

    def test_empty_plugin_list(self) -> None:
        """Test with empty plugin list."""
        result = collect_plugin_mutexes([])
        assert result == {}

    def test_single_plugin_no_mutexes(self) -> None:
        """Test single plugin with no mutexes."""
        plugin = self._create_mock_plugin("test-plugin")
        result = collect_plugin_mutexes([plugin])
        assert result == {"test-plugin": []}

    def test_single_plugin_with_execute_mutexes(self) -> None:
        """Test single plugin with EXECUTE phase mutexes."""
        plugin = self._create_mock_plugin(
            "apt",
            mutexes={Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"]},
        )
        result = collect_plugin_mutexes([plugin], Phase.EXECUTE)
        assert result == {"apt": ["pkgmgr:apt", "pkgmgr:dpkg"]}

    def test_single_plugin_with_multiple_phases(self) -> None:
        """Test single plugin with mutexes in multiple phases."""
        plugin = self._create_mock_plugin(
            "test",
            mutexes={
                Phase.DOWNLOAD: ["system:network"],
                Phase.EXECUTE: ["pkgmgr:apt"],
            },
        )
        # Filter by DOWNLOAD phase
        result = collect_plugin_mutexes([plugin], Phase.DOWNLOAD)
        assert result == {"test": ["system:network"]}

        # Filter by EXECUTE phase
        result = collect_plugin_mutexes([plugin], Phase.EXECUTE)
        assert result == {"test": ["pkgmgr:apt"]}

    def test_collect_all_mutexes_no_phase_filter(self) -> None:
        """Test collecting all mutexes without phase filter."""
        plugin = self._create_mock_plugin(
            "test",
            mutexes={
                Phase.DOWNLOAD: ["system:network"],
                Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"],
            },
        )
        result = collect_plugin_mutexes([plugin], phase=None)
        # Should collect all mutexes, sorted
        assert result == {"test": ["pkgmgr:apt", "pkgmgr:dpkg", "system:network"]}

    def test_multiple_plugins(self) -> None:
        """Test with multiple plugins."""
        apt_plugin = self._create_mock_plugin(
            "apt",
            mutexes={Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"]},
        )
        snap_plugin = self._create_mock_plugin(
            "snap",
            mutexes={Phase.EXECUTE: ["pkgmgr:snap"]},
        )
        result = collect_plugin_mutexes([apt_plugin, snap_plugin], Phase.EXECUTE)
        assert result == {
            "apt": ["pkgmgr:apt", "pkgmgr:dpkg"],
            "snap": ["pkgmgr:snap"],
        }

    def test_phase_not_in_mutexes(self) -> None:
        """Test when requested phase has no mutexes."""
        plugin = self._create_mock_plugin(
            "test",
            mutexes={Phase.EXECUTE: ["pkgmgr:apt"]},
        )
        result = collect_plugin_mutexes([plugin], Phase.DOWNLOAD)
        assert result == {"test": []}

    def test_deduplication_across_phases(self) -> None:
        """Test that mutexes are deduplicated when collecting all."""
        plugin = self._create_mock_plugin(
            "test",
            mutexes={
                Phase.DOWNLOAD: ["system:network"],
                Phase.EXECUTE: ["system:network", "pkgmgr:apt"],
            },
        )
        result = collect_plugin_mutexes([plugin], phase=None)
        # system:network should appear only once
        assert result == {"test": ["pkgmgr:apt", "system:network"]}


class TestCollectPluginDependencies:
    """Tests for collect_plugin_dependencies() function."""

    def _create_mock_plugin(
        self,
        name: str,
        dependencies: list[str] | None = None,
    ) -> Mock:
        """Create a mock plugin with specified dependencies."""
        plugin = Mock()
        plugin.name = name
        plugin.dependencies = dependencies or []
        return plugin

    def test_empty_plugin_list(self) -> None:
        """Test with empty plugin list."""
        result = collect_plugin_dependencies([])
        assert result == {}

    def test_single_plugin_no_dependencies(self) -> None:
        """Test single plugin with no dependencies."""
        plugin = self._create_mock_plugin("test-plugin")
        result = collect_plugin_dependencies([plugin])
        assert result == {"test-plugin": []}

    def test_single_plugin_with_dependencies(self) -> None:
        """Test single plugin with dependencies."""
        plugin = self._create_mock_plugin(
            "conda-packages",
            dependencies=["conda-self"],
        )
        result = collect_plugin_dependencies([plugin])
        assert result == {"conda-packages": ["conda-self"]}

    def test_multiple_plugins(self) -> None:
        """Test with multiple plugins."""
        apt_plugin = self._create_mock_plugin("apt")
        conda_self = self._create_mock_plugin("conda-self")
        conda_packages = self._create_mock_plugin(
            "conda-packages",
            dependencies=["conda-self"],
        )
        result = collect_plugin_dependencies([apt_plugin, conda_self, conda_packages])
        assert result == {
            "apt": [],
            "conda-self": [],
            "conda-packages": ["conda-self"],
        }

    def test_multiple_dependencies(self) -> None:
        """Test plugin with multiple dependencies."""
        plugin = self._create_mock_plugin(
            "complex-plugin",
            dependencies=["dep1", "dep2", "dep3"],
        )
        result = collect_plugin_dependencies([plugin])
        assert result == {"complex-plugin": ["dep1", "dep2", "dep3"]}


class TestBuildDependencyGraph:
    """Tests for build_dependency_graph() function."""

    def _create_mock_plugin(
        self,
        name: str,
        dependencies: list[str] | None = None,
    ) -> Mock:
        """Create a mock plugin with specified dependencies."""
        plugin = Mock()
        plugin.name = name
        plugin.dependencies = dependencies or []
        return plugin

    def test_empty_plugin_list(self) -> None:
        """Test with empty plugin list."""
        result = build_dependency_graph([])
        assert result == {}

    def test_single_plugin_no_dependencies(self) -> None:
        """Test single plugin with no dependencies."""
        plugin = self._create_mock_plugin("test")
        result = build_dependency_graph([plugin])
        assert result == {"test": set()}

    def test_single_plugin_with_dependencies(self) -> None:
        """Test single plugin with dependencies."""
        plugin = self._create_mock_plugin("child", dependencies=["parent"])
        result = build_dependency_graph([plugin])
        assert result == {"child": {"parent"}}

    def test_multiple_plugins_with_dependencies(self) -> None:
        """Test multiple plugins with dependencies."""
        parent = self._create_mock_plugin("parent")
        child = self._create_mock_plugin("child", dependencies=["parent"])
        grandchild = self._create_mock_plugin("grandchild", dependencies=["child"])

        result = build_dependency_graph([parent, child, grandchild])
        assert result == {
            "parent": set(),
            "child": {"parent"},
            "grandchild": {"child"},
        }


class TestValidateDependencies:
    """Tests for validate_dependencies() function."""

    def _create_mock_plugin(
        self,
        name: str,
        dependencies: list[str] | None = None,
    ) -> Mock:
        """Create a mock plugin with specified dependencies."""
        plugin = Mock()
        plugin.name = name
        plugin.dependencies = dependencies or []
        return plugin

    def test_empty_plugin_list(self) -> None:
        """Test with empty plugin list."""
        errors = validate_dependencies([])
        assert errors == []

    def test_valid_dependencies(self) -> None:
        """Test with valid dependencies."""
        parent = self._create_mock_plugin("parent")
        child = self._create_mock_plugin("child", dependencies=["parent"])
        errors = validate_dependencies([parent, child])
        assert errors == []

    def test_self_dependency_detected(self) -> None:
        """Test that self-dependency is detected.

        Note: Self-dependency also triggers circular dependency detection,
        so we expect at least one error mentioning self-dependency.
        """
        plugin = self._create_mock_plugin("test", dependencies=["test"])
        errors = validate_dependencies([plugin])
        assert len(errors) >= 1
        assert any("depends on itself" in e for e in errors)

    def test_missing_dependency_detected(self) -> None:
        """Test that missing dependency is detected."""
        plugin = self._create_mock_plugin("child", dependencies=["nonexistent"])
        errors = validate_dependencies([plugin])
        assert len(errors) == 1
        assert "non-existent plugin" in errors[0]

    def test_circular_dependency_detected(self) -> None:
        """Test that circular dependency is detected."""
        plugin_a = self._create_mock_plugin("a", dependencies=["b"])
        plugin_b = self._create_mock_plugin("b", dependencies=["a"])
        errors = validate_dependencies([plugin_a, plugin_b])
        assert len(errors) >= 1
        assert any("Circular dependency" in e for e in errors)

    def test_complex_circular_dependency(self) -> None:
        """Test detection of complex circular dependency (A -> B -> C -> A)."""
        plugin_a = self._create_mock_plugin("a", dependencies=["b"])
        plugin_b = self._create_mock_plugin("b", dependencies=["c"])
        plugin_c = self._create_mock_plugin("c", dependencies=["a"])
        errors = validate_dependencies([plugin_a, plugin_b, plugin_c])
        assert len(errors) >= 1
        assert any("Circular dependency" in e for e in errors)

    def test_multiple_errors(self) -> None:
        """Test that multiple errors are reported.

        Note: Self-dependency also triggers circular dependency detection,
        so we may get more than 2 errors.
        """
        plugin_a = self._create_mock_plugin("a", dependencies=["a", "nonexistent"])
        errors = validate_dependencies([plugin_a])
        assert len(errors) >= 2
        assert any("depends on itself" in e for e in errors)
        assert any("non-existent plugin" in e for e in errors)

    def test_valid_chain_no_errors(self) -> None:
        """Test that valid dependency chain has no errors."""
        root = self._create_mock_plugin("root")
        level1 = self._create_mock_plugin("level1", dependencies=["root"])
        level2 = self._create_mock_plugin("level2", dependencies=["level1"])
        level3 = self._create_mock_plugin("level3", dependencies=["level2"])
        errors = validate_dependencies([root, level1, level2, level3])
        assert errors == []
