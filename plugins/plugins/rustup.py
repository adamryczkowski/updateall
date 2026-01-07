"""Rustup (Rust toolchain) manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class RustupPlugin(BasePlugin):
    """Plugin for Rustup toolchain manager (Rust).

    Executes:
    1. rustup update - update all installed toolchains
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "rustup"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "rustup"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Rust toolchain manager (rustup)"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update Rust toolchains.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["rustup", "check"],
                    description="Check for Rust toolchain updates (dry run)",
                    sudo=False,
                )
            ]
        return [
            UpdateCommand(
                cmd=["rustup", "update"],
                description="Update Rust toolchains",
                sudo=False,
                success_patterns=("unchanged", "up to date"),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute rustup update (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["rustup", "update"],
            timeout=config.timeout_seconds,
            sudo=False,  # rustup runs as user
        )

        output = f"=== rustup update ===\n{stdout}"

        if return_code != 0:
            # Check for "already up to date" message
            if "unchanged" in stdout.lower() or "up to date" in stdout.lower():
                return output, None
            return output, f"rustup update failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated toolchains from rustup output.

        Looks for patterns like:
        - "stable-x86_64-unknown-linux-gnu updated"
        - "info: downloading component"
        - Lines with version changes (1.70.0 -> 1.71.0)

        Args:
            output: Command output.

        Returns:
            Number of toolchains/components updated.
        """
        # Count "updated" toolchains
        updated_count = len(re.findall(r"\S+-\S+-\S+-\S+\s+updated", output, re.IGNORECASE))

        if updated_count == 0:
            # Count version change patterns
            updated_count = len(re.findall(r"\d+\.\d+\.\d+\s*->\s*\d+\.\d+\.\d+", output))

        if updated_count == 0:
            # Count "installing component" lines
            updated_count = len(re.findall(r"installing component", output, re.IGNORECASE))

        return updated_count
