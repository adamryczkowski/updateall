"""Flatpak package manager plugin."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    StreamEvent,
)
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig


class FlatpakPlugin(BasePlugin):
    """Plugin for Flatpak application manager.

    Executes:
    1. flatpak update -y - update all installed applications
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "flatpak"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "flatpak"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Flatpak application manager"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs flatpak update, showing live output
        in the terminal.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            # Show what would be updated without actually updating
            return ["flatpak", "update", "--no-deploy"]
        return ["flatpak", "update", "-y"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute flatpak update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["flatpak", "update", "-y", "--noninteractive"],
            timeout=config.timeout_seconds,
            sudo=False,  # flatpak can run as user
        )

        output = f"=== flatpak update ===\n{stdout}"

        if return_code != 0:
            # Check for common non-error conditions
            if "Nothing to do" in stdout or "Nothing to do" in stderr:
                return output, None
            return output, f"flatpak update failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from flatpak output.

        Looks for patterns like:
        - "Updating app/org.example.App"
        - Lines with version changes

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "Updating" lines
        updating_count = len(re.findall(r"^Updating\s+", output, re.MULTILINE))

        if updating_count == 0:
            # Alternative: count lines with arrow indicating version change
            updating_count = len(re.findall(r"→", output))

        return updating_count

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute flatpak update with streaming output.

        This method provides real-time output during flatpak operations.

        Yields:
            StreamEvent objects as flatpak executes.
        """
        from core.models import PluginConfig

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== flatpak update ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            ["flatpak", "update", "-y", "--noninteractive"],
            timeout=config.timeout_seconds,
            sudo=False,
            phase=Phase.EXECUTE,
        ):
            # Collect output for package counting
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            # Check for completion event
            if isinstance(event, CompletionEvent):
                # flatpak returns non-zero sometimes when nothing to do
                success = event.success
                if not success:
                    output_str = "\n".join(collected_output)
                    if "Nothing to do" in output_str:
                        success = True

                packages_updated = self._count_updated_packages("\n".join(collected_output))
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=success,
                    exit_code=0 if success else event.exit_code,
                    packages_updated=packages_updated,
                    error_message=None if success else event.error_message,
                )
                return

            yield event
