"""Base plugin implementation with common functionality."""

from __future__ import annotations

import asyncio
import shutil
from abc import abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from core.interfaces import UpdatePlugin
from core.models import PluginResult, UpdateStatus

if TYPE_CHECKING:
    from core.models import PluginConfig

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

    async def run_update(self, config: PluginConfig) -> PluginResult:
        """Run the update process.

        Args:
            config: Plugin configuration including timeout and options.

        Returns:
            PluginResult with status, output, and timing information.
        """
        start_time = datetime.now(tz=UTC)
        log = logger.bind(plugin=self.name)

        log.info("starting_update", timeout=config.timeout)

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
            log.warning("update_timeout", timeout=config.timeout)
            return PluginResult(
                plugin_name=self.name,
                status=UpdateStatus.TIMEOUT,
                start_time=start_time,
                end_time=datetime.now(tz=UTC),
                output="",
                error_message=f"Update timed out after {config.timeout} seconds",
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
