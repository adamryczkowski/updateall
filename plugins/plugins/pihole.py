"""Pi-hole update plugin.

This plugin updates Pi-hole, a network-wide ad blocker.

Official documentation:
- Pi-hole: https://pi-hole.net/
- Update command: https://docs.pi-hole.net/main/update/

Update mechanism:
- pihole updatePihole - Updates Pi-hole to the latest version
- pihole -up - Alternative update command
"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import TYPE_CHECKING

from core.models import UpdateEstimate
from core.version import compare_versions
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class PiholePlugin(BasePlugin):
    """Plugin for updating Pi-hole."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "pihole"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "pihole"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Pi-hole network-wide ad blocker"

    def is_available(self) -> bool:
        """Check if Pi-hole is installed."""
        return shutil.which("pihole") is not None

    async def check_available(self) -> bool:
        """Check if Pi-hole is available for updates."""
        return self.is_available()

    # =========================================================================
    # Version Checking Protocol Implementation
    # =========================================================================

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Pi-hole version.

        Returns:
            Version string (e.g., "5.17.1") or None if not installed.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "pihole",
                "-v",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                output = stdout.decode()
                # Parse version from output (e.g., "Pi-hole version is v5.17.1")
                for line in output.split("\n"):
                    if "pi-hole" in line.lower() and "version" in line.lower():
                        match = re.search(r"v(\d+\.\d+(?:\.\d+)?)", line)
                        if match:
                            return match.group(1)
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available Pi-hole version.

        Returns:
            Version string or None if cannot determine.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "pihole",
                "-v",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                output = stdout.decode()
                # Parse latest version from output (e.g., "Latest: v5.17.2")
                for line in output.split("\n"):
                    if "latest" in line.lower():
                        match = re.search(
                            r"latest[:\s]+v?(\d+\.\d+(?:\.\d+)?)", line, re.IGNORECASE
                        )
                        if match:
                            return match.group(1)
        except (TimeoutError, OSError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Pi-hole needs an update.

        Returns:
            True if update available, False if up-to-date, None if cannot determine.
        """
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed and available:
            return compare_versions(installed, available) < 0

        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size for Pi-hole update.

        Pi-hole updates are typically small (scripts and configs).

        Returns:
            UpdateEstimate or None if no update needed.
        """
        needs = await self.needs_update()
        if not needs:
            return None

        # Pi-hole updates are relatively small
        return UpdateEstimate(
            download_bytes=50 * 1024 * 1024,  # ~50MB estimate
            package_count=1,
            packages=["pihole"],
            estimated_seconds=60,  # 1 minute typical
            confidence=0.5,  # Medium confidence
        )

    # =========================================================================
    # Legacy API (for backward compatibility)
    # =========================================================================

    def get_local_version(self) -> str | None:
        """Get the currently installed Pi-hole version (sync version).

        Deprecated: Use get_installed_version() instead.

        Returns:
            Version string or None if Pi-hole is not installed.
        """
        import subprocess

        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["pihole", "-v"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output
                for line in result.stdout.split("\n"):
                    if "Pi-hole" in line and "v" in line:
                        # Extract version like "v5.17.1"
                        parts = line.split()
                        for part in parts:
                            if part.startswith("v"):
                                return part
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of components updated.
        """
        output_lower = output.lower()

        # Check for successful update
        if "update complete" in output_lower or "updated" in output_lower:
            return 1

        # Check for already up-to-date
        if "up to date" in output_lower or "already" in output_lower:
            return 0

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Pi-hole update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["pihole", "-v"]
        return ["pihole", "updatePihole"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Pi-hole update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Pi-hole is installed
        if not self.is_available():
            return "Pi-hole not installed, skipping update", None

        local_version = self.get_local_version()
        output_lines.append(f"Current Pi-hole version: {local_version}")
        output_lines.append("Updating Pi-hole...")

        # Run the update command
        return_code, stdout, stderr = await self._run_command(
            ["pihole", "updatePihole"],
            timeout=config.timeout_seconds,
            sudo=False,  # pihole command handles sudo internally
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Pi-hole update with streaming output.

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

        # Check if Pi-hole is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Pi-hole not installed, skipping update",
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

        local_version = self.get_local_version()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Current Pi-hole version: {local_version}",
            stream="stdout",
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Pi-hole...",
            stream="stdout",
        )

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        async for event in self._run_command_streaming(
            ["pihole", "updatePihole"],
            timeout=config.timeout_seconds,
            sudo=False,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            yield event
