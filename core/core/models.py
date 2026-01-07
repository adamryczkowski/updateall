"""Core data models for update-all system.

This module defines Pydantic models for configuration, plugin definitions,
and execution results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed at runtime by Pydantic
from enum import Enum
from pathlib import Path  # noqa: TC003 - needed at runtime by Pydantic
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .streaming import Phase


class PluginStatus(str, Enum):
    """Status of a plugin execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


# Alias for backward compatibility with plugins
UpdateStatus = PluginStatus


class LogLevel(str, Enum):
    """Log level for plugin output."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PluginConfig(BaseModel):
    """Configuration for a single plugin."""

    name: str = Field(..., description="Unique plugin identifier")
    enabled: bool = Field(default=True, description="Whether the plugin is enabled")
    timeout_seconds: int = Field(default=300, description="Execution timeout in seconds")
    retry_count: int = Field(default=0, description="Number of retries on failure")
    requires_sudo: bool = Field(default=False, description="Whether plugin requires sudo")
    dependencies: list[str] = Field(
        default_factory=list, description="List of plugin names this plugin depends on"
    )
    options: dict[str, Any] = Field(
        default_factory=dict, description="Plugin-specific configuration options"
    )


class GlobalConfig(BaseModel):
    """Global configuration for update-all system."""

    log_level: LogLevel = Field(default=LogLevel.INFO, description="Global log level")
    log_file: Path | None = Field(default=None, description="Path to log file")
    parallel_execution: bool = Field(default=False, description="Enable parallel plugin execution")
    max_parallel: int = Field(default=4, description="Maximum parallel executions")
    dry_run: bool = Field(default=False, description="Simulate updates without executing")
    stats_enabled: bool = Field(default=True, description="Enable statistics collection")
    stats_file: Path | None = Field(default=None, description="Path to statistics file")

    # Phase 5 - Streaming Feature Flag (Risk I3 mitigation)
    streaming_enabled: bool = Field(
        default=True,
        description="Enable streaming output from plugins. Set to False to fall back to batch mode.",
    )

    # Centralized Download Manager Configuration
    download_cache_dir: Path | None = Field(
        default=None,
        description="Directory for caching downloaded files. None = use system temp.",
    )
    download_max_retries: int = Field(
        default=3,
        description="Maximum number of retry attempts for failed downloads.",
    )
    download_retry_delay: float = Field(
        default=1.0,
        description="Initial delay between retries in seconds (exponential backoff).",
    )
    download_bandwidth_limit: int | None = Field(
        default=None,
        description="Maximum download bandwidth in bytes per second. None = unlimited.",
    )
    download_max_concurrent: int = Field(
        default=2,
        description="Maximum number of concurrent downloads.",
    )
    download_timeout_seconds: int = Field(
        default=3600,
        description="Default timeout for downloads in seconds.",
    )


class SystemConfig(BaseModel):
    """Complete system configuration."""

    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    plugins: dict[str, PluginConfig] = Field(default_factory=dict)


class PluginResult(BaseModel):
    """Result of a plugin update operation.

    Used by plugins to report the outcome of an update.
    """

    plugin_name: str = Field(..., description="Name of the plugin")
    status: PluginStatus = Field(..., description="Update status")
    start_time: datetime = Field(..., description="Update start time")
    end_time: datetime | None = Field(default=None, description="Update end time")
    output: str = Field(default="", description="Command output")
    error_message: str | None = Field(default=None, description="Error message if failed")
    packages_updated: int = Field(default=0, description="Number of packages updated")


class ExecutionResult(BaseModel):
    """Result of a single plugin execution."""

    plugin_name: str = Field(..., description="Name of the executed plugin")
    status: PluginStatus = Field(..., description="Execution status")
    start_time: datetime = Field(..., description="Execution start time")
    end_time: datetime | None = Field(default=None, description="Execution end time")
    duration_seconds: float | None = Field(default=None, description="Execution duration")
    exit_code: int | None = Field(default=None, description="Process exit code")
    stdout: str = Field(default="", description="Standard output")
    stderr: str = Field(default="", description="Standard error")
    error_message: str | None = Field(default=None, description="Error message if failed")
    packages_updated: int = Field(default=0, description="Number of packages updated")
    packages_info: list[dict[str, Any]] = Field(
        default_factory=list, description="Detailed package update information"
    )


class ExecutionSummary(BaseModel):
    """Summary of a complete update run."""

    run_id: str = Field(..., description="Unique run identifier")
    start_time: datetime = Field(..., description="Run start time")
    end_time: datetime | None = Field(default=None, description="Run end time")
    total_duration_seconds: float | None = Field(default=None, description="Total duration")
    results: list[ExecutionResult] = Field(default_factory=list)
    total_plugins: int = Field(default=0, description="Total number of plugins")
    successful_plugins: int = Field(default=0, description="Number of successful plugins")
    failed_plugins: int = Field(default=0, description="Number of failed plugins")
    skipped_plugins: int = Field(default=0, description="Number of skipped plugins")


class PluginMetadata(BaseModel):
    """Metadata about a plugin."""

    name: str = Field(..., description="Plugin name")
    version: str = Field(default="0.1.0", description="Plugin version")
    description: str = Field(default="", description="Plugin description")
    author: str = Field(default="", description="Plugin author")
    requires_sudo: bool = Field(default=False, description="Whether plugin requires sudo")
    supported_platforms: list[str] = Field(
        default_factory=lambda: ["linux"], description="Supported platforms"
    )
    dependencies: list[str] = Field(default_factory=list, description="Plugin dependencies")


class RunResult(BaseModel):
    """Result of a complete update run.

    Used for storing run history and statistics.
    """

    run_id: str = Field(..., description="Unique run identifier")
    start_time: datetime = Field(..., description="Run start time")
    end_time: datetime | None = Field(default=None, description="Run end time")
    plugin_results: list[PluginResult] = Field(
        default_factory=list, description="Results for each plugin"
    )

    @property
    def total_packages_updated(self) -> int:
        """Total packages updated across all plugins."""
        return sum(r.packages_updated for r in self.plugin_results)

    @property
    def success_count(self) -> int:
        """Number of successful plugin runs."""
        return sum(1 for r in self.plugin_results if r.status == PluginStatus.SUCCESS)

    @property
    def failure_count(self) -> int:
        """Number of failed plugin runs."""
        return sum(1 for r in self.plugin_results if r.status == PluginStatus.FAILED)


# =============================================================================
# Download API Models (Phase 2 - Download API)
# =============================================================================


class PackageDownload(BaseModel):
    """Download information for a single package.

    Used to provide detailed information about individual packages
    that need to be downloaded during the download phase.

    Attributes:
        name: Package name/identifier.
        version: Version to download.
        size_bytes: Download size in bytes (None if unknown).
        url: Download URL for logging/debugging (optional).
    """

    name: str = Field(..., description="Package name")
    version: str = Field(default="", description="Version to download")
    size_bytes: int | None = Field(default=None, description="Download size in bytes")
    url: str | None = Field(default=None, description="Download URL (for logging/debugging)")


class DownloadEstimate(BaseModel):
    """Estimate for download phase.

    Provides information about the expected download size, package count,
    and estimated time before the download begins. This allows the UI to
    show progress information and estimated completion time.

    Attributes:
        total_bytes: Total bytes to download (None if unknown).
        package_count: Number of packages to download.
        estimated_seconds: Estimated download time in seconds.
        packages: Detailed information for each package to download.
    """

    total_bytes: int | None = Field(default=None, description="Total bytes to download")
    package_count: int | None = Field(default=None, description="Number of packages to download")
    estimated_seconds: float | None = Field(
        default=None, description="Estimated download time in seconds"
    )
    packages: list[PackageDownload] = Field(
        default_factory=list, description="Details for each package to download"
    )

    @property
    def total_size_mb(self) -> float | None:
        """Total download size in megabytes."""
        if self.total_bytes is None:
            return None
        return self.total_bytes / (1024 * 1024)

    @property
    def has_size_info(self) -> bool:
        """Check if size information is available."""
        return self.total_bytes is not None and self.total_bytes > 0


# =============================================================================
# Centralized Download Manager API (Proposal 2)
# =============================================================================


def _infer_extract_format(url: str) -> str | None:
    """Infer archive format from URL.

    Args:
        url: Download URL.

    Returns:
        Archive format string or None if not an archive.
    """
    url_lower = url.lower()
    if url_lower.endswith(".tar.gz") or url_lower.endswith(".tgz"):
        return "tar.gz"
    if url_lower.endswith(".tar.bz2") or url_lower.endswith(".tbz2"):
        return "tar.bz2"
    if url_lower.endswith(".tar.xz") or url_lower.endswith(".txz"):
        return "tar.xz"
    if url_lower.endswith(".zip"):
        return "zip"
    return None


@dataclass(frozen=True)
class DownloadSpec:
    """Specification for files to download.

    This dataclass describes what a plugin needs to download. The core
    download manager handles the actual download with progress reporting,
    retry logic, and caching.

    Attributes:
        url: URL to download from.
        destination: Local path to save the file (or extract directory).
        expected_size: Expected file size in bytes (for progress reporting).
        checksum: Checksum for verification (format: "algorithm:hash").
        extract: Whether to extract the file after download.
        extract_format: Archive format ("tar.gz", "tar.bz2", "zip", "tar.xz").
        headers: Additional HTTP headers for the request.
        timeout_seconds: Download timeout (None = use default).
        version_url: URL to check latest version (optional).
        version_pattern: Regex to extract version from version_url response.

    Example:
        >>> from pathlib import Path
        >>> spec = DownloadSpec(
        ...     url="https://example.com/file.tar.gz",
        ...     destination=Path("/tmp/download"),
        ...     expected_size=100_000_000,
        ...     checksum="sha256:abc123...",
        ...     extract=True,
        ... )
    """

    url: str
    destination: Path
    expected_size: int | None = None
    checksum: str | None = None  # "sha256:abc123..." or "md5:abc123..."
    extract: bool = False
    extract_format: str | None = None  # "tar.gz", "tar.bz2", "zip", "tar.xz"
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int | None = None

    # For version checking (optional)
    version_url: str | None = None
    version_pattern: str | None = None  # Regex to extract version

    def __post_init__(self) -> None:
        """Validate and normalize the download spec."""
        if not self.url:
            raise ValueError("url must be non-empty")

        # Infer extract format from URL if extract=True but no format specified
        if self.extract and not self.extract_format:
            inferred = _infer_extract_format(self.url)
            if inferred:
                object.__setattr__(self, "extract_format", inferred)

        # Validate checksum format if provided
        if self.checksum:
            if ":" not in self.checksum:
                raise ValueError(
                    "checksum must be in format 'algorithm:hash' (e.g., 'sha256:abc123...')"
                )
            algorithm = self.checksum.split(":")[0].lower()
            if algorithm not in ("sha256", "sha512", "sha1", "md5"):
                raise ValueError(
                    f"Unsupported checksum algorithm: {algorithm}. "
                    "Supported: sha256, sha512, sha1, md5"
                )

    @property
    def checksum_algorithm(self) -> str | None:
        """Get the checksum algorithm."""
        if not self.checksum:
            return None
        return self.checksum.split(":")[0].lower()

    @property
    def checksum_value(self) -> str | None:
        """Get the checksum hash value."""
        if not self.checksum:
            return None
        return self.checksum.split(":", 1)[1]

    @property
    def filename(self) -> str:
        """Get the filename from the URL."""
        from urllib.parse import urlparse

        path = urlparse(self.url).path
        return path.split("/")[-1] if "/" in path else path


@dataclass
class DownloadResult:
    """Result of a download operation.

    Attributes:
        success: Whether the download succeeded.
        path: Path to the downloaded file (or extracted directory).
        bytes_downloaded: Total bytes downloaded.
        duration_seconds: Time taken for download.
        from_cache: Whether the file was served from cache.
        checksum_verified: Whether checksum was verified.
        error_message: Error message if download failed.
        spec: The original download specification.
    """

    success: bool
    path: Path | None = None
    bytes_downloaded: int = 0
    duration_seconds: float = 0.0
    from_cache: bool = False
    checksum_verified: bool = False
    error_message: str | None = None
    spec: DownloadSpec | None = None

    @property
    def download_speed_mbps(self) -> float | None:
        """Calculate download speed in MB/s."""
        if self.duration_seconds <= 0 or self.bytes_downloaded <= 0:
            return None
        return (self.bytes_downloaded / (1024 * 1024)) / self.duration_seconds


# =============================================================================
# Declarative Command Execution API (Proposal 1)
# =============================================================================


def _get_default_phase() -> Phase:
    """Get the default Phase value.

    This is a factory function to avoid circular import issues.
    """
    from .streaming import Phase

    return Phase.EXECUTE


@dataclass(frozen=True)
class UpdateCommand:
    """A single command in an update sequence.

    This dataclass represents a command that can be executed as part of
    a plugin's update process. Plugins can return a list of UpdateCommand
    objects from get_update_commands() to declaratively specify their
    update logic.

    Attributes:
        cmd: Command and arguments as a list of strings.
        description: Human-readable description of what the command does.
        sudo: Whether to prepend sudo to the command.
        timeout_seconds: Custom timeout in seconds (None = use default).
        phase: Execution phase (CHECK, DOWNLOAD, or EXECUTE).
        step_name: Logical name for this step (e.g., "refresh", "upgrade").
        step_number: Step number for progress reporting (1-based).
        total_steps: Total number of steps for progress reporting.
        ignore_exit_codes: Exit codes that should not be treated as errors.
        error_patterns: Patterns in output that indicate error (even with exit 0).
        success_patterns: Patterns in output that indicate success (even with non-zero exit).
        env: Additional environment variables for the command.
        cwd: Working directory for the command.

    Example:
        >>> cmd = UpdateCommand(
        ...     cmd=["apt", "upgrade", "-y"],
        ...     description="Upgrade packages",
        ...     sudo=True,
        ...     step_number=2,
        ...     total_steps=2,
        ...     success_patterns=("0 upgraded",),
        ... )
    """

    cmd: list[str]
    description: str = ""
    sudo: bool = False
    timeout_seconds: int | None = None
    phase: Phase = field(default_factory=_get_default_phase)

    # Multi-step support
    step_name: str | None = None
    step_number: int | None = None
    total_steps: int | None = None

    # Error handling
    ignore_exit_codes: tuple[int, ...] = ()
    error_patterns: tuple[str, ...] = ()
    success_patterns: tuple[str, ...] = ()

    # Environment
    env: dict[str, str] | None = None
    cwd: str | None = None

    def __post_init__(self) -> None:
        """Validate the command after initialization."""
        if not self.cmd:
            raise ValueError("cmd must be a non-empty list")
