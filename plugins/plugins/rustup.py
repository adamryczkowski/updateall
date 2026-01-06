"""Rustup (Rust toolchain) manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

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

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute rustup update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["rustup", "update"],
            timeout=config.timeout,
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
