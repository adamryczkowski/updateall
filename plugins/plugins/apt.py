"""APT package manager plugin."""

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


class AptPlugin(BasePlugin):
    """Plugin for APT package manager (Debian/Ubuntu).

    Executes:
    1. sudo apt update - refresh package lists
    2. sudo apt upgrade -y - upgrade all packages
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "apt"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "apt"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Debian/Ubuntu APT package manager"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute apt update and upgrade.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        output_parts: list[str] = []

        # Step 1: apt update
        return_code, stdout, stderr = await self._run_command(
            ["apt", "update"],
            timeout=config.timeout_seconds // 2,  # Use half timeout for update
            sudo=True,
        )

        output_parts.append("=== apt update ===")
        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"apt update failed: {stderr}"

        # Step 2: apt upgrade
        return_code, stdout, stderr = await self._run_command(
            ["apt", "upgrade", "-y"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        output_parts.append("\n=== apt upgrade ===")
        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"apt upgrade failed: {stderr}"

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from apt output.

        Looks for patterns like:
        - "X upgraded, Y newly installed"
        - "Unpacking package-name"

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Try to find the summary line
        match = re.search(r"(\d+)\s+upgraded", output)
        if match:
            return int(match.group(1))

        # Fallback: count "Unpacking" lines
        unpacking_count = len(re.findall(r"^Unpacking\s+", output, re.MULTILINE))
        return unpacking_count

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute apt update and upgrade with streaming output.

        This method provides real-time output during apt operations.

        Yields:
            StreamEvent objects as apt executes.
        """
        from core.models import PluginConfig

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []
        final_success = True
        final_error: str | None = None

        # Step 1: apt update
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== apt update ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            ["apt", "update"],
            timeout=config.timeout_seconds // 2,
            sudo=True,
            phase=Phase.EXECUTE,
        ):
            # Collect output for package counting
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            # Check for completion event from apt update
            if isinstance(event, CompletionEvent):
                if not event.success:
                    final_success = False
                    final_error = event.error_message or "apt update failed"
                    # Yield the failure and stop
                    yield CompletionEvent(
                        event_type=EventType.COMPLETION,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        success=False,
                        exit_code=event.exit_code,
                        error_message=final_error,
                    )
                    return
                # Don't yield the intermediate completion event
                continue

            yield event

        # Step 2: apt upgrade
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== apt upgrade ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            ["apt", "upgrade", "-y"],
            timeout=config.timeout_seconds,
            sudo=True,
            phase=Phase.EXECUTE,
        ):
            # Collect output for package counting
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            # Check for completion event from apt upgrade
            if isinstance(event, CompletionEvent):
                if not event.success:
                    final_success = False
                    final_error = event.error_message or "apt upgrade failed"
                # This is the final completion - yield it with package count
                packages_updated = self._count_updated_packages("\n".join(collected_output))
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=final_success,
                    exit_code=event.exit_code if not final_success else 0,
                    packages_updated=packages_updated,
                    error_message=final_error,
                )
                return

            yield event
