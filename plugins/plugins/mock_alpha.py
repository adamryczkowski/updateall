"""Mock Alpha plugin for debugging the interactive tabbed UI.

This plugin simulates a long-running update task with three phases:
- CHECK: Simulates checking for updates (light CPU, minimal download)
- DOWNLOAD: Simulates downloading packages (heavy download, light CPU)
- EXECUTE: Simulates installing packages (heavy CPU, minimal download)

Uses external shell scripts that generate REAL CPU, memory, and network load
to test update-all's resource estimation capabilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.streaming import Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MockAlphaPlugin(BasePlugin):
    """Mock Alpha plugin for debugging interactive mode.

    Simulates a multi-phase update with REAL download and CPU load.
    Uses external shell scripts that spawn child processes.
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "mock-alpha"

    @property
    def command(self) -> str:
        """Return the main command (always available for mock)."""
        return "bash"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Mock Alpha - Multi-phase update with real CPU/network load (debugging)"

    async def check_available(self) -> bool:
        """Mock is always available."""
        return True

    def _get_scripts_dir(self) -> Path:
        """Get the path to the scripts directory."""
        return Path(__file__).parent / "scripts"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a bash command that runs all three phase scripts sequentially.
        This is used when phase-by-phase execution is not enabled.

        Args:
            dry_run: If True, return a command that simulates faster.

        Returns:
            Command and arguments as a list.
        """
        scripts_dir = self._get_scripts_dir()
        dry_run_arg = "true" if dry_run else "false"

        # Run all three phases sequentially
        script = f"""
{scripts_dir}/mock_check.sh mock-alpha {dry_run_arg}
{scripts_dir}/mock_download.sh mock-alpha {dry_run_arg}
{scripts_dir}/mock_execute.sh mock-alpha {dry_run_arg}
"""
        return ["/bin/bash", "-c", script]

    def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
        """Get commands for each execution phase.

        Mock Alpha phases use external scripts that generate real load:
        - CHECK: Real network requests + openssl CPU work
        - DOWNLOAD: Real downloads from httpbin.org
        - EXECUTE: Real CPU load via openssl + memory allocation

        Args:
            dry_run: If True, return commands that run faster.

        Returns:
            Dict mapping Phase to command list.
        """
        scripts_dir = self._get_scripts_dir()
        dry_run_arg = "true" if dry_run else "false"

        return {
            Phase.CHECK: [
                str(scripts_dir / "mock_check.sh"),
                "mock-alpha",
                dry_run_arg,
            ],
            Phase.DOWNLOAD: [
                str(scripts_dir / "mock_download.sh"),
                "mock-alpha",
                dry_run_arg,
            ],
            Phase.EXECUTE: [
                str(scripts_dir / "mock_execute.sh"),
                "mock-alpha",
                dry_run_arg,
            ],
        }

    async def _execute_update(
        self,
        config: PluginConfig,  # noqa: ARG002
    ) -> tuple[str, str | None]:
        """Execute the mock update.

        Args:
            config: Plugin configuration (unused in mock).

        Returns:
            Tuple of (output, error_message).
        """
        # For non-interactive mode, just return a simple message
        return (
            "Mock Alpha plugin executed successfully.\n"
            "This is a debugging plugin for testing the interactive UI.\n"
            "Use --interactive mode to see the full simulation with real load.",
            None,
        )

    def _count_updated_packages(
        self,
        output: str,  # noqa: ARG002
    ) -> int:
        """Count the number of updated packages from command output.

        Args:
            output: Command output to parse (unused in mock).

        Returns:
            Number of packages updated (simulated).
        """
        # Return a simulated count
        return 12
