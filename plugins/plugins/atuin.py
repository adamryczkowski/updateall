"""Atuin shell history sync plugin."""

from __future__ import annotations

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


class AtuinPlugin(BasePlugin):
    """Plugin for Atuin shell history synchronization.

    Atuin is a shell history tool that syncs history across machines.
    This plugin runs `atuin sync` to synchronize shell history with
    the Atuin server (either self-hosted or api.atuin.sh).

    The sync is encrypted end-to-end, so the server operator cannot
    see your command history.

    Executes:
    1. atuin sync - synchronize shell history with the server

    Note: This is a sync operation, not a traditional package update.
    It ensures your shell history is backed up and synchronized across
    all your machines.
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "atuin"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "atuin"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Atuin shell history sync"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs atuin sync, showing live output
        in the terminal.

        Args:
            dry_run: If True, return a command that simulates the sync.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            # In dry-run mode, just show status
            return ["atuin", "status"]
        return ["atuin", "sync"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute atuin sync.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["atuin", "sync"],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output = f"=== atuin sync ===\n{stdout}"

        if return_code != 0:
            # Check for common non-error situations
            if "already up to date" in stdout.lower() or "nothing to sync" in stdout.lower():
                return output, None
            return output, f"atuin sync failed: {stderr}"

        return output, None

    def _count_updated_packages(self, _output: str) -> int:
        """Count synced items from atuin output.

        Atuin doesn't report package counts in the traditional sense,
        but we can try to count synced history entries if reported.

        Args:
            _output: Command output (unused - atuin sync doesn't report counts).

        Returns:
            Number of items synced (0 - sync operation, not package update).
        """
        # Atuin sync doesn't typically report counts in a parseable format
        # Return 0 as this is a sync operation, not a package update
        return 0

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute atuin sync with streaming output.

        This method provides real-time output during atuin sync.

        Yields:
            StreamEvent objects as atuin executes.
        """
        from core.models import PluginConfig

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== atuin sync ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            ["atuin", "sync"],
            timeout=config.timeout_seconds,
            sudo=False,
            phase=Phase.EXECUTE,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            if isinstance(event, CompletionEvent):
                success = event.success
                if not success:
                    output_str = "\n".join(collected_output)
                    # Check for "already up to date" situations
                    if (
                        "already up to date" in output_str.lower()
                        or "nothing to sync" in output_str.lower()
                    ):
                        success = True

                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=success,
                    exit_code=0 if success else event.exit_code,
                    packages_updated=0,  # Sync operation, not package update
                    error_message=None if success else event.error_message,
                )
                return

            yield event
