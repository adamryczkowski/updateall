"""DAG-based scheduler for plugin execution.

This module provides a scheduler that builds a directed acyclic graph (DAG)
from plugin dependencies and mutexes, then determines execution order.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .interfaces import UpdatePlugin

logger = structlog.get_logger(__name__)


class SchedulingError(Exception):
    """Error during scheduling."""

    pass


@dataclass
class PluginNode:
    """Node in the execution DAG representing a plugin."""

    name: str
    plugin: UpdatePlugin
    mutexes: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    runs_after: list[str] = field(default_factory=list)


class ExecutionDAG:
    """Directed Acyclic Graph for plugin execution ordering.

    The DAG represents dependencies between plugins, including:
    - Explicit dependencies (runs-after relationships)
    - Implicit dependencies from mutex conflicts
    """

    def __init__(self) -> None:
        """Initialize an empty DAG."""
        self.nodes: dict[str, PluginNode] = {}
        self.edges: dict[str, set[str]] = defaultdict(set)  # from -> set of to
        self.reverse_edges: dict[str, set[str]] = defaultdict(set)  # to -> set of from

    def add_node(self, name: str, plugin: UpdatePlugin) -> None:
        """Add a plugin node to the DAG.

        Args:
            name: Plugin name.
            plugin: The plugin instance.
        """
        if name not in self.nodes:
            self.nodes[name] = PluginNode(name=name, plugin=plugin)

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a directed edge from one plugin to another.

        An edge from A to B means A must complete before B can start.

        Args:
            from_node: Plugin that must complete first.
            to_node: Plugin that depends on from_node.
        """
        if from_node not in self.nodes or to_node not in self.nodes:
            return

        if to_node not in self.edges[from_node]:
            self.edges[from_node].add(to_node)
            self.reverse_edges[to_node].add(from_node)

    def predecessors(self, node: str) -> set[str]:
        """Get all predecessors of a node (plugins that must complete first).

        Args:
            node: Plugin name.

        Returns:
            Set of plugin names that must complete before this plugin.
        """
        return self.reverse_edges.get(node, set())

    def successors(self, node: str) -> set[str]:
        """Get all successors of a node (plugins that depend on this one).

        Args:
            node: Plugin name.

        Returns:
            Set of plugin names that depend on this plugin.
        """
        return self.edges.get(node, set())

    def has_cycle(self) -> bool:
        """Check if the DAG contains a cycle.

        Returns:
            True if a cycle exists, False otherwise.
        """
        # Use DFS with coloring: 0=white (unvisited), 1=gray (visiting), 2=black (done)
        colors: dict[str, int] = dict.fromkeys(self.nodes, 0)

        def dfs(node: str) -> bool:
            colors[node] = 1  # Mark as visiting
            for neighbor in self.edges.get(node, set()):
                if colors[neighbor] == 1:  # Back edge found
                    return True
                if colors[neighbor] == 0 and dfs(neighbor):
                    return True
            colors[node] = 2  # Mark as done
            return False

        return any(colors[node] == 0 and dfs(node) for node in self.nodes)

    def find_cycle(self) -> list[str]:
        """Find a cycle in the DAG if one exists.

        Returns:
            List of plugin names forming a cycle, or empty list if no cycle.
        """
        colors: dict[str, int] = dict.fromkeys(self.nodes, 0)

        def dfs(node: str, path: list[str]) -> list[str]:
            colors[node] = 1
            path.append(node)

            for neighbor in self.edges.get(node, set()):
                if colors[neighbor] == 1:
                    # Found cycle, extract it
                    cycle_start = path.index(neighbor)
                    return [*path[cycle_start:], neighbor]
                if colors[neighbor] == 0:
                    result = dfs(neighbor, path)
                    if result:
                        return result

            path.pop()
            colors[node] = 2
            return []

        for node in self.nodes:
            if colors[node] == 0:
                cycle = dfs(node, [])
                if cycle:
                    return cycle
        return []

    def topological_sort(self) -> list[str]:
        """Perform topological sort on the DAG.

        Returns:
            List of plugin names in topological order.

        Raises:
            SchedulingError: If the DAG contains a cycle.
        """
        if self.has_cycle():
            cycle = self.find_cycle()
            raise SchedulingError(f"Circular dependency detected: {' -> '.join(cycle)}")

        # Kahn's algorithm
        in_degree = {node: len(self.reverse_edges.get(node, set())) for node in self.nodes}
        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # Sort for deterministic ordering
            queue.sort()
            node = queue.pop(0)
            result.append(node)

            for neighbor in self.edges.get(node, set()):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result


class Scheduler:
    """DAG-based scheduler for plugin execution.

    The scheduler builds an execution DAG from plugin dependencies and
    mutex conflicts, then determines the optimal execution order.
    """

    def __init__(self) -> None:
        """Initialize the scheduler."""
        self._log = logger.bind(component="scheduler")

    def build_execution_dag(
        self,
        plugins: list[UpdatePlugin],
        plugin_mutexes: dict[str, list[str]] | None = None,
        plugin_dependencies: dict[str, list[str]] | None = None,
    ) -> ExecutionDAG:
        """Build an execution DAG from plugins and their constraints.

        Args:
            plugins: List of plugins to schedule.
            plugin_mutexes: Optional dict mapping plugin names to their mutexes.
            plugin_dependencies: Optional dict mapping plugin names to dependencies.

        Returns:
            ExecutionDAG representing the execution order.

        Raises:
            SchedulingError: If a circular dependency is detected.
        """
        dag = ExecutionDAG()
        plugin_mutexes = plugin_mutexes or {}
        plugin_dependencies = plugin_dependencies or {}

        # Add all plugins as nodes
        for plugin in plugins:
            dag.add_node(plugin.name, plugin)
            node = dag.nodes[plugin.name]
            node.mutexes = plugin_mutexes.get(plugin.name, [])
            node.dependencies = plugin_dependencies.get(plugin.name, [])

        # Add edges from explicit dependencies
        for plugin in plugins:
            deps = plugin_dependencies.get(plugin.name, [])
            for dep in deps:
                if dep in dag.nodes:
                    dag.add_edge(dep, plugin.name)
                    self._log.debug(
                        "added_dependency_edge",
                        from_plugin=dep,
                        to_plugin=plugin.name,
                    )

        # Add edges from mutex conflicts
        # If two plugins share a mutex, they cannot run in parallel
        # We add an edge based on alphabetical order for determinism
        plugin_names = [p.name for p in plugins]
        for i, name1 in enumerate(plugin_names):
            mutexes1 = set(plugin_mutexes.get(name1, []))
            for name2 in plugin_names[i + 1 :]:
                mutexes2 = set(plugin_mutexes.get(name2, []))
                shared = mutexes1 & mutexes2
                if shared:
                    # Add edge from alphabetically first to second
                    if name1 < name2:
                        dag.add_edge(name1, name2)
                    else:
                        dag.add_edge(name2, name1)
                    self._log.debug(
                        "added_mutex_edge",
                        from_plugin=min(name1, name2),
                        to_plugin=max(name1, name2),
                        shared_mutexes=list(shared),
                    )

        # Validate no cycles
        if dag.has_cycle():
            cycle = dag.find_cycle()
            raise SchedulingError(f"Circular dependency detected: {' -> '.join(cycle)}")

        return dag

    def get_execution_waves(self, dag: ExecutionDAG) -> list[list[str]]:
        """Group plugins into execution waves.

        Plugins in the same wave can be executed in parallel.
        Each wave must complete before the next wave starts.

        Args:
            dag: The execution DAG.

        Returns:
            List of waves, where each wave is a list of plugin names.
        """
        waves: list[list[str]] = []
        remaining = set(dag.nodes.keys())
        completed: set[str] = set()

        while remaining:
            # Find nodes with no unprocessed dependencies
            wave = [
                node
                for node in remaining
                if all(dep in completed for dep in dag.predecessors(node))
            ]

            if not wave:
                # This shouldn't happen if the DAG is acyclic
                raise SchedulingError("Unable to make progress - possible deadlock")

            # Sort for deterministic ordering
            wave.sort()
            waves.append(wave)

            # Mark as completed
            completed.update(wave)
            remaining -= set(wave)

            self._log.debug("wave_determined", wave_number=len(waves), plugins=wave)

        return waves

    def get_execution_order(self, dag: ExecutionDAG) -> list[str]:
        """Get a linear execution order for plugins.

        This is useful for sequential execution or as a fallback.

        Args:
            dag: The execution DAG.

        Returns:
            List of plugin names in execution order.
        """
        return dag.topological_sort()

    def can_run_parallel(
        self,
        plugin1: str,
        plugin2: str,
        dag: ExecutionDAG,
    ) -> bool:
        """Check if two plugins can run in parallel.

        Args:
            plugin1: First plugin name.
            plugin2: Second plugin name.
            dag: The execution DAG.

        Returns:
            True if the plugins can run in parallel, False otherwise.
        """
        # Check if there's a path between them
        if plugin2 in dag.predecessors(plugin1):
            return False
        if plugin1 in dag.predecessors(plugin2):
            return False

        # Check for shared mutexes
        node1 = dag.nodes.get(plugin1)
        node2 = dag.nodes.get(plugin2)
        if node1 and node2:
            shared = set(node1.mutexes) & set(node2.mutexes)
            if shared:
                return False

        return True
