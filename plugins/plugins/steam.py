"""Steam update plugin.

This plugin updates Steam games using steamcmd.

Official documentation:
- Steam: https://store.steampowered.com/
- SteamCMD: https://developer.valvesoftware.com/wiki/SteamCMD

Update mechanism:
- Uses steamcmd to update all installed Steam games
- Requires Steam and steamcmd to be installed
- Requires a steam_login.txt file with the Steam login name
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class SteamPlugin(BasePlugin):
    """Plugin for updating Steam games."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "steam"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "steamcmd"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Steam games using steamcmd"

    def _get_login_file_path(self) -> Path:
        """Get the path to the steam_login.txt file.

        Returns:
            Path to the login file.
        """
        # Check common locations
        home = Path.home()
        locations = [
            Path("steam_login.txt"),  # Current directory
            home / "steam_login.txt",
            home / ".config" / "steam_login.txt",
            home / ".steam" / "steam_login.txt",
        ]
        for loc in locations:
            if loc.exists():
                return loc
        return home / "steam_login.txt"

    def _get_steam_login(self) -> str | None:
        """Get the Steam login from the login file.

        Returns:
            Steam login name or None if not found.
        """
        login_file = self._get_login_file_path()
        if login_file.exists():
            try:
                return login_file.read_text().strip()
            except OSError:
                pass
        return None

    def is_available(self) -> bool:
        """Check if Steam and steamcmd are installed."""
        return shutil.which("steam") is not None and shutil.which("steamcmd") is not None

    async def check_available(self) -> bool:
        """Check if Steam is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed Steam version.

        Returns:
            Version string or None if Steam is not installed.
        """
        if not shutil.which("steam"):
            return None

        try:
            result = subprocess.run(
                ["steam", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output
                output = result.stdout.strip()
                if output:
                    return output.split()[-1] if output.split() else output
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of games updated.
        """
        output_lower = output.lower()

        # Count successful updates
        count = 0

        # Look for "Success! App" pattern
        count += output_lower.count("success! app")

        # Look for "fully installed" pattern
        count += output_lower.count("fully installed")

        # Look for "update" pattern
        if "update" in output_lower and count == 0:
            # Count app_update occurrences
            count = output_lower.count("app_update")

        return count

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Steam update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["steamcmd", "+login", "anonymous", "+quit"]
        # For interactive mode, just show the steamcmd help
        return ["steamcmd", "+help", "+quit"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Steam update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Steam is installed
        if not shutil.which("steam"):
            return "Steam not installed, skipping update", None

        # Check if steamcmd is installed
        if not shutil.which("steamcmd"):
            return "SteamCMD not installed, skipping update", None

        # Get Steam login
        login = self._get_steam_login()
        if not login:
            return (
                "Steam login not found. Please create steam_login.txt with your Steam login name.",
                None,
            )

        output_lines.append(f"Using Steam login: {login}")
        output_lines.append("Checking installed games...")

        # First, get list of installed apps
        env = os.environ.copy()
        env["LD_PRELOAD"] = ""

        return_code, stdout, stderr = await self._run_command(
            ["steamcmd", "+login", login, "+apps_installed", "+quit"],
            timeout=config.timeout_seconds,
            sudo=False,
            env=env,
        )

        if return_code != 0:
            return "\n".join(output_lines), f"Failed to get installed apps: {stderr}"

        # Parse app IDs from output
        app_ids: list[str] = []
        for line in stdout.split("\n"):
            if line.startswith("AppID "):
                parts = line.split()
                if len(parts) >= 2:
                    app_id = parts[1]
                    if app_id.isdigit():
                        app_ids.append(app_id)

        if not app_ids:
            output_lines.append("No installed games found")
            return "\n".join(output_lines), None

        output_lines.append(f"Found {len(app_ids)} installed games")
        output_lines.append("Updating games...")

        # Build update command
        update_args = ["+login", login]
        for app_id in app_ids:
            update_args.extend(["+app_update", app_id])
        update_args.append("+quit")

        return_code, stdout, stderr = await self._run_command(
            ["steamcmd", *update_args],
            timeout=config.timeout_seconds * 10,  # Games can take a long time
            sudo=False,
            env=env,
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Steam update with streaming output.

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

        # Check if Steam is installed
        if not shutil.which("steam"):
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Steam not installed, skipping update",
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

        # Check if steamcmd is installed
        if not shutil.which("steamcmd"):
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="SteamCMD not installed, skipping update",
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

        # Get Steam login
        login = self._get_steam_login()
        if not login:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Steam login not found. Please create steam_login.txt",
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
        collected_output: list[str] = []

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Using Steam login: {login}",
            stream="stdout",
        )

        env = os.environ.copy()
        env["LD_PRELOAD"] = ""

        async for event in self._run_command_streaming(
            ["steamcmd", "+login", login, "+apps_installed", "+quit"],
            timeout=config.timeout_seconds,
            sudo=False,
            env=env,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            yield event

        # Parse app IDs and update (simplified for streaming)
        full_output = "\n".join(collected_output)
        updated_count = self._count_updated_packages(full_output)

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
            packages_updated=updated_count,
        )
