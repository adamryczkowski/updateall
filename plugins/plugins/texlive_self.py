"""TeX Live Manager (tlmgr) self-update plugin.

This plugin updates tlmgr itself using tlmgr update --self.

Official documentation:
- TeX Live: https://www.tug.org/texlive/
- tlmgr: https://www.tug.org/texlive/tlmgr.html

Note: This plugin should run before texlive-packages to ensure tlmgr
is up to date before updating packages.
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


class TexliveSelfPlugin(BasePlugin):
    """Plugin for updating tlmgr itself."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "texlive-self"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "tlmgr"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update TeX Live Manager (tlmgr) itself"

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
        """Count updated items from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of items updated.
        """
        output_lower = output.lower()

        # Check for tlmgr update
        if "updated" in output_lower:
            return 1

        # Check for no updates needed
        if "up to date" in output_lower or "no updates" in output_lower:
            return 0

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for tlmgr self-update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["tlmgr", "--version"]
        return ["sudo", "tlmgr", "update", "--self"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the tlmgr self-update.

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
        output_lines.append(f"Current tlmgr version: {local_version}")

        # Update tlmgr itself
        output_lines.append("Updating tlmgr...")
        return_code, stdout, stderr = await self._run_command(
            ["tlmgr", "update", "--self"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        if return_code != 0:
            output_lines.append(f"tlmgr self-update failed: {stderr}")
            return "\n".join(output_lines), f"tlmgr self-update failed: {stderr}"

        output_lines.append(stdout.strip() if stdout.strip() else "tlmgr is up to date")
        output_lines.append("tlmgr self-update completed successfully")
        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute tlmgr self-update with streaming output.

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

        local_version = self.get_local_version()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Current tlmgr version: {local_version}",
            stream="stdout",
        )

        # Update tlmgr itself
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating tlmgr...",
            stream="stdout",
        )

        collected_output: list[str] = []
        final_success = True
        final_exit_code = 0

        async for event in self._run_command_streaming(
            ["tlmgr", "update", "--self"],
            timeout=config.timeout_seconds,
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
