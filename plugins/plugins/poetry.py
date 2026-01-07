"""Poetry update plugin.

This plugin updates Poetry itself to the latest version.

Official documentation:
- Poetry: https://python-poetry.org/
- Self update: https://python-poetry.org/docs/cli/#self-update

Update mechanism:
- poetry self update - Updates Poetry to the latest version
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


class PoetryPlugin(BasePlugin):
    """Plugin for updating Poetry."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "poetry"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "poetry"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Poetry dependency manager"

    def is_available(self) -> bool:
        """Check if Poetry is installed."""
        return shutil.which("poetry") is not None

    async def check_available(self) -> bool:
        """Check if Poetry is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed Poetry version.

        Returns:
            Version string or None if Poetry is not installed.
        """
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["poetry", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output like "Poetry (version 1.8.0)"
                output = result.stdout.strip()
                if "version" in output.lower():
                    # Extract version number
                    parts = output.split()
                    for i, part in enumerate(parts):
                        if part.lower() == "version" and i + 1 < len(parts):
                            version = parts[i + 1].rstrip(")").rstrip(")")
                            return version
                # Alternative format: "Poetry version 1.8.0"
                if output.startswith("Poetry"):
                    parts = output.split()
                    if len(parts) >= 3:
                        return parts[-1].rstrip(")")
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

        # Check for successful update
        if "updating" in output_lower and "->" in output:
            return 1

        # Check for already up-to-date
        if "already" in output_lower and "latest" in output_lower:
            return 0

        if "up to date" in output_lower:
            return 0

        # Check for successful update message
        if "updated" in output_lower:
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Poetry update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["poetry", "--version"]
        return ["poetry", "self", "update"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Poetry update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Poetry is installed
        if not self.is_available():
            return "Poetry not installed, skipping update", None

        local_version = self.get_local_version()
        output_lines.append(f"Current Poetry version: {local_version}")
        output_lines.append("Updating Poetry...")

        # Run the update command
        return_code, stdout, stderr = await self._run_command(
            ["poetry", "self", "update"],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Poetry update with streaming output.

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

        # Check if Poetry is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Poetry not installed, skipping update",
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
            line=f"Current Poetry version: {local_version}",
            stream="stdout",
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Poetry...",
            stream="stdout",
        )

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        async for event in self._run_command_streaming(
            ["poetry", "self", "update"],
            timeout=config.timeout_seconds,
            sudo=False,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            yield event
