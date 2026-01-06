"""Tests for core models."""

from datetime import datetime

from core.models import (
    DownloadEstimate,
    ExecutionResult,
    GlobalConfig,
    LogLevel,
    PackageDownload,
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


# =============================================================================
# Download API Models Tests (Phase 2)
# =============================================================================


class TestPackageDownload:
    """Tests for PackageDownload model."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        pkg = PackageDownload(name="python3.12")

        assert pkg.name == "python3.12"
        assert pkg.version == ""
        assert pkg.size_bytes is None
        assert pkg.url is None

    def test_full_values(self) -> None:
        """Test all values can be set."""
        pkg = PackageDownload(
            name="python3.12",
            version="3.12.2",
            size_bytes=15_000_000,
            url="https://archive.ubuntu.com/pool/main/p/python3.12/python3.12_3.12.2.deb",
        )

        assert pkg.name == "python3.12"
        assert pkg.version == "3.12.2"
        assert pkg.size_bytes == 15_000_000
        assert pkg.url == "https://archive.ubuntu.com/pool/main/p/python3.12/python3.12_3.12.2.deb"


class TestDownloadEstimate:
    """Tests for DownloadEstimate model."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        estimate = DownloadEstimate()

        assert estimate.total_bytes is None
        assert estimate.package_count is None
        assert estimate.estimated_seconds is None
        assert estimate.packages == []

    def test_full_values(self) -> None:
        """Test all values can be set."""
        packages = [
            PackageDownload(name="pkg1", version="1.0", size_bytes=10_000_000),
            PackageDownload(name="pkg2", version="2.0", size_bytes=20_000_000),
            PackageDownload(name="pkg3", version="3.0", size_bytes=30_000_000),
        ]

        estimate = DownloadEstimate(
            total_bytes=60_000_000,
            package_count=3,
            estimated_seconds=30.5,
            packages=packages,
        )

        assert estimate.total_bytes == 60_000_000
        assert estimate.package_count == 3
        assert estimate.estimated_seconds == 30.5
        assert len(estimate.packages) == 3
        assert estimate.packages[0].name == "pkg1"

    def test_total_size_mb_property(self) -> None:
        """Test total_size_mb computed property."""
        # With bytes set
        estimate = DownloadEstimate(total_bytes=104_857_600)  # 100 MB
        assert estimate.total_size_mb == 100.0

        # With None
        estimate_none = DownloadEstimate()
        assert estimate_none.total_size_mb is None

    def test_has_size_info_property(self) -> None:
        """Test has_size_info computed property."""
        # With bytes set
        estimate = DownloadEstimate(total_bytes=1000)
        assert estimate.has_size_info is True

        # With zero bytes
        estimate_zero = DownloadEstimate(total_bytes=0)
        assert estimate_zero.has_size_info is False

        # With None
        estimate_none = DownloadEstimate()
        assert estimate_none.has_size_info is False
