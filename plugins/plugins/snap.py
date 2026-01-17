"""Snap package manager plugin.

This plugin updates Snap packages on Ubuntu and other distributions
that support the Snap package format.

Official documentation:
- Snapcraft: https://snapcraft.io/
- snap command: https://snapcraft.io/docs/getting-started
- Managing updates: https://snapcraft.io/docs/keeping-snaps-up-to-date

Update mechanism:
- snap refresh: Refreshes all installed snaps to their latest versions
- snap remove --revision: Removes old disabled snap revisions to free disk space

Note: Requires sudo privileges for refresh and remove operations.

References for cleanup approach:
- https://superuser.com/questions/1310825/how-to-remove-old-version-of-installed-snaps
- https://itsfoss.com/clean-snap-packages/
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from core.models import UpdateCommand
from core.mutex import StandardMutexes
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

logger = structlog.get_logger(__name__)


class SnapPlugin(BasePlugin):
    """Plugin for Snap package manager (Ubuntu/Canonical).

    Executes:
    1. sudo snap refresh - refresh all snaps
    2. Remove old disabled snap revisions to free disk space
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "snap"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "snap"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Canonical Snap package manager"

    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        Snap requires sudo for refresh and remove operations.
        """
        return ["/usr/bin/snap"]

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Return mutexes required for each execution phase.

        Snap requires exclusive access to the SNAP lock during execution.
        """
        return {
            Phase.EXECUTE: [StandardMutexes.SNAP_LOCK],
        }

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to refresh snaps.

        Note: This returns only the refresh command. The cleanup of old
        revisions is handled in _execute_update_streaming() because it
        requires parsing output and executing multiple commands dynamically.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["snap", "refresh", "--list"],
                    description="List available snap updates (dry run)",
                    sudo=False,
                )
            ]
        # Return empty list to use _execute_update_streaming() for full control
        return []

    async def _get_disabled_snap_revisions(self) -> list[tuple[str, str]]:
        """Get list of disabled snap revisions.

        Parses output of 'snap list --all' to find disabled revisions.
        Uses LANG=en_US.UTF-8 to ensure consistent "disabled" label.

        Returns:
            List of (snap_name, revision) tuples for disabled snaps.
        """
        log = logger.bind(plugin=self.name)

        # Set LANG to ensure consistent output parsing
        env = os.environ.copy()
        env["LANG"] = "en_US.UTF-8"

        return_code, stdout, stderr = await self._run_command(
            ["snap", "list", "--all"],
            timeout=60,
            sudo=False,
            env=env,
        )

        if return_code != 0:
            log.warning("snap_list_failed", stderr=stderr)
            return []

        disabled_snaps: list[tuple[str, str]] = []

        for line in stdout.splitlines():
            # Skip header line
            if line.startswith("Name") or not line.strip():
                continue

            # Parse line: Name Version Rev Tracking Publisher Notes
            # The "disabled" keyword appears in the Notes column
            if "disabled" in line.lower():
                parts = line.split()
                if len(parts) >= 3:
                    snap_name = parts[0]
                    revision = parts[2]
                    disabled_snaps.append((snap_name, revision))
                    log.debug("found_disabled_snap", name=snap_name, revision=revision)

        return disabled_snaps

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute snap refresh and cleanup old revisions with streaming.

        This method:
        1. Runs 'snap refresh' to update all snaps
        2. Finds and removes old disabled snap revisions

        Yields:
            StreamEvent objects as the update executes.
        """
        log = logger.bind(plugin=self.name)
        collected_output: list[str] = []
        final_success = True
        final_error: str | None = None
        packages_updated = 0

        # Step 1: Refresh all snaps
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [1/2] Refresh all snaps ===",
            stream="stdout",
        )

        log.debug("executing_snap_refresh")

        refresh_success = True
        async for event in self._run_command_streaming(
            ["snap", "refresh"],
            timeout=300,
            sudo=True,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
                yield event
            elif isinstance(event, CompletionEvent):
                # Check for success - "All snaps up to date" is also success
                if not event.success:
                    # Check if it's actually a success case
                    full_output = "\n".join(collected_output)
                    if "All snaps up to date" not in full_output:
                        refresh_success = False
                        final_error = event.error_message
            else:
                yield event

        if not refresh_success:
            log.warning("snap_refresh_failed", error=final_error)
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=final_error,
            )
            return

        # Count refreshed packages
        full_output = "\n".join(collected_output)
        packages_updated = self._count_updated_packages(full_output)

        # Step 2: Remove old disabled revisions
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="",
            stream="stdout",
        )
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [2/2] Remove old snap revisions ===",
            stream="stdout",
        )

        disabled_snaps = await self._get_disabled_snap_revisions()

        if not disabled_snaps:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="No old snap revisions to remove.",
                stream="stdout",
            )
        else:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Found {len(disabled_snaps)} old revision(s) to remove.",
                stream="stdout",
            )

            removed_count = 0
            for snap_name, revision in disabled_snaps:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Removing {snap_name} revision {revision}...",
                    stream="stdout",
                )

                log.debug("removing_snap_revision", name=snap_name, revision=revision)

                # Remove the specific revision
                return_code, _stdout, stderr = await self._run_command(
                    ["snap", "remove", snap_name, f"--revision={revision}"],
                    timeout=120,
                    sudo=True,
                )

                if return_code == 0:
                    removed_count += 1
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=f"  ✓ Removed {snap_name} revision {revision}",
                        stream="stdout",
                    )
                else:
                    # Log warning but continue with other revisions
                    log.warning(
                        "snap_remove_revision_failed",
                        name=snap_name,
                        revision=revision,
                        stderr=stderr,
                    )
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=f"  ✗ Failed to remove {snap_name} revision {revision}: {stderr.strip()}",
                        stream="stderr",
                    )

            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Removed {removed_count}/{len(disabled_snaps)} old revision(s).",
                stream="stdout",
            )

        # Emit final completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=final_success,
            exit_code=0 if final_success else 1,
            packages_updated=packages_updated,
            error_message=final_error,
        )

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute snap refresh and cleanup (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        output_parts: list[str] = []

        # Step 1: Refresh snaps
        return_code, stdout, stderr = await self._run_command(
            ["snap", "refresh"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        output_parts.append("=== snap refresh ===")
        output_parts.append(stdout)

        # snap returns non-zero if nothing to refresh (but "All snaps up to date" is success)
        if (
            return_code != 0
            and "All snaps up to date" not in stdout
            and "All snaps up to date" not in stderr
        ):
            return "\n".join(output_parts), f"snap refresh failed: {stderr}"

        # Step 2: Remove old disabled revisions
        output_parts.append("")
        output_parts.append("=== Remove old snap revisions ===")

        disabled_snaps = await self._get_disabled_snap_revisions()

        if not disabled_snaps:
            output_parts.append("No old snap revisions to remove.")
        else:
            output_parts.append(f"Found {len(disabled_snaps)} old revision(s) to remove.")
            removed_count = 0

            for snap_name, revision in disabled_snaps:
                return_code, stdout, stderr = await self._run_command(
                    ["snap", "remove", snap_name, f"--revision={revision}"],
                    timeout=120,
                    sudo=True,
                )

                if return_code == 0:
                    removed_count += 1
                    output_parts.append(f"  ✓ Removed {snap_name} revision {revision}")
                else:
                    output_parts.append(
                        f"  ✗ Failed to remove {snap_name} revision {revision}: {stderr.strip()}"
                    )

            output_parts.append(f"Removed {removed_count}/{len(disabled_snaps)} old revision(s).")

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from snap output.

        Looks for patterns like:
        - "name X refreshed"
        - Lines with version changes

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "refreshed" mentions
        refreshed_count = len(re.findall(r"\S+\s+\S+\s+refreshed", output, re.IGNORECASE))

        if refreshed_count == 0:
            # Alternative: count lines with arrow indicating version change
            refreshed_count = len(re.findall(r"→|->", output))

        return refreshed_count
