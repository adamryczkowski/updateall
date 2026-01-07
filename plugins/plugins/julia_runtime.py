"""Julia runtime update plugin using juliaup.

This plugin updates the Julia programming language runtime using juliaup.
Juliaup is a cross-platform Julia version manager written in Rust.

Official documentation:
- Juliaup: https://github.com/JuliaLang/juliaup

Note: This plugin should run after the cargo plugin since juliaup is
distributed via cargo (cargo install juliaup).
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.streaming import CompletionEvent, EventType, OutputEvent
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class JuliaRuntimePlugin(BasePlugin):
    """Plugin for updating Julia runtime via juliaup."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "julia-runtime"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "juliaup"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Julia runtime via juliaup"

    def is_available(self) -> bool:
        """Check if juliaup is installed."""
        return shutil.which("juliaup") is not None

    async def check_available(self) -> bool:
        """Check if juliaup is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed Julia version.

        Returns:
            Version string (e.g., "1.10.0") or None if Julia is not installed.
        """
        import subprocess

        if not shutil.which("julia"):
            return None

        try:
            result = subprocess.run(
                ["julia", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Output format: "julia version 1.10.0"
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    return parts[2]  # e.g., "1.10.0"
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated items from juliaup output.

        Args:
            output: Command output to parse.

        Returns:
            Number of items updated.
        """
        output_lower = output.lower()

        # Check for juliaup updates
        count = 0
        if "updated" in output_lower:
            # Count lines with "updated" for juliaup
            for line in output.split("\n"):
                if "updated" in line.lower():
                    count += 1

        return count

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Julia runtime update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["juliaup", "status"]
        return ["juliaup", "update"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Julia runtime update via juliaup.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if juliaup is installed
        if not self.is_available():
            return "juliaup not installed, skipping Julia runtime update", None

        local_version = self.get_local_version()
        if local_version:
            output_lines.append(f"Current Julia version: {local_version}")

        output_lines.append("Updating Julia via juliaup...")

        try:
            process = await asyncio.create_subprocess_exec(
                "juliaup",
                "update",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=config.timeout_seconds,
            )
            juliaup_output = stdout.decode() if stdout else ""
            output_lines.append(juliaup_output)

            if process.returncode != 0:
                error_msg = f"juliaup update failed with exit code {process.returncode}"
                output_lines.append(error_msg)
                return "\n".join(output_lines), error_msg

            output_lines.append("Julia runtime updated successfully")
            return "\n".join(output_lines), None

        except TimeoutError:
            return "\n".join(output_lines), "juliaup update timed out"
        except Exception as e:
            return "\n".join(output_lines), f"Error running juliaup: {e}"

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Julia runtime update with streaming output.

        Yields:
            StreamEvent objects from the update process.
        """
        # Check if juliaup is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="juliaup not installed, skipping Julia runtime update",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        local_version = self.get_local_version()
        if local_version:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Current Julia version: {local_version}",
                stream="stdout",
            )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Julia via juliaup...",
            stream="stdout",
        )

        collected_output: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                "juliaup",
                "update",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            if process.stdout:
                async for raw_line in process.stdout:
                    line_str = raw_line.decode().rstrip()
                    collected_output.append(line_str)
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=line_str,
                        stream="stdout",
                    )

            await process.wait()

            if process.returncode != 0:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"juliaup update failed with exit code {process.returncode}",
                    stream="stderr",
                )
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=False,
                    exit_code=process.returncode or 1,
                )
            else:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line="Julia runtime updated successfully",
                    stream="stdout",
                )
                full_output = "\n".join(collected_output)
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=True,
                    exit_code=0,
                    packages_updated=self._count_updated_packages(full_output),
                )
        except Exception as e:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Error running juliaup: {e}",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=str(e),
            )
