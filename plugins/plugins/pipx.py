"""Pipx package manager plugin."""

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


class PipxPlugin(BasePlugin):
    """Plugin for pipx Python application manager.

    Executes:
    1. pipx upgrade-all - upgrade all installed applications
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "pipx"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "pipx"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Python application installer (pipx)"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute pipx upgrade-all.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["pipx", "upgrade-all"],
            timeout=config.timeout_seconds,
            sudo=False,  # pipx runs as user
        )

        output = f"=== pipx upgrade-all ===\n{stdout}"

        if return_code != 0:
            # pipx returns non-zero if nothing to upgrade, check stderr
            if "No packages to upgrade" in stderr or "already at latest" in stdout:
                return output, None
            return output, f"pipx upgrade-all failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from pipx output.

        Looks for patterns like:
        - "upgraded package-name from X to Y"
        - "Package 'name' upgraded"

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "upgraded" mentions
        upgraded_count = len(re.findall(r"upgraded\s+\S+\s+from", output, re.IGNORECASE))

        if upgraded_count == 0:
            # Alternative pattern
            upgraded_count = len(re.findall(r"Package\s+'\S+'\s+upgraded", output, re.IGNORECASE))

        return upgraded_count

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute pipx upgrade-all with streaming output.

        This method provides real-time output during pipx operations.

        Yields:
            StreamEvent objects as pipx executes.
        """
        from core.models import PluginConfig

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== pipx upgrade-all ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            ["pipx", "upgrade-all"],
            timeout=config.timeout_seconds,
            sudo=False,
            phase=Phase.EXECUTE,
        ):
            # Collect output for package counting
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            # Check for completion event
            if isinstance(event, CompletionEvent):
                # pipx returns non-zero if nothing to upgrade
                success = event.success
                if not success:
                    output_str = "\n".join(collected_output)
                    if "No packages to upgrade" in output_str or "already at latest" in output_str:
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
