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
from core.orchestrator import Orchestrator

__version__ = "0.1.0"

__all__ = [
    "ConfigLoader",
    "ConfigManager",
    "ExecutionResult",
    "ExecutionSummary",
    "GlobalConfig",
    "LogLevel",
    "Orchestrator",
    "PluginConfig",
    "PluginExecutor",
    "PluginMetadata",
    "PluginResult",
    "PluginStatus",
    "RunResult",
    "SystemConfig",
    "UpdatePlugin",
    "YamlConfigLoader",
    "get_config_dir",
    "get_default_config_path",
]
