"""Sudo declaration and management utilities.

This module provides utilities for handling sudo requirements in plugins,
including:
- Collecting sudo requirements from plugins
- Generating sudoers file entries
- Validating sudo access for required commands

Proposal 5 - Sudo Declaration
See docs/update-plugins-api-sudo-declaration-implementation-plan.md
"""

from __future__ import annotations

import asyncio
import getpass
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .interfaces import UpdatePlugin

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SudoRequirement:
    """Sudo requirement for a plugin.

    This dataclass represents the sudo requirements declared by a plugin,
    including the list of commands that require sudo privileges.

    Attributes:
        plugin_name: Name of the plugin declaring the requirement.
        commands: List of full paths to commands requiring sudo.
        reason: Optional explanation of why sudo is needed.
    """

    plugin_name: str
    commands: tuple[str, ...]
    reason: str = ""

    def __post_init__(self) -> None:
        """Validate the sudo requirement."""
        if not self.plugin_name:
            raise ValueError("plugin_name cannot be empty")
        # Convert list to tuple if needed (for frozen dataclass)
        if isinstance(self.commands, list):
            object.__setattr__(self, "commands", tuple(self.commands))


@dataclass
class SudoersEntry:
    """Entry for sudoers file generation.

    This dataclass represents a single entry in a sudoers file,
    specifying which commands a user can run with sudo.

    Attributes:
        user: Username for the sudoers entry.
        host: Host specification (default: ALL).
        runas: User to run as (default: ALL).
        commands: List of command paths.
        nopasswd: Whether to allow passwordless execution.
        comment: Optional comment for the entry.
    """

    user: str
    host: str = "ALL"
    runas: str = "ALL"
    commands: list[str] = field(default_factory=list)
    nopasswd: bool = True
    comment: str = ""

    def to_sudoers_line(self) -> str:
        """Generate a sudoers file line.

        Returns:
            A properly formatted sudoers file line.

        Raises:
            ValueError: If no commands are specified.
        """
        if not self.commands:
            raise ValueError("Cannot generate sudoers line without commands")

        tag = "NOPASSWD: " if self.nopasswd else ""
        cmds = ", ".join(self.commands)
        return f"{self.user} {self.host}=({self.runas}) {tag}{cmds}"


async def collect_sudo_requirements(
    plugins: Sequence[UpdatePlugin],
) -> list[SudoRequirement]:
    """Collect sudo requirements from all plugins.

    This function iterates through the provided plugins and collects
    their sudo requirements into a list of SudoRequirement objects.

    Args:
        plugins: Sequence of plugins to check for sudo requirements.

    Returns:
        List of SudoRequirement objects for plugins that need sudo.
        Plugins without sudo requirements are not included.
    """
    log = logger.bind(component="sudo_collect")
    requirements: list[SudoRequirement] = []

    for plugin in plugins:
        try:
            # Get sudo_commands from plugin (defaults to empty list)
            sudo_commands = getattr(plugin, "sudo_commands", [])

            if sudo_commands:
                requirement = SudoRequirement(
                    plugin_name=plugin.name,
                    commands=tuple(sudo_commands),
                )
                requirements.append(requirement)
                log.debug(
                    "collected_sudo_requirement",
                    plugin=plugin.name,
                    commands=sudo_commands,
                )
        except Exception as e:
            log.warning(
                "failed_to_collect_sudo_requirement",
                plugin=plugin.name,
                error=str(e),
            )

    log.info(
        "sudo_requirements_collected",
        total_plugins=len(plugins),
        plugins_with_sudo=len(requirements),
    )

    return requirements


def generate_sudoers_entries(
    requirements: Sequence[SudoRequirement],
    user: str | None = None,
    *,
    consolidate: bool = True,
) -> list[SudoersEntry]:
    """Generate sudoers entries for the given requirements.

    This function takes sudo requirements from plugins and generates
    sudoers file entries that can be used to configure passwordless
    sudo access for the specified commands.

    Args:
        requirements: Sudo requirements from plugins.
        user: Username for sudoers entries. Defaults to current user.
        consolidate: If True, consolidate all commands into a single entry.
            If False, create one entry per plugin.

    Returns:
        List of SudoersEntry objects.
    """
    if user is None:
        user = getpass.getuser()

    if not requirements:
        return []

    if consolidate:
        # Consolidate all commands into a single entry
        all_commands: set[str] = set()
        plugin_names: list[str] = []

        for req in requirements:
            all_commands.update(req.commands)
            plugin_names.append(req.plugin_name)

        # Sort commands for consistent output
        sorted_commands = sorted(all_commands)

        return [
            SudoersEntry(
                user=user,
                commands=sorted_commands,
                nopasswd=True,
                comment=f"update-all plugins: {', '.join(plugin_names)}",
            )
        ]
    else:
        # Create one entry per plugin
        entries: list[SudoersEntry] = []

        for req in requirements:
            entries.append(
                SudoersEntry(
                    user=user,
                    commands=list(req.commands),
                    nopasswd=True,
                    comment=f"update-all plugin: {req.plugin_name}",
                )
            )

        return entries


async def validate_sudo_access(
    requirements: Sequence[SudoRequirement],
    *,
    timeout: float = 10.0,
) -> dict[str, bool]:
    """Validate that the user has sudo access for all required commands.

    This function checks if the current user has sudo access for each
    command declared in the requirements. It uses `sudo -l` to check
    permissions without actually executing the commands.

    Args:
        requirements: Sudo requirements to validate.
        timeout: Timeout for sudo check in seconds.

    Returns:
        Dict mapping plugin names to whether sudo access is available.
        True means all commands for that plugin are accessible.
    """
    log = logger.bind(component="sudo_validate")
    results: dict[str, bool] = {}

    # Check if running as root (no sudo needed)
    if os.geteuid() == 0:
        log.debug("running_as_root")
        for req in requirements:
            results[req.plugin_name] = True
        return results

    # Check if sudo is available
    if not shutil.which("sudo"):
        log.warning("sudo_not_available")
        for req in requirements:
            results[req.plugin_name] = False
        return results

    for req in requirements:
        try:
            # Check if we can run the commands with sudo
            all_accessible = True

            for cmd in req.commands:
                # Use sudo -l to check if command is allowed
                process = await asyncio.create_subprocess_exec(
                    "sudo",
                    "-n",  # Non-interactive
                    "-l",  # List allowed commands
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    await asyncio.wait_for(process.communicate(), timeout=timeout)
                except TimeoutError:
                    log.warning(
                        "sudo_check_timeout",
                        plugin=req.plugin_name,
                        command=cmd,
                    )
                    all_accessible = False
                    break

                if process.returncode != 0:
                    log.debug(
                        "sudo_access_denied",
                        plugin=req.plugin_name,
                        command=cmd,
                    )
                    all_accessible = False
                    break

            results[req.plugin_name] = all_accessible

            if all_accessible:
                log.debug(
                    "sudo_access_granted",
                    plugin=req.plugin_name,
                    commands=req.commands,
                )
            else:
                log.debug(
                    "sudo_access_denied",
                    plugin=req.plugin_name,
                )

        except Exception as e:
            log.warning(
                "sudo_validation_error",
                plugin=req.plugin_name,
                error=str(e),
            )
            results[req.plugin_name] = False

    return results


def generate_sudoers_file(
    plugins: Sequence[UpdatePlugin],
    user: str | None = None,
    *,
    include_header: bool = True,
) -> str:
    """Generate complete sudoers file content for plugins.

    This is a convenience function that collects requirements from plugins
    and generates a complete sudoers file content.

    Args:
        plugins: Plugins to generate sudoers for.
        user: Username for sudoers entries. Defaults to current user.
        include_header: Whether to include header comments.

    Returns:
        Complete sudoers file content as a string.
    """
    if user is None:
        user = getpass.getuser()

    # Collect requirements synchronously by checking sudo_commands
    requirements: list[SudoRequirement] = []
    for plugin in plugins:
        sudo_commands = getattr(plugin, "sudo_commands", [])
        if sudo_commands:
            requirements.append(
                SudoRequirement(
                    plugin_name=plugin.name,
                    commands=tuple(sudo_commands),
                )
            )

    if not requirements:
        return "# No plugins require sudo\n"

    entries = generate_sudoers_entries(requirements, user=user, consolidate=True)

    lines: list[str] = []

    if include_header:
        lines.extend(
            [
                "# Generated by update-all",
                f"# Date: {datetime.now(tz=UTC).isoformat()}",
                "# Do not edit manually - regenerate with: update-all sudoers generate",
                "#",
                "# This file grants passwordless sudo access for update-all plugins.",
                "# Install to /etc/sudoers.d/update-all",
                "",
            ]
        )

    for entry in entries:
        if entry.comment:
            lines.append(f"# {entry.comment}")
        lines.append(entry.to_sudoers_line())
        lines.append("")

    return "\n".join(lines)


def resolve_command_path(command: str) -> str | None:
    """Resolve a command name to its full path.

    Args:
        command: Command name or path.

    Returns:
        Full path to the command, or None if not found.
    """
    # If already an absolute path, verify it exists
    if command.startswith("/"):
        path = Path(command)
        if path.is_file() and os.access(command, os.X_OK):
            return command
        return None

    # Use shutil.which to find the command
    return shutil.which(command)


def validate_command_paths(commands: Sequence[str]) -> dict[str, str | None]:
    """Validate and resolve command paths.

    Args:
        commands: List of command names or paths.

    Returns:
        Dict mapping original commands to resolved paths (or None if not found).
    """
    return {cmd: resolve_command_path(cmd) for cmd in commands}
