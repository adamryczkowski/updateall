"""Resource controller for managing system resource limits.

This module provides resource control for plugin execution, including
CPU, memory, and network bandwidth limits.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ResourceLimits:
    """Configuration for resource limits.

    Attributes:
        max_parallel_tasks: Maximum number of plugins that can run in parallel.
        max_parallel_downloads: Maximum number of concurrent downloads.
        max_memory_mb: Maximum total memory usage in MB (0 = unlimited).
        max_cpu_percent: Maximum CPU usage percentage (0 = unlimited).
        nice_value: Nice value for plugin processes (0-19, higher = lower priority).
    """

    max_parallel_tasks: int = 4
    max_parallel_downloads: int = 2
    max_memory_mb: int = 0  # 0 = unlimited
    max_cpu_percent: int = 0  # 0 = unlimited
    nice_value: int = 10


@dataclass
class ResourceUsage:
    """Current resource usage statistics."""

    active_tasks: int = 0
    active_downloads: int = 0
    memory_mb: int = 0
    cpu_percent: float = 0.0
    active_pids: set[int] = field(default_factory=set)


class ResourceController:
    """Controls resource usage across all plugin executions.

    The resource controller uses semaphores to limit concurrent operations
    and monitors system resource usage.
    """

    def __init__(self, limits: ResourceLimits | None = None) -> None:
        """Initialize the resource controller.

        Args:
            limits: Resource limits configuration. Uses defaults if not provided.
        """
        self.limits = limits or ResourceLimits()
        self._task_semaphore = asyncio.Semaphore(self.limits.max_parallel_tasks)
        self._download_semaphore = asyncio.Semaphore(self.limits.max_parallel_downloads)
        self._usage = ResourceUsage()
        self._lock = asyncio.Lock()
        self._log = logger.bind(component="resource_controller")

        self._log.info(
            "initialized",
            max_parallel_tasks=self.limits.max_parallel_tasks,
            max_parallel_downloads=self.limits.max_parallel_downloads,
        )

    async def acquire_task_slot(self, plugin_name: str) -> bool:
        """Acquire a slot for task execution.

        This method blocks until a slot is available and memory limits allow.

        Args:
            plugin_name: Name of the plugin requesting the slot.

        Returns:
            True when the slot is acquired.
        """
        log = self._log.bind(plugin=plugin_name)
        log.debug("waiting_for_task_slot")

        await self._task_semaphore.acquire()

        # Wait for memory if limits are set
        if self.limits.max_memory_mb > 0:
            await self._wait_for_memory()

        async with self._lock:
            self._usage.active_tasks += 1

        log.debug("task_slot_acquired", active_tasks=self._usage.active_tasks)
        return True

    def release_task_slot(self, plugin_name: str) -> None:
        """Release a task execution slot.

        Args:
            plugin_name: Name of the plugin releasing the slot.
        """
        self._task_semaphore.release()

        # Update usage synchronously (safe since we're just decrementing)
        self._usage.active_tasks = max(0, self._usage.active_tasks - 1)

        self._log.debug(
            "task_slot_released",
            plugin=plugin_name,
            active_tasks=self._usage.active_tasks,
        )

    async def acquire_download_slot(self, plugin_name: str) -> bool:
        """Acquire a slot for download operations.

        Args:
            plugin_name: Name of the plugin requesting the slot.

        Returns:
            True when the slot is acquired.
        """
        log = self._log.bind(plugin=plugin_name)
        log.debug("waiting_for_download_slot")

        await self._download_semaphore.acquire()

        async with self._lock:
            self._usage.active_downloads += 1

        log.debug("download_slot_acquired", active_downloads=self._usage.active_downloads)
        return True

    def release_download_slot(self, plugin_name: str) -> None:
        """Release a download slot.

        Args:
            plugin_name: Name of the plugin releasing the slot.
        """
        self._download_semaphore.release()
        self._usage.active_downloads = max(0, self._usage.active_downloads - 1)

        self._log.debug(
            "download_slot_released",
            plugin=plugin_name,
            active_downloads=self._usage.active_downloads,
        )

    def register_pid(self, pid: int, plugin_name: str) -> None:
        """Register a process ID for resource tracking.

        Args:
            pid: Process ID to track.
            plugin_name: Name of the plugin that owns the process.
        """
        self._usage.active_pids.add(pid)
        self._log.debug("pid_registered", pid=pid, plugin=plugin_name)

    def unregister_pid(self, pid: int, plugin_name: str) -> None:
        """Unregister a process ID.

        Args:
            pid: Process ID to stop tracking.
            plugin_name: Name of the plugin that owned the process.
        """
        self._usage.active_pids.discard(pid)
        self._log.debug("pid_unregistered", pid=pid, plugin=plugin_name)

    def get_usage(self) -> ResourceUsage:
        """Get current resource usage.

        Returns:
            Current resource usage statistics.
        """
        return ResourceUsage(
            active_tasks=self._usage.active_tasks,
            active_downloads=self._usage.active_downloads,
            memory_mb=self._get_total_memory_mb(),
            cpu_percent=self._get_cpu_percent(),
            active_pids=set(self._usage.active_pids),
        )

    def get_available_slots(self) -> int:
        """Get the number of available task slots.

        Returns:
            Number of available slots.
        """
        return self.limits.max_parallel_tasks - self._usage.active_tasks

    async def _wait_for_memory(self) -> None:
        """Wait until memory usage is below the limit."""
        if self.limits.max_memory_mb <= 0:
            return

        while self._get_total_memory_mb() >= self.limits.max_memory_mb:
            self._log.debug(
                "waiting_for_memory",
                current_mb=self._get_total_memory_mb(),
                limit_mb=self.limits.max_memory_mb,
            )
            await asyncio.sleep(1.0)

    def _get_total_memory_mb(self) -> int:
        """Get total memory usage of tracked processes in MB.

        Returns:
            Total memory usage in MB.
        """
        try:
            import psutil

            total = 0
            for pid in list(self._usage.active_pids):
                try:
                    proc = psutil.Process(pid)
                    total += proc.memory_info().rss // (1024 * 1024)
                except psutil.NoSuchProcess:
                    self._usage.active_pids.discard(pid)
            return total
        except ImportError:
            # psutil not available
            return 0

    def _get_cpu_percent(self) -> float:
        """Get total CPU usage of tracked processes.

        Returns:
            Total CPU usage percentage.
        """
        try:
            import psutil

            total = 0.0
            for pid in list(self._usage.active_pids):
                try:
                    proc = psutil.Process(pid)
                    total += proc.cpu_percent(interval=0.1)
                except psutil.NoSuchProcess:
                    self._usage.active_pids.discard(pid)
            return total
        except ImportError:
            # psutil not available
            return 0.0


class ResourceContext:
    """Context manager for resource acquisition.

    Usage:
        async with ResourceContext(controller, "apt", task=True, download=True):
            # Run plugin with both task and download slots
            ...
    """

    def __init__(
        self,
        controller: ResourceController,
        plugin_name: str,
        *,
        task: bool = True,
        download: bool = False,
    ) -> None:
        """Initialize the resource context.

        Args:
            controller: The resource controller.
            plugin_name: Name of the plugin.
            task: Whether to acquire a task slot.
            download: Whether to acquire a download slot.
        """
        self.controller = controller
        self.plugin_name = plugin_name
        self.acquire_task = task
        self.acquire_download = download
        self._task_acquired = False
        self._download_acquired = False

    async def __aenter__(self) -> ResourceContext:
        """Acquire resources."""
        if self.acquire_task:
            await self.controller.acquire_task_slot(self.plugin_name)
            self._task_acquired = True

        if self.acquire_download:
            await self.controller.acquire_download_slot(self.plugin_name)
            self._download_acquired = True

        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: object
    ) -> None:
        """Release resources."""
        if self._download_acquired:
            self.controller.release_download_slot(self.plugin_name)

        if self._task_acquired:
            self.controller.release_task_slot(self.plugin_name)
