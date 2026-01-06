"""Tests for the DAG-based scheduler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.scheduler import ExecutionDAG, PluginNode, Scheduler, SchedulingError


class MockPlugin:
    """Mock plugin for testing."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.metadata = MagicMock()
        self.metadata.description = f"Mock {name} plugin"


class TestExecutionDAG:
    """Tests for ExecutionDAG class."""

    def test_add_node(self) -> None:
        """Test adding nodes to DAG."""
        dag = ExecutionDAG()
        plugin = MockPlugin("test")
        dag.add_node("test", plugin)
        assert "test" in dag.nodes
        assert dag.nodes["test"].plugin == plugin

    def test_add_duplicate_node(self) -> None:
        """Test adding duplicate node is idempotent."""
        dag = ExecutionDAG()
        plugin1 = MockPlugin("test")
        plugin2 = MockPlugin("test")
        dag.add_node("test", plugin1)
        dag.add_node("test", plugin2)
        assert dag.nodes["test"].plugin == plugin1  # First one wins

    def test_add_edge(self) -> None:
        """Test adding edges to DAG."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_edge("a", "b")
        assert "b" in dag.edges["a"]
        assert "a" in dag.reverse_edges["b"]

    def test_add_edge_missing_node(self) -> None:
        """Test adding edge with missing node is ignored."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_edge("a", "nonexistent")
        assert "nonexistent" not in dag.edges.get("a", set())

    def test_predecessors(self) -> None:
        """Test getting predecessors of a node."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_node("c", MockPlugin("c"))
        dag.add_edge("a", "c")
        dag.add_edge("b", "c")
        assert dag.predecessors("c") == {"a", "b"}

    def test_successors(self) -> None:
        """Test getting successors of a node."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_node("c", MockPlugin("c"))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        assert dag.successors("a") == {"b", "c"}

    def test_has_cycle_no_cycle(self) -> None:
        """Test cycle detection with no cycle."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_node("c", MockPlugin("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        assert not dag.has_cycle()

    def test_has_cycle_with_cycle(self) -> None:
        """Test cycle detection with cycle."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_node("c", MockPlugin("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        dag.add_edge("c", "a")  # Creates cycle
        assert dag.has_cycle()

    def test_find_cycle(self) -> None:
        """Test finding a cycle."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_node("c", MockPlugin("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        dag.add_edge("c", "a")
        cycle = dag.find_cycle()
        assert len(cycle) > 0
        # Cycle should contain the cycling nodes
        assert set(cycle[:-1]) == {"a", "b", "c"}

    def test_find_cycle_no_cycle(self) -> None:
        """Test find_cycle returns empty list when no cycle."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_edge("a", "b")
        assert dag.find_cycle() == []

    def test_topological_sort(self) -> None:
        """Test topological sort."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_node("c", MockPlugin("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_topological_sort_with_cycle_raises(self) -> None:
        """Test topological sort raises on cycle."""
        dag = ExecutionDAG()
        dag.add_node("a", MockPlugin("a"))
        dag.add_node("b", MockPlugin("b"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "a")
        with pytest.raises(SchedulingError, match="Circular dependency"):
            dag.topological_sort()


class TestScheduler:
    """Tests for Scheduler class."""

    @pytest.fixture
    def scheduler(self) -> Scheduler:
        """Create a scheduler for testing."""
        return Scheduler()

    def test_build_dag_empty(self, scheduler: Scheduler) -> None:
        """Test building DAG with no plugins."""
        dag = scheduler.build_execution_dag([])
        assert len(dag.nodes) == 0

    def test_build_dag_single_plugin(self, scheduler: Scheduler) -> None:
        """Test building DAG with single plugin."""
        plugins = [MockPlugin("apt")]
        dag = scheduler.build_execution_dag(plugins)
        assert len(dag.nodes) == 1
        assert "apt" in dag.nodes

    def test_build_dag_with_dependencies(self, scheduler: Scheduler) -> None:
        """Test building DAG with explicit dependencies."""
        plugins = [MockPlugin("apt"), MockPlugin("pipx")]
        dependencies = {"pipx": ["apt"]}
        dag = scheduler.build_execution_dag(plugins, plugin_dependencies=dependencies)
        assert "pipx" in dag.successors("apt")

    def test_build_dag_with_mutex_conflicts(self, scheduler: Scheduler) -> None:
        """Test building DAG with mutex conflicts."""
        plugins = [MockPlugin("apt"), MockPlugin("snap")]
        mutexes = {
            "apt": ["pkgmgr:dpkg"],
            "snap": ["pkgmgr:dpkg"],  # Shared mutex
        }
        dag = scheduler.build_execution_dag(plugins, plugin_mutexes=mutexes)
        # Should have an edge between them (alphabetically ordered)
        assert "snap" in dag.successors("apt") or "apt" in dag.successors("snap")

    def test_build_dag_cycle_detection(self, scheduler: Scheduler) -> None:
        """Test that cycle is detected during DAG build."""
        plugins = [MockPlugin("a"), MockPlugin("b")]
        dependencies = {"a": ["b"], "b": ["a"]}
        with pytest.raises(SchedulingError, match="Circular dependency"):
            scheduler.build_execution_dag(plugins, plugin_dependencies=dependencies)

    def test_get_execution_waves_linear(self, scheduler: Scheduler) -> None:
        """Test getting execution waves for linear dependencies."""
        plugins = [MockPlugin("a"), MockPlugin("b"), MockPlugin("c")]
        dependencies = {"b": ["a"], "c": ["b"]}
        dag = scheduler.build_execution_dag(plugins, plugin_dependencies=dependencies)
        waves = scheduler.get_execution_waves(dag)
        assert len(waves) == 3
        assert waves[0] == ["a"]
        assert waves[1] == ["b"]
        assert waves[2] == ["c"]

    def test_get_execution_waves_parallel(self, scheduler: Scheduler) -> None:
        """Test getting execution waves for parallel plugins."""
        plugins = [MockPlugin("a"), MockPlugin("b"), MockPlugin("c")]
        # No dependencies - all can run in parallel
        dag = scheduler.build_execution_dag(plugins)
        waves = scheduler.get_execution_waves(dag)
        assert len(waves) == 1
        assert set(waves[0]) == {"a", "b", "c"}

    def test_get_execution_waves_mixed(self, scheduler: Scheduler) -> None:
        """Test getting execution waves with mixed dependencies."""
        plugins = [
            MockPlugin("a"),
            MockPlugin("b"),
            MockPlugin("c"),
            MockPlugin("d"),
        ]
        dependencies = {"c": ["a"], "d": ["a"]}  # c and d depend on a, b is independent
        dag = scheduler.build_execution_dag(plugins, plugin_dependencies=dependencies)
        waves = scheduler.get_execution_waves(dag)
        # Wave 1: a, b (no dependencies)
        # Wave 2: c, d (depend on a)
        assert len(waves) == 2
        assert set(waves[0]) == {"a", "b"}
        assert set(waves[1]) == {"c", "d"}

    def test_get_execution_order(self, scheduler: Scheduler) -> None:
        """Test getting linear execution order."""
        plugins = [MockPlugin("a"), MockPlugin("b"), MockPlugin("c")]
        dependencies = {"b": ["a"], "c": ["b"]}
        dag = scheduler.build_execution_dag(plugins, plugin_dependencies=dependencies)
        order = scheduler.get_execution_order(dag)
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_can_run_parallel_no_deps(self, scheduler: Scheduler) -> None:
        """Test can_run_parallel with no dependencies."""
        plugins = [MockPlugin("a"), MockPlugin("b")]
        dag = scheduler.build_execution_dag(plugins)
        assert scheduler.can_run_parallel("a", "b", dag)

    def test_can_run_parallel_with_deps(self, scheduler: Scheduler) -> None:
        """Test can_run_parallel with dependencies."""
        plugins = [MockPlugin("a"), MockPlugin("b")]
        dependencies = {"b": ["a"]}
        dag = scheduler.build_execution_dag(plugins, plugin_dependencies=dependencies)
        assert not scheduler.can_run_parallel("a", "b", dag)

    def test_can_run_parallel_shared_mutex(self, scheduler: Scheduler) -> None:
        """Test can_run_parallel with shared mutex."""
        plugins = [MockPlugin("a"), MockPlugin("b")]
        mutexes = {"a": ["shared"], "b": ["shared"]}
        dag = scheduler.build_execution_dag(plugins, plugin_mutexes=mutexes)
        # They share a mutex, so they can't run in parallel
        # (but the DAG already has an edge between them)
        assert not scheduler.can_run_parallel("a", "b", dag)


class TestPluginNode:
    """Tests for PluginNode dataclass."""

    def test_plugin_node_creation(self) -> None:
        """Test creating PluginNode."""
        plugin = MockPlugin("test")
        node = PluginNode(name="test", plugin=plugin)
        assert node.name == "test"
        assert node.plugin == plugin
        assert node.mutexes == []
        assert node.dependencies == []

    def test_plugin_node_with_mutexes(self) -> None:
        """Test PluginNode with mutexes."""
        plugin = MockPlugin("test")
        node = PluginNode(
            name="test",
            plugin=plugin,
            mutexes=["mutex1", "mutex2"],
            dependencies=["dep1"],
        )
        assert node.mutexes == ["mutex1", "mutex2"]
        assert node.dependencies == ["dep1"]
