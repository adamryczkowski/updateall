"""Mutex system for plugin execution coordination.

This module provides a mutex manager for preventing conflicts between
plugins that update shared resources.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class MutexInfo:
    """Information about a held mutex."""

    name: str
    holder: str
    acquired_at: float = field(default_factory=time.monotonic)


class MutexManager:
    """Manages mutex acquisition and release for plugin coordination.

    Mutexes prevent conflicts between plugins that update shared resources.
    For example, apt and dpkg both need exclusive access to the dpkg lock.

    Mutex naming convention:
    - pkgmgr:apt, pkgmgr:dpkg - Package manager locks
    - runtime:python, runtime:node - Language runtime updates
    - app:firefox, app:vscode - Application updates
    - system:network, system:disk - System resources
    """

    def __init__(self) -> None:
        """Initialize the mutex manager."""
        self._held: dict[str, MutexInfo] = {}
        self._lock = asyncio.Lock()
        self._waiters: dict[str, asyncio.Event] = {}
        self._log = logger.bind(component="mutex_manager")

    async def acquire(
        self,
        plugin: str,
        mutexes: list[str],
        timeout: float = 300.0,
    ) -> bool:
        """Acquire all mutexes for a plugin.

        This method atomically acquires all requested mutexes. If any mutex
        is unavailable, it waits until all can be acquired or timeout occurs.

        Args:
            plugin: Name of the plugin requesting the mutexes.
            mutexes: List of mutex names to acquire.
            timeout: Maximum time to wait in seconds.

        Returns:
            True if all mutexes were acquired, False on timeout.
        """
        if not mutexes:
            return True

        deadline = time.monotonic() + timeout
        log = self._log.bind(plugin=plugin, mutexes=mutexes)

        log.debug("acquiring_mutexes")

        while True:
            async with self._lock:
                # Check if all mutexes are available
                conflicts = self._get_conflicts(mutexes)

                if not conflicts:
                    # Acquire all mutexes atomically
                    now = time.monotonic()
                    for mutex in mutexes:
                        self._held[mutex] = MutexInfo(
                            name=mutex,
                            holder=plugin,
                            acquired_at=now,
                        )
                    log.debug("mutexes_acquired")
                    return True

                # Log what we're waiting for
                log.debug(
                    "waiting_for_mutexes",
                    conflicts={m: self._held[m].holder for m in conflicts},
                )

            # Check timeout
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("mutex_acquisition_timeout", conflicts=conflicts)
                return False

            # Wait for any held mutex to be released
            await asyncio.sleep(min(0.1, remaining))

    async def release(self, plugin: str, mutexes: list[str] | None = None) -> None:
        """Release mutexes held by a plugin.

        Args:
            plugin: Name of the plugin releasing mutexes.
            mutexes: Specific mutexes to release. If None, releases all
                     mutexes held by the plugin.
        """
        async with self._lock:
            if mutexes is None:
                # Release all mutexes held by this plugin
                to_release = [name for name, info in self._held.items() if info.holder == plugin]
            else:
                # Release only specified mutexes
                to_release = [
                    m for m in mutexes if m in self._held and self._held[m].holder == plugin
                ]

            for mutex in to_release:
                del self._held[mutex]

            if to_release:
                self._log.debug(
                    "mutexes_released",
                    plugin=plugin,
                    released=to_release,
                )

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

    def _get_conflicts(self, mutexes: list[str]) -> list[str]:
        """Get mutexes from the list that are currently held.

        Args:
            mutexes: List of mutex names to check.

        Returns:
            List of mutex names that are currently held.
        """
        return [m for m in mutexes if m in self._held]


# Standard mutex names for common resources
class StandardMutexes:
    """Standard mutex names for common resources."""

    # Package manager locks
    APT_LOCK = "pkgmgr:apt"
    DPKG_LOCK = "pkgmgr:dpkg"
    SNAP_LOCK = "pkgmgr:snap"
    FLATPAK_LOCK = "pkgmgr:flatpak"
    PIPX_LOCK = "pkgmgr:pipx"
    CARGO_LOCK = "pkgmgr:cargo"
    NPM_LOCK = "pkgmgr:npm"
    RUSTUP_LOCK = "pkgmgr:rustup"

    # Runtime locks
    PYTHON_RUNTIME = "runtime:python"
    NODE_RUNTIME = "runtime:node"
    RUST_RUNTIME = "runtime:rust"

    # System resources
    NETWORK = "system:network"
    DISK = "system:disk"
