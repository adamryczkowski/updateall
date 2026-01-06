"""Base plugin implementation with common functionality."""

from __future__ import annotations

import asyncio
import shutil
from abc import abstractmethod
from datetime import UTC, datetime

import structlog

from core.interfaces import UpdatePlugin
from core.models import ExecutionResult, PluginConfig, PluginResult, PluginStatus, UpdateStatus

logger = structlog.get_logger(__name__)


class BasePlugin(UpdatePlugin):
    """Base class for all update plugins with common functionality.

    Provides:
    - Command execution with timeout handling
    - Structured logging
    - Common availability checking
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
