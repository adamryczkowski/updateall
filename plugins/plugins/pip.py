"""pip update plugin.

This plugin updates pip itself to the latest version.

Official documentation:
- pip: https://pip.pypa.io/
- Upgrading pip: https://pip.pypa.io/en/stable/installation/#upgrading-pip

Update mechanism:
- python -m pip install --upgrade pip - Updates pip to the latest version
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


class PipPlugin(BasePlugin):
    """Plugin for updating pip."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "pip"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "pip"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update pip package installer"

    def is_available(self) -> bool:
        """Check if pip is installed."""
        return shutil.which("pip") is not None or shutil.which("pip3") is not None

    async def check_available(self) -> bool:
        """Check if pip is available for updates."""
        return self.is_available()

    def _get_python_executable(self) -> str | None:
        """Get the Python executable to use for pip updates.

        Returns:
            Python executable path or None if not found.
        """
        # Prefer python3 over python
        python3 = shutil.which("python3")
        if python3:
            return python3
        python = shutil.which("python")
        if python:
            return python
        return None

    def get_local_version(self) -> str | None:
        """Get the currently installed pip version.

        Returns:
            Version string or None if pip is not installed.
        """
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["pip", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output like "pip 24.0 from /path/to/pip"
                parts = result.stdout.split()
                if len(parts) >= 2:
                    return parts[1]
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

        # Check for successful upgrade
        if "successfully installed" in output_lower:
            return 1

        # Check for already up-to-date
        if "requirement already satisfied" in output_lower:
            return 0

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for pip update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        python = self._get_python_executable()
        if not python:
            return ["pip", "--version"]

        if dry_run:
            return [python, "-m", "pip", "show", "pip"]
        return [python, "-m", "pip", "install", "--upgrade", "pip"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the pip update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if pip is installed
        if not self.is_available():
            return "pip not installed, skipping update", None

        python = self._get_python_executable()
        if not python:
            return "Python not found, cannot update pip", "Python not found"

        local_version = self.get_local_version()
        output_lines.append(f"Current pip version: {local_version}")
        output_lines.append("Updating pip...")

        # Run the update command
        return_code, stdout, stderr = await self._run_command(
            [python, "-m", "pip", "install", "--upgrade", "pip"],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute pip update with streaming output.

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

        # Check if pip is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="pip not installed, skipping update",
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

        python = self._get_python_executable()
        if not python:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Python not found, cannot update pip",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message="Python not found",
            )
            return

        local_version = self.get_local_version()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Current pip version: {local_version}",
            stream="stdout",
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating pip...",
            stream="stdout",
        )

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        async for event in self._run_command_streaming(
            [python, "-m", "pip", "install", "--upgrade", "pip"],
            timeout=config.timeout_seconds,
            sudo=False,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            yield event
