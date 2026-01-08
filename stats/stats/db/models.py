"""Data models for historical data storage.

This module defines dataclasses representing the core entities stored in DuckDB:
- Run: A complete update-all execution session
- PluginExecution: A single plugin's execution within a run
- StepMetrics: Metrics collected for a step (check/download/execute)
- Estimate: Plugin-reported estimates for comparison with actuals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class ExecutionStatus(str, Enum):
    """Status of a plugin execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class StepPhase(str, Enum):
    """Phase of execution.

    Each plugin execution goes through these phases:
    - CHECK: Checking for available updates
    - DOWNLOAD: Downloading update packages
    - EXECUTE: Applying the updates
    """

    CHECK = "CHECK"
    DOWNLOAD = "DOWNLOAD"
    EXECUTE = "EXECUTE"


@dataclass
class Run:
    """Represents a complete update-all run.

    A run is a single invocation of the update-all system, which may
    execute multiple plugins. Each run has a unique ID and tracks
    aggregate statistics about the plugins executed.

    Attributes:
        run_id: Unique identifier for this run.
        start_time: When the run started.
        hostname: Name of the host machine.
        end_time: When the run completed (None if still running).
        username: User who initiated the run.
        config_hash: Hash of the configuration used.
        total_plugins: Total number of plugins scheduled.
        successful_plugins: Number of plugins that completed successfully.
        failed_plugins: Number of plugins that failed.
        skipped_plugins: Number of plugins that were skipped.
        created_at: When this record was created in the database.
    """

    run_id: UUID
    start_time: datetime
    hostname: str
    end_time: datetime | None = None
    username: str | None = None
    config_hash: str | None = None
    total_plugins: int = 0
    successful_plugins: int = 0
    failed_plugins: int = 0
    skipped_plugins: int = 0
    created_at: datetime | None = field(default=None)


@dataclass
class PluginExecution:
    """Represents a single plugin execution within a run.

    Each plugin execution tracks the status and outcome of running
    a specific plugin during an update-all run.

    Attributes:
        execution_id: Unique identifier for this execution.
        run_id: ID of the parent run.
        plugin_name: Name of the plugin being executed.
        status: Current status of the execution.
        start_time: When the plugin started executing.
        end_time: When the plugin finished executing.
        packages_updated: Number of packages that were updated.
        packages_total: Total number of packages managed by this plugin.
        error_message: Error message if the execution failed.
        exit_code: Exit code of the plugin process.
        created_at: When this record was created in the database.
    """

    execution_id: UUID
    run_id: UUID
    plugin_name: str
    status: ExecutionStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    packages_updated: int = 0
    packages_total: int | None = None
    error_message: str | None = None
    exit_code: int | None = None
    created_at: datetime | None = field(default=None)


@dataclass
class StepMetrics:
    """Metrics collected for a single execution step.

    Each plugin execution consists of multiple steps (check, download, execute),
    and this class captures detailed metrics for each step.

    Attributes:
        metric_id: Unique identifier for this metrics record.
        execution_id: ID of the parent plugin execution.
        step_name: Name of the step (e.g., "prepare", "download", "update").
        phase: Phase of execution (CHECK, DOWNLOAD, EXECUTE).
        start_time: When the step started.
        end_time: When the step completed.
        wall_clock_seconds: Wall-clock time in seconds.
        cpu_user_seconds: CPU time spent in user mode.
        cpu_kernel_seconds: CPU time spent in kernel mode.
        memory_peak_bytes: Peak memory usage in bytes.
        memory_avg_bytes: Average memory usage in bytes.
        io_read_bytes: Bytes read from disk.
        io_write_bytes: Bytes written to disk.
        io_read_ops: Number of read operations.
        io_write_ops: Number of write operations.
        network_rx_bytes: Bytes received over network.
        network_tx_bytes: Bytes transmitted over network.
        download_size_bytes: Size of downloaded data in bytes.
        download_speed_bps: Download speed in bytes per second.
        created_at: When this record was created in the database.
    """

    metric_id: UUID
    execution_id: UUID
    step_name: str
    phase: StepPhase
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Time metrics
    wall_clock_seconds: float | None = None
    cpu_user_seconds: float | None = None
    cpu_kernel_seconds: float | None = None

    # Memory metrics
    memory_peak_bytes: int | None = None
    memory_avg_bytes: int | None = None

    # I/O metrics
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    io_read_ops: int | None = None
    io_write_ops: int | None = None

    # Network metrics
    network_rx_bytes: int | None = None
    network_tx_bytes: int | None = None

    # Download-specific
    download_size_bytes: int | None = None
    download_speed_bps: float | None = None

    created_at: datetime | None = field(default=None)


@dataclass
class Estimate:
    """Plugin-reported estimate for comparison with actuals.

    Plugins can provide estimates of resource usage before execution.
    This class stores those estimates for later comparison with actual
    measurements, enabling model calibration.

    Attributes:
        estimate_id: Unique identifier for this estimate.
        execution_id: ID of the parent plugin execution.
        phase: Phase this estimate applies to.
        download_bytes_est: Estimated download size in bytes.
        cpu_seconds_est: Estimated CPU time in seconds.
        wall_seconds_est: Estimated wall-clock time in seconds.
        memory_bytes_est: Estimated peak memory usage in bytes.
        package_count_est: Estimated number of packages to update.
        confidence: Confidence level of the estimate (0.0 - 1.0).
        created_at: When this record was created in the database.
    """

    estimate_id: UUID
    execution_id: UUID
    phase: StepPhase
    download_bytes_est: int | None = None
    cpu_seconds_est: float | None = None
    wall_seconds_est: float | None = None
    memory_bytes_est: int | None = None
    package_count_est: int | None = None
    confidence: float | None = None  # 0.0 - 1.0
    created_at: datetime | None = field(default=None)
