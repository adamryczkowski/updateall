#!/usr/bin/env python3
"""Example streaming plugin in Python.

This is a complete example of an external Update-All plugin that
demonstrates the streaming protocol for real-time output.

Usage: example-python-plugin.py <command>

Commands:
    is-applicable         Check if this plugin can run on this system
    does-require-sudo     Check if sudo is required
    can-separate-download Check if download is separate from install
    estimate-update       Estimate update size and time
    download              Download updates only
    update [--dry-run]    Run the update process

Streaming Protocol:
    - stdout: Regular output lines (displayed to user)
    - stderr: Progress events as JSON with PROGRESS: prefix

For more information, see docs/external-plugin-streaming-protocol.md
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, TypedDict

# =============================================================================
# Configuration
# =============================================================================

PLUGIN_NAME = "example-python"
PLUGIN_VERSION = "1.0.0"


class PackageInfo(TypedDict):
    """Type definition for package information."""

    name: str
    version: str
    size_bytes: int


# Simulated packages for demonstration
PACKAGES: list[PackageInfo] = [
    {"name": "package-alpha", "version": "2.1.0", "size_bytes": 10_000_000},
    {"name": "package-beta", "version": "1.5.3", "size_bytes": 15_000_000},
    {"name": "package-gamma", "version": "3.0.0", "size_bytes": 25_000_000},
    {"name": "package-delta", "version": "1.2.1", "size_bytes": 8_000_000},
    {"name": "package-epsilon", "version": "4.0.0", "size_bytes": 12_000_000},
]


# =============================================================================
# Streaming Protocol Helpers
# =============================================================================


def emit_progress(
    phase: str,
    percent: float | None = None,
    message: str | None = None,
    bytes_downloaded: int | None = None,
    bytes_total: int | None = None,
    items_completed: int | None = None,
    items_total: int | None = None,
) -> None:
    """Emit a progress event to stderr.

    Progress events are JSON objects prefixed with PROGRESS: and written
    to stderr. They provide real-time progress information to the UI.

    Args:
        phase: Current phase (check, download, execute)
        percent: Progress percentage (0-100)
        message: Human-readable status message
        bytes_downloaded: Bytes downloaded so far
        bytes_total: Total bytes to download
        items_completed: Number of items completed
        items_total: Total number of items
    """
    event: dict[str, Any] = {"phase": phase}

    if percent is not None:
        event["percent"] = round(percent, 1)
    if message is not None:
        event["message"] = message
    if bytes_downloaded is not None:
        event["bytes_downloaded"] = bytes_downloaded
    if bytes_total is not None:
        event["bytes_total"] = bytes_total
    if items_completed is not None:
        event["items_completed"] = items_completed
    if items_total is not None:
        event["items_total"] = items_total

    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr, flush=True)


def emit_phase_start(phase: str) -> None:
    """Emit a phase start event.

    Args:
        phase: The phase that is starting (check, download, execute)
    """
    event = {"type": "phase_start", "phase": phase}
    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr, flush=True)


def emit_phase_end(phase: str, success: bool, error: str | None = None) -> None:
    """Emit a phase end event.

    Args:
        phase: The phase that is ending
        success: Whether the phase completed successfully
        error: Error message if success is False
    """
    event: dict[str, Any] = {
        "type": "phase_end",
        "phase": phase,
        "success": success,
    }
    if error:
        event["error"] = error
    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr, flush=True)


def output(message: str) -> None:
    """Print a message to stdout with flush.

    Args:
        message: The message to print
    """
    print(message, flush=True)


# =============================================================================
# Helper Functions
# =============================================================================


def get_total_size() -> int:
    """Calculate total size of all packages."""
    return sum(pkg["size_bytes"] for pkg in PACKAGES)


def format_bytes(size: int) -> str:
    """Format bytes as human-readable string."""
    size_float = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if size_float < 1024:
            return f"{size_float:.1f} {unit}"
        size_float /= 1024
    return f"{size_float:.1f} TB"


# =============================================================================
# Commands
# =============================================================================


def cmd_is_applicable() -> int:
    """Check if the plugin is applicable on this system.

    For this example, we're always applicable. In a real plugin,
    you would check if the package manager exists.

    Returns:
        0 if applicable, 1 if not applicable
    """
    # Example: Check if a command exists
    # if shutil.which("my-package-manager"):
    #     return 0
    # return 1

    # For demonstration, always applicable
    return 0


def cmd_does_require_sudo() -> int:
    """Check if sudo is required.

    Returns:
        0 if sudo is required, 1 if not required
    """
    # This example plugin doesn't require sudo
    return 1


def cmd_can_separate_download() -> int:
    """Check if download can be separate from install.

    Returns:
        0 if download can be separate, 1 if not
    """
    # We support separate download
    return 0


def cmd_estimate_update() -> int:
    """Estimate update size and time.

    Outputs JSON with download size and time estimates.

    Returns:
        0 on success
    """
    total_size = get_total_size()

    estimate = {
        "status": "success",
        "data": {
            "total_bytes": total_size,
            "package_count": len(PACKAGES),
            "estimated_seconds": 30,
            "packages": [
                {
                    "name": pkg["name"],
                    "version": pkg["version"],
                    "size_bytes": pkg["size_bytes"],
                }
                for pkg in PACKAGES
            ],
        },
    }

    print(json.dumps(estimate, indent=2))
    return 0


def cmd_download() -> int:
    """Download updates without installing.

    Demonstrates streaming progress during download phase.

    Returns:
        0 on success, 1 on failure
    """
    emit_phase_start("download")

    total_size = get_total_size()
    bytes_downloaded = 0
    package_count = len(PACKAGES)

    output(f"Starting download of {package_count} packages...")
    output("")

    try:
        for i, pkg in enumerate(PACKAGES):
            name = pkg["name"]
            size = pkg["size_bytes"]

            output(f"Downloading {name}...")

            # Simulate download progress in steps
            for step in [25, 50, 75, 100]:
                step_bytes = size * step // 100
                current_total = bytes_downloaded + step_bytes
                percent = (current_total / total_size) * 100

                emit_progress(
                    phase="download",
                    percent=percent,
                    message=f"Downloading {name}... ({step}%)",
                    bytes_downloaded=current_total,
                    bytes_total=total_size,
                    items_completed=i,
                    items_total=package_count,
                )

                time.sleep(0.15)  # Simulate network delay

            bytes_downloaded += size
            output(f"  ✓ Downloaded {name} ({format_bytes(size)})")

        output("")
        output(f"Download complete! {format_bytes(total_size)} downloaded.")

        emit_phase_end("download", success=True)
        return 0

    except Exception as e:
        emit_phase_end("download", success=False, error=str(e))
        return 1


def cmd_update(dry_run: bool = False) -> int:
    """Run the update process.

    Args:
        dry_run: If True, simulate update without making changes

    Returns:
        0 on success, 1 on failure
    """
    if dry_run:
        output("Dry run mode - no changes will be made")
        output("")
        output("Would update the following packages:")
        for pkg in PACKAGES:
            output(f"  - {pkg['name']} ({pkg['version']})")
        output("")
        output(f"Total: {len(PACKAGES)} packages")
        return 0

    emit_phase_start("execute")

    package_count = len(PACKAGES)
    output(f"Starting update of {package_count} packages...")
    output("")

    try:
        for i, pkg in enumerate(PACKAGES):
            name = pkg["name"]
            version = pkg["version"]
            pkg_num = i + 1
            percent = (pkg_num / package_count) * 100

            output(f"[{pkg_num}/{package_count}] Installing {name} v{version}...")

            emit_progress(
                phase="execute",
                percent=percent,
                message=f"Installing {name}...",
                items_completed=pkg_num,
                items_total=package_count,
            )

            # Simulate installation time
            time.sleep(0.3)

            output(f"  ✓ {name} installed successfully")

        output("")
        output(f"Update complete! {package_count} packages updated.")

        emit_phase_end("execute", success=True)
        return 0

    except Exception as e:
        emit_phase_end("execute", success=False, error=str(e))
        return 1


def cmd_help() -> int:
    """Show help information."""
    help_text = f"""
{PLUGIN_NAME} v{PLUGIN_VERSION} - Example Update-All Plugin

Usage: {sys.argv[0]} <command> [options]

Commands:
  is-applicable         Check if this plugin can run on this system
  does-require-sudo     Check if sudo is required (exit 0=yes, 1=no)
  can-separate-download Check if download is separate (exit 0=yes, 1=no)
  estimate-update       Estimate update size and time (JSON output)
  download              Download updates only
  update [--dry-run]    Run the update process

Options:
  --dry-run             Simulate update without making changes

Examples:
  {sys.argv[0]} is-applicable
  {sys.argv[0]} update --dry-run
  {sys.argv[0]} download
  {sys.argv[0]} update

For more information, see docs/external-plugin-streaming-protocol.md
"""
    print(help_text.strip())
    return 0


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Error: No command specified", file=sys.stderr)
        print(f"Run '{sys.argv[0]} help' for usage information.", file=sys.stderr)
        return 1

    command = sys.argv[1]

    # Command dispatch
    commands: dict[str, Any] = {
        "is-applicable": cmd_is_applicable,
        "does-require-sudo": cmd_does_require_sudo,
        "can-separate-download": cmd_can_separate_download,
        "estimate-update": cmd_estimate_update,
        "download": cmd_download,
        "help": cmd_help,
        "--help": cmd_help,
        "-h": cmd_help,
    }

    if command == "update":
        # Handle update command with optional --dry-run
        dry_run = "--dry-run" in sys.argv[2:]
        return cmd_update(dry_run=dry_run)

    if command in commands:
        return commands[command]()

    print(f"Error: Unknown command '{command}'", file=sys.stderr)
    print(f"Run '{sys.argv[0]} help' for usage information.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
