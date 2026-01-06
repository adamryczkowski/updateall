"""Tests for core models."""

from datetime import datetime

from core.models import (
    ExecutionResult,
    GlobalConfig,
    LogLevel,
    PluginConfig,
    PluginMetadata,
    PluginStatus,
)


class TestPluginConfig:
    """Tests for PluginConfig model."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        config = PluginConfig(name="test-plugin")

        assert config.name == "test-plugin"
        assert config.enabled is True
        assert config.timeout_seconds == 300
        assert config.retry_count == 0
        assert config.requires_sudo is False
        assert config.dependencies == []
        assert config.options == {}

    def test_custom_values(self) -> None:
        """Test custom values are set correctly."""
        config = PluginConfig(
            name="apt",
            enabled=True,
            timeout_seconds=600,
            retry_count=2,
            requires_sudo=True,
            dependencies=["network-check"],
            options={"upgrade_type": "full"},
        )

        assert config.name == "apt"
        assert config.timeout_seconds == 600
        assert config.retry_count == 2
        assert config.requires_sudo is True
        assert config.dependencies == ["network-check"]
        assert config.options == {"upgrade_type": "full"}


class TestGlobalConfig:
    """Tests for GlobalConfig model."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        config = GlobalConfig()

        assert config.log_level == LogLevel.INFO
        assert config.log_file is None
        assert config.parallel_execution is False
        assert config.max_parallel == 4
        assert config.dry_run is False
        assert config.stats_enabled is True
        assert config.stats_file is None


class TestExecutionResult:
    """Tests for ExecutionResult model."""

    def test_successful_result(self) -> None:
        """Test creating a successful execution result."""
        start = datetime.now()
        end = datetime.now()

        result = ExecutionResult(
            plugin_name="apt",
            status=PluginStatus.SUCCESS,
            start_time=start,
            end_time=end,
            duration_seconds=10.5,
            exit_code=0,
            packages_updated=5,
        )

        assert result.plugin_name == "apt"
        assert result.status == PluginStatus.SUCCESS
        assert result.exit_code == 0
        assert result.packages_updated == 5

    def test_failed_result(self) -> None:
        """Test creating a failed execution result."""
        result = ExecutionResult(
            plugin_name="apt",
            status=PluginStatus.FAILED,
            start_time=datetime.now(),
            exit_code=1,
            error_message="Package manager locked",
        )

        assert result.status == PluginStatus.FAILED
        assert result.exit_code == 1
        assert result.error_message == "Package manager locked"


class TestPluginMetadata:
    """Tests for PluginMetadata model."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        metadata = PluginMetadata(name="test-plugin")

        assert metadata.name == "test-plugin"
        assert metadata.version == "0.1.0"
        assert metadata.description == ""
        assert metadata.requires_sudo is False
        assert metadata.supported_platforms == ["linux"]
        assert metadata.dependencies == []


class TestPluginStatus:
    """Tests for PluginStatus enum."""

    def test_status_values(self) -> None:
        """Test all status values exist."""
        assert PluginStatus.PENDING == "pending"
        assert PluginStatus.RUNNING == "running"
        assert PluginStatus.SUCCESS == "success"
        assert PluginStatus.FAILED == "failed"
        assert PluginStatus.SKIPPED == "skipped"
        assert PluginStatus.TIMEOUT == "timeout"
