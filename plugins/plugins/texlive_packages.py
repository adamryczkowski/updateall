"""TeX Live packages update plugin.

This plugin updates all TeX Live packages using tlmgr update --all.

Official documentation:
- TeX Live: https://www.tug.org/texlive/
- tlmgr: https://www.tug.org/texlive/tlmgr.html

Note: This plugin should run after texlive-self to ensure tlmgr
is up to date before updating packages.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from core.mutex import StandardMutexes
from core.streaming import Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class TexlivePackagesPlugin(BasePlugin):
    """Plugin for updating all TeX Live packages."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "texlive-packages"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "tlmgr"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update all TeX Live packages"

    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        tlmgr requires sudo for update operations on system-wide installations.
        """
        tlmgr_path = shutil.which("tlmgr")
        if tlmgr_path:
            return [tlmgr_path]
        return ["/usr/bin/tlmgr"]

    @property
    def dependencies(self) -> list[str]:
        """Return list of plugins that must run before this one.

        texlive-packages depends on texlive-self to ensure tlmgr
        is up to date before updating packages.
        """
        return ["texlive-self"]

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Return mutexes required for each execution phase.

        TeX Live packages update requires exclusive access to the TEXLIVE lock
        during execution to prevent conflicts with self-update.
        """
        return {
            Phase.EXECUTE: [StandardMutexes.TEXLIVE_LOCK],
        }

    def is_available(self) -> bool:
        """Check if tlmgr is installed."""
        return shutil.which("tlmgr") is not None

    async def check_available(self) -> bool:
        """Check if TeX Live is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed TeX Live version.

        Returns:
            Version string or None if TeX Live is not installed.
        """
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["tlmgr", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output
                output = result.stdout.strip()
                for line in output.split("\n"):
                    if "revision" in line.lower():
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part.lower() == "revision" and i + 1 < len(parts):
                                return parts[i + 1]
                # Fallback: return first line
                if output:
                    return output.split("\n")[0]
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated.
        """
        output_lower = output.lower()

        # Count "update:" occurrences
        count = output_lower.count("update:")

        # Also count "updated" occurrences
        if count == 0:
            count = output_lower.count(" updated")

        # Count packages with version changes (e.g., "package: local: 12345, source: 12346")
        if count == 0:
            count = output.count("source:")

        return count

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for TeX Live packages update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["tlmgr", "update", "--list"]
        return ["sudo", "tlmgr", "update", "--all"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the TeX Live packages update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if tlmgr is installed
        if not self.is_available():
            return "TeX Live (tlmgr) not installed, skipping update", None

        local_version = self.get_local_version()
        output_lines.append(f"TeX Live version: {local_version}")

        # Update all packages
        output_lines.append("Updating all TeX Live packages...")
        return_code, stdout, stderr = await self._run_command(
            ["tlmgr", "update", "--all"],
            timeout=config.timeout_seconds * 5,  # Package updates can take a while
            sudo=True,
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        output_lines.append("TeX Live packages updated successfully")
        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute TeX Live packages update with streaming output.

        Yields:
            StreamEvent objects as the update executes.
        """
        from datetime import UTC, datetime

        from core.models import PluginConfig
        from core.streaming import (
            CompletionEvent,
            EventType,
            OutputEvent,
        )

        # Check if tlmgr is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="TeX Live (tlmgr) not installed, skipping update",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
                packages_updated=0,
            )
            return

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        local_version = self.get_local_version()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"TeX Live version: {local_version}",
            stream="stdout",
        )

        # Update all packages
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating all TeX Live packages...",
            stream="stdout",
        )

        final_success = True
        final_exit_code = 0

        async for event in self._run_command_streaming(
            ["tlmgr", "update", "--all"],
            timeout=config.timeout_seconds * 5,
            sudo=True,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            elif isinstance(event, CompletionEvent):
                final_success = event.success
                final_exit_code = event.exit_code
            yield event

        full_output = "\n".join(collected_output)
        updated_count = self._count_updated_packages(full_output)

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=final_success,
            exit_code=final_exit_code,
            packages_updated=updated_count,
        )
