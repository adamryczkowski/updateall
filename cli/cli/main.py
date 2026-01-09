"""Main CLI entry point for update-all.

This module defines the Typer application and main commands.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__

if TYPE_CHECKING:
    from plugins import PluginRegistry

    from core import ConfigManager

# Create the main Typer app
app = typer.Typer(
    name="update-all",
    help="System update orchestrator - manage updates across multiple package managers.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Create console for rich output
console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold blue]update-all[/bold blue] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Update-All: System update orchestrator.

    Manage updates across multiple package managers including apt, pipx, flatpak, and more.
    """


def _get_registry() -> PluginRegistry:
    """Get the plugin registry with built-in plugins registered."""
    from plugins import PluginRegistry, register_builtin_plugins

    registry = PluginRegistry()
    register_builtin_plugins(registry)
    return registry


def _get_config_manager() -> ConfigManager:
    """Get the configuration manager."""
    from core import ConfigManager

    return ConfigManager()


@app.command()
def run(
    plugins: Annotated[
        list[str] | None,
        typer.Option(
            "--plugin",
            "-p",
            help="Specific plugins to run. Can be specified multiple times.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Simulate updates without making changes.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output.",
        ),
    ] = False,
    continue_on_error: Annotated[
        bool,
        typer.Option(
            "--continue-on-error",
            "-c",
            help="Continue with remaining plugins after a failure.",
        ),
    ] = True,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Use interactive tabbed UI with live output for each plugin.",
        ),
    ] = False,
) -> None:
    """Run system updates.

    Execute updates for all enabled plugins or specific plugins if specified.

    Use --interactive (-i) for a tabbed interface that shows live output
    for each plugin and allows interaction (e.g., entering sudo password).
    """
    asyncio.run(_run_updates(plugins, dry_run, verbose, continue_on_error, interactive))


async def _run_updates(
    plugin_names: list[str] | None,
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    continue_on_error: bool,  # noqa: ARG001
    interactive: bool = False,
) -> None:
    """Run updates asynchronously."""
    from plugins import register_builtin_plugins
    from plugins.registry import PluginRegistry

    from core import ConfigManager

    # Initialize components
    registry = PluginRegistry()
    register_builtin_plugins(registry)
    config_manager = ConfigManager()
    config = config_manager.load()

    # Get plugins to run
    if plugin_names:
        plugins_to_run = []
        for name in plugin_names:
            plugin = registry.get(name)
            if plugin:
                plugins_to_run.append(plugin)
            else:
                console.print(f"[yellow]Warning: Plugin '{name}' not found[/yellow]")
    else:
        plugins_to_run = registry.get_all()

    if not plugins_to_run:
        console.print("[yellow]No plugins to run[/yellow]")
        return

    if dry_run:
        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")

    # Use interactive tabbed UI if requested
    if interactive:
        from ui.interactive_tabbed_run import run_with_interactive_tabbed_ui

        await run_with_interactive_tabbed_ui(
            plugins=plugins_to_run,
            configs=config.plugins,
            dry_run=dry_run,
        )
        return

    # Standard progress display mode
    from ui.progress import ProgressDisplay

    from core import Orchestrator

    console.print(f"Running {len(plugins_to_run)} plugin(s)...")

    # Create orchestrator
    orchestrator = Orchestrator(dry_run=dry_run, continue_on_error=True)

    # Run with progress display
    async with ProgressDisplay(console) as progress:
        # Add all plugins as pending first
        for plugin in plugins_to_run:
            progress.add_plugin_pending(plugin.name)

        # Run plugins sequentially
        summary = await orchestrator.run_all(plugins_to_run, config.plugins)

        # Update progress display with results
        for result in summary.results:
            # First start the plugin (changes from pending to running)
            progress.start_plugin(result.plugin_name)

            if result.status.value == "success":
                progress.complete_plugin(
                    result.plugin_name,
                    success=True,
                    message=f"Updated {result.packages_updated} packages",
                )
            elif result.status.value == "skipped":
                progress.skip_plugin(result.plugin_name, result.error_message or "Skipped")
            else:
                progress.complete_plugin(
                    result.plugin_name,
                    success=False,
                    message=result.error_message or "Failed",
                )

    # Print summary
    console.print()
    _print_summary(summary)


def _print_summary(summary: Any) -> None:
    """Print execution summary."""
    from core import PluginStatus

    table = Table(title="Update Summary", show_header=True)
    table.add_column("Plugin", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Packages", justify="right")
    table.add_column("Duration", justify="right")

    for result in summary.results:
        status_style = {
            PluginStatus.SUCCESS: "[green]✓ Success[/green]",
            PluginStatus.FAILED: "[red]✗ Failed[/red]",
            PluginStatus.SKIPPED: "[yellow]⊘ Skipped[/yellow]",
            PluginStatus.TIMEOUT: "[red]⏱ Timeout[/red]",
        }.get(result.status, str(result.status.value))

        duration = ""
        if result.start_time and result.end_time:
            secs = (result.end_time - result.start_time).total_seconds()
            duration = f"{secs:.1f}s"

        table.add_row(
            result.plugin_name,
            status_style,
            str(result.packages_updated),
            duration,
        )

    console.print(table)

    # Print totals
    console.print()
    console.print(f"[bold]Total:[/bold] {summary.total_plugins} plugins")
    console.print(f"  [green]Successful:[/green] {summary.successful_plugins}")
    console.print(f"  [red]Failed:[/red] {summary.failed_plugins}")
    console.print(f"  [yellow]Skipped:[/yellow] {summary.skipped_plugins}")
    if summary.total_duration_seconds:
        console.print(f"  [dim]Duration:[/dim] {summary.total_duration_seconds:.1f}s")


@app.command()
def check(
    plugins: Annotated[
        list[str] | None,
        typer.Option(
            "--plugin",
            "-p",
            help="Specific plugins to check. Can be specified multiple times.",
        ),
    ] = None,
) -> None:
    """Check for available updates.

    Show what updates are available without applying them.
    """
    asyncio.run(_check_updates(plugins))


async def _check_updates(plugin_names: list[str] | None) -> None:
    """Check for updates asynchronously."""
    from plugins import register_builtin_plugins
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()
    register_builtin_plugins(registry)

    # Get plugins to check
    if plugin_names:
        plugins_to_check = []
        for name in plugin_names:
            plugin = registry.get(name)
            if plugin:
                plugins_to_check.append(plugin)
            else:
                console.print(f"[yellow]Warning: Plugin '{name}' not found[/yellow]")
    else:
        plugins_to_check = registry.get_all()

    if not plugins_to_check:
        console.print("[yellow]No plugins to check[/yellow]")
        return

    console.print("[bold]Checking for updates...[/bold]")
    console.print()

    table = Table(title="Available Updates", show_header=True)
    table.add_column("Plugin", style="cyan")
    table.add_column("Available", style="bold")
    table.add_column("Status")

    for plugin in plugins_to_check:
        available = await plugin.check_available()
        if not available:
            table.add_row(plugin.name, "[dim]N/A[/dim]", "[dim]Not installed[/dim]")
            continue

        try:
            updates = await plugin.check_updates()
            if updates:
                table.add_row(
                    plugin.name,
                    f"[green]{len(updates)} updates[/green]",
                    "[green]Updates available[/green]",
                )
            else:
                table.add_row(plugin.name, "[dim]0[/dim]", "[dim]Up to date[/dim]")
        except Exception as e:
            table.add_row(plugin.name, "[red]Error[/red]", f"[red]{e}[/red]")

    console.print(table)


@app.command()
def status() -> None:
    """Show current system status.

    Display information about available plugins and their status.
    """
    asyncio.run(_show_status())


async def _show_status() -> None:
    """Show status asynchronously."""
    from plugins import register_builtin_plugins
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()
    register_builtin_plugins(registry)

    plugins = registry.get_all()

    table = Table(title="Plugin Status", show_header=True)
    table.add_column("Plugin", style="cyan")
    table.add_column("Description")
    table.add_column("Available", justify="center")

    for plugin in plugins:
        available = await plugin.check_available()
        available_str = "[green]✓[/green]" if available else "[red]✗[/red]"
        table.add_row(plugin.name, plugin.metadata.description or plugin.name, available_str)

    console.print(table)


@app.command()
def history(
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            help="Maximum number of entries to show.",
        ),
    ] = 10,
) -> None:
    """Show update history.

    Display recent update runs and their results.
    """
    from stats.history import HistoryStore

    store = HistoryStore()
    runs = store.get_recent_runs(limit)

    if not runs:
        console.print("[dim]No history available yet.[/dim]")
        return

    console.print(f"[bold]Update History[/bold] (last {len(runs)} entries)")
    console.print()

    for run_data in runs:
        run_id = run_data.get("id", "unknown")
        start_time = run_data.get("start_time", "unknown")
        plugins_data = run_data.get("plugins", [])

        success_count = sum(1 for p in plugins_data if p.get("status") == "success")
        failed_count = sum(1 for p in plugins_data if p.get("status") == "failed")
        total_packages = sum(p.get("packages_updated", 0) for p in plugins_data)

        console.print(f"[cyan]Run {run_id}[/cyan] - {start_time}")
        console.print(
            f"  Plugins: {len(plugins_data)} | "
            f"[green]Success: {success_count}[/green] | "
            f"[red]Failed: {failed_count}[/red] | "
            f"Packages: {total_packages}"
        )
        console.print()


# Create plugins subcommand group
plugins_app = typer.Typer(
    name="plugins",
    help="Manage update plugins.",
    no_args_is_help=True,
)
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list() -> None:
    """List available plugins.

    Show all registered plugins and their status.
    """
    asyncio.run(_list_plugins())


async def _list_plugins() -> None:
    """List plugins asynchronously."""
    from plugins import register_builtin_plugins
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()
    register_builtin_plugins(registry)

    config_manager = _get_config_manager()
    config = config_manager.load()

    plugins = registry.get_all()

    table = Table(title="Available Plugins", show_header=True)
    table.add_column("Plugin", style="cyan")
    table.add_column("Description")
    table.add_column("Enabled", justify="center")
    table.add_column("Available", justify="center")

    for plugin in plugins:
        plugin_config = config.plugins.get(plugin.name)
        enabled = plugin_config.enabled if plugin_config else True
        enabled_str = "[green]✓[/green]" if enabled else "[red]✗[/red]"

        available = await plugin.check_available()
        available_str = "[green]✓[/green]" if available else "[red]✗[/red]"

        table.add_row(
            plugin.name,
            plugin.metadata.description or plugin.name,
            enabled_str,
            available_str,
        )

    console.print(table)


@plugins_app.command("enable")
def plugins_enable(
    name: Annotated[str, typer.Argument(help="Plugin name to enable.")],
) -> None:
    """Enable a plugin."""
    from core import PluginConfig

    config_manager = _get_config_manager()
    config = config_manager.load()

    if name not in config.plugins:
        config.plugins[name] = PluginConfig(name=name, enabled=True)
    else:
        config.plugins[name].enabled = True

    config_manager.save(config)
    console.print(f"[green]Enabled plugin: {name}[/green]")


@plugins_app.command("disable")
def plugins_disable(
    name: Annotated[str, typer.Argument(help="Plugin name to disable.")],
) -> None:
    """Disable a plugin."""
    from core import PluginConfig

    config_manager = _get_config_manager()
    config = config_manager.load()

    if name not in config.plugins:
        config.plugins[name] = PluginConfig(name=name, enabled=False)
    else:
        config.plugins[name].enabled = False

    config_manager.save(config)
    console.print(f"[yellow]Disabled plugin: {name}[/yellow]")


@plugins_app.command("validate")
def plugins_validate(
    plugin_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the plugin executable to validate.",
        ),
    ],
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="Timeout for each command in seconds.",
        ),
    ] = 30,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output.",
        ),
    ] = False,
) -> None:
    """Validate an external plugin.

    Check that a plugin conforms to the Update-All plugin protocol,
    including streaming output format and required commands.

    Example:
        update-all plugins validate /path/to/my-plugin
        update-all plugins validate ./my-plugin.sh --verbose
    """
    from .validate_plugin import print_validation_result, validate_plugin_async

    result = asyncio.run(validate_plugin_async(Path(plugin_path), timeout=timeout, verbose=verbose))
    print_validation_result(result, verbose=verbose)

    # Exit with appropriate code
    if result.has_errors:
        raise typer.Exit(1)


# Create config subcommand group
config_app = typer.Typer(
    name="config",
    help="Manage configuration.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    import yaml

    config_manager = _get_config_manager()
    config = config_manager.load()

    console.print(f"[bold]Configuration File:[/bold] {config_manager.config_path}")
    console.print()

    # Serialize and display
    data = {
        "global": config.global_config.model_dump(exclude_defaults=True),
        "plugins": {
            name: plugin.model_dump(exclude={"name"}, exclude_defaults=True)
            for name, plugin in config.plugins.items()
        },
    }

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    console.print(yaml_str)


@config_app.command("init")
def config_init(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing configuration.",
        ),
    ] = False,
) -> None:
    """Initialize configuration file."""
    config_manager = _get_config_manager()

    if config_manager.init_config(force=force):
        console.print(f"[green]Configuration initialized: {config_manager.config_path}[/green]")
    else:
        console.print(
            f"[yellow]Configuration already exists: {config_manager.config_path}[/yellow]"
        )
        console.print("Use --force to overwrite.")


@config_app.command("path")
def config_path() -> None:
    """Show configuration file path."""
    config_manager = _get_config_manager()
    console.print(str(config_manager.config_path))


# =============================================================================
# Remote Commands (Phase 3)
# =============================================================================

remote_app = typer.Typer(
    name="remote",
    help="Manage remote host updates.",
    no_args_is_help=True,
)
app.add_typer(remote_app, name="remote")


def _get_hosts_config_path() -> Path:
    """Get the path to the hosts configuration file."""
    from core import get_config_dir

    return get_config_dir() / "hosts.yaml"


@remote_app.command("list")
def remote_list() -> None:
    """List configured remote hosts."""
    from core import RemoteUpdateManager

    manager = RemoteUpdateManager.from_config_file(_get_hosts_config_path())
    hosts = manager.get_all_hosts()

    if not hosts:
        console.print("[dim]No remote hosts configured.[/dim]")
        console.print(f"Add hosts to: {_get_hosts_config_path()}")
        return

    table = Table(title="Remote Hosts", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Hostname")
    table.add_column("User")
    table.add_column("Port", justify="right")

    for host in hosts:
        table.add_row(
            host.name,
            host.hostname,
            host.user,
            str(host.port),
        )

    console.print(table)


@remote_app.command("run")
def remote_run(
    hosts: Annotated[
        list[str],
        typer.Argument(help="Host names to update."),
    ],
    plugins: Annotated[
        list[str] | None,
        typer.Option(
            "--plugin",
            "-p",
            help="Specific plugins to run. Can be specified multiple times.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Simulate updates without making changes.",
        ),
    ] = False,
    parallel: Annotated[
        bool,
        typer.Option(
            "--parallel",
            help="Run updates on all hosts in parallel.",
        ),
    ] = False,
) -> None:
    """Run updates on remote hosts."""
    asyncio.run(_remote_run(hosts, plugins, dry_run, parallel))


async def _remote_run(
    host_names: list[str],
    plugins: list[str] | None,
    dry_run: bool,
    parallel: bool,
) -> None:
    """Run remote updates asynchronously."""
    from core import RemoteUpdateManager

    manager = RemoteUpdateManager.from_config_file(_get_hosts_config_path())

    # Validate hosts exist
    for name in host_names:
        if not manager.get_host(name):
            console.print(f"[red]Error: Host '{name}' not found in configuration[/red]")
            raise typer.Exit(1)

    console.print(f"Running updates on {len(host_names)} host(s)...")
    if dry_run:
        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")

    if parallel:
        results = await manager.run_update_parallel(host_names, plugins, dry_run)
    else:
        results = await manager.run_update_sequential(host_names, plugins, dry_run)

    # Print results
    console.print()
    table = Table(title="Remote Update Results", show_header=True)
    table.add_column("Host", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Duration", justify="right")
    table.add_column("Message")

    for result in results:
        status = "[green]✓ Success[/green]" if result.success else "[red]✗ Failed[/red]"
        duration = ""
        if result.end_time and result.start_time:
            secs = (result.end_time - result.start_time).total_seconds()
            duration = f"{secs:.1f}s"

        message = result.error_message or ""
        table.add_row(result.host_name, status, duration, message)

    console.print(table)


@remote_app.command("check")
def remote_check(
    hosts: Annotated[
        list[str],
        typer.Argument(help="Host names to check."),
    ],
) -> None:
    """Check connectivity to remote hosts."""
    asyncio.run(_remote_check(hosts))


async def _remote_check(host_names: list[str]) -> None:
    """Check remote host connectivity."""
    from core import RemoteUpdateManager, ResilientRemoteExecutor

    manager = RemoteUpdateManager.from_config_file(_get_hosts_config_path())

    table = Table(title="Connection Status", show_header=True)
    table.add_column("Host", style="cyan")
    table.add_column("Status", style="bold")

    for name in host_names:
        host = manager.get_host(name)
        if not host:
            table.add_row(name, "[red]✗ Not configured[/red]")
            continue

        executor = ResilientRemoteExecutor(host)
        try:
            connected = await executor.check_connection()
            if connected:
                table.add_row(name, "[green]✓ Connected[/green]")
            else:
                table.add_row(name, "[red]✗ Connection failed[/red]")
        except Exception as e:
            table.add_row(name, f"[red]✗ {e}[/red]")

    console.print(table)


# =============================================================================
# Schedule Commands (Phase 3)
# =============================================================================

schedule_app = typer.Typer(
    name="schedule",
    help="Manage scheduled updates.",
    no_args_is_help=True,
)
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("enable")
def schedule_enable(
    interval: Annotated[
        str,
        typer.Option(
            "--interval",
            "-i",
            help="Schedule interval: hourly, daily, weekly, monthly, or custom OnCalendar value.",
        ),
    ] = "weekly",
) -> None:
    """Enable scheduled updates."""
    from core import ScheduleInterval, get_schedule_manager

    manager = get_schedule_manager()

    # Try to parse as ScheduleInterval
    schedule_value: ScheduleInterval | str
    try:
        schedule_value = ScheduleInterval(interval)
    except ValueError:
        # Use as custom OnCalendar value
        schedule_value = interval

    try:
        manager.enable(schedule_value)
        console.print(f"[green]Scheduled updates enabled: {interval}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to enable schedule: {e}[/red]")
        raise typer.Exit(1) from None


@schedule_app.command("disable")
def schedule_disable() -> None:
    """Disable scheduled updates."""
    from core import get_schedule_manager

    manager = get_schedule_manager()

    try:
        manager.disable()
        console.print("[yellow]Scheduled updates disabled[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to disable schedule: {e}[/red]")
        raise typer.Exit(1) from None


@schedule_app.command("status")
def schedule_status() -> None:
    """Show schedule status."""
    from core import get_schedule_manager

    manager = get_schedule_manager()
    status = manager.get_status()

    console.print("[bold]Schedule Status[/bold]")
    console.print()

    if status.enabled:
        console.print("  [green]Enabled:[/green] Yes")
    else:
        console.print("  [yellow]Enabled:[/yellow] No")

    if status.active:
        console.print("  [green]Active:[/green] Yes")
    else:
        console.print("  [dim]Active:[/dim] No")

    if status.schedule:
        console.print(f"  [cyan]Schedule:[/cyan] {status.schedule}")

    if status.next_run:
        console.print(f"  [cyan]Next run:[/cyan] {status.next_run}")

    if status.last_run:
        console.print(f"  [dim]Last run:[/dim] {status.last_run}")

    if status.last_result:
        result_style = "green" if status.last_result == "success" else "red"
        console.print(
            f"  [dim]Last result:[/dim] [{result_style}]{status.last_result}[/{result_style}]"
        )


@schedule_app.command("run-now")
def schedule_run_now() -> None:
    """Trigger an immediate update run."""
    from core import get_schedule_manager

    manager = get_schedule_manager()

    try:
        manager.run_now()
        console.print("[green]Update triggered[/green]")
    except Exception as e:
        console.print(f"[red]Failed to trigger update: {e}[/red]")
        raise typer.Exit(1) from None


@schedule_app.command("logs")
def schedule_logs(
    lines: Annotated[
        int,
        typer.Option(
            "--lines",
            "-n",
            help="Number of log lines to show.",
        ),
    ] = 50,
) -> None:
    """Show recent update logs."""
    from core import get_schedule_manager

    manager = get_schedule_manager()
    logs = manager.get_logs(lines)

    if logs:
        console.print(logs)
    else:
        console.print("[dim]No logs available[/dim]")


if __name__ == "__main__":
    app()
