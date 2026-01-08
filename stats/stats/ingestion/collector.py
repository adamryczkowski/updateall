"""Real-time metrics collection during plugin execution.

This module provides the DuckDBMetricsCollector class for collecting
and storing metrics in real-time as plugins execute.
"""

from __future__ import annotations

import resource
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog

from stats.db.connection import DatabaseConnection, get_default_db_path
from stats.db.models import (
    Estimate,
    ExecutionStatus,
    PluginExecution,
    Run,
    StepMetrics,
    StepPhase,
)
from stats.repository.estimates import EstimatesRepository
from stats.repository.executions import ExecutionsRepository
from stats.repository.metrics import MetricsRepository
from stats.repository.runs import RunsRepository

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)


@dataclass
class StepMetricsData:
    """In-progress metrics data for a step.

    This class holds the metrics being collected for a step that
    is currently in progress. When the step ends, this data is
    used to create a StepMetrics record.

    Attributes:
        step_name: Name of the step (e.g., "prepare", "download", "update").
        phase: Phase of execution (CHECK, DOWNLOAD, EXECUTE).
        start_time: When the step started.
        start_wall_clock: Wall clock time at start (from time.perf_counter).
        start_cpu_user: CPU user time at start.
        start_cpu_kernel: CPU kernel time at start.
    """

    step_name: str
    phase: StepPhase
    start_time: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    start_wall_clock: float = field(default_factory=time.perf_counter)
    start_cpu_user: float = 0.0
    start_cpu_kernel: float = 0.0

    def __post_init__(self) -> None:
        """Capture CPU times at initialization."""
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.start_cpu_user = usage.ru_utime
        self.start_cpu_kernel = usage.ru_stime


class DuckDBMetricsCollector:
    """Collects and stores metrics in real-time during plugin execution.

    This class provides methods to track runs, plugin executions, and
    step-level metrics. It stores all data in a DuckDB database for
    later analysis and model training.

    Example:
        >>> collector = DuckDBMetricsCollector("/path/to/db.duckdb")
        >>> run_id = collector.start_run("hostname", "username")
        >>> collector.start_plugin_execution("apt")
        >>> collector.start_step("apt", "update", "EXECUTE")
        >>> # ... plugin executes ...
        >>> collector.end_step("apt", "update", download_size_bytes=1024)
        >>> collector.end_plugin_execution("apt", "success", packages_updated=5)
        >>> collector.end_run(total_plugins=1, successful=1, failed=0, skipped=0)

    Attributes:
        db_path: Path to the DuckDB database file.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize the metrics collector.

        Args:
            db_path: Path to the DuckDB database file.
                    Uses the default XDG path if not provided.
        """
        if db_path is None:
            self.db_path = get_default_db_path()
        else:
            self.db_path = Path(db_path)

        self._db: DatabaseConnection | None = None
        self._conn: duckdb.DuckDBPyConnection | None = None

        # Current state tracking
        self._current_run_id: UUID | None = None
        self._current_executions: dict[str, UUID] = {}  # plugin_name -> execution_id
        self._current_steps: dict[str, StepMetricsData] = {}  # "plugin:step" -> data

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create a database connection.

        Returns:
            The DuckDB connection.
        """
        if self._db is None:
            self._db = DatabaseConnection(self.db_path)
            self._conn = self._db.connect()
        return self._conn  # type: ignore[return-value]

    def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            self._db.close()
            self._db = None
            self._conn = None

    def start_run(
        self,
        hostname: str | None = None,
        username: str | None = None,
        config_hash: str | None = None,
    ) -> UUID:
        """Start tracking a new update-all run.

        Creates a new run record in the database and sets it as the
        current run for subsequent operations.

        Args:
            hostname: Name of the host machine. Defaults to socket.gethostname().
            username: User who initiated the run.
            config_hash: Hash of the configuration used.

        Returns:
            The UUID of the new run.
        """
        conn = self._get_connection()
        repo = RunsRepository(conn)

        if hostname is None:
            hostname = socket.gethostname()

        run = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname=hostname,
            username=username,
            config_hash=config_hash,
        )

        created = repo.create(run)
        self._current_run_id = created.run_id
        self._current_executions.clear()
        self._current_steps.clear()

        logger.info(
            "run_started",
            run_id=str(created.run_id),
            hostname=hostname,
        )

        return created.run_id

    def end_run(
        self,
        total_plugins: int = 0,
        successful: int = 0,
        failed: int = 0,
        skipped: int = 0,
    ) -> None:
        """End the current run and update its record.

        Args:
            total_plugins: Total number of plugins scheduled.
            successful: Number of plugins that completed successfully.
            failed: Number of plugins that failed.
            skipped: Number of plugins that were skipped.

        Raises:
            RuntimeError: If no run is currently active.
        """
        if self._current_run_id is None:
            raise RuntimeError("No active run. Call start_run() first.")

        conn = self._get_connection()
        repo = RunsRepository(conn)

        run = repo.get_by_id(self._current_run_id)
        if run is None:
            raise RuntimeError(f"Run {self._current_run_id} not found in database")

        run.end_time = datetime.now(tz=UTC)
        run.total_plugins = total_plugins
        run.successful_plugins = successful
        run.failed_plugins = failed
        run.skipped_plugins = skipped

        repo.update(run)

        logger.info(
            "run_ended",
            run_id=str(self._current_run_id),
            total=total_plugins,
            successful=successful,
            failed=failed,
            skipped=skipped,
        )

        self._current_run_id = None
        self._current_executions.clear()
        self._current_steps.clear()

    def start_plugin_execution(
        self,
        plugin_name: str,
        packages_total: int | None = None,
    ) -> UUID:
        """Start tracking a plugin execution.

        Args:
            plugin_name: Name of the plugin being executed.
            packages_total: Total number of packages managed by this plugin.

        Returns:
            The UUID of the new execution.

        Raises:
            RuntimeError: If no run is currently active.
        """
        if self._current_run_id is None:
            raise RuntimeError("No active run. Call start_run() first.")

        conn = self._get_connection()
        repo = ExecutionsRepository(conn)

        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=self._current_run_id,
            plugin_name=plugin_name,
            status=ExecutionStatus.RUNNING,
            start_time=datetime.now(tz=UTC),
            packages_total=packages_total,
        )

        created = repo.create(execution)
        self._current_executions[plugin_name] = created.execution_id

        logger.debug(
            "plugin_execution_started",
            plugin_name=plugin_name,
            execution_id=str(created.execution_id),
        )

        return created.execution_id

    def end_plugin_execution(
        self,
        plugin_name: str,
        status: str | ExecutionStatus,
        packages_updated: int = 0,
        error_message: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """End a plugin execution and update its record.

        Args:
            plugin_name: Name of the plugin.
            status: Final status of the execution (success, failed, etc.).
            packages_updated: Number of packages that were updated.
            error_message: Error message if the execution failed.
            exit_code: Exit code of the plugin process.

        Raises:
            RuntimeError: If the plugin execution is not active.
        """
        if plugin_name not in self._current_executions:
            raise RuntimeError(f"No active execution for plugin {plugin_name}")

        execution_id = self._current_executions[plugin_name]
        conn = self._get_connection()
        repo = ExecutionsRepository(conn)

        execution = repo.get_by_id(execution_id)
        if execution is None:
            raise RuntimeError(f"Execution {execution_id} not found in database")

        # Convert string status to enum if needed
        if isinstance(status, str):
            status = ExecutionStatus(status)

        execution.status = status
        execution.end_time = datetime.now(tz=UTC)
        execution.packages_updated = packages_updated
        execution.error_message = error_message
        execution.exit_code = exit_code

        repo.update(execution)

        logger.debug(
            "plugin_execution_ended",
            plugin_name=plugin_name,
            status=status.value,
            packages_updated=packages_updated,
        )

        del self._current_executions[plugin_name]

    def start_step(
        self,
        plugin_name: str,
        step_name: str,
        phase: str | StepPhase,
    ) -> None:
        """Start tracking metrics for a step.

        Args:
            plugin_name: Name of the plugin.
            step_name: Name of the step (e.g., "prepare", "download", "update").
            phase: Phase of execution (CHECK, DOWNLOAD, EXECUTE).

        Raises:
            RuntimeError: If the plugin execution is not active.
        """
        if plugin_name not in self._current_executions:
            raise RuntimeError(f"No active execution for plugin {plugin_name}")

        # Convert string phase to enum if needed
        if isinstance(phase, str):
            phase = StepPhase(phase)

        step_key = f"{plugin_name}:{step_name}"
        self._current_steps[step_key] = StepMetricsData(
            step_name=step_name,
            phase=phase,
        )

        logger.debug(
            "step_started",
            plugin_name=plugin_name,
            step_name=step_name,
            phase=phase.value,
        )

    def end_step(
        self,
        plugin_name: str,
        step_name: str,
        download_size_bytes: int | None = None,
        memory_peak_bytes: int | None = None,
        io_read_bytes: int | None = None,
        io_write_bytes: int | None = None,
        network_rx_bytes: int | None = None,
        network_tx_bytes: int | None = None,
    ) -> None:
        """End a step and store its metrics.

        Args:
            plugin_name: Name of the plugin.
            step_name: Name of the step.
            download_size_bytes: Size of downloaded data in bytes.
            memory_peak_bytes: Peak memory usage in bytes.
            io_read_bytes: Bytes read from disk.
            io_write_bytes: Bytes written to disk.
            network_rx_bytes: Bytes received over network.
            network_tx_bytes: Bytes transmitted over network.

        Raises:
            RuntimeError: If the step is not active.
        """
        step_key = f"{plugin_name}:{step_name}"
        if step_key not in self._current_steps:
            raise RuntimeError(f"No active step {step_name} for plugin {plugin_name}")

        step_data = self._current_steps[step_key]
        execution_id = self._current_executions[plugin_name]

        # Calculate elapsed times
        end_time = datetime.now(tz=UTC)
        wall_clock_seconds = time.perf_counter() - step_data.start_wall_clock

        # Get CPU times
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_user_seconds = usage.ru_utime - step_data.start_cpu_user
        cpu_kernel_seconds = usage.ru_stime - step_data.start_cpu_kernel

        # Calculate download speed if applicable
        download_speed_bps: float | None = None
        if download_size_bytes is not None and wall_clock_seconds > 0:
            download_speed_bps = download_size_bytes / wall_clock_seconds

        # Create metrics record
        conn = self._get_connection()
        repo = MetricsRepository(conn)

        metrics = StepMetrics(
            metric_id=uuid4(),
            execution_id=execution_id,
            step_name=step_name,
            phase=step_data.phase,
            start_time=step_data.start_time,
            end_time=end_time,
            wall_clock_seconds=wall_clock_seconds,
            cpu_user_seconds=cpu_user_seconds,
            cpu_kernel_seconds=cpu_kernel_seconds,
            memory_peak_bytes=memory_peak_bytes,
            io_read_bytes=io_read_bytes,
            io_write_bytes=io_write_bytes,
            network_rx_bytes=network_rx_bytes,
            network_tx_bytes=network_tx_bytes,
            download_size_bytes=download_size_bytes,
            download_speed_bps=download_speed_bps,
        )

        repo.create(metrics)

        logger.debug(
            "step_ended",
            plugin_name=plugin_name,
            step_name=step_name,
            wall_clock_seconds=wall_clock_seconds,
            download_size_bytes=download_size_bytes,
        )

        del self._current_steps[step_key]

    def record_estimate(
        self,
        plugin_name: str,
        phase: str | StepPhase,
        download_bytes: int | None = None,
        cpu_seconds: float | None = None,
        wall_seconds: float | None = None,
        memory_bytes: int | None = None,
        package_count: int | None = None,
        confidence: float | None = None,
    ) -> UUID:
        """Record a plugin's estimate for a phase.

        Args:
            plugin_name: Name of the plugin.
            phase: Phase this estimate applies to.
            download_bytes: Estimated download size in bytes.
            cpu_seconds: Estimated CPU time in seconds.
            wall_seconds: Estimated wall-clock time in seconds.
            memory_bytes: Estimated peak memory usage in bytes.
            package_count: Estimated number of packages to update.
            confidence: Confidence level of the estimate (0.0 - 1.0).

        Returns:
            The UUID of the new estimate.

        Raises:
            RuntimeError: If the plugin execution is not active.
        """
        if plugin_name not in self._current_executions:
            raise RuntimeError(f"No active execution for plugin {plugin_name}")

        execution_id = self._current_executions[plugin_name]

        # Convert string phase to enum if needed
        if isinstance(phase, str):
            phase = StepPhase(phase)

        conn = self._get_connection()
        repo = EstimatesRepository(conn)

        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=execution_id,
            phase=phase,
            download_bytes_est=download_bytes,
            cpu_seconds_est=cpu_seconds,
            wall_seconds_est=wall_seconds,
            memory_bytes_est=memory_bytes,
            package_count_est=package_count,
            confidence=confidence,
        )

        created = repo.create(estimate)

        logger.debug(
            "estimate_recorded",
            plugin_name=plugin_name,
            phase=phase.value,
            download_bytes=download_bytes,
            confidence=confidence,
        )

        return created.estimate_id

    @property
    def current_run_id(self) -> UUID | None:
        """Get the current run ID, if any.

        Returns:
            The current run ID or None if no run is active.
        """
        return self._current_run_id

    def get_execution_id(self, plugin_name: str) -> UUID | None:
        """Get the execution ID for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            The execution ID or None if not found.
        """
        return self._current_executions.get(plugin_name)
