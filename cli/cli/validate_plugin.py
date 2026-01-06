"""Plugin validation tool for external plugin authors.

This module provides a CLI command to validate external plugins,
checking that they conform to the streaming protocol and work correctly.
"""

from __future__ import annotations

import asyncio
import json
import stat
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path  # noqa: TC003 - Required at runtime for typer
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.streaming import PROGRESS_PREFIX

console = Console()


class ValidationSeverity(str, Enum):
    """Severity level for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """A single validation issue."""

    severity: ValidationSeverity
    message: str
    details: str | None = None


@dataclass
class CommandResult:
    """Result of running a plugin command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    timeout: bool = False
    error: str | None = None


@dataclass
class ValidationResult:
    """Result of plugin validation."""

    plugin_path: Path
    issues: list[ValidationIssue] = field(default_factory=list)
    commands_tested: list[CommandResult] = field(default_factory=list)
    streaming_events: list[dict[str, object]] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)

    def add_error(self, message: str, details: str | None = None) -> None:
        """Add an error issue."""
        self.issues.append(ValidationIssue(ValidationSeverity.ERROR, message, details))

    def add_warning(self, message: str, details: str | None = None) -> None:
        """Add a warning issue."""
        self.issues.append(ValidationIssue(ValidationSeverity.WARNING, message, details))

    def add_info(self, message: str, details: str | None = None) -> None:
        """Add an info issue."""
        self.issues.append(ValidationIssue(ValidationSeverity.INFO, message, details))


class PluginValidator:
    """Validates external plugins for correctness and protocol compliance."""

    def __init__(
        self,
        plugin_path: Path,
        timeout: int = 30,
        verbose: bool = False,
    ) -> None:
        """Initialize the validator.

        Args:
            plugin_path: Path to the plugin executable.
            timeout: Timeout for each command in seconds.
            verbose: Enable verbose output.
        """
        self.plugin_path = plugin_path.resolve()
        self.timeout = timeout
        self.verbose = verbose
        self.result = ValidationResult(plugin_path=self.plugin_path)

    async def validate(self) -> ValidationResult:
        """Run all validation checks.

        Returns:
            ValidationResult with all issues found.
        """
        # Check file exists and is executable
        self._check_file_exists()
        if self.result.has_errors:
            return self.result

        self._check_executable()
        if self.result.has_errors:
            return self.result

        # Check required commands
        await self._check_is_applicable()
        await self._check_update_command()

        # Check optional commands
        await self._check_optional_commands()

        # Validate streaming output if update command worked
        self._validate_streaming_events()

        return self.result

    def _check_file_exists(self) -> None:
        """Check that the plugin file exists."""
        if not self.plugin_path.exists():
            self.result.add_error(
                f"Plugin file not found: {self.plugin_path}",
                "Ensure the path to the plugin is correct.",
            )
        elif not self.plugin_path.is_file():
            self.result.add_error(
                f"Plugin path is not a file: {self.plugin_path}",
                "The plugin must be a regular file, not a directory.",
            )

    def _check_executable(self) -> None:
        """Check that the plugin is executable."""
        mode = self.plugin_path.stat().st_mode
        if not (mode & stat.S_IXUSR or mode & stat.S_IXGRP or mode & stat.S_IXOTH):
            self.result.add_error(
                "Plugin is not executable",
                f"Run: chmod +x {self.plugin_path}",
            )

    async def _run_command(
        self,
        command: str,
        *args: str,
    ) -> CommandResult:
        """Run a plugin command.

        Args:
            command: The command to run (e.g., "is-applicable").
            *args: Additional arguments.

        Returns:
            CommandResult with output and exit code.
        """
        cmd = [str(self.plugin_path), command, *args]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout,
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                result = CommandResult(
                    command=command,
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    timeout=True,
                    error=f"Command timed out after {self.timeout}s",
                )
                self.result.commands_tested.append(result)
                return result

            result = CommandResult(
                command=command,
                exit_code=process.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
            )
            self.result.commands_tested.append(result)

            # Parse streaming events from stderr
            for line in result.stderr.splitlines():
                if line.startswith(PROGRESS_PREFIX):
                    json_str = line[len(PROGRESS_PREFIX) :].strip()
                    try:
                        event = json.loads(json_str)
                        self.result.streaming_events.append(event)
                    except json.JSONDecodeError:
                        pass

            return result

        except FileNotFoundError:
            result = CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="",
                error="Plugin executable not found",
            )
            self.result.commands_tested.append(result)
            return result
        except PermissionError:
            result = CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="",
                error="Permission denied - plugin not executable",
            )
            self.result.commands_tested.append(result)
            return result

    async def _check_is_applicable(self) -> None:
        """Check the is-applicable command."""
        result = await self._run_command("is-applicable")

        if result.error:
            self.result.add_error(
                f"is-applicable command failed: {result.error}",
            )
            return

        if result.timeout:
            self.result.add_error(
                "is-applicable command timed out",
                "This command should complete quickly (< 5 seconds).",
            )
            return

        # Exit code 0 = applicable, 1 = not applicable, other = error
        if result.exit_code not in (0, 1):
            self.result.add_warning(
                f"is-applicable returned unexpected exit code: {result.exit_code}",
                "Expected 0 (applicable) or 1 (not applicable).",
            )

        if result.exit_code == 0:
            self.result.add_info("Plugin is applicable on this system")
        else:
            self.result.add_info(
                "Plugin is not applicable on this system",
                "This may be expected if the package manager is not installed.",
            )

    async def _check_update_command(self) -> None:
        """Check the update command with --dry-run."""
        # First try with --dry-run
        result = await self._run_command("update", "--dry-run")

        if result.error:
            self.result.add_error(
                f"update command failed: {result.error}",
            )
            return

        if result.timeout:
            self.result.add_error(
                "update --dry-run command timed out",
                f"Command should complete within {self.timeout} seconds.",
            )
            return

        if result.exit_code != 0:
            # Check if it's because the plugin doesn't support --dry-run
            if "dry-run" in result.stderr.lower() or "unknown" in result.stderr.lower():
                self.result.add_warning(
                    "Plugin may not support --dry-run flag",
                    "Consider adding --dry-run support for safer testing.",
                )
            else:
                self.result.add_warning(
                    f"update --dry-run returned exit code {result.exit_code}",
                    result.stderr[:200] if result.stderr else None,
                )

    async def _check_optional_commands(self) -> None:
        """Check optional commands."""
        optional_commands = [
            ("does-require-sudo", "Check if sudo is required"),
            ("can-separate-download", "Check if download is separate"),
            ("estimate-update", "Estimate update size/time"),
        ]

        for cmd, description in optional_commands:
            result = await self._run_command(cmd)

            if result.error or result.timeout:
                self.result.add_info(
                    f"Optional command '{cmd}' not available",
                    description,
                )
                continue

            if result.exit_code not in (0, 1):
                self.result.add_warning(
                    f"Optional command '{cmd}' returned unexpected exit code: {result.exit_code}",
                )

            # Validate estimate-update JSON output
            if cmd == "estimate-update" and result.exit_code == 0:
                self._validate_estimate_output(result.stdout)

    def _validate_estimate_output(self, output: str) -> None:
        """Validate estimate-update JSON output."""
        try:
            data = json.loads(output)

            if "status" not in data:
                self.result.add_warning(
                    "estimate-update output missing 'status' field",
                )

            if "data" in data:
                estimate_data = data["data"]
                expected_fields = ["total_bytes", "package_count", "estimated_seconds"]
                for field_name in expected_fields:
                    if field_name not in estimate_data:
                        self.result.add_info(
                            f"estimate-update missing optional field: {field_name}",
                        )

        except json.JSONDecodeError as e:
            self.result.add_warning(
                "estimate-update output is not valid JSON",
                str(e),
            )

    def _validate_streaming_events(self) -> None:
        """Validate streaming events from stderr."""
        if not self.result.streaming_events:
            self.result.add_info(
                "No streaming events detected",
                "Plugin uses legacy (non-streaming) output mode.",
            )
            return

        self.result.add_info(
            f"Found {len(self.result.streaming_events)} streaming events",
        )

        # Validate each event
        for i, event in enumerate(self.result.streaming_events):
            self._validate_single_event(i, event)

    def _validate_single_event(self, index: int, event: dict[str, object]) -> None:
        """Validate a single streaming event."""
        event_type = event.get("type", "progress")

        if event_type == "progress":
            # Validate progress event
            if "phase" not in event:
                self.result.add_warning(
                    f"Event {index}: progress event missing 'phase' field",
                )
            else:
                phase = event["phase"]
                if phase not in ("check", "download", "execute"):
                    self.result.add_warning(
                        f"Event {index}: unknown phase '{phase}'",
                        "Expected: check, download, or execute",
                    )

            # Check percent is valid if present
            if "percent" in event:
                percent = event["percent"]
                if not isinstance(percent, (int, float)):
                    self.result.add_warning(
                        f"Event {index}: 'percent' should be a number",
                    )
                elif not 0 <= float(percent) <= 100:
                    self.result.add_warning(
                        f"Event {index}: 'percent' should be 0-100, got {percent}",
                    )

        elif event_type == "phase_start":
            if "phase" not in event:
                self.result.add_warning(
                    f"Event {index}: phase_start event missing 'phase' field",
                )

        elif event_type == "phase_end":
            if "phase" not in event:
                self.result.add_warning(
                    f"Event {index}: phase_end event missing 'phase' field",
                )
            if "success" not in event:
                self.result.add_warning(
                    f"Event {index}: phase_end event missing 'success' field",
                )

        else:
            self.result.add_info(
                f"Event {index}: unknown event type '{event_type}'",
            )


def print_validation_result(result: ValidationResult, verbose: bool = False) -> None:
    """Print validation results to console.

    Args:
        result: The validation result to print.
        verbose: Enable verbose output.
    """
    # Header
    console.print()
    console.print(
        Panel(
            f"[bold]Plugin Validation: {result.plugin_path.name}[/bold]",
            subtitle=str(result.plugin_path),
        )
    )
    console.print()

    # Issues table
    if result.issues:
        table = Table(title="Validation Results", show_header=True)
        table.add_column("Severity", style="bold", width=10)
        table.add_column("Message")
        table.add_column("Details", style="dim")

        for issue in result.issues:
            severity_style = {
                ValidationSeverity.ERROR: "[red]ERROR[/red]",
                ValidationSeverity.WARNING: "[yellow]WARN[/yellow]",
                ValidationSeverity.INFO: "[blue]INFO[/blue]",
            }.get(issue.severity, issue.severity.value)

            table.add_row(
                severity_style,
                issue.message,
                issue.details or "",
            )

        console.print(table)
        console.print()

    # Commands tested
    if verbose and result.commands_tested:
        table = Table(title="Commands Tested", show_header=True)
        table.add_column("Command", style="cyan")
        table.add_column("Exit Code", justify="right")
        table.add_column("Status")

        for cmd in result.commands_tested:
            if cmd.timeout:
                status = "[red]TIMEOUT[/red]"
            elif cmd.error:
                status = f"[red]{cmd.error}[/red]"
            elif cmd.exit_code == 0:
                status = "[green]OK[/green]"
            else:
                status = f"[yellow]Exit {cmd.exit_code}[/yellow]"

            table.add_row(cmd.command, str(cmd.exit_code), status)

        console.print(table)
        console.print()

    # Streaming events
    if verbose and result.streaming_events:
        console.print("[bold]Streaming Events:[/bold]")
        for i, event in enumerate(result.streaming_events):
            console.print(f"  {i}: {json.dumps(event)}")
        console.print()

    # Summary
    error_count = sum(1 for i in result.issues if i.severity == ValidationSeverity.ERROR)
    warning_count = sum(1 for i in result.issues if i.severity == ValidationSeverity.WARNING)
    info_count = sum(1 for i in result.issues if i.severity == ValidationSeverity.INFO)

    if error_count > 0:
        console.print("[red bold]✗ Validation FAILED[/red bold]")
        console.print(f"  Errors: {error_count}, Warnings: {warning_count}, Info: {info_count}")
    elif warning_count > 0:
        console.print("[yellow bold]⚠ Validation passed with warnings[/yellow bold]")
        console.print(f"  Warnings: {warning_count}, Info: {info_count}")
    else:
        console.print("[green bold]✓ Validation PASSED[/green bold]")
        console.print(f"  Info: {info_count}")


async def validate_plugin_async(
    plugin_path: Path,
    timeout: int = 30,
    verbose: bool = False,
) -> ValidationResult:
    """Validate a plugin asynchronously.

    Args:
        plugin_path: Path to the plugin executable.
        timeout: Timeout for each command.
        verbose: Enable verbose output.

    Returns:
        ValidationResult with all issues found.
    """
    validator = PluginValidator(plugin_path, timeout=timeout, verbose=verbose)
    return await validator.validate()


def validate_plugin_command(
    plugin_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the plugin executable to validate.",
            exists=False,  # We check existence ourselves for better error messages
        ),
    ],
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="Timeout for each command in seconds.",
        ),
    ] = 30,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output.",
        ),
    ] = False,
) -> None:
    """Validate an external plugin.

    Check that a plugin conforms to the Update-All plugin protocol,
    including streaming output format and required commands.

    Example:
        update-all plugins validate /path/to/my-plugin
        update-all plugins validate ./my-plugin.sh --verbose
    """
    result = asyncio.run(validate_plugin_async(plugin_path, timeout=timeout, verbose=verbose))
    print_validation_result(result, verbose=verbose)

    # Exit with appropriate code
    if result.has_errors:
        raise typer.Exit(1)
    elif result.has_warnings:
        raise typer.Exit(0)  # Warnings don't fail validation
    else:
        raise typer.Exit(0)
