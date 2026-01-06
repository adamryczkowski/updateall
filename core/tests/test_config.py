"""Tests for the configuration module."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import ConfigManager, YamlConfigLoader, get_config_dir
from core.models import GlobalConfig, LogLevel, PluginConfig, SystemConfig


class TestYamlConfigLoader:
    """Tests for YamlConfigLoader class."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """Test loading a valid YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
global:
  log_level: debug
  dry_run: true
plugins:
  apt:
    enabled: true
    timeout_seconds: 600
""")

        loader = YamlConfigLoader()
        data = loader.load(str(config_file))

        assert data["global"]["log_level"] == "debug"
        assert data["global"]["dry_run"] is True
        assert data["plugins"]["apt"]["enabled"] is True
        assert data["plugins"]["apt"]["timeout_seconds"] == 600

    def test_load_empty_yaml(self, tmp_path: Path) -> None:
        """Test loading an empty YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        loader = YamlConfigLoader()
        data = loader.load(str(config_file))

        assert data == {}

    def test_load_nonexistent_file(self) -> None:
        """Test loading a non-existent file raises FileNotFoundError."""
        loader = YamlConfigLoader()

        with pytest.raises(FileNotFoundError):
            loader.load("/nonexistent/path/config.yaml")

    def test_save_yaml(self, tmp_path: Path) -> None:
        """Test saving a YAML file."""
        config_file = tmp_path / "config.yaml"
        loader = YamlConfigLoader()

        data = {
            "global": {"log_level": "info"},
            "plugins": {"apt": {"enabled": True}},
        }

        loader.save(data, str(config_file))

        assert config_file.exists()
        content = config_file.read_text()
        assert "log_level: info" in content
        assert "apt:" in content

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that save creates parent directories if needed."""
        config_file = tmp_path / "subdir" / "another" / "config.yaml"
        loader = YamlConfigLoader()

        loader.save({"test": "value"}, str(config_file))

        assert config_file.exists()


class TestConfigManager:
    """Tests for ConfigManager class."""

    def test_load_default_config(self, tmp_path: Path) -> None:
        """Test loading default config when file doesn't exist."""
        config_file = tmp_path / "config.yaml"
        manager = ConfigManager(config_path=config_file)

        config = manager.load()

        assert isinstance(config, SystemConfig)
        assert config.global_config.log_level == LogLevel.INFO

    def test_load_existing_config(self, tmp_path: Path) -> None:
        """Test loading an existing config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
global:
  log_level: debug
  dry_run: true
plugins:
  apt:
    enabled: false
    timeout_seconds: 1200
""")

        manager = ConfigManager(config_path=config_file)
        config = manager.load()

        assert config.global_config.log_level == LogLevel.DEBUG
        assert config.global_config.dry_run is True
        assert "apt" in config.plugins
        assert config.plugins["apt"].enabled is False
        assert config.plugins["apt"].timeout_seconds == 1200

    def test_save_config(self, tmp_path: Path) -> None:
        """Test saving configuration."""
        config_file = tmp_path / "config.yaml"
        manager = ConfigManager(config_path=config_file)

        config = SystemConfig(
            global_config=GlobalConfig(log_level=LogLevel.WARNING),
            plugins={"test": PluginConfig(name="test", enabled=True)},
        )

        manager.save(config)

        assert config_file.exists()
        content = config_file.read_text()
        assert "warning" in content.lower() or "WARNING" in content

    def test_get_config_loads_if_needed(self, tmp_path: Path) -> None:
        """Test that get_config loads config if not already loaded."""
        config_file = tmp_path / "config.yaml"
        manager = ConfigManager(config_path=config_file)

        config = manager.get_config()

        assert isinstance(config, SystemConfig)

    def test_get_plugin_config_existing(self, tmp_path: Path) -> None:
        """Test getting config for an existing plugin."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
plugins:
  apt:
    enabled: true
    timeout_seconds: 900
""")

        manager = ConfigManager(config_path=config_file)
        plugin_config = manager.get_plugin_config("apt")

        assert plugin_config.name == "apt"
        assert plugin_config.enabled is True
        assert plugin_config.timeout_seconds == 900

    def test_get_plugin_config_default(self, tmp_path: Path) -> None:
        """Test getting default config for a non-configured plugin."""
        config_file = tmp_path / "config.yaml"
        manager = ConfigManager(config_path=config_file)

        plugin_config = manager.get_plugin_config("unknown")

        assert plugin_config.name == "unknown"
        assert plugin_config.enabled is True  # Default
        assert plugin_config.timeout_seconds == 300  # Default

    def test_init_config_creates_file(self, tmp_path: Path) -> None:
        """Test that init_config creates a new config file."""
        config_file = tmp_path / "config.yaml"
        manager = ConfigManager(config_path=config_file)

        result = manager.init_config()

        assert result is True
        assert config_file.exists()

    def test_init_config_does_not_overwrite(self, tmp_path: Path) -> None:
        """Test that init_config doesn't overwrite existing file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("existing: content")
        manager = ConfigManager(config_path=config_file)

        result = manager.init_config(force=False)

        assert result is False
        assert "existing: content" in config_file.read_text()

    def test_init_config_force_overwrites(self, tmp_path: Path) -> None:
        """Test that init_config with force=True overwrites existing file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("existing: content")
        manager = ConfigManager(config_path=config_file)

        result = manager.init_config(force=True)

        assert result is True
        assert "existing: content" not in config_file.read_text()

    def test_default_config_includes_builtin_plugins(self, tmp_path: Path) -> None:
        """Test that default config includes apt, pipx, flatpak."""
        config_file = tmp_path / "config.yaml"
        manager = ConfigManager(config_path=config_file)

        manager.init_config()
        config = manager.load()

        assert "apt" in config.plugins
        assert "pipx" in config.plugins
        assert "flatpak" in config.plugins


class TestGetConfigDir:
    """Tests for get_config_dir function."""

    def test_returns_path(self) -> None:
        """Test that get_config_dir returns a Path."""
        config_dir = get_config_dir()
        assert isinstance(config_dir, Path)

    def test_path_ends_with_update_all(self) -> None:
        """Test that the path ends with 'update-all'."""
        config_dir = get_config_dir()
        assert config_dir.name == "update-all"
