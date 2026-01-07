"""Pi-hole update plugin.

This plugin updates Pi-hole, a network-wide ad blocker.

Official documentation:
- Pi-hole: https://pi-hole.net/
- Update command: https://docs.pi-hole.net/main/update/

Update mechanism:
- pihole updatePihole - Updates Pi-hole to the latest version
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class PiholePlugin(BasePlugin):
    """Plugin for updating Pi-hole."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "pihole"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "pihole"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Pi-hole network-wide ad blocker"

    def is_available(self) -> bool:
        """Check if Pi-hole is installed."""
        return shutil.which("pihole") is not None

    async def check_available(self) -> bool:
        """Check if Pi-hole is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed Pi-hole version.

        Returns:
            Version string or None if Pi-hole is not installed.
        """
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["pihole", "-v"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output
                for line in result.stdout.split("\n"):
                    if "Pi-hole" in line and "v" in line:
                        # Extract version like "v5.17.1"
                        parts = line.split()
                        for part in parts:
                            if part.startswith("v"):
                                return part
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of components updated.
        """
        output_lower = output.lower()

        # Check for successful update
        if "update complete" in output_lower or "updated" in output_lower:
            return 1

        # Check for already up-to-date
        if "up to date" in output_lower or "already" in output_lower:
            return 0

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Pi-hole update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["pihole", "-v"]
        return ["pihole", "updatePihole"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Pi-hole update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Pi-hole is installed
        if not self.is_available():
            return "Pi-hole not installed, skipping update", None

        local_version = self.get_local_version()
        output_lines.append(f"Current Pi-hole version: {local_version}")
        output_lines.append("Updating Pi-hole...")

        # Run the update command
        return_code, stdout, stderr = await self._run_command(
            ["pihole", "updatePihole"],
            timeout=config.timeout_seconds,
            sudo=False,  # pihole command handles sudo internally
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Pi-hole update with streaming output.

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

        # Check if Pi-hole is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Pi-hole not installed, skipping update",
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

        local_version = self.get_local_version()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Current Pi-hole version: {local_version}",
            stream="stdout",
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Pi-hole...",
            stream="stdout",
        )

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        async for event in self._run_command_streaming(
            ["pihole", "updatePihole"],
            timeout=config.timeout_seconds,
            sudo=False,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            yield event
