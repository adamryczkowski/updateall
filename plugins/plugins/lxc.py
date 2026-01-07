"""LXC containers update plugin.

This plugin updates all running LXC containers by SSHing into them
and running the update-all script.

Official documentation:
- LXC: https://linuxcontainers.org/lxc/
- LXD: https://linuxcontainers.org/lxd/

Update mechanism:
1. List all running LXC containers
2. SSH into each container using its IP
3. Run update-all.sh inside each container
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.streaming import CompletionEvent, EventType, OutputEvent, Phase, PhaseEvent
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class LxcPlugin(BasePlugin):
    """Plugin for updating LXC containers."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "lxc"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "lxc"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update all running LXC containers"

    def is_available(self) -> bool:
        """Check if LXC is installed and working."""
        if shutil.which("lxc") is None:
            return False

        # Also check if lxc list works
        import subprocess

        try:
            result = subprocess.run(
                ["lxc", "list", "--format", "csv"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return False

    async def check_available(self) -> bool:
        """Check if LXC is available for updates."""
        return self.is_available()

    def _get_running_containers(self) -> list[str]:
        """Get list of running LXC container names.

        Returns:
            List of container names that are currently running.
        """
        import subprocess

        try:
            result = subprocess.run(
                ["lxc", "list", "--format", "csv"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return []

            containers = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) >= 2 and parts[1] == "RUNNING":
                    containers.append(parts[0])
            return containers
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return []

    def _get_container_ips(self, container_name: str) -> list[str]:
        """Get IP addresses for a container.

        Args:
            container_name: Name of the LXC container.

        Returns:
            List of IP addresses for the container.
        """
        import re
        import subprocess

        try:
            result = subprocess.run(
                ["lxc", "list", "-c4", "--format", "csv", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            # Parse IPs, removing interface info like " (eth0)"
            ips = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # Remove interface info like " (eth0)"
                cleaned = re.sub(r"\s*\([^)]*\)\s*", "", line)
                for ip in cleaned.split():
                    if ip:
                        ips.append(ip)
            return ips
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return []

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of containers updated.
        """
        output_lower = output.lower()

        # Count containers that were updated
        count = 0
        if "updating container" in output_lower:
            count = output_lower.count("updating container")
        elif "updated container" in output_lower:
            count = output_lower.count("updated container")

        return count

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for LXC update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["lxc", "list"]
        # For interactive mode, just list containers
        return ["lxc", "list"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the LXC containers update.

        This operation:
        1. Lists all running containers
        2. SSHs into each container
        3. Runs update commands inside each container

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if LXC is available
        if not self.is_available():
            return "LXC not available, skipping update", None

        # Get running containers
        containers = self._get_running_containers()
        if not containers:
            return "No running LXC containers found", None

        output_lines.append(f"Found {len(containers)} running container(s)")

        # Calculate timeout per container
        timeout_per_container = config.timeout_seconds // max(len(containers), 1)

        for container in containers:
            output_lines.append(f"Updating container: {container}")

            # Get container IPs
            ips = self._get_container_ips(container)
            if not ips:
                output_lines.append(f"  No IP addresses found for {container}")
                continue

            # Try to SSH into the container
            updated = False
            for ip in ips:
                output_lines.append(f"  Trying IP: {ip}")

                # Check if we can SSH
                try:
                    check_process = await asyncio.create_subprocess_exec(
                        "ssh",
                        "-o",
                        "PreferredAuthentications=publickey",
                        "-o",
                        "ConnectTimeout=5",
                        "-o",
                        "StrictHostKeyChecking=no",
                        ip,
                        "/bin/true",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(check_process.wait(), timeout=10)

                    if check_process.returncode != 0:
                        continue

                    # Run apt update && apt upgrade in the container
                    update_cmd = "apt update && apt upgrade -y"
                    process = await asyncio.create_subprocess_exec(
                        "ssh",
                        "-o",
                        "StrictHostKeyChecking=no",
                        ip,
                        "sh",
                        "-c",
                        update_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    stdout, _ = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout_per_container,
                    )
                    update_output = stdout.decode() if stdout else ""
                    output_lines.append(update_output)

                    if process.returncode == 0:
                        output_lines.append(f"  Updated container {container} successfully")
                        updated = True
                        break
                    else:
                        output_lines.append(
                            f"  Update failed for {container} with exit code {process.returncode}"
                        )
                except TimeoutError:
                    output_lines.append(f"  Update timed out for {container}")
                except Exception as e:
                    output_lines.append(f"  Error updating {container}: {e}")

            if not updated:
                output_lines.append(f"  Could not update container {container}")

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute LXC update with streaming output.

        Yields:
            StreamEvent objects from the update process.
        """
        # Check if LXC is available
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="LXC not available, skipping update",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        # Get running containers
        containers = self._get_running_containers()
        if not containers:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="No running LXC containers found",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Found {len(containers)} running container(s)",
            stream="stdout",
        )

        updated_count = 0
        failed_count = 0

        for container in containers:
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
                line=f"Updating container: {container}",
                stream="stdout",
            )

            # Get container IPs
            ips = self._get_container_ips(container)
            if not ips:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"  No IP addresses found for {container}",
                    stream="stderr",
                )
                failed_count += 1
                continue

            # Try to SSH into the container
            updated = False
            for ip in ips:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"  Trying IP: {ip}",
                    stream="stdout",
                )

                # Check if we can SSH
                try:
                    check_process = await asyncio.create_subprocess_exec(
                        "ssh",
                        "-o",
                        "PreferredAuthentications=publickey",
                        "-o",
                        "ConnectTimeout=5",
                        "-o",
                        "StrictHostKeyChecking=no",
                        ip,
                        "/bin/true",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await check_process.wait()

                    if check_process.returncode != 0:
                        continue

                    # Run apt update && apt upgrade in the container
                    update_cmd = "apt update && apt upgrade -y"
                    process = await asyncio.create_subprocess_exec(
                        "ssh",
                        "-o",
                        "StrictHostKeyChecking=no",
                        ip,
                        "sh",
                        "-c",
                        update_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )

                    if process.stdout:
                        async for raw_line in process.stdout:
                            yield OutputEvent(
                                event_type=EventType.OUTPUT,
                                plugin_name=self.name,
                                timestamp=datetime.now(tz=UTC),
                                line=f"    {raw_line.decode().rstrip()}",
                                stream="stdout",
                            )

                    await process.wait()

                    if process.returncode == 0:
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=f"  Updated container {container} successfully",
                            stream="stdout",
                        )
                        updated = True
                        updated_count += 1
                        break
                    else:
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=f"  Update failed for {container} with exit code {process.returncode}",
                            stream="stderr",
                        )
                except Exception as e:
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=f"  Error updating {container}: {e}",
                        stream="stderr",
                    )

            if not updated:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"  Could not update container {container}",
                    stream="stderr",
                )
                failed_count += 1

        # Final completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=failed_count == 0,
            exit_code=0 if failed_count == 0 else 1,
            packages_updated=updated_count,
        )
