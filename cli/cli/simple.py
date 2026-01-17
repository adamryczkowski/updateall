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
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from core.interfaces import UpdatePlugin


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
    from core.streaming import CompletionEvent

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
    # Step 4: Execute (upgrade)
    # =========================================================================
    if verbose:
        click.echo(f"[{name}] Step 4/4: Executing update...")
    else:
        click.echo(f"[{name}] Executing...")

    try:
        result = await plugin.execute(dry_run=dry_run)

        if result.status.value == "success":
            msg = f"[{name}] Success ✓"
            if result.packages_updated:
                msg += f" - {result.packages_updated} package(s) updated"
            click.echo(msg)
            if verbose and result.stdout:
                # Show last few lines of output
                lines = result.stdout.strip().splitlines()
                for line in lines[-5:]:
                    click.echo(f"  {line}")
            return 0
        else:
            click.echo(f"[{name}] Failed: {result.error_message or result.status.value}")
            if verbose and result.stderr:
                for line in result.stderr.strip().splitlines()[-5:]:
                    click.echo(f"  {line}")
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
    """
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
