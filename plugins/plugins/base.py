"""Base plugin implementation with common functionality."""

from __future__ import annotations

import asyncio
import shutil
from abc import abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import structlog

from core.interfaces import UpdatePlugin
from core.models import ExecutionResult, PluginConfig, PluginResult, PluginStatus, UpdateStatus

logger = structlog.get_logger(__name__)


class SelfUpdateStatus(str, Enum):
    """Status of a self-update operation."""

    SUCCESS = "success"
    NOT_SUPPORTED = "not_supported"
    ALREADY_LATEST = "already_latest"
    FAILED = "failed"


@dataclass
class SelfUpdateResult:
    """Result of a plugin self-update operation."""

    status: SelfUpdateStatus
    old_version: str | None = None
    new_version: str | None = None
    message: str = ""


class BasePlugin(UpdatePlugin):
    """Base class for all update plugins with common functionality.

    Provides:
    - Command execution with timeout handling
    - Structured logging
    - Common availability checking
    - Self-update mechanism (Phase 3)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the plugin name."""
        ...

    @property
    @abstractmethod
    def command(self) -> str:
        """Return the main command this plugin uses (e.g., 'apt', 'pipx')."""
        ...

    @property
    def description(self) -> str:
        """Return a human-readable description of the plugin."""
        return f"Update plugin for {self.name}"

    async def check_available(self) -> bool:
        """Check if the plugin's command is available on the system."""
        return shutil.which(self.command) is not None

    async def execute(self, dry_run: bool = False) -> ExecutionResult:
        """Execute the update process.

        This method implements the UpdatePlugin interface and is called by the orchestrator.

        Args:
            dry_run: If True, simulate the update without making changes.

        Returns:
            ExecutionResult with status and details.
        """
        # Create a default config for execution
        config = PluginConfig(name=self.name)

        # Run the update using the internal method
        result = await self.run_update(config, dry_run=dry_run)

        # Convert PluginResult to ExecutionResult
        duration = None
        if result.end_time and result.start_time:
            duration = (result.end_time - result.start_time).total_seconds()

        return ExecutionResult(
            plugin_name=result.plugin_name,
            status=PluginStatus(result.status.value),
            start_time=result.start_time,
            end_time=result.end_time,
            duration_seconds=duration,
            stdout=result.output,
            stderr="",
            error_message=result.error_message,
            packages_updated=result.packages_updated,
        )

    async def run_update(self, config: PluginConfig, *, dry_run: bool = False) -> PluginResult:
        """Run the update process.

        Args:
            config: Plugin configuration including timeout and options.
            dry_run: If True, simulate the update without making changes.

        Returns:
            PluginResult with status, output, and timing information.
        """
        start_time = datetime.now(tz=UTC)
        log = logger.bind(plugin=self.name)

        log.info("starting_update", timeout=config.timeout_seconds, dry_run=dry_run)

        try:
            # Check availability first
            if not await self.check_available():
                return PluginResult(
                    plugin_name=self.name,
                    status=UpdateStatus.SKIPPED,
                    start_time=start_time,
                    end_time=datetime.now(tz=UTC),
                    output="",
                    error_message=f"Command '{self.command}' not found",
                    packages_updated=0,
                )

            # In dry-run mode, just report what would be done
            if dry_run:
                return PluginResult(
                    plugin_name=self.name,
                    status=UpdateStatus.SUCCESS,
                    start_time=start_time,
                    end_time=datetime.now(tz=UTC),
                    output="Dry run - no changes made",
                    error_message=None,
                    packages_updated=0,
                )

            # Run the actual update
            output, error = await self._execute_update(config)

            end_time = datetime.now(tz=UTC)

            if error:
                log.error("update_failed", error=error)
                return PluginResult(
                    plugin_name=self.name,
                    status=UpdateStatus.FAILED,
                    start_time=start_time,
                    end_time=end_time,
                    output=output,
                    error_message=error,
                    packages_updated=0,
                )

            packages_updated = self._count_updated_packages(output)
            log.info("update_completed", packages_updated=packages_updated)

            return PluginResult(
                plugin_name=self.name,
                status=UpdateStatus.SUCCESS,
                start_time=start_time,
                end_time=end_time,
                output=output,
                error_message=None,
                packages_updated=packages_updated,
            )

        except TimeoutError:
            log.warning("update_timeout", timeout=config.timeout_seconds)
            return PluginResult(
                plugin_name=self.name,
                status=UpdateStatus.TIMEOUT,
                start_time=start_time,
                end_time=datetime.now(tz=UTC),
                output="",
                error_message=f"Update timed out after {config.timeout_seconds} seconds",
                packages_updated=0,
            )
        except Exception as e:
            log.exception("update_error", error=str(e))
            return PluginResult(
                plugin_name=self.name,
                status=UpdateStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(tz=UTC),
                output="",
                error_message=str(e),
                packages_updated=0,
            )

    @abstractmethod
    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the actual update commands.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        ...

    def _count_updated_packages(self, output: str) -> int:  # noqa: ARG002
        """Count the number of updated packages from command output.

        Override in subclasses for plugin-specific parsing.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated.
        """
        return 0

    async def _run_command(
        self,
        cmd: list[str],
        timeout: int,
        *,
        check: bool = True,  # noqa: ARG002
        sudo: bool = False,
    ) -> tuple[int, str, str]:
        """Run a shell command with timeout.

        Args:
            cmd: Command and arguments as a list.
            timeout: Timeout in seconds.
            check: Whether to raise on non-zero exit code (reserved for future use).
            sudo: Whether to prepend sudo to the command.

        Returns:
            Tuple of (return_code, stdout, stderr).

        Raises:
            TimeoutError: If command exceeds timeout.
        """
        if sudo:
            cmd = ["sudo", *cmd]

        log = logger.bind(plugin=self.name, command=" ".join(cmd))
        log.debug("running_command")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            return_code = process.returncode or 0
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            log.debug(
                "command_completed",
                return_code=return_code,
                stdout_len=len(stdout_str),
                stderr_len=len(stderr_str),
            )

            return return_code, stdout_str, stderr_str

        except TimeoutError as e:
            log.warning("command_timeout", timeout=timeout)
            # Try to kill the process
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise TimeoutError(f"Command timed out after {timeout}s") from e

    # =========================================================================
    # Self-Update Mechanism (Phase 3)
    # =========================================================================

    @property
    def supports_self_update(self) -> bool:
        """Check if this plugin supports self-update.

        Override in subclasses that support self-update.

        Returns:
            True if self-update is supported, False otherwise.
        """
        return False

    @property
    def current_version(self) -> str | None:
        """Get the current version of the plugin.

        Override in subclasses to return the actual version.

        Returns:
            Version string or None if unknown.
        """
        return None

    async def check_self_update_available(self) -> tuple[bool, str | None]:
        """Check if a self-update is available.

        Override in subclasses that support self-update.

        Returns:
            Tuple of (update_available, new_version).
        """
        return False, None

    async def self_update(self, *, force: bool = False) -> SelfUpdateResult:
        """Perform a self-update of the plugin.

        This method updates the plugin to the latest version. Override
        in subclasses that support self-update.

        Args:
            force: If True, update even if already at latest version.

        Returns:
            SelfUpdateResult with the outcome.
        """
        if not self.supports_self_update:
            return SelfUpdateResult(
                status=SelfUpdateStatus.NOT_SUPPORTED,
                message=f"Plugin '{self.name}' does not support self-update",
            )

        log = logger.bind(plugin=self.name)
        old_version = self.current_version

        # Check if update is available
        update_available, new_version = await self.check_self_update_available()

        if not update_available and not force:
            return SelfUpdateResult(
                status=SelfUpdateStatus.ALREADY_LATEST,
                old_version=old_version,
                new_version=old_version,
                message="Already at the latest version",
            )

        log.info("performing_self_update", old_version=old_version, new_version=new_version)

        try:
            success, message = await self._perform_self_update()

            if success:
                # Re-check version after update
                updated_version = self.current_version
                return SelfUpdateResult(
                    status=SelfUpdateStatus.SUCCESS,
                    old_version=old_version,
                    new_version=updated_version or new_version,
                    message=message or "Self-update completed successfully",
                )
            else:
                return SelfUpdateResult(
                    status=SelfUpdateStatus.FAILED,
                    old_version=old_version,
                    message=message or "Self-update failed",
                )

        except Exception as e:
            log.exception("self_update_error", error=str(e))
            return SelfUpdateResult(
                status=SelfUpdateStatus.FAILED,
                old_version=old_version,
                message=f"Self-update failed: {e}",
            )

    async def _perform_self_update(self) -> tuple[bool, str]:
        """Perform the actual self-update.

        Override in subclasses that support self-update.

        Returns:
            Tuple of (success, message).
        """
        return False, "Self-update not implemented"

    async def self_upgrade(self, *, force: bool = False) -> SelfUpdateResult:
        """Perform a major version upgrade of the plugin.

        This method upgrades the plugin to a new major version, which may
        include breaking changes. Override in subclasses that support
        major version upgrades.

        Args:
            force: If True, upgrade even if there are warnings.

        Returns:
            SelfUpdateResult with the outcome.
        """
        # Default implementation delegates to self_update
        # Subclasses can override for different behavior
        return await self.self_update(force=force)
