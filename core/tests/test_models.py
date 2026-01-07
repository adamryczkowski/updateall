"""Tests for core models."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.models import (
    DownloadEstimate,
    DownloadResult,
    DownloadSpec,
    ExecutionResult,
    GlobalConfig,
    LogLevel,
    PackageDownload,
    PluginConfig,
    PluginMetadata,
    PluginStatus,
    UpdateCommand,
    UpdateEstimate,
    VersionInfo,
)
from core.streaming import Phase


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
        # Phase 5 - Streaming feature flag
        assert config.streaming_enabled is True

    def test_streaming_enabled_can_be_disabled(self) -> None:
        """Test streaming_enabled can be set to False for fallback mode."""
        config = GlobalConfig(streaming_enabled=False)

        assert config.streaming_enabled is False


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


# =============================================================================
# Declarative Command Execution API Tests (Proposal 1)
# =============================================================================


class TestUpdateCommand:
    """Tests for UpdateCommand dataclass."""

    def test_update_command_defaults(self) -> None:
        """UCM-001: Default values are correct."""
        cmd = UpdateCommand(cmd=["echo", "test"])

        assert cmd.cmd == ["echo", "test"]
        assert cmd.description == ""
        assert cmd.sudo is False
        assert cmd.timeout_seconds is None
        assert cmd.phase == Phase.EXECUTE
        assert cmd.step_name is None
        assert cmd.step_number is None
        assert cmd.total_steps is None
        assert cmd.ignore_exit_codes == ()
        assert cmd.error_patterns == ()
        assert cmd.success_patterns == ()
        assert cmd.env is None
        assert cmd.cwd is None

    def test_update_command_required_fields(self) -> None:
        """UCM-002: cmd is required."""
        with pytest.raises(TypeError):
            UpdateCommand()  # type: ignore

    def test_update_command_immutable(self) -> None:
        """UCM-003: Dataclass is frozen."""
        cmd = UpdateCommand(cmd=["echo", "test"])
        with pytest.raises(FrozenInstanceError):
            cmd.description = "new description"  # type: ignore

    def test_update_command_tuple_fields(self) -> None:
        """UCM-004: Tuple fields work correctly."""
        cmd = UpdateCommand(
            cmd=["echo"],
            ignore_exit_codes=(1, 2),
            error_patterns=("ERROR", "FATAL"),
            success_patterns=("OK", "SUCCESS"),
        )

        assert 1 in cmd.ignore_exit_codes
        assert 2 in cmd.ignore_exit_codes
        assert "ERROR" in cmd.error_patterns
        assert "FATAL" in cmd.error_patterns
        assert "OK" in cmd.success_patterns
        assert "SUCCESS" in cmd.success_patterns

    def test_update_command_empty_cmd_raises(self) -> None:
        """UCM-005: Empty cmd list raises ValueError."""
        with pytest.raises(ValueError, match="cmd must be a non-empty list"):
            UpdateCommand(cmd=[])

    def test_update_command_full_values(self) -> None:
        """UCM-006: All values can be set."""
        cmd = UpdateCommand(
            cmd=["apt", "upgrade", "-y"],
            description="Upgrade all packages",
            sudo=True,
            timeout_seconds=3600,
            phase=Phase.EXECUTE,
            step_name="upgrade",
            step_number=2,
            total_steps=2,
            ignore_exit_codes=(100,),
            error_patterns=("FATAL",),
            success_patterns=("0 upgraded",),
            env={"DEBIAN_FRONTEND": "noninteractive"},
            cwd="/tmp",
        )

        assert cmd.cmd == ["apt", "upgrade", "-y"]
        assert cmd.description == "Upgrade all packages"
        assert cmd.sudo is True
        assert cmd.timeout_seconds == 3600
        assert cmd.phase == Phase.EXECUTE
        assert cmd.step_name == "upgrade"
        assert cmd.step_number == 2
        assert cmd.total_steps == 2
        assert cmd.ignore_exit_codes == (100,)
        assert cmd.error_patterns == ("FATAL",)
        assert cmd.success_patterns == ("0 upgraded",)
        assert cmd.env == {"DEBIAN_FRONTEND": "noninteractive"}
        assert cmd.cwd == "/tmp"

    def test_update_command_step_numbers_optional(self) -> None:
        """UCM-007: Step numbers are optional."""
        cmd = UpdateCommand(cmd=["echo"], step_name="test")

        assert cmd.step_name == "test"
        assert cmd.step_number is None
        assert cmd.total_steps is None

    def test_update_command_partial_step_info(self) -> None:
        """UCM-008: Partial step info (only step_name and step_number) works."""
        cmd = UpdateCommand(cmd=["echo"], step_name="test", step_number=1)

        assert cmd.step_name == "test"
        assert cmd.step_number == 1
        assert cmd.total_steps is None

    def test_update_command_different_phases(self) -> None:
        """UCM-009: Different phases can be set."""
        cmd_check = UpdateCommand(cmd=["apt", "update"], phase=Phase.CHECK)
        cmd_download = UpdateCommand(cmd=["apt", "download"], phase=Phase.DOWNLOAD)
        cmd_execute = UpdateCommand(cmd=["apt", "upgrade"], phase=Phase.EXECUTE)

        assert cmd_check.phase == Phase.CHECK
        assert cmd_download.phase == Phase.DOWNLOAD
        assert cmd_execute.phase == Phase.EXECUTE


# =============================================================================
# Centralized Download Manager API Tests (Proposal 2)
# =============================================================================


class TestDownloadSpec:
    """Tests for DownloadSpec dataclass."""

    def test_create_minimal_spec(self) -> None:
        """DS-001: Create spec with only required fields."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp/download"),
        )

        assert spec.url == "https://example.com/file.tar.gz"
        assert spec.destination == Path("/tmp/download")
        assert spec.expected_size is None
        assert spec.checksum is None
        assert spec.extract is False
        assert spec.extract_format is None
        assert spec.headers == {}
        assert spec.timeout_seconds is None

    def test_create_full_spec(self) -> None:
        """DS-002: Create spec with all fields."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp/download"),
            expected_size=100_000_000,
            checksum="sha256:abc123def456",
            extract=True,
            extract_format="tar.gz",
            headers={"User-Agent": "test-agent"},
            timeout_seconds=600,
            version_url="https://example.com/version",
            version_pattern=r"v(\d+\.\d+\.\d+)",
        )

        assert spec.url == "https://example.com/file.tar.gz"
        assert spec.destination == Path("/tmp/download")
        assert spec.expected_size == 100_000_000
        assert spec.checksum == "sha256:abc123def456"
        assert spec.extract is True
        assert spec.extract_format == "tar.gz"
        assert spec.headers == {"User-Agent": "test-agent"}
        assert spec.timeout_seconds == 600
        assert spec.version_url == "https://example.com/version"
        assert spec.version_pattern == r"v(\d+\.\d+\.\d+)"

    def test_url_required(self) -> None:
        """DS-003: Empty URL raises ValueError."""
        with pytest.raises(ValueError, match="url must be non-empty"):
            DownloadSpec(url="", destination=Path("/tmp"))

    def test_infer_extract_format_tar_gz(self) -> None:
        """DS-004: Automatic format inference for .tar.gz."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec.extract_format == "tar.gz"

        # Also test .tgz extension
        spec_tgz = DownloadSpec(
            url="https://example.com/file.tgz",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec_tgz.extract_format == "tar.gz"

    def test_infer_extract_format_tar_bz2(self) -> None:
        """DS-005: Automatic format inference for .tar.bz2."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.bz2",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec.extract_format == "tar.bz2"

        # Also test .tbz2 extension
        spec_tbz2 = DownloadSpec(
            url="https://example.com/file.tbz2",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec_tbz2.extract_format == "tar.bz2"

    def test_infer_extract_format_zip(self) -> None:
        """DS-006: Automatic format inference for .zip."""
        spec = DownloadSpec(
            url="https://example.com/file.zip",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec.extract_format == "zip"

    def test_infer_extract_format_tar_xz(self) -> None:
        """DS-007: Automatic format inference for .tar.xz."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.xz",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec.extract_format == "tar.xz"

        # Also test .txz extension
        spec_txz = DownloadSpec(
            url="https://example.com/file.txz",
            destination=Path("/tmp"),
            extract=True,
        )
        assert spec_txz.extract_format == "tar.xz"

    def test_explicit_format_not_overwritten(self) -> None:
        """DS-008: Explicit format is not overwritten by inference."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
            extract=True,
            extract_format="custom",
        )
        assert spec.extract_format == "custom"

    def test_no_format_inference_when_extract_false(self) -> None:
        """DS-009: No format inference when extract is False."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
            extract=False,
        )
        assert spec.extract_format is None

    def test_checksum_format_sha256(self) -> None:
        """DS-010: sha256 checksum format is valid."""
        spec = DownloadSpec(
            url="https://example.com/file",
            destination=Path("/tmp"),
            checksum="sha256:abc123def456",
        )
        assert spec.checksum_algorithm == "sha256"
        assert spec.checksum_value == "abc123def456"

    def test_checksum_format_md5(self) -> None:
        """DS-011: md5 checksum format is valid."""
        spec = DownloadSpec(
            url="https://example.com/file",
            destination=Path("/tmp"),
            checksum="md5:abc123",
        )
        assert spec.checksum_algorithm == "md5"
        assert spec.checksum_value == "abc123"

    def test_checksum_format_sha512(self) -> None:
        """DS-012: sha512 checksum format is valid."""
        spec = DownloadSpec(
            url="https://example.com/file",
            destination=Path("/tmp"),
            checksum="sha512:abc123def456",
        )
        assert spec.checksum_algorithm == "sha512"
        assert spec.checksum_value == "abc123def456"

    def test_checksum_format_sha1(self) -> None:
        """DS-013: sha1 checksum format is valid."""
        spec = DownloadSpec(
            url="https://example.com/file",
            destination=Path("/tmp"),
            checksum="sha1:abc123",
        )
        assert spec.checksum_algorithm == "sha1"
        assert spec.checksum_value == "abc123"

    def test_checksum_invalid_format_no_colon(self) -> None:
        """DS-014: Checksum without colon raises ValueError."""
        with pytest.raises(ValueError, match="checksum must be in format"):
            DownloadSpec(
                url="https://example.com/file",
                destination=Path("/tmp"),
                checksum="abc123",
            )

    def test_checksum_invalid_algorithm(self) -> None:
        """DS-015: Unsupported checksum algorithm raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported checksum algorithm"):
            DownloadSpec(
                url="https://example.com/file",
                destination=Path("/tmp"),
                checksum="crc32:abc123",
            )

    def test_frozen_dataclass(self) -> None:
        """DS-016: DownloadSpec is immutable."""
        spec = DownloadSpec(
            url="https://example.com/file",
            destination=Path("/tmp"),
        )
        with pytest.raises(FrozenInstanceError):
            spec.url = "https://other.com/file"  # type: ignore

    def test_filename_property(self) -> None:
        """DS-017: filename property extracts filename from URL."""
        spec = DownloadSpec(
            url="https://example.com/path/to/file.tar.gz",
            destination=Path("/tmp"),
        )
        assert spec.filename == "file.tar.gz"

    def test_filename_property_no_path(self) -> None:
        """DS-018: filename property handles URL without path."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
        )
        assert spec.filename == "file.tar.gz"

    def test_checksum_properties_none_when_no_checksum(self) -> None:
        """DS-019: Checksum properties return None when no checksum."""
        spec = DownloadSpec(
            url="https://example.com/file",
            destination=Path("/tmp"),
        )
        assert spec.checksum_algorithm is None
        assert spec.checksum_value is None


class TestDownloadResult:
    """Tests for DownloadResult dataclass."""

    def test_create_success_result(self) -> None:
        """DR-001: Create successful result."""
        result = DownloadResult(
            success=True,
            path=Path("/tmp/downloaded-file"),
            bytes_downloaded=100_000_000,
            duration_seconds=10.5,
            checksum_verified=True,
        )

        assert result.success is True
        assert result.path == Path("/tmp/downloaded-file")
        assert result.bytes_downloaded == 100_000_000
        assert result.duration_seconds == 10.5
        assert result.from_cache is False
        assert result.checksum_verified is True
        assert result.error_message is None

    def test_create_failure_result(self) -> None:
        """DR-002: Create failed result."""
        result = DownloadResult(
            success=False,
            error_message="Connection refused",
        )

        assert result.success is False
        assert result.path is None
        assert result.bytes_downloaded == 0
        assert result.error_message == "Connection refused"

    def test_from_cache_flag(self) -> None:
        """DR-003: from_cache flag works correctly."""
        result = DownloadResult(
            success=True,
            path=Path("/tmp/cached-file"),
            from_cache=True,
        )

        assert result.from_cache is True

    def test_checksum_verified_flag(self) -> None:
        """DR-004: checksum_verified flag works correctly."""
        result = DownloadResult(
            success=True,
            path=Path("/tmp/file"),
            checksum_verified=True,
        )

        assert result.checksum_verified is True

    def test_download_speed_mbps_property(self) -> None:
        """DR-005: download_speed_mbps computed property."""
        # 100 MB in 10 seconds = 10 MB/s
        result = DownloadResult(
            success=True,
            bytes_downloaded=104_857_600,  # 100 MB
            duration_seconds=10.0,
        )

        assert result.download_speed_mbps is not None
        assert abs(result.download_speed_mbps - 10.0) < 0.01

    def test_download_speed_mbps_zero_duration(self) -> None:
        """DR-006: download_speed_mbps returns None for zero duration."""
        result = DownloadResult(
            success=True,
            bytes_downloaded=1000,
            duration_seconds=0.0,
        )

        assert result.download_speed_mbps is None

    def test_download_speed_mbps_zero_bytes(self) -> None:
        """DR-007: download_speed_mbps returns None for zero bytes."""
        result = DownloadResult(
            success=True,
            bytes_downloaded=0,
            duration_seconds=10.0,
        )

        assert result.download_speed_mbps is None

    def test_spec_reference(self) -> None:
        """DR-008: Result can reference original spec."""
        spec = DownloadSpec(
            url="https://example.com/file.tar.gz",
            destination=Path("/tmp"),
        )
        result = DownloadResult(
            success=True,
            path=Path("/tmp/file.tar.gz"),
            spec=spec,
        )

        assert result.spec is spec
        assert result.spec.url == "https://example.com/file.tar.gz"


class TestGlobalConfigDownloadSettings:
    """Tests for GlobalConfig download-related settings."""

    def test_download_config_defaults(self) -> None:
        """GC-D01: Download config has correct defaults."""
        config = GlobalConfig()

        assert config.download_cache_dir is None
        assert config.download_max_retries == 3
        assert config.download_retry_delay == 1.0
        assert config.download_bandwidth_limit is None
        assert config.download_max_concurrent == 2
        assert config.download_timeout_seconds == 3600

    def test_download_config_custom_values(self) -> None:
        """GC-D02: Download config accepts custom values."""
        config = GlobalConfig(
            download_cache_dir=Path("/var/cache/update-all"),
            download_max_retries=5,
            download_retry_delay=2.0,
            download_bandwidth_limit=1_000_000,  # 1 MB/s
            download_max_concurrent=4,
            download_timeout_seconds=7200,
        )

        assert config.download_cache_dir == Path("/var/cache/update-all")
        assert config.download_max_retries == 5
        assert config.download_retry_delay == 2.0
        assert config.download_bandwidth_limit == 1_000_000
        assert config.download_max_concurrent == 4
        assert config.download_timeout_seconds == 7200


# =============================================================================
# Version Checking Protocol Tests (Proposal 3)
# =============================================================================


class TestUpdateEstimate:
    """Tests for UpdateEstimate dataclass."""

    def test_update_estimate_creation(self) -> None:
        """UE-001: Create UpdateEstimate with all fields."""
        estimate = UpdateEstimate(
            download_bytes=157286400,
            package_count=15,
            packages=["pkg1", "pkg2"],
            estimated_seconds=120.5,
            confidence=0.85,
        )

        assert estimate.download_bytes == 157286400
        assert estimate.package_count == 15
        assert estimate.packages == ["pkg1", "pkg2"]
        assert estimate.estimated_seconds == 120.5
        assert estimate.confidence == 0.85

    def test_update_estimate_defaults(self) -> None:
        """UE-002: UpdateEstimate default values."""
        estimate = UpdateEstimate()

        assert estimate.download_bytes is None
        assert estimate.package_count is None
        assert estimate.packages is None
        assert estimate.estimated_seconds is None
        assert estimate.confidence is None

    def test_has_download_info_true(self) -> None:
        """UE-003: has_download_info when download_bytes is set."""
        estimate = UpdateEstimate(download_bytes=1024)
        assert estimate.has_download_info is True

    def test_has_download_info_false(self) -> None:
        """UE-004: has_download_info when download_bytes is None."""
        estimate = UpdateEstimate()
        assert estimate.has_download_info is False

    def test_format_download_size_bytes(self) -> None:
        """UE-005: Format small sizes in bytes."""
        estimate = UpdateEstimate(download_bytes=512)
        assert estimate.format_download_size() == "512 B"

    def test_format_download_size_kilobytes(self) -> None:
        """UE-006: Format sizes in kilobytes."""
        estimate = UpdateEstimate(download_bytes=2048)
        assert estimate.format_download_size() == "2.0 KB"

    def test_format_download_size_megabytes(self) -> None:
        """UE-007: Format sizes in megabytes."""
        estimate = UpdateEstimate(download_bytes=157286400)
        assert estimate.format_download_size() == "150.0 MB"

    def test_format_download_size_gigabytes(self) -> None:
        """UE-008: Format sizes in gigabytes."""
        estimate = UpdateEstimate(download_bytes=2147483648)
        assert estimate.format_download_size() == "2.00 GB"

    def test_format_download_size_unknown(self) -> None:
        """UE-009: Format when download_bytes is None."""
        estimate = UpdateEstimate()
        assert estimate.format_download_size() == "Unknown"

    def test_update_estimate_frozen(self) -> None:
        """UE-010: UpdateEstimate is immutable."""
        estimate = UpdateEstimate(download_bytes=1024)
        with pytest.raises(FrozenInstanceError):
            estimate.download_bytes = 2048  # type: ignore


class TestVersionInfo:
    """Tests for VersionInfo dataclass."""

    def test_version_info_creation(self) -> None:
        """VI-001: Create VersionInfo with all fields."""
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
        )

        assert info.installed == "1.2.3"
        assert info.available == "1.3.0"
        assert info.needs_update is True

    def test_version_info_defaults(self) -> None:
        """VI-002: VersionInfo default values."""
        info = VersionInfo()

        assert info.installed is None
        assert info.available is None
        assert info.needs_update is None
        assert info.check_time is None
        assert info.error_message is None
        assert info.estimate is None

    def test_is_up_to_date_true(self) -> None:
        """VI-003: is_up_to_date when no update needed."""
        info = VersionInfo(needs_update=False)
        assert info.is_up_to_date is True

    def test_is_up_to_date_false(self) -> None:
        """VI-004: is_up_to_date when update needed."""
        info = VersionInfo(needs_update=True)
        assert info.is_up_to_date is False

    def test_is_up_to_date_none(self) -> None:
        """VI-005: is_up_to_date when cannot determine."""
        info = VersionInfo(needs_update=None)
        assert info.is_up_to_date is None

    def test_version_change_string(self) -> None:
        """VI-006: version_change property."""
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
        )
        assert info.version_change == "1.2.3 -> 1.3.0"

    def test_version_change_none_when_up_to_date(self) -> None:
        """VI-007: version_change is None when up-to-date."""
        info = VersionInfo(
            installed="1.3.0",
            available="1.3.0",
            needs_update=False,
        )
        assert info.version_change is None

    def test_version_change_none_when_missing_versions(self) -> None:
        """VI-008: version_change is None when versions missing."""
        info = VersionInfo(needs_update=True)
        assert info.version_change is None

    def test_version_info_with_estimate(self) -> None:
        """VI-009: VersionInfo with UpdateEstimate."""
        estimate = UpdateEstimate(download_bytes=157286400, package_count=15)
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
            estimate=estimate,
        )

        assert info.estimate is not None
        assert info.download_size == "150.0 MB"

    def test_download_size_none_without_estimate(self) -> None:
        """VI-010: download_size is None when no estimate."""
        info = VersionInfo(needs_update=True)
        assert info.download_size is None

    def test_version_info_with_check_time(self) -> None:
        """VI-011: VersionInfo with check_time."""
        check_time = datetime.now(tz=UTC)
        info = VersionInfo(
            installed="1.2.3",
            available="1.3.0",
            needs_update=True,
            check_time=check_time,
        )

        assert info.check_time == check_time

    def test_version_info_with_error(self) -> None:
        """VI-012: VersionInfo with error message."""
        info = VersionInfo(
            error_message="Network error",
            check_time=datetime.now(tz=UTC),
        )

        assert info.error_message == "Network error"
        assert info.installed is None
        assert info.available is None
        assert info.needs_update is None

    def test_version_info_frozen(self) -> None:
        """VI-013: VersionInfo is immutable."""
        info = VersionInfo(installed="1.2.3")
        with pytest.raises(FrozenInstanceError):
            info.installed = "1.3.0"  # type: ignore
