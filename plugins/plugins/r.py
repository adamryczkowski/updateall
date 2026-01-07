"""R packages plugin for CRAN package updates."""

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


class RPlugin(BasePlugin):
    """Plugin for R package manager (CRAN).

    Updates R packages installed in the user's R library using the
    update.packages() function from CRAN (Comprehensive R Archive Network).

    Executes:
    1. Creates user library directory if it doesn't exist
    2. Runs update.packages() with ask=FALSE and checkBuilt=TRUE

    Best practices implemented:
    - Uses checkBuilt=TRUE to rebuild packages built with older R versions
    - Uses user library (R_LIBS_USER) to avoid permission issues
    - Uses cloud.r-project.org mirror for automatic redirection to nearest CRAN mirror
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "r"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "Rscript"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "R packages from CRAN"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs R package updates, showing live output
        in the terminal.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            # In dry-run mode, just list outdated packages
            r_code = (
                "old <- old.packages(repos='https://cloud.r-project.org'); "
                "if (!is.null(old)) print(old[, c('Package', 'Installed', 'ReposVer')]) "
                "else cat('All packages are up to date\\n')"
            )
            return ["Rscript", "-e", r_code]

        # Create user library and update packages
        r_code = (
            "dir.create(path = Sys.getenv('R_LIBS_USER'), showWarnings = FALSE, recursive = TRUE); "
            "update.packages(ask = FALSE, checkBuilt = TRUE, "
            "lib = Sys.getenv('R_LIBS_USER'), repos = 'https://cloud.r-project.org')"
        )
        return ["Rscript", "-e", r_code]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute R package update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        output_parts: list[str] = []

        # Step 1: Create user library directory
        return_code, stdout, stderr = await self._run_command(
            [
                "Rscript",
                "-e",
                "dir.create(path = Sys.getenv('R_LIBS_USER'), "
                "showWarnings = FALSE, recursive = TRUE)",
            ],
            timeout=30,
            sudo=False,
        )

        output_parts.append("=== Creating R user library ===")
        if stdout.strip():
            output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"Failed to create R user library: {stderr}"

        # Step 2: Update packages
        return_code, stdout, stderr = await self._run_command(
            [
                "Rscript",
                "-e",
                "update.packages(ask = FALSE, checkBuilt = TRUE, "
                "lib = Sys.getenv('R_LIBS_USER'), repos = 'https://cloud.r-project.org')",
            ],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output_parts.append("\n=== Updating R packages ===")
        output_parts.append(stdout)

        if return_code != 0:
            # Check if it's just a warning about no packages to update
            if "no packages" in stderr.lower() or "up-to-date" in stdout.lower():
                return "\n".join(output_parts), None
            return "\n".join(output_parts), f"R package update failed: {stderr}"

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from R output.

        Looks for patterns like:
        - "installing source package 'packagename'"
        - "package 'packagename' successfully unpacked"
        - "downloaded X.X MB"

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "installing *source* package" or "installing *binary* package" mentions
        installing_count = len(
            re.findall(r"installing\s+(?:source|binary)\s+package", output, re.IGNORECASE)
        )

        if installing_count > 0:
            return installing_count

        # Fallback: count "successfully unpacked" mentions
        unpacked_count = len(re.findall(r"successfully unpacked", output, re.IGNORECASE))

        return unpacked_count

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute R package update with streaming output.

        This method provides real-time output during R package operations.

        Yields:
            StreamEvent objects as R executes.
        """
        from core.models import PluginConfig

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        # Step 1: Create user library directory
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== Creating R user library ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            [
                "Rscript",
                "-e",
                "dir.create(path = Sys.getenv('R_LIBS_USER'), "
                "showWarnings = FALSE, recursive = TRUE)",
            ],
            timeout=30,
            sudo=False,
            phase=Phase.EXECUTE,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            if isinstance(event, CompletionEvent):
                if not event.success:
                    error_msg = event.error_message or "Failed to create R user library"
                    yield CompletionEvent(
                        event_type=EventType.COMPLETION,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        success=False,
                        exit_code=event.exit_code,
                        error_message=error_msg,
                    )
                    return
                continue

            yield event

        # Step 2: Update packages
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== Updating R packages ===",
            stream="stdout",
        )

        async for event in self._run_command_streaming(
            [
                "Rscript",
                "-e",
                "update.packages(ask = FALSE, checkBuilt = TRUE, "
                "lib = Sys.getenv('R_LIBS_USER'), repos = 'https://cloud.r-project.org')",
            ],
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
                    # Check if it's just a "no packages to update" situation
                    if "no packages" in output_str.lower() or "up-to-date" in output_str.lower():
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
