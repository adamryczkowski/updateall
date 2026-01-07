"""Julia packages update plugin.

This plugin updates Julia packages in the default environment using Pkg.update().

Official documentation:
- Julia Pkg: https://pkgdocs.julialang.org/

Note: This plugin should run after julia-runtime to ensure the Julia
runtime is up to date before updating packages.
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


class JuliaPackagesPlugin(BasePlugin):
    """Plugin for updating Julia packages via Pkg.update()."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "julia-packages"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "julia"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Julia packages in the default environment"

    def is_available(self) -> bool:
        """Check if Julia is installed."""
        return shutil.which("julia") is not None

    async def check_available(self) -> bool:
        """Check if Julia is available for package updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed Julia version.

        Returns:
            Version string (e.g., "1.10.0") or None if Julia is not installed.
        """
        import subprocess

        if not self.is_available():
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
        """Count updated packages from Pkg.update() output.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated.
        """
        output_lower = output.lower()
        count = 0

        # Check for Pkg.update() output
        # Julia Pkg shows "Updating" for each package
        count += output_lower.count("updating ")

        # Also check for "↑" which Julia uses for upgrades
        count += output.count("↑")

        return count

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Julia package update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            # Show package status instead of updating
            return ["julia", "-e", "using Pkg; Pkg.status()"]
        return ["julia", "-e", "using Pkg; Pkg.update()"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Julia package update.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Julia is installed
        if not self.is_available():
            return "Julia not installed, skipping package update", None

        local_version = self.get_local_version()
        if local_version:
            output_lines.append(f"Julia version: {local_version}")

        output_lines.append("Updating Julia packages...")
        pkg_update_script = "using Pkg; Pkg.update()"

        try:
            process = await asyncio.create_subprocess_exec(
                "julia",
                "-e",
                pkg_update_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=config.timeout_seconds,
            )
            pkg_output = stdout.decode() if stdout else ""
            output_lines.append(pkg_output)

            if process.returncode != 0:
                error_msg = f"Pkg.update() failed with exit code {process.returncode}"
                output_lines.append(error_msg)
                return "\n".join(output_lines), error_msg

            output_lines.append("Julia packages updated successfully")
            return "\n".join(output_lines), None

        except TimeoutError:
            return "\n".join(output_lines), "Pkg.update() timed out"
        except Exception as e:
            return "\n".join(output_lines), f"Error updating packages: {e}"

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Julia package update with streaming output.

        Yields:
            StreamEvent objects from the update process.
        """
        # Check if Julia is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Julia not installed, skipping package update",
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
                line=f"Julia version: {local_version}",
                stream="stdout",
            )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Julia packages...",
            stream="stdout",
        )
        pkg_update_script = "using Pkg; Pkg.update()"

        collected_output: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                "julia",
                "-e",
                pkg_update_script,
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
                    line=f"Pkg.update() failed with exit code {process.returncode}",
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
                    line="Julia packages updated successfully",
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
                line=f"Error updating packages: {e}",
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
