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

import asyncio
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from core.models import UpdateEstimate
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

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Spack version.

        This is the new async API method (Version Checking Protocol).

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
            process = await asyncio.create_subprocess_exec(
                str(spack_bin),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                # Output is like "spack 0.21.0" or just "0.21.0"
                output = stdout.decode().strip()
                if output.startswith("spack "):
                    return output[6:]
                return output
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the available Spack version from the remote repository.

        This is the new async API method (Version Checking Protocol).
        Uses git fetch to check for available updates.

        Returns:
            Remote commit hash or None if unable to fetch.
        """
        spack_dir = self._find_spack_installation()
        if spack_dir is None:
            return None

        try:
            # Fetch latest from remote
            process = await asyncio.create_subprocess_exec(
                "git",
                "fetch",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(spack_dir),
            )
            await asyncio.wait_for(process.communicate(), timeout=60)

            # Get remote HEAD commit
            process = await asyncio.create_subprocess_exec(
                "git",
                "rev-parse",
                "--short",
                "origin/HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(spack_dir),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                return stdout.decode().strip()
        except (TimeoutError, OSError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Spack needs to be updated.

        This is the new async API method (Version Checking Protocol).

        Returns:
            True if remote has newer commits than local,
            False if up-to-date, None if unable to determine.
        """
        spack_dir = self._find_spack_installation()
        if spack_dir is None:
            return None

        local = await self._get_git_commit_async(spack_dir)
        remote = await self.get_available_version()

        if not local or not remote:
            return None

        return local != remote

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Estimate download size and time for Spack update.

        This is the new async API method (Version Checking Protocol).
        Spack git updates are typically small.

        Returns:
            UpdateEstimate with download size, or None if no update needed.
        """
        if not await self.needs_update():
            return None

        remote_version = await self.get_available_version()
        if not remote_version:
            return None

        # Git updates are typically small (deltas)
        return UpdateEstimate(
            download_bytes=10_000_000,  # ~10MB estimate for git objects
            package_count=1,
            packages=[f"spack-{remote_version}"],
            estimated_seconds=60,
            confidence=0.4,  # Very approximate
        )

    async def _get_git_commit_async(self, spack_dir: Path) -> str | None:
        """Get the current git commit hash asynchronously.

        Args:
            spack_dir: Path to Spack installation.

        Returns:
            Short commit hash or None on error.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "rev-parse",
                "--short",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(spack_dir),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                return stdout.decode().strip()
        except (TimeoutError, OSError):
            pass
        return None

    # Backward compatibility aliases (deprecated)
    def get_local_version(self) -> str | None:
        """Get the currently installed Spack version.

        .. deprecated::
            Use :meth:`get_installed_version` instead.

        Returns:
            Version string or None if Spack is not installed.
        """
        warnings.warn(
            "get_local_version() is deprecated, use get_installed_version() instead",
            DeprecationWarning,
            stacklevel=2,
        )
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

        .. deprecated::
            Use :meth:`_get_git_commit_async` instead.

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
            # Use new async method
            before_commit = await self._get_git_commit_async(spack_dir)

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
            # Use new async method
            after_commit = await self._get_git_commit_async(spack_dir)

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

            # Use new async method
            before_commit = await self._get_git_commit_async(spack_dir)
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

            # Use new async method
            after_commit = await self._get_git_commit_async(spack_dir)
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
