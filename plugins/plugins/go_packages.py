"""Go packages update plugin using go-global-update.

This plugin updates Go-installed packages using go-global-update.

go-global-update is a tool that updates all globally installed Go binaries.
Install it with: go install github.com/Gelio/go-global-update@latest

Note: This plugin should run after go-runtime to ensure the Go
runtime is up to date before updating packages.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.streaming import CompletionEvent, EventType, OutputEvent
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class GoPackagesPlugin(BasePlugin):
    """Plugin for updating Go-installed packages via go-global-update."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "go-packages"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "go-global-update"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Go-installed packages via go-global-update"

    def is_available(self) -> bool:
        """Check if go-global-update is installed."""
        # Check in PATH
        if shutil.which("go-global-update"):
            return True
        # Check in ~/go/bin
        home_bin = Path.home() / "go" / "bin" / "go-global-update"
        return home_bin.exists()

    async def check_available(self) -> bool:
        """Check if go-global-update is available for updates."""
        return self.is_available()

    def _get_go_global_update_path(self) -> str:
        """Get the path to go-global-update.

        Returns:
            Path to go-global-update executable.
        """
        # Check in PATH first
        if shutil.which("go-global-update"):
            return "go-global-update"
        # Check in ~/go/bin
        home_bin = Path.home() / "go" / "bin" / "go-global-update"
        if home_bin.exists():
            return str(home_bin)
        return "go-global-update"

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from go-global-update output.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated.
        """
        output_lower = output.lower()
        count = 0

        # Count "updating" or "updated" patterns
        count += output_lower.count("updating ")
        count += output_lower.count("updated ")

        return count

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Go packages update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        cmd = self._get_go_global_update_path()
        if dry_run:
            return [cmd, "--dry-run"]
        return [cmd]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Go packages update.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if go-global-update is installed
        if not self.is_available():
            return "go-global-update not installed, skipping Go packages update", None

        cmd = self._get_go_global_update_path()
        output_lines.append("Updating Go-installed packages...")

        try:
            process = await asyncio.create_subprocess_exec(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=config.timeout_seconds,
            )
            update_output = stdout.decode() if stdout else ""
            output_lines.append(update_output)

            if process.returncode != 0:
                error_msg = f"go-global-update failed with exit code {process.returncode}"
                output_lines.append(error_msg)
                return "\n".join(output_lines), error_msg

            output_lines.append("Go packages updated successfully")
            return "\n".join(output_lines), None

        except TimeoutError:
            return "\n".join(output_lines), "go-global-update timed out"
        except Exception as e:
            return "\n".join(output_lines), f"Error updating Go packages: {e}"

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Go packages update with streaming output.

        Yields:
            StreamEvent objects from the update process.
        """
        # Check if go-global-update is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="go-global-update not installed, skipping Go packages update",
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

        cmd = self._get_go_global_update_path()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Go-installed packages...",
            stream="stdout",
        )

        collected_output: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                cmd,
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

            full_output = "\n".join(collected_output)
            if process.returncode != 0:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"go-global-update failed with exit code {process.returncode}",
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
                    line="Go packages updated successfully",
                    stream="stdout",
                )
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
                line=f"Error updating Go packages: {e}",
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
