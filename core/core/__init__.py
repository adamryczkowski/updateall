"""Update-All Core Library.

Core library providing models, interfaces, and utilities for the update-all system.
"""

from core.config import ConfigManager, YamlConfigLoader, get_config_dir, get_default_config_path
from core.interfaces import ConfigLoader, PluginExecutor, UpdatePlugin
from core.models import (
    ExecutionResult,
    ExecutionSummary,
    GlobalConfig,
    LogLevel,
    PluginConfig,
    PluginMetadata,
    PluginResult,
    PluginStatus,
    RunResult,
    SystemConfig,
)
from core.mutex import MutexInfo, MutexManager, StandardMutexes
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
from core.schedule import (
    ScheduleError,
    ScheduleInterval,
    ScheduleManager,
    ScheduleStatus,
    get_schedule_manager,
)
from core.scheduler import ExecutionDAG, PluginNode, Scheduler, SchedulingError

__version__ = "0.1.0"

__all__ = [
    "ConfigLoader",
    "ConfigManager",
    "ConnectionError",
    "ExecutionDAG",
    "ExecutionResult",
    "ExecutionSummary",
    "GlobalConfig",
    "HostConfig",
    "LogLevel",
    "MutexInfo",
    "MutexManager",
    "NotificationConfig",
    "NotificationError",
    "NotificationManager",
    "NotificationUrgency",
    "Orchestrator",
    "ParallelOrchestrator",
    "PluginConfig",
    "PluginExecutor",
    "PluginMetadata",
    "PluginNode",
    "PluginResult",
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
    "RunResult",
    "ScheduleError",
    "ScheduleInterval",
    "ScheduleManager",
    "ScheduleStatus",
    "Scheduler",
    "SchedulingError",
    "StandardMutexes",
    "SystemConfig",
    "UpdatePlugin",
    "YamlConfigLoader",
    "get_config_dir",
    "get_default_config_path",
    "get_notification_manager",
    "get_schedule_manager",
    "load_notification_config",
]
