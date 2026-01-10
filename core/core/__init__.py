"""Update-All Core Library.

Core library providing models, interfaces, and utilities for the update-all system.

This package contains the foundational components used by all other update-all
subprojects (cli, plugins, ui, stats).

Module Overview:
    config: YAML-based configuration management (XDG spec compliant)
    download_manager: Centralized download handling with progress, retry, caching
    interfaces: Abstract base classes for plugins and executors
    metrics: Production observability metrics with alert thresholds
    models: Pydantic data models for configuration and execution results
    mutex: Mutex system for coordinating plugin execution
    notifications: Desktop notification support via notify-send
    orchestrator: Sequential plugin execution
    parallel_orchestrator: Parallel plugin execution with DAG scheduling
    remote: SSH-based remote execution via asyncssh
    resource: Resource limits (CPU, memory, bandwidth)
    rollback: Snapshot and rollback support for failed updates
    schedule: Systemd timer integration for scheduled updates
    scheduler: DAG-based scheduling for plugin dependencies
    streaming: Streaming event types for live plugin output
    sudo: Sudo declaration and sudoers file generation
    version: Version parsing and comparison utilities

Orchestrator Selection:
    - Use Orchestrator for simple sequential execution
    - Use ParallelOrchestrator for parallel execution with mutex/resource management

Metrics Distinction:
    - core.metrics: Production observability (alert thresholds, SLO tracking)
    - ui.metrics: UI display (runtime stats in status bar)
"""

from importlib.metadata import version as get_package_version

from core.config import ConfigManager, YamlConfigLoader, get_config_dir, get_default_config_path
from core.interfaces import ConfigLoader, PluginExecutor, UpdatePlugin
from core.metrics import (
    LatencyTimer,
    MetricLevel,
    MetricsCollector,
    MetricValue,
    PluginMetrics,
    get_metrics_collector,
    set_metrics_collector,
)
from core.models import (
    DownloadEstimate,
    ExecutionResult,
    ExecutionSummary,
    GlobalConfig,
    LogLevel,
    PackageDownload,
    PluginConfig,
    PluginMetadata,
    PluginResult,
    PluginStatus,
    RunResult,
    SystemConfig,
    UpdateCommand,
    UpdateEstimate,
    VersionInfo,
)
from core.mutex import (
    DeadlockError,
    MutexInfo,
    MutexManager,
    MutexState,
    StandardMutexes,
    WaiterInfo,
    build_dependency_graph,
    collect_plugin_dependencies,
    collect_plugin_mutexes,
    validate_dependencies,
)
from core.notifications import (
    NotificationConfig,
    NotificationError,
    NotificationManager,
    NotificationUrgency,
    get_notification_manager,
    load_notification_config,
)
from core.orchestrator import Orchestrator
from core.parallel_orchestrator import ParallelOrchestrator
from core.remote import (
    ConnectionError,
    HostConfig,
    ProgressEvent,
    ProgressEventType,
    RemoteExecutor,
    RemoteUpdateError,
    RemoteUpdateManager,
    RemoteUpdateResult,
    ResilientRemoteExecutor,
)
from core.resource import ResourceContext, ResourceController, ResourceLimits, ResourceUsage
from core.rollback import (
    PluginSnapshot,
    RollbackError,
    RollbackManager,
    RollbackPoint,
    RollbackResult,
    RollbackStatus,
    SnapshotError,
    SnapshotManager,
    SnapshotType,
)
from core.schedule import (
    ScheduleError,
    ScheduleInterval,
    ScheduleManager,
    ScheduleStatus,
    get_schedule_manager,
)
from core.scheduler import ExecutionDAG, PluginNode, Scheduler, SchedulingError
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    StreamEvent,
    StreamEventQueue,
    batched_stream,
    parse_event,
    parse_progress_line,
    safe_consume_stream,
    timeout_stream,
)
from core.streaming import ProgressEvent as StreamProgressEvent
from core.version import (
    Version,
    VersionComponents,
    compare_versions,
    is_git_hash,
    needs_update,
    normalize_version,
    parse_version,
)

__version__ = get_package_version("update-all-core")

__all__ = [
    "CompletionEvent",
    "ConfigLoader",
    "ConfigManager",
    "ConnectionError",
    "DeadlockError",
    "DownloadEstimate",
    "EventType",
    "ExecutionDAG",
    "ExecutionResult",
    "ExecutionSummary",
    "GlobalConfig",
    "HostConfig",
    "LatencyTimer",
    "LogLevel",
    "MetricLevel",
    "MetricValue",
    "MetricsCollector",
    "MutexInfo",
    "MutexManager",
    "MutexState",
    "NotificationConfig",
    "NotificationError",
    "NotificationManager",
    "NotificationUrgency",
    "Orchestrator",
    "OutputEvent",
    "PackageDownload",
    "ParallelOrchestrator",
    "Phase",
    "PhaseEvent",
    "PluginConfig",
    "PluginExecutor",
    "PluginMetadata",
    "PluginMetrics",
    "PluginNode",
    "PluginResult",
    "PluginSnapshot",
    "PluginStatus",
    "ProgressEvent",
    "ProgressEventType",
    "RemoteExecutor",
    "RemoteUpdateError",
    "RemoteUpdateManager",
    "RemoteUpdateResult",
    "ResilientRemoteExecutor",
    "ResourceContext",
    "ResourceController",
    "ResourceLimits",
    "ResourceUsage",
    "RollbackError",
    "RollbackManager",
    "RollbackPoint",
    "RollbackResult",
    "RollbackStatus",
    "RunResult",
    "ScheduleError",
    "ScheduleInterval",
    "ScheduleManager",
    "ScheduleStatus",
    "Scheduler",
    "SchedulingError",
    "SnapshotError",
    "SnapshotManager",
    "SnapshotType",
    "StandardMutexes",
    "StreamEvent",
    "StreamEventQueue",
    "StreamProgressEvent",
    "SystemConfig",
    "UpdateCommand",
    "UpdateEstimate",
    "UpdatePlugin",
    "Version",
    "VersionComponents",
    "VersionInfo",
    "WaiterInfo",
    "YamlConfigLoader",
    "batched_stream",
    "build_dependency_graph",
    "collect_plugin_dependencies",
    "collect_plugin_mutexes",
    "compare_versions",
    "get_config_dir",
    "get_default_config_path",
    "get_metrics_collector",
    "get_notification_manager",
    "get_schedule_manager",
    "is_git_hash",
    "load_notification_config",
    "needs_update",
    "normalize_version",
    "parse_event",
    "parse_progress_line",
    "parse_version",
    "safe_consume_stream",
    "set_metrics_collector",
    "timeout_stream",
    "validate_dependencies",
]
