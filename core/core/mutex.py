"""Mutex system for plugin execution coordination.

This module provides a mutex manager for preventing conflicts between
plugins that update shared resources.

Phase 1 Enhancements (Risk T4 mitigation):
- Ordered mutex acquisition to prevent deadlocks
- asyncio.Condition for efficient waiting instead of polling
- Deadlock detection with configurable timeout
- Comprehensive mutex state logging
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from core.streaming import Phase

logger = structlog.get_logger(__name__)


class DeadlockError(Exception):
    """Raised when a potential deadlock is detected."""

    def __init__(
        self,
        plugin: str,
        mutexes: list[str],
        conflicts: dict[str, str],
        wait_time: float,
    ) -> None:
        """Initialize the deadlock error.

        Args:
            plugin: Plugin that detected the deadlock
            mutexes: Mutexes the plugin was trying to acquire
            conflicts: Dict of mutex -> holder for conflicting mutexes
            wait_time: How long the plugin waited before detecting deadlock
        """
        self.plugin = plugin
        self.mutexes = mutexes
        self.conflicts = conflicts
        self.wait_time = wait_time
        super().__init__(
            f"Potential deadlock detected: {plugin} waiting for {mutexes} "
            f"held by {conflicts} after {wait_time:.1f}s"
        )


class MutexState(str, Enum):
    """State of a mutex acquisition attempt."""

    ACQUIRED = "acquired"
    WAITING = "waiting"
    TIMEOUT = "timeout"
    DEADLOCK = "deadlock"


@dataclass
class MutexInfo:
    """Information about a held mutex."""

    name: str
    holder: str
    acquired_at: float = field(default_factory=time.monotonic)

    @property
    def hold_duration(self) -> float:
        """Return how long the mutex has been held in seconds."""
        return time.monotonic() - self.acquired_at


@dataclass
class WaiterInfo:
    """Information about a plugin waiting for mutexes."""

    plugin: str
    mutexes: list[str]
    started_at: float = field(default_factory=time.monotonic)

    @property
    def wait_duration(self) -> float:
        """Return how long the plugin has been waiting in seconds."""
        return time.monotonic() - self.started_at


class MutexManager:
    """Manages mutex acquisition and release for plugin coordination.

    Mutexes prevent conflicts between plugins that update shared resources.
    For example, apt and dpkg both need exclusive access to the dpkg lock.

    Phase 1 Enhancements:
    - Ordered acquisition: Mutexes are always acquired in sorted order to
      prevent deadlocks (Risk T4 mitigation)
    - Efficient waiting: Uses asyncio.Condition instead of polling
    - Deadlock detection: Detects potential deadlocks after configurable timeout
    - Comprehensive logging: Detailed logging of mutex state changes

    Mutex naming convention:
    - pkgmgr:apt, pkgmgr:dpkg - Package manager locks
    - runtime:python, runtime:node - Language runtime updates
    - app:firefox, app:vscode - Application updates
    - system:network, system:disk - System resources
    """

    def __init__(
        self,
        deadlock_timeout: float = 60.0,
        enable_deadlock_detection: bool = True,
    ) -> None:
        """Initialize the mutex manager.

        Args:
            deadlock_timeout: Time in seconds after which to detect potential deadlock.
            enable_deadlock_detection: Whether to enable deadlock detection.
        """
        self._held: dict[str, MutexInfo] = {}
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._waiters: dict[str, WaiterInfo] = {}
        self._deadlock_timeout = deadlock_timeout
        self._enable_deadlock_detection = enable_deadlock_detection
        self._log = logger.bind(component="mutex_manager")

    @property
    def deadlock_timeout(self) -> float:
        """Return the deadlock detection timeout in seconds."""
        return self._deadlock_timeout

    @property
    def enable_deadlock_detection(self) -> bool:
        """Return whether deadlock detection is enabled."""
        return self._enable_deadlock_detection

    async def acquire(
        self,
        plugin: str,
        mutexes: list[str],
        timeout: float = 300.0,
    ) -> bool:
        """Acquire all mutexes for a plugin.

        This method atomically acquires all requested mutexes. If any mutex
        is unavailable, it waits until all can be acquired or timeout occurs.

        Mutexes are acquired in sorted order to prevent deadlocks (Risk T4).

        Args:
            plugin: Name of the plugin requesting the mutexes.
            mutexes: List of mutex names to acquire.
            timeout: Maximum time to wait in seconds.

        Returns:
            True if all mutexes were acquired, False on timeout.

        Raises:
            DeadlockError: If a potential deadlock is detected.
        """
        if not mutexes:
            return True

        # Sort mutexes to prevent deadlocks (Risk T4 mitigation)
        sorted_mutexes = sorted(set(mutexes))

        deadline = time.monotonic() + timeout
        log = self._log.bind(plugin=plugin, mutexes=sorted_mutexes)

        log.debug("acquiring_mutexes", original_order=mutexes)

        # Register as waiter for deadlock detection
        waiter_info = WaiterInfo(plugin=plugin, mutexes=sorted_mutexes)
        self._waiters[plugin] = waiter_info

        try:
            async with self._condition:
                while True:
                    # Check if all mutexes are available
                    conflicts = self._get_conflicts(sorted_mutexes)

                    if not conflicts:
                        # Acquire all mutexes atomically
                        now = time.monotonic()
                        for mutex in sorted_mutexes:
                            self._held[mutex] = MutexInfo(
                                name=mutex,
                                holder=plugin,
                                acquired_at=now,
                            )

                        log.info(
                            "mutexes_acquired",
                            count=len(sorted_mutexes),
                            state=MutexState.ACQUIRED.value,
                        )
                        return True

                    # Log what we're waiting for
                    conflict_holders = {m: self._held[m].holder for m in conflicts}
                    log.debug(
                        "waiting_for_mutexes",
                        conflicts=conflict_holders,
                        state=MutexState.WAITING.value,
                    )

                    # Check for potential deadlock
                    if self._enable_deadlock_detection:
                        wait_duration = waiter_info.wait_duration
                        # Combine conditions to avoid nested if (SIM102)
                        if wait_duration > self._deadlock_timeout and self._detect_deadlock(
                            plugin, sorted_mutexes
                        ):
                            log.error(
                                "deadlock_detected",
                                conflicts=conflict_holders,
                                wait_duration=wait_duration,
                                state=MutexState.DEADLOCK.value,
                            )
                            raise DeadlockError(
                                plugin=plugin,
                                mutexes=sorted_mutexes,
                                conflicts=conflict_holders,
                                wait_time=wait_duration,
                            )

                    # Calculate remaining time
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        log.warning(
                            "mutex_acquisition_timeout",
                            conflicts=conflict_holders,
                            state=MutexState.TIMEOUT.value,
                        )
                        return False

                    # Wait for condition with timeout
                    # Use min of remaining time and a check interval for deadlock detection
                    wait_time = min(remaining, self._deadlock_timeout / 2)
                    # Use contextlib.suppress for expected timeout (SIM105)
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._condition.wait(),
                            timeout=wait_time,
                        )

        finally:
            # Remove from waiters
            self._waiters.pop(plugin, None)

    async def release(self, plugin: str, mutexes: list[str] | None = None) -> None:
        """Release mutexes held by a plugin.

        Args:
            plugin: Name of the plugin releasing mutexes.
            mutexes: Specific mutexes to release. If None, releases all
                     mutexes held by the plugin.
        """
        async with self._condition:
            if mutexes is None:
                # Release all mutexes held by this plugin
                to_release = [name for name, info in self._held.items() if info.holder == plugin]
            else:
                # Release only specified mutexes
                to_release = [
                    m for m in mutexes if m in self._held and self._held[m].holder == plugin
                ]

            # Calculate hold durations for logging
            hold_durations = {}
            for mutex in to_release:
                info = self._held.get(mutex)
                if info:
                    hold_durations[mutex] = info.hold_duration
                del self._held[mutex]

            if to_release:
                self._log.info(
                    "mutexes_released",
                    plugin=plugin,
                    released=to_release,
                    hold_durations=hold_durations,
                )

                # Notify all waiters that mutexes are available
                self._condition.notify_all()

    def get_holder(self, mutex: str) -> str | None:
        """Get the plugin currently holding a mutex.

        Args:
            mutex: Name of the mutex.

        Returns:
            Name of the holding plugin, or None if not held.
        """
        info = self._held.get(mutex)
        return info.holder if info else None

    def is_held(self, mutex: str) -> bool:
        """Check if a mutex is currently held.

        Args:
            mutex: Name of the mutex.

        Returns:
            True if the mutex is held, False otherwise.
        """
        return mutex in self._held

    def get_held_by(self, plugin: str) -> list[str]:
        """Get all mutexes held by a plugin.

        Args:
            plugin: Name of the plugin.

        Returns:
            List of mutex names held by the plugin.
        """
        return [name for name, info in self._held.items() if info.holder == plugin]

    def get_all_held(self) -> dict[str, str]:
        """Get all currently held mutexes.

        Returns:
            Dictionary mapping mutex names to holder plugin names.
        """
        return {name: info.holder for name, info in self._held.items()}

    def get_mutex_info(self, mutex: str) -> MutexInfo | None:
        """Get detailed information about a mutex.

        Args:
            mutex: Name of the mutex.

        Returns:
            MutexInfo if held, None otherwise.
        """
        return self._held.get(mutex)

    def get_all_mutex_info(self) -> dict[str, MutexInfo]:
        """Get detailed information about all held mutexes.

        Returns:
            Dictionary mapping mutex names to MutexInfo.
        """
        return dict(self._held)

    def get_waiters(self) -> dict[str, WaiterInfo]:
        """Get information about all waiting plugins.

        Returns:
            Dictionary mapping plugin names to WaiterInfo.
        """
        return dict(self._waiters)

    def get_state_summary(self) -> dict[str, Any]:
        """Get a summary of the current mutex state.

        Useful for debugging and monitoring.

        Returns:
            Dictionary with mutex state information.
        """
        return {
            "held_count": len(self._held),
            "waiter_count": len(self._waiters),
            "held_mutexes": {
                name: {
                    "holder": info.holder,
                    "hold_duration": info.hold_duration,
                }
                for name, info in self._held.items()
            },
            "waiters": {
                plugin: {
                    "mutexes": info.mutexes,
                    "wait_duration": info.wait_duration,
                }
                for plugin, info in self._waiters.items()
            },
        }

    def _get_conflicts(self, mutexes: list[str]) -> list[str]:
        """Get mutexes from the list that are currently held.

        Args:
            mutexes: List of mutex names to check.

        Returns:
            List of mutex names that are currently held.
        """
        return [m for m in mutexes if m in self._held]

    def _detect_deadlock(self, plugin: str, mutexes: list[str]) -> bool:
        """Detect if there's a potential deadlock.

        A deadlock is detected if:
        1. Plugin A is waiting for mutexes held by Plugin B
        2. Plugin B is waiting for mutexes held by Plugin A

        This is a simplified cycle detection that only checks direct cycles.

        Args:
            plugin: The waiting plugin.
            mutexes: Mutexes the plugin is waiting for.

        Returns:
            True if a potential deadlock is detected.
        """
        # Get holders of the mutexes we're waiting for
        holders = set()
        for mutex in mutexes:
            info = self._held.get(mutex)
            if info and info.holder != plugin:
                holders.add(info.holder)

        # Check if any holder is waiting for mutexes we hold
        our_mutexes = set(self.get_held_by(plugin))
        if not our_mutexes:
            return False

        for holder in holders:
            waiter_info = self._waiters.get(holder)
            if waiter_info:
                # Check if the holder is waiting for any of our mutexes
                waiting_for = set(waiter_info.mutexes)
                if waiting_for & our_mutexes:
                    self._log.warning(
                        "deadlock_cycle_detected",
                        plugin=plugin,
                        holder=holder,
                        our_mutexes=list(our_mutexes),
                        holder_waiting_for=list(waiting_for),
                    )
                    return True

        return False


# Standard mutex names for common resources
class StandardMutexes:
    """Standard mutex names for common resources.

    Mutex naming convention:
    - pkgmgr:<name> - Package manager locks (apt, dpkg, snap, etc.)
    - runtime:<name> - Language runtime updates (python, node, rust)
    - app:<name> - Application-specific locks (firefox, vscode, etc.)
    - system:<name> - System resources (network, disk)

    Usage:
        from core.mutex import StandardMutexes

        @property
        def mutexes(self) -> dict[Phase, list[str]]:
            return {
                Phase.EXECUTE: [StandardMutexes.APT_LOCK, StandardMutexes.DPKG_LOCK],
            }
    """

    # Package manager locks
    APT_LOCK = "pkgmgr:apt"
    DPKG_LOCK = "pkgmgr:dpkg"
    SNAP_LOCK = "pkgmgr:snap"
    FLATPAK_LOCK = "pkgmgr:flatpak"
    PIPX_LOCK = "pkgmgr:pipx"
    CARGO_LOCK = "pkgmgr:cargo"
    NPM_LOCK = "pkgmgr:npm"
    RUSTUP_LOCK = "pkgmgr:rustup"

    # Additional package manager locks (Proposal 6)
    CONDA_LOCK = "pkgmgr:conda"
    TEXLIVE_LOCK = "pkgmgr:texlive"
    MISE_LOCK = "pkgmgr:mise"
    GEM_LOCK = "pkgmgr:gem"
    BREW_LOCK = "pkgmgr:brew"

    # Runtime locks
    PYTHON_RUNTIME = "runtime:python"
    NODE_RUNTIME = "runtime:node"
    RUST_RUNTIME = "runtime:rust"

    # Application locks (Proposal 6)
    FIREFOX_LOCK = "app:firefox"
    WATERFOX_LOCK = "app:waterfox"
    CALIBRE_LOCK = "app:calibre"
    VSCODE_LOCK = "app:vscode"
    JETBRAINS_LOCK = "app:jetbrains"

    # System resources
    NETWORK = "system:network"
    DISK = "system:disk"

    @classmethod
    def all_mutexes(cls) -> list[str]:
        """Return all defined mutex names.

        Returns:
            Sorted list of all mutex constant values.
        """
        return sorted(
            value
            for name, value in vars(cls).items()
            if not name.startswith("_") and isinstance(value, str) and not callable(value)
        )


# =============================================================================
# Helper Functions for Plugin Mutex/Dependency Collection (Proposal 6)
# =============================================================================


def collect_plugin_mutexes(
    plugins: list,
    phase: Phase | None = None,
) -> dict[str, list[str]]:
    """Collect mutexes from all plugins.

    This function iterates over a list of plugins and collects their
    mutex declarations. It can filter by phase or collect all mutexes.

    Args:
        plugins: List of plugin instances (must have `mutexes` property).
        phase: Optional phase to filter mutexes. If None, collects all mutexes.

    Returns:
        Dictionary mapping plugin names to their mutex lists.

    Example:
        plugins = [apt_plugin, snap_plugin, pipx_plugin]
        mutexes = collect_plugin_mutexes(plugins, Phase.EXECUTE)
        # Returns: {"apt": ["pkgmgr:apt", "pkgmgr:dpkg"], "snap": ["pkgmgr:snap"], ...}
    """

    result: dict[str, list[str]] = {}

    for plugin in plugins:
        plugin_name = getattr(plugin, "name", str(plugin))
        plugin_mutexes = getattr(plugin, "mutexes", {})

        if phase is not None:
            # Get mutexes for specific phase
            result[plugin_name] = list(plugin_mutexes.get(phase, []))
        else:
            # Get all mutexes across all phases
            all_mutexes: set[str] = set()
            for phase_mutexes in plugin_mutexes.values():
                all_mutexes.update(phase_mutexes)
            result[plugin_name] = sorted(all_mutexes)

    return result


def collect_plugin_dependencies(plugins: list) -> dict[str, list[str]]:
    """Collect dependencies from all plugins.

    This function iterates over a list of plugins and collects their
    dependency declarations.

    Args:
        plugins: List of plugin instances (must have `dependencies` property).

    Returns:
        Dictionary mapping plugin names to their dependency lists.

    Example:
        plugins = [apt_plugin, conda_packages_plugin, texlive_packages_plugin]
        deps = collect_plugin_dependencies(plugins)
        # Returns: {"apt": [], "conda-packages": ["conda-self"], ...}
    """
    result: dict[str, list[str]] = {}

    for plugin in plugins:
        plugin_name = getattr(plugin, "name", str(plugin))
        plugin_deps = getattr(plugin, "dependencies", [])
        result[plugin_name] = list(plugin_deps)

    return result


def build_dependency_graph(plugins: list) -> dict[str, set[str]]:
    """Build a dependency graph from plugin declarations.

    Creates a graph where each node is a plugin name and edges represent
    dependencies (plugin A depends on plugin B means A -> B edge).

    Args:
        plugins: List of plugin instances.

    Returns:
        Dictionary mapping plugin names to sets of dependency names.

    Example:
        graph = build_dependency_graph(plugins)
        # Returns: {"conda-packages": {"conda-self"}, "texlive-packages": {"texlive-self"}, ...}
    """
    return {
        getattr(plugin, "name", str(plugin)): set(getattr(plugin, "dependencies", []))
        for plugin in plugins
    }


def validate_dependencies(plugins: list) -> list[str]:
    """Validate plugin dependencies for common issues.

    Checks for:
    - Circular dependencies
    - Missing dependencies (plugin depends on non-existent plugin)
    - Self-dependencies

    Args:
        plugins: List of plugin instances.

    Returns:
        List of error messages. Empty list means no issues found.

    Example:
        errors = validate_dependencies(plugins)
        if errors:
            for error in errors:
                print(f"Dependency error: {error}")
    """
    errors: list[str] = []
    plugin_names = {getattr(p, "name", str(p)) for p in plugins}
    graph = build_dependency_graph(plugins)

    for plugin_name, deps in graph.items():
        # Check for self-dependency
        if plugin_name in deps:
            errors.append(f"Plugin '{plugin_name}' depends on itself")

        # Check for missing dependencies
        for dep in deps:
            if dep not in plugin_names:
                errors.append(f"Plugin '{plugin_name}' depends on non-existent plugin '{dep}'")

    # Check for circular dependencies using DFS
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def has_cycle(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                if has_cycle(neighbor):
                    return True
            elif neighbor in rec_stack:
                errors.append(f"Circular dependency detected involving '{node}' and '{neighbor}'")
                return True

        rec_stack.remove(node)
        return False

    for plugin_name in graph:
        if plugin_name not in visited:
            has_cycle(plugin_name)

    return errors
