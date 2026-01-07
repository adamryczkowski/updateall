"""Base plugin implementation with common functionality."""

from __future__ import annotations

import asyncio
import shutil
from abc import abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from core.download_manager import get_download_manager
from core.interfaces import UpdatePlugin
from core.models import (
    DownloadEstimate,
    DownloadSpec,
    ExecutionResult,
    PluginConfig,
    PluginResult,
    PluginStatus,
    UpdateCommand,
    UpdateStatus,
)
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
    StreamEventQueue,
    parse_progress_line,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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

    # =========================================================================
    # Sudo Declaration API (Proposal 5)
    # =========================================================================

    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        Override this property to declare which commands need sudo privileges.
        This enables:
        1. Automatic sudoers file generation
        2. Pre-checking sudo availability before execution
        3. Prompting for password once at start

        Returns:
            List of full paths to commands requiring sudo.
            Return empty list if no sudo is needed.

        Example:
            @property
            def sudo_commands(self) -> list[str]:
                return ["/usr/bin/apt", "/usr/bin/dpkg"]
        """
        return []

    @property
    def requires_sudo(self) -> bool:
        """Check if any commands require sudo.

        This is a convenience property that checks if sudo_commands
        returns a non-empty list.

        Returns:
            True if sudo_commands is non-empty, False otherwise.
        """
        return len(self.sudo_commands) > 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        This method returns the command that will be executed in a PTY
        for interactive terminal display. Override in subclasses to
        provide the actual update command.

        The command should be a single command that performs the full
        update process. For plugins that require multiple commands
        (e.g., apt update && apt upgrade), use a shell wrapper.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        # Default implementation: run the command with common update flags
        # Subclasses should override for plugin-specific behavior
        if dry_run:
            return ["/bin/bash", "-c", f"echo '[{self.name}] Dry run - no changes made'"]
        return ["/bin/bash", "-c", f"echo '[{self.name}] No interactive command defined'"]

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

    # =========================================================================
    # Declarative Command Execution API
    # =========================================================================

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:  # noqa: ARG002
        """Get the list of commands to execute for an update.

        Override this method to use the declarative command execution API.
        When this method returns a non-empty list, the plugin will use
        _execute_commands_streaming() instead of _execute_update_streaming().

        This is the preferred way to implement plugins as it reduces
        boilerplate and provides automatic:
        - Command header output
        - Step progress tracking
        - Output collection for package counting
        - Success/error pattern matching
        - Exit code handling

        Args:
            dry_run: If True, return commands for dry-run mode.

        Returns:
            List of UpdateCommand objects to execute sequentially.
            Return empty list to use the legacy _execute_update_streaming() API.

        Example:
            def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
                if dry_run:
                    return [UpdateCommand(cmd=["apt", "update", "--dry-run"])]
                return [
                    UpdateCommand(
                        cmd=["apt", "update"],
                        description="Update package lists",
                        sudo=True,
                        step_number=1,
                        total_steps=2,
                    ),
                    UpdateCommand(
                        cmd=["apt", "upgrade", "-y"],
                        description="Upgrade packages",
                        sudo=True,
                        step_number=2,
                        total_steps=2,
                    ),
                ]
        """
        return []

    async def _run_command(
        self,
        cmd: list[str],
        timeout: int,
        *,
        check: bool = True,  # noqa: ARG002
        sudo: bool = False,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Run a shell command with timeout.

        Args:
            cmd: Command and arguments as a list.
            timeout: Timeout in seconds.
            check: Whether to raise on non-zero exit code (reserved for future use).
            sudo: Whether to prepend sudo to the command.
            cwd: Working directory for the command.
            env: Environment variables for the command.

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
                cwd=cwd,
                env=env,
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
    # Streaming Execution (Phase 1 - Core Streaming Infrastructure)
    # =========================================================================

    @property
    def supports_streaming(self) -> bool:
        """Check if this plugin supports streaming output.

        BasePlugin provides native streaming support via _run_command_streaming.

        Returns:
            True - BasePlugin supports streaming.
        """
        return True

    async def _run_command_streaming(
        self,
        cmd: list[str],
        timeout: int,
        *,
        sudo: bool = False,
        phase: Phase = Phase.EXECUTE,  # noqa: ARG002
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Run a command with streaming output.

        This method streams output line-by-line as the command executes,
        enabling real-time display in the UI.

        Args:
            cmd: Command and arguments as a list.
            timeout: Timeout in seconds.
            sudo: Whether to prepend sudo to the command.
            phase: Current execution phase (reserved for future progress events).
            cwd: Working directory for the command.
            env: Environment variables for the command.

        Yields:
            StreamEvent objects as output is produced.
            Final event is always a CompletionEvent.
        """
        if sudo:
            cmd = ["sudo", *cmd]

        log = logger.bind(plugin=self.name, command=" ".join(cmd))
        log.debug("running_command_streaming")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        # Use bounded queue for backpressure (Risk T3 mitigation)
        queue: StreamEventQueue = StreamEventQueue(maxsize=1000)

        async def read_stream(
            stream: asyncio.StreamReader | None,
            stream_name: str,
        ) -> None:
            """Read lines from a stream and put events in queue."""
            if stream is None:
                return

            while True:
                try:
                    line = await stream.readline()
                    if not line:
                        break

                    line_str = line.decode("utf-8", errors="replace").rstrip()

                    # Check for JSON progress events (PROGRESS: prefix)
                    progress_event = parse_progress_line(line_str, self.name)
                    if progress_event:
                        await queue.put(progress_event)
                        continue

                    # Regular output line
                    await queue.put(
                        OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=line_str,
                            stream=stream_name,
                        )
                    )
                except Exception as e:
                    log.warning("stream_read_error", stream=stream_name, error=str(e))
                    break

        # Use TaskGroup for concurrent stream reading (Risk T2 mitigation)
        try:
            async with asyncio.timeout(timeout):
                # Start stream readers as tasks
                async with asyncio.TaskGroup() as tg:
                    stdout_task = tg.create_task(read_stream(process.stdout, "stdout"))
                    stderr_task = tg.create_task(read_stream(process.stderr, "stderr"))

                    # Yield events from queue while tasks are running
                    async def yield_events() -> None:
                        """Signal when both streams are done."""
                        await stdout_task
                        await stderr_task
                        await queue.close()

                    tg.create_task(yield_events())

                    # Yield events as they arrive
                    async for event in queue:
                        yield event

                # Wait for process to complete
                await process.wait()

                # Log if events were dropped
                if queue.dropped_count > 0:
                    log.warning(
                        "events_dropped",
                        dropped_count=queue.dropped_count,
                    )

                # Emit completion event
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=process.returncode == 0,
                    exit_code=process.returncode or 0,
                )

        except TimeoutError:
            log.warning("command_streaming_timeout", timeout=timeout)
            # Kill the process
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=f"Command timed out after {timeout}s",
            )

        except ExceptionGroup as eg:
            # Handle exceptions from TaskGroup
            log.exception("streaming_exception_group", errors=str(eg.exceptions))
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=f"Streaming error: {eg.exceptions[0]}",
            )

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute the update process with streaming output.

        This method provides real-time output during plugin execution.
        Override this method to provide custom streaming behavior.

        Args:
            dry_run: If True, simulate the update without making changes.

        Yields:
            StreamEvent objects as the plugin executes.
            The final event is always a CompletionEvent.
        """
        log = logger.bind(plugin=self.name)

        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        # Check availability first
        if not await self.check_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Command '{self.command}' not found - skipping",
                stream="stderr",
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                success=False,
                error_message=f"Command '{self.command}' not found",
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=f"Command '{self.command}' not found",
            )
            return

        # Check for declarative commands first
        commands = self.get_update_commands(dry_run=dry_run)

        # In dry-run mode with no declarative commands, just report what would be done
        if dry_run and not commands:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Dry run - no changes made",
                stream="stdout",
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                success=True,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        # Run the streaming update
        log.info("starting_streaming_update", declarative=bool(commands))

        try:
            final_success = False
            final_error: str | None = None

            # Use declarative execution if commands are provided
            if commands:
                async for event in self._execute_commands_streaming(commands):
                    yield event

                    # Track completion status
                    if isinstance(event, CompletionEvent):
                        final_success = event.success
                        final_error = event.error_message
            else:
                # Fall back to legacy API
                async for event in self._execute_update_streaming():
                    yield event

                    # Track completion status
                    if isinstance(event, CompletionEvent):
                        final_success = event.success
                        final_error = event.error_message

            # Emit phase end
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                success=final_success,
                error_message=final_error,
            )

            log.info("streaming_update_completed", success=final_success)

        except Exception as e:
            log.exception("streaming_update_error", error=str(e))

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                success=False,
                error_message=str(e),
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=str(e),
            )

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute the actual update commands with streaming.

        Override this method in subclasses to provide streaming update execution.
        The default implementation falls back to the non-streaming _execute_update.

        Yields:
            StreamEvent objects as the update executes.
        """
        # Default: fall back to non-streaming execution
        config = PluginConfig(name=self.name)
        output, error = await self._execute_update(config)

        # Emit output lines
        if output:
            for line in output.splitlines():
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=line,
                    stream="stdout",
                )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=error is None,
            exit_code=0 if error is None else 1,
            packages_updated=self._count_updated_packages(output) if output else 0,
            error_message=error,
        )

    async def _execute_commands_streaming(
        self,
        commands: list[UpdateCommand],
    ) -> AsyncIterator[StreamEvent]:
        """Execute a list of commands sequentially with streaming output.

        This method is used by execute_streaming() when get_update_commands()
        returns a non-empty list. It provides automatic:
        - Command header output with step progress
        - Output collection for package counting
        - Success/error pattern matching
        - Exit code handling with ignore_exit_codes support

        Args:
            commands: List of UpdateCommand objects to execute.

        Yields:
            StreamEvent objects as commands execute.
            Final event is always a CompletionEvent.
        """
        log = logger.bind(plugin=self.name)
        collected_output: list[str] = []
        final_success = True
        final_error: str | None = None
        final_exit_code = 0

        for i, command in enumerate(commands):
            # Emit header for this command
            step_info = ""
            if command.step_number and command.total_steps:
                step_info = f"[{command.step_number}/{command.total_steps}] "
            elif len(commands) > 1:
                step_info = f"[{i + 1}/{len(commands)}] "

            header = f"=== {step_info}{command.description or ' '.join(command.cmd)} ==="
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=header,
                stream="stdout",
            )

            log.debug(
                "executing_command",
                step=i + 1,
                total=len(commands),
                cmd=" ".join(command.cmd),
            )

            # Track output for this command
            command_output: list[str] = []
            command_success = True
            command_exit_code = 0
            has_success_pattern = False
            has_error_pattern = False

            # Execute the command
            timeout = command.timeout_seconds or 300  # Default 5 minutes
            async for event in self._run_command_streaming(
                command.cmd,
                timeout,
                sudo=command.sudo,
                phase=command.phase,
            ):
                # Collect output for pattern matching and package counting
                if isinstance(event, OutputEvent):
                    command_output.append(event.line)
                    collected_output.append(event.line)

                    # Check for success patterns
                    if command.success_patterns:
                        for pattern in command.success_patterns:
                            if pattern in event.line:
                                has_success_pattern = True
                                break

                    # Check for error patterns
                    if command.error_patterns:
                        for pattern in command.error_patterns:
                            if pattern in event.line:
                                has_error_pattern = True
                                break

                    yield event

                elif isinstance(event, CompletionEvent):
                    command_exit_code = event.exit_code
                    command_success = event.success
                    # Don't yield the intermediate completion event

                else:
                    # Pass through other events (progress, etc.)
                    yield event

            # Determine final success for this command based on pattern matching
            # and exit codes (error patterns take precedence over success patterns)
            if has_error_pattern:
                command_success = False
                final_error = "Error pattern detected in output"
            elif has_success_pattern or command_exit_code in command.ignore_exit_codes:
                command_success = True
            elif command_exit_code != 0:
                command_success = False
                final_error = f"Command exited with code {command_exit_code}"

            # If this command failed, stop execution
            if not command_success:
                final_success = False
                final_exit_code = command_exit_code
                log.warning(
                    "command_failed",
                    step=i + 1,
                    exit_code=command_exit_code,
                    error=final_error,
                )
                break

        # Calculate package count from collected output
        full_output = "\n".join(collected_output)
        packages_updated = self._count_updated_packages(full_output)

        # Emit final completion event
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=final_success,
            exit_code=final_exit_code,
            packages_updated=packages_updated,
            error_message=final_error,
        )

    # =========================================================================
    # Download API (Phase 2 - Download API)
    # =========================================================================

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Override in subclasses that support downloading updates separately
        from applying them. This enables:
        - Pre-downloading updates for offline installation
        - Download progress tracking
        - Separate download and execute phases in the UI

        Returns:
            False by default. Override to return True if supported.
        """
        return False

    async def estimate_download(self) -> DownloadEstimate | None:
        """Estimate the download size and time.

        Override this method to provide accurate download estimates.
        The default implementation returns None (no estimate available).

        Returns:
            DownloadEstimate with size and time estimates, or None if
            no downloads are needed or estimation is not supported.
        """
        return None

    # =========================================================================
    # Centralized Download Manager API
    # =========================================================================

    async def get_download_spec(self) -> DownloadSpec | None:
        """Get the download specification for this plugin.

        Override this method to use the Centralized Download Manager.
        When this method returns a DownloadSpec, download_streaming() will
        automatically use the DownloadManager instead of the legacy download()
        method.

        This is the preferred way to implement downloads as it provides:
        - Automatic retry with exponential backoff
        - Bandwidth limiting
        - Download caching with checksum verification
        - Archive extraction (tar.gz, tar.bz2, tar.xz, zip)
        - Progress reporting

        Returns:
            DownloadSpec with URL, destination, and options, or None if
            no download is needed or the legacy API should be used.

        Example:
            async def get_download_spec(self) -> DownloadSpec | None:
                version = await self._get_latest_version()
                return DownloadSpec(
                    url=f"https://example.com/app-{version}.tar.gz",
                    destination=Path(f"/tmp/app-{version}.tar.gz"),
                    checksum=f"sha256:{await self._get_checksum(version)}",
                    extract=True,
                    extract_to=Path("/opt/app"),
                )
        """
        return None

    async def get_download_specs(self) -> list[DownloadSpec]:
        """Get multiple download specifications for this plugin.

        Override this method when the plugin needs to download multiple files.
        When this method returns a non-empty list, download_streaming() will
        download all files sequentially using the DownloadManager.

        Returns:
            List of DownloadSpec objects, or empty list if no downloads needed.

        Example:
            async def get_download_specs(self) -> list[DownloadSpec]:
                return [
                    DownloadSpec(
                        url="https://example.com/main.tar.gz",
                        destination=Path("/tmp/main.tar.gz"),
                    ),
                    DownloadSpec(
                        url="https://example.com/data.zip",
                        destination=Path("/tmp/data.zip"),
                    ),
                ]
        """
        return []

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Download updates without applying them.

        This method downloads updates but does not install them. Override
        this method to implement download-only functionality.

        The default implementation raises NotImplementedError.

        Yields:
            StreamEvent objects with download progress.

        Raises:
            NotImplementedError: If the plugin does not support separate download.
        """
        raise NotImplementedError(f"Plugin '{self.name}' does not support separate download")
        # Make this a generator (required for AsyncIterator return type)
        yield  # pragma: no cover

    async def download_streaming(self) -> AsyncIterator[StreamEvent]:
        """Download updates with streaming progress output.

        This method provides real-time progress updates during the download phase.
        It automatically uses the Centralized Download Manager when get_download_spec()
        or get_download_specs() returns download specifications.

        The priority order is:
        1. get_download_specs() - for multiple downloads
        2. get_download_spec() - for single download
        3. download() - legacy API fallback

        Yields:
            StreamEvent objects with download progress.
        """
        log = logger.bind(plugin=self.name)

        # Check if download is supported
        if not self.supports_download:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Plugin '{self.name}' does not support separate download",
                stream="stderr",
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message="Plugin does not support separate download",
            )
            return

        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        log.info("starting_download")

        try:
            final_success = False
            final_error: str | None = None

            # Check for Centralized Download Manager API first
            download_specs = await self.get_download_specs()
            if not download_specs:
                # Try single download spec
                single_spec = await self.get_download_spec()
                if single_spec:
                    download_specs = [single_spec]

            if download_specs:
                # Use Centralized Download Manager
                log.info("using_download_manager", spec_count=len(download_specs))
                download_manager = get_download_manager()

                for i, spec in enumerate(download_specs):
                    log.debug(
                        "downloading_spec",
                        index=i + 1,
                        total=len(download_specs),
                        url=spec.url,
                    )

                    # Emit progress header for multiple downloads
                    if len(download_specs) > 1:
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=f"=== [{i + 1}/{len(download_specs)}] Downloading {spec.url} ===",
                            stream="stdout",
                        )

                    # Stream download progress
                    async for event in download_manager.download_streaming(
                        spec, plugin_name=self.name
                    ):
                        yield event

                        # Track completion status
                        if isinstance(event, CompletionEvent):
                            if not event.success:
                                final_success = False
                                final_error = event.error_message
                                break
                            final_success = True

                    # Stop if a download failed
                    if final_error:
                        break
            else:
                # Fall back to legacy download() API
                log.info("using_legacy_download_api")
                async for event in self.download():
                    yield event

                    # Track completion status
                    if isinstance(event, CompletionEvent):
                        final_success = event.success
                        final_error = event.error_message

            # Emit phase end
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=final_success,
                error_message=final_error,
            )

            log.info("download_completed", success=final_success)

        except NotImplementedError as e:
            log.warning("download_not_supported", error=str(e))

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message=str(e),
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=str(e),
            )

        except Exception as e:
            log.exception("download_error", error=str(e))

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message=str(e),
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=str(e),
            )

    async def execute_after_download(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute updates after download phase.

        This method applies updates that were previously downloaded.
        It assumes download() was already called successfully.

        Override this method to implement post-download execution.
        The default implementation delegates to execute_streaming().

        Args:
            dry_run: If True, simulate the update without making changes.

        Yields:
            StreamEvent objects as the plugin executes.
        """
        # Default: same as execute_streaming
        async for event in self.execute_streaming(dry_run=dry_run):
            yield event

    async def _run_download_command_streaming(
        self,
        cmd: list[str],
        timeout: int,
        *,
        sudo: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Run a download command with streaming output and progress tracking.

        This is a specialized version of _run_command_streaming for download
        operations. It parses progress events and emits them with the DOWNLOAD phase.

        Args:
            cmd: Command and arguments as a list.
            timeout: Timeout in seconds.
            sudo: Whether to prepend sudo to the command.

        Yields:
            StreamEvent objects as output is produced.
        """
        async for event in self._run_command_streaming(
            cmd, timeout, sudo=sudo, phase=Phase.DOWNLOAD
        ):
            # Re-tag progress events with DOWNLOAD phase
            if isinstance(event, ProgressEvent):
                yield ProgressEvent(
                    event_type=EventType.PROGRESS,
                    plugin_name=self.name,
                    timestamp=event.timestamp,
                    phase=Phase.DOWNLOAD,
                    percent=event.percent,
                    message=event.message,
                    bytes_downloaded=event.bytes_downloaded,
                    bytes_total=event.bytes_total,
                    items_completed=event.items_completed,
                    items_total=event.items_total,
                )
            else:
                yield event

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
