#!/usr/bin/env python3
"""Simple CLI layer for running plugins directly.

This module provides a minimal CLI interface using Click that bypasses
the orchestrator and UI, running plugins in sequence like simple shell scripts.

The 4-step process for each plugin:
    1. check_available() - Does plugin apply to this system?
    2. check_updates() - Are updates available? (returns info if upgrade required)
    3. download() - Download updates (if supported as separate step)
    4. execute() - Apply updates (upgrade)

Usage:
    update-simple mock-alpha mock-beta
    update-simple --all
    update-simple mock-alpha --dry-run
    update-simple --list

Environment Variables:
    UPDATE_ALL_DEBUG_MOCK_ONLY: Set to "1" to use only mock plugins.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from typing import TYPE_CHECKING

import click
import structlog

if TYPE_CHECKING:
    from core.interfaces import UpdatePlugin


def configure_logging(log_level: str) -> None:
    """Configure structlog and standard logging with the specified level.

    Args:
        log_level: Log level string (debug, info, warning, error).
    """
    # Map string to logging level
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    level = level_map.get(log_level.lower(), logging.INFO)

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,  # Override any existing configuration
    )

    # Configure structlog to filter by level
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def parse_step_summary(lines: list[str]) -> dict[str, str | int | None]:
    """Parse output lines from a step to extract summary information.

    Looks for patterns like:
    - "X package(s) can be upgraded" - package count
    - "Need to get X MB" - download size
    - "X upgraded, Y newly installed" - upgrade summary

    Args:
        lines: Output lines from a command step.

    Returns:
        Dict with extracted info: packages_to_update, download_size, etc.
    """
    result: dict[str, str | int | None] = {
        "packages_to_update": None,
        "download_size": None,
        "packages_upgraded": None,
        "packages_installed": None,
    }

    for line in lines:
        # Match "X package can be upgraded" or "X packages can be upgraded"
        match = re.search(r"(\d+)\s+packages?\s+can\s+be\s+upgraded", line)
        if match:
            result["packages_to_update"] = int(match.group(1))
            continue

        # Match "Need to get X MB of archives" or "Need to get X kB"
        match = re.search(r"Need\s+to\s+get\s+([\d.,]+)\s*([kMG]?B)", line)
        if match:
            size = match.group(1).replace(",", "")
            unit = match.group(2)
            result["download_size"] = f"{size} {unit}"
            continue

        # Match "X upgraded, Y newly installed, Z to remove"
        match = re.search(r"(\d+)\s+upgraded,\s+(\d+)\s+newly\s+installed", line)
        if match:
            result["packages_upgraded"] = int(match.group(1))
            result["packages_installed"] = int(match.group(2))
            continue

        # Match "0 upgraded, 0 newly installed" (already up to date)
        match = re.search(r"(\d+)\s+upgraded", line)
        if match and result["packages_upgraded"] is None:
            result["packages_upgraded"] = int(match.group(1))

    return result


def format_step_summary(summary: dict[str, str | int | None]) -> str | None:
    """Format the step summary for display.

    Args:
        summary: Dict with extracted info from parse_step_summary.

    Returns:
        Formatted summary string, or None if no relevant info.
    """
    parts = []

    if summary.get("packages_to_update") is not None:
        count = summary["packages_to_update"]
        parts.append(f"{count} package(s) to update")

    if summary.get("download_size"):
        parts.append(f"download size: {summary['download_size']}")

    if summary.get("packages_upgraded") is not None:
        upgraded = summary["packages_upgraded"]
        installed = summary.get("packages_installed", 0) or 0
        if upgraded > 0 or installed > 0:
            parts.append(f"{upgraded} upgraded, {installed} newly installed")

    if parts:
        return " | ".join(parts)
    return None


def get_plugin(name: str) -> UpdatePlugin | None:
    """Get a plugin by name.

    Args:
        name: Plugin name to look up.

    Returns:
        Plugin instance or None if not found.
    """
    from plugins import PluginRegistry, register_builtin_plugins

    registry = PluginRegistry()
    register_builtin_plugins(registry)
    return registry.get(name)


def get_all_plugins() -> list[UpdatePlugin]:
    """Get all registered plugins.

    Returns:
        List of all plugin instances.
    """
    from plugins import PluginRegistry, register_builtin_plugins

    registry = PluginRegistry()
    register_builtin_plugins(registry)
    return registry.get_all()


async def run_plugin_steps(
    plugin: UpdatePlugin,
    dry_run: bool = False,
    skip_download: bool = False,
    verbose: bool = False,
) -> int:
    """Run the 4-step process for a single plugin.

    Steps:
        1. check_available() - Does plugin apply to this system?
        2. check_updates() - Are updates available?
        3. download() - Download updates (if supported and not skipped)
        4. execute() - Apply updates

    Args:
        plugin: The plugin to run.
        dry_run: If True, simulate updates without making changes.
        skip_download: If True, skip the separate download phase.
        verbose: If True, show detailed output.

    Returns:
        Exit code (0 = success, 1 = failure, 2 = skipped)
    """
    from core.streaming import CompletionEvent, OutputEvent, PhaseEvent, ProgressEvent

    name = plugin.name

    # =========================================================================
    # Step 1: Check if plugin applies to this system
    # =========================================================================
    if verbose:
        click.echo(f"[{name}] Step 1/4: Checking availability...")

    available = await plugin.check_available()
    if not available:
        click.echo(f"[{name}] Not available on this system, skipping")
        return 2  # Skipped

    if verbose:
        click.echo(f"[{name}] Available ✓")

    # =========================================================================
    # Step 2: Check for updates (returns info if upgrade required)
    # =========================================================================
    if verbose:
        click.echo(f"[{name}] Step 2/4: Checking for updates...")

    updates = await plugin.check_updates()
    update_count = len(updates) if updates else 0

    if update_count == 0:
        click.echo(f"[{name}] No updates reported by check_updates()")
        # Still proceed - some plugins don't implement check_updates
        # but execute() will handle the actual update check
    else:
        click.echo(f"[{name}] {update_count} update(s) available")
        if verbose:
            for update in updates[:5]:  # Show first 5
                pkg_name = update.get("name", update.get("package", "unknown"))
                version = update.get("version", update.get("new_version", ""))
                click.echo(f"  - {pkg_name} {version}")
            if update_count > 5:
                click.echo(f"  ... and {update_count - 5} more")

    if dry_run:
        click.echo(f"[{name}] Dry run mode - would execute update")
        # Still call execute with dry_run=True to show what would happen
        result = await plugin.execute(dry_run=True)
        if result.stdout:
            for line in result.stdout.splitlines()[:10]:
                click.echo(f"  {line}")
        return 0

    # =========================================================================
    # Step 3: Download (if supported and not skipped)
    # =========================================================================
    if plugin.supports_download and not skip_download:
        if verbose:
            click.echo(f"[{name}] Step 3/4: Downloading updates...")
        else:
            click.echo(f"[{name}] Downloading...")

        try:
            async for event in plugin.download_streaming():
                # Print output lines if verbose
                if verbose and hasattr(event, "line"):
                    click.echo(f"  {event.line}")
                # Check for completion
                if isinstance(event, CompletionEvent):
                    if not event.success:
                        click.echo(f"[{name}] Download failed: {event.error_message}")
                        return 1
                    if verbose:
                        click.echo(f"[{name}] Download complete ✓")
        except NotImplementedError:
            if verbose:
                click.echo(f"[{name}] Download not implemented, will download during execute")
    else:
        if verbose:
            if not plugin.supports_download:
                click.echo(f"[{name}] Step 3/4: Skipping (download not supported separately)")
            else:
                click.echo(f"[{name}] Step 3/4: Skipping (--skip-download)")

    # =========================================================================
    # Step 4: Execute (upgrade) - Use streaming for real-time output
    # =========================================================================
    if verbose:
        click.echo(f"[{name}] Step 4/4: Executing update...")
    else:
        click.echo(f"[{name}] Executing...")

    try:
        # Use execute_streaming() for real-time output display
        final_success = False
        final_packages = 0
        final_error: str | None = None

        # Track output lines per step for summary extraction
        current_step_lines: list[str] = []
        current_step_header: str | None = None

        async for event in plugin.execute_streaming(dry_run=dry_run):
            if isinstance(event, OutputEvent):
                line = event.line

                # Detect step headers (e.g., "=== [1/2] Update package lists ===")
                if line.startswith("===") and line.endswith("==="):
                    # If we have a previous step, show its summary
                    if current_step_header and current_step_lines:
                        summary = parse_step_summary(current_step_lines)
                        summary_text = format_step_summary(summary)
                        if summary_text:
                            click.echo(f"  → {summary_text}")

                    # Start tracking new step
                    current_step_header = line
                    current_step_lines = []

                # Collect lines for current step
                current_step_lines.append(line)

                # Print output lines in real-time
                click.echo(f"  {line}")

            elif isinstance(event, ProgressEvent):
                # Show progress updates
                if event.percent is not None:
                    msg = f"  [{event.percent:.0f}%]"
                    if event.message:
                        msg += f" {event.message}"
                    click.echo(msg)
                elif event.message:
                    click.echo(f"  {event.message}")
            elif isinstance(event, PhaseEvent):
                # Log phase transitions in verbose mode
                if verbose:
                    if event.event_type.value == "phase_start":
                        click.echo(f"  [Phase: {event.phase.value} started]")
                    elif event.event_type.value == "phase_end":
                        status = "✓" if event.success else "✗"
                        click.echo(f"  [Phase: {event.phase.value} {status}]")
            elif isinstance(event, CompletionEvent):
                # Show summary for the last step before completion
                if current_step_lines:
                    summary = parse_step_summary(current_step_lines)
                    summary_text = format_step_summary(summary)
                    if summary_text:
                        click.echo(f"  → {summary_text}")

                # Track final status
                final_success = event.success
                final_packages = event.packages_updated
                final_error = event.error_message

        # Report final status
        if final_success:
            msg = f"[{name}] Success ✓"
            if final_packages:
                msg += f" - {final_packages} package(s) updated"
            click.echo(msg)
            return 0
        else:
            click.echo(f"[{name}] Failed: {final_error or 'Unknown error'}")
            return 1

    except Exception as e:
        click.echo(f"[{name}] Error: {e}")
        return 1


@click.command()
@click.argument("plugins", nargs=-1)
@click.option("--all", "-a", "run_all", is_flag=True, help="Run all available plugins")
@click.option("--dry-run", "-n", is_flag=True, help="Simulate updates without making changes")
@click.option("--skip-download", "-S", is_flag=True, help="Skip separate download phase")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output showing all steps")
@click.option("--list", "-l", "list_plugins", is_flag=True, help="List available plugins")
@click.option(
    "--log-level",
    "-L",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="info",
    help="Set log level for structlog output (default: info)",
)
@click.option(
    "--continue-on-error/--stop-on-error",
    "-c/-x",
    default=True,
    help="Continue with remaining plugins after a failure (default: continue)",
)
def main(
    plugins: tuple[str, ...],
    run_all: bool,
    dry_run: bool,
    skip_download: bool,
    verbose: bool,
    list_plugins: bool,
    log_level: str,
    continue_on_error: bool,
) -> None:
    """Run update plugins directly without orchestrator overhead.

    This is a simple CLI layer that calls the 4-step plugin API directly:

    \b
    1. check_available() - Does plugin apply to this system?
    2. check_updates()   - Are updates available?
    3. download()        - Download updates (if supported)
    4. execute()         - Apply updates

    \b
    Examples:
        update-simple mock-alpha mock-beta
        update-simple --all
        update-simple mock-alpha --dry-run --verbose
        update-simple --list
        update-simple apt --log-level warning  # Suppress debug/info logs
    """
    # Configure logging before any plugin operations
    configure_logging(log_level)

    if list_plugins:
        all_plugins = get_all_plugins()
        click.echo("Available plugins:")
        for p in all_plugins:
            available = asyncio.run(p.check_available())
            status = "✓" if available else "✗"
            desc = getattr(p, "description", p.name)
            click.echo(f"  {status} {p.name:20} {desc}")
        return

    if run_all:
        plugins_to_run = get_all_plugins()
    elif plugins:
        plugins_to_run = []
        for name in plugins:
            plugin = get_plugin(name)
            if plugin:
                plugins_to_run.append(plugin)
            else:
                click.echo(f"Warning: Plugin '{name}' not found", err=True)
    else:
        click.echo("No plugins specified. Use --all or provide plugin names.", err=True)
        click.echo("Use --list to see available plugins.", err=True)
        sys.exit(1)

    if not plugins_to_run:
        click.echo("No plugins to run.", err=True)
        sys.exit(1)

    click.echo(f"Running {len(plugins_to_run)} plugin(s)...")
    if dry_run:
        click.echo("[Dry run mode - no changes will be made]")
    click.echo()

    # Run plugins sequentially
    exit_code = 0
    success_count = 0
    skip_count = 0
    fail_count = 0

    for plugin in plugins_to_run:
        result = asyncio.run(run_plugin_steps(plugin, dry_run, skip_download, verbose))
        if result == 0:
            success_count += 1
        elif result == 2:
            skip_count += 1
        else:
            fail_count += 1
            exit_code = 1
            if not continue_on_error:
                click.echo("Stopping due to error (use -c to continue on error)")
                break
        click.echo()  # Blank line between plugins

    # Summary
    click.echo("=" * 40)
    click.echo(f"Summary: {success_count} success, {skip_count} skipped, {fail_count} failed")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
