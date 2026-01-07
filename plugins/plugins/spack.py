"""Spack update plugin.

This plugin updates Spack package manager by pulling the latest changes from git.

Official documentation:
- Spack: https://spack.io/
- Getting Started: https://spack.readthedocs.io/en/latest/getting_started.html

Update mechanism:
- Spack is installed via git clone, so updates are done via git pull
- The plugin checks common installation locations: /opt/spack, ~/spack, ~/tmp/spack
- Uses git pull --ff-only to update
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class SpackPlugin(BasePlugin):
    """Plugin for updating Spack package manager."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "spack"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "spack"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Spack package manager (HPC package manager)"

    def _get_spack_dirs(self) -> list[Path]:
        """Get list of potential Spack installation directories.

        Returns:
            List of paths where Spack might be installed.
        """
        home = Path.home()
        return [
            Path("/opt/spack"),
            home / "spack",
            home / "tmp" / "spack",
        ]

    def _find_spack_installation(self) -> Path | None:
        """Find the first valid Spack installation.

        Returns:
            Path to Spack installation or None if not found.
        """
        for spack_dir in self._get_spack_dirs():
            if spack_dir.is_dir() and (spack_dir / ".git").is_dir():
                return spack_dir
        return None

    def is_available(self) -> bool:
        """Check if Spack is installed and git is available."""
        # Need git to update Spack
        if shutil.which("git") is None:
            return False
        # Check if any Spack installation exists
        return self._find_spack_installation() is not None

    async def check_available(self) -> bool:
        """Check if Spack is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed Spack version.

        Returns:
            Version string or None if Spack is not installed.
        """
        spack_dir = self._find_spack_installation()
        if spack_dir is None:
            return None

        spack_bin = spack_dir / "bin" / "spack"
        if not spack_bin.exists():
            return None

        try:
            result = subprocess.run(
                [str(spack_bin), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Output is like "spack 0.21.0" or just "0.21.0"
                output = result.stdout.strip()
                if output.startswith("spack "):
                    return output[6:]
                return output
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _get_git_commit(self, spack_dir: Path) -> str | None:
        """Get the current git commit hash.

        Args:
            spack_dir: Path to Spack installation.

        Returns:
            Short commit hash or None on error.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(spack_dir),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of directories updated (1 if any updates, 0 otherwise).
        """
        output_lower = output.lower()

        # Check for successful update
        if "updating" in output_lower or "fast-forward" in output_lower:
            return 1

        # Check for already up-to-date
        if "already up to date" in output_lower or "already up-to-date" in output_lower:
            return 0

        # Check for files changed pattern
        if "files changed" in output_lower or "insertions" in output_lower:
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Spack update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        spack_dir = self._find_spack_installation()
        if spack_dir is None:
            return ["echo", "Spack not found"]

        if dry_run:
            return ["git", "-C", str(spack_dir), "fetch", "--dry-run"]
        return ["git", "-C", str(spack_dir), "pull", "--ff-only"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Spack update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if git is available
        if shutil.which("git") is None:
            return "Git not installed, skipping Spack update", None

        # Find all Spack installations and update them
        updated_any = False
        for spack_dir in self._get_spack_dirs():
            if not spack_dir.is_dir() or not (spack_dir / ".git").is_dir():
                continue

            output_lines.append(f"Updating Spack in {spack_dir}...")
            before_commit = self._get_git_commit(spack_dir)

            # Run git pull
            return_code, stdout, stderr = await self._run_command(
                ["git", "pull", "--ff-only"],
                timeout=config.timeout_seconds,
                sudo=False,
                cwd=str(spack_dir),
            )

            if return_code != 0:
                output_lines.append(f"  Failed to update: {stderr}")
                continue

            output_lines.append(f"  {stdout.strip()}")
            after_commit = self._get_git_commit(spack_dir)

            if before_commit and after_commit and before_commit != after_commit:
                output_lines.append(f"  Updated from {before_commit} to {after_commit}")
                updated_any = True

        if not output_lines:
            return "No Spack installations found", None

        if not updated_any:
            output_lines.append("All Spack installations are up to date")

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Spack update with streaming output.

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

        # Check if git is available
        if shutil.which("git") is None:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Git not installed, skipping Spack update",
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
        total_updated = 0
        found_any = False

        for spack_dir in self._get_spack_dirs():
            if not spack_dir.is_dir() or not (spack_dir / ".git").is_dir():
                continue

            found_any = True
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Updating Spack in {spack_dir}...",
                stream="stdout",
            )

            before_commit = self._get_git_commit(spack_dir)
            collected_output: list[str] = []

            async for event in self._run_command_streaming(
                ["git", "pull", "--ff-only"],
                timeout=config.timeout_seconds,
                sudo=False,
                cwd=str(spack_dir),
            ):
                if isinstance(event, OutputEvent):
                    collected_output.append(event.line)
                yield event

            after_commit = self._get_git_commit(spack_dir)
            if before_commit and after_commit and before_commit != after_commit:
                total_updated += 1
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Updated from {before_commit} to {after_commit}",
                    stream="stdout",
                )

        if not found_any:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="No Spack installations found",
                stream="stdout",
            )

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
            packages_updated=total_updated,
        )
