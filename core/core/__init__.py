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
from core.orchestrator import Orchestrator
from core.parallel_orchestrator import ParallelOrchestrator
from core.resource import ResourceContext, ResourceController, ResourceLimits, ResourceUsage
from core.scheduler import ExecutionDAG, PluginNode, Scheduler, SchedulingError

__version__ = "0.1.0"

__all__ = [
    "ConfigLoader",
    "ConfigManager",
    "ExecutionDAG",
    "ExecutionResult",
    "ExecutionSummary",
    "GlobalConfig",
    "LogLevel",
    "MutexInfo",
    "MutexManager",
    "Orchestrator",
    "ParallelOrchestrator",
    "PluginConfig",
    "PluginExecutor",
    "PluginMetadata",
    "PluginNode",
    "PluginResult",
    "PluginStatus",
    "ResourceContext",
    "ResourceController",
    "ResourceLimits",
    "ResourceUsage",
    "RunResult",
    "Scheduler",
    "SchedulingError",
    "StandardMutexes",
    "SystemConfig",
    "UpdatePlugin",
    "YamlConfigLoader",
    "get_config_dir",
    "get_default_config_path",
]
