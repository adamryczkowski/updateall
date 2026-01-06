"""Configuration management for update-all.

This module provides YAML-based configuration loading and saving,
following the XDG Base Directory Specification.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog
import yaml

from .interfaces import ConfigLoader
from .models import GlobalConfig, PluginConfig, SystemConfig

logger = structlog.get_logger(__name__)


def get_config_dir() -> Path:
    """Get the configuration directory following XDG spec.

    Returns:
        Path to the configuration directory.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"

    config_dir = base / "update-all"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_default_config_path() -> Path:
    """Get the default configuration file path.

    Returns:
        Path to the default config file.
    """
    return get_config_dir() / "config.yaml"


class YamlConfigLoader(ConfigLoader):
    """YAML-based configuration loader.

    Loads and saves configuration from/to YAML files.
    """

    def load(self, path: str) -> dict[str, Any]:
        """Load configuration from a YAML file.

        Args:
            path: Path to the configuration file.

        Returns:
            Configuration dictionary.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            yaml.YAMLError: If the file is not valid YAML.
        """
        config_path = Path(path)

        if not config_path.exists():
            logger.debug("config_file_not_found", path=path)
            raise FileNotFoundError(f"Configuration file not found: {path}")

        content = config_path.read_text()
        data = yaml.safe_load(content)

        if data is None:
            return {}

        return data  # type: ignore[no-any-return]

    def save(self, config: dict[str, Any], path: str) -> None:
        """Save configuration to a YAML file.

        Args:
            config: Configuration dictionary.
            path: Path to save the configuration.
        """
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        content = yaml.dump(config, default_flow_style=False, sort_keys=False)
        config_path.write_text(content)

        logger.info("config_saved", path=path)


class ConfigManager:
    """Manages application configuration.

    Provides high-level methods for loading, saving, and accessing
    configuration values.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the configuration manager.

        Args:
            config_path: Optional path to configuration file.
                        Uses default path if not provided.
        """
        self.config_path = config_path or get_default_config_path()
        self._loader = YamlConfigLoader()
        self._config: SystemConfig | None = None

    def load(self) -> SystemConfig:
        """Load configuration from file.

        Returns:
            SystemConfig with loaded values, or defaults if file doesn't exist.
        """
        try:
            data = self._loader.load(str(self.config_path))
            self._config = self._parse_config(data)
        except FileNotFoundError:
            logger.info("using_default_config")
            self._config = SystemConfig()

        return self._config

    def save(self, config: SystemConfig | None = None) -> None:
        """Save configuration to file.

        Args:
            config: Configuration to save. Uses current config if not provided.
        """
        if config is not None:
            self._config = config

        if self._config is None:
            self._config = SystemConfig()

        data = self._serialize_config(self._config)
        self._loader.save(data, str(self.config_path))

    def get_config(self) -> SystemConfig:
        """Get the current configuration.

        Returns:
            Current SystemConfig, loading from file if needed.
        """
        if self._config is None:
            self.load()
        return self._config or SystemConfig()

    def get_plugin_config(self, plugin_name: str) -> PluginConfig:
        """Get configuration for a specific plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            PluginConfig for the plugin (default if not configured).
        """
        config = self.get_config()
        if plugin_name in config.plugins:
            return config.plugins[plugin_name]
        return PluginConfig(name=plugin_name)

    def get_global_config(self) -> GlobalConfig:
        """Get global configuration.

        Returns:
            GlobalConfig with global settings.
        """
        return self.get_config().global_config

    def init_config(self, force: bool = False) -> bool:
        """Initialize a new configuration file with defaults.

        Args:
            force: If True, overwrite existing configuration.

        Returns:
            True if configuration was created, False if it already exists.
        """
        if self.config_path.exists() and not force:
            logger.info("config_exists", path=str(self.config_path))
            return False

        default_config = self._create_default_config()
        self.save(default_config)
        logger.info("config_initialized", path=str(self.config_path))
        return True

    def _parse_config(self, data: dict[str, Any]) -> SystemConfig:
        """Parse configuration dictionary into SystemConfig.

        Args:
            data: Raw configuration dictionary.

        Returns:
            Parsed SystemConfig.
        """
        global_data = data.get("global", {})
        plugins_data = data.get("plugins", {})

        global_config = GlobalConfig(**global_data) if global_data else GlobalConfig()

        plugins: dict[str, PluginConfig] = {}
        for name, plugin_data in plugins_data.items():
            if isinstance(plugin_data, dict):
                plugins[name] = PluginConfig(name=name, **plugin_data)
            else:
                # Handle simple enabled/disabled format
                plugins[name] = PluginConfig(name=name, enabled=bool(plugin_data))

        return SystemConfig(global_config=global_config, plugins=plugins)

    def _serialize_config(self, config: SystemConfig) -> dict[str, Any]:
        """Serialize SystemConfig to dictionary.

        Args:
            config: SystemConfig to serialize.

        Returns:
            Dictionary representation.
        """
        return {
            "global": config.global_config.model_dump(exclude_defaults=True),
            "plugins": {
                name: plugin.model_dump(exclude={"name"}, exclude_defaults=True)
                for name, plugin in config.plugins.items()
            },
        }

    def _create_default_config(self) -> SystemConfig:
        """Create default configuration with common plugins.

        Returns:
            Default SystemConfig.
        """
        return SystemConfig(
            global_config=GlobalConfig(),
            plugins={
                "apt": PluginConfig(
                    name="apt",
                    enabled=True,
                    timeout_seconds=600,
                    requires_sudo=True,
                ),
                "pipx": PluginConfig(
                    name="pipx",
                    enabled=True,
                    timeout_seconds=300,
                ),
                "flatpak": PluginConfig(
                    name="flatpak",
                    enabled=True,
                    timeout_seconds=600,
                ),
            },
        )
