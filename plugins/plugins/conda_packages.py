"""Conda packages update plugin.

This plugin updates all packages in all conda environments.

Uses mamba if available (faster C++ implementation), otherwise falls back to conda.

Sources:
- https://docs.conda.io/projects/conda/en/latest/commands/update.html
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    StreamEvent,
)

from .base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig


class CondaPackagesPlugin(BasePlugin):
    """Plugin for updating conda packages across all environments."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "conda-packages"

    @property
    def command(self) -> str:
        """Return the primary update command."""
        if shutil.which("mamba"):
            return "mamba"
        return "conda"

    @property
    def description(self) -> str:
        """Return a description of what this plugin updates."""
        return "Updates all packages in all conda environments"

    def is_available(self) -> bool:
        """Check if conda or mamba is available on the system."""
        return shutil.which("conda") is not None or shutil.which("mamba") is not None

    async def check_available(self) -> bool:
        """Check if conda or mamba is available on the system."""
        return self.is_available()

    def _get_package_manager(self) -> str:
        """Get the preferred package manager (mamba or conda)."""
        if shutil.which("mamba"):
            return "mamba"
        return "conda"

    async def _get_environments(self) -> list[str]:
        """Get list of all conda environments.

        Returns:
            List of environment names.
        """
        return_code, stdout, _stderr = await self._run_command(
            ["conda", "env", "list", "--json"],
            timeout=30,
        )

        if return_code != 0:
            return ["base"]

        try:
            data = json.loads(stdout)
            envs = data.get("envs", [])
            # Extract environment names from paths
            env_names = []
            for env_path in envs:
                if "/envs/" in env_path:
                    # Named environment
                    env_names.append(env_path.split("/envs/")[-1])
                else:
                    # Base environment
                    env_names.append("base")
            return env_names if env_names else ["base"]
        except (json.JSONDecodeError, KeyError):
            return ["base"]

    @property
    def supports_streaming(self) -> bool:
        """This plugin supports streaming output."""
        return True

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute the update with streaming output.

        This plugin needs custom streaming because it dynamically
        discovers and updates multiple conda environments.

        Args:
            dry_run: If True, only list packages without updating.

        Yields:
            StreamEvent objects with progress and output information.
        """
        pkg_manager = self._get_package_manager()

        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Using package manager: {pkg_manager}",
            stream="stdout",
        )

        # Get all environments
        environments = await self._get_environments()
        total_envs = len(environments)

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Found {total_envs} environment(s) to update",
            stream="stdout",
        )

        overall_success = True
        packages_updated = 0

        for i, env_name in enumerate(environments):
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"\n=== Updating environment: {env_name} ===",
                stream="stdout",
            )

            if dry_run:
                cmd = [pkg_manager, "list", "-n", env_name]
            else:
                cmd = [pkg_manager, "update", "--all", "-n", env_name, "-y"]

            return_code, stdout, stderr = await self._run_command(cmd, timeout=600)

            # Emit output
            for line in stdout.splitlines():
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=line,
                    stream="stdout",
                )

            if stderr:
                for line in stderr.splitlines():
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=line,
                        stream="stderr",
                    )

            if return_code != 0:
                overall_success = False
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Warning: Failed to update environment {env_name}",
                    stream="stderr",
                )
            else:
                packages_updated += self._count_updated_packages(stdout + stderr)

            # Progress update
            progress = (i + 1) / total_envs
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Progress: {i + 1}/{total_envs} environments ({progress:.0%})",
                stream="stdout",
            )

        # Emit phase end
        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            success=overall_success,
        )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=overall_success,
            exit_code=0 if overall_success else 1,
            packages_updated=packages_updated,
            error_message=None if overall_success else "Some environments failed to update",
        )

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the conda packages update (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message or None).
        """
        pkg_manager = self._get_package_manager()
        all_output: list[str] = []
        overall_success = True

        all_output.append(f"Using package manager: {pkg_manager}")

        # Get all environments and update them
        environments = await self._get_environments()
        all_output.append(f"Found {len(environments)} environment(s)")

        for env_name in environments:
            all_output.append(f"\n=== Updating environment: {env_name} ===")

            return_code, stdout, stderr = await self._run_command(
                [pkg_manager, "update", "--all", "-n", env_name, "-y"],
                timeout=config.timeout_seconds if config else 600,
            )

            all_output.append(stdout + stderr)

            if return_code != 0:
                overall_success = False
                all_output.append(f"Warning: Failed to update environment {env_name}")

        if overall_success:
            all_output.append("\nAll environments updated successfully")
            return "\n".join(all_output), None
        else:
            return "\n".join(all_output), "Some environments failed to update"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command for interactive mode."""
        pkg_manager = self._get_package_manager()
        if dry_run:
            return [pkg_manager, "list", "-n", "base"]
        return [pkg_manager, "update", "--all", "-n", "base"]

    def _count_updated_packages(self, output: str) -> int:
        """Count the number of packages updated from command output."""
        output_lower = output.lower()

        if "all requested packages already installed" in output_lower:
            return 0

        # Count packages being updated
        update_count = len(re.findall(r"updating\s+\w+", output_lower))
        if update_count > 0:
            return update_count

        # Count version changes (arrows indicate updates)
        arrow_count = len(re.findall(r"-->|->", output))
        if arrow_count > 0:
            return arrow_count

        return 0
