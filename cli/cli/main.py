"""Main CLI entry point for update-all.

This module defines the Typer application and main commands.
"""

from __future__ import annotations

import asyncio
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
) -> None:
    """Run system updates.

    Execute updates for all enabled plugins or specific plugins if specified.
    """
    asyncio.run(_run_updates(plugins, dry_run, verbose, continue_on_error))


async def _run_updates(
    plugin_names: list[str] | None,
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    continue_on_error: bool,
) -> None:
    """Run updates asynchronously."""
    from plugins import register_builtin_plugins
    from plugins.registry import PluginRegistry
    from ui.progress import ProgressDisplay

    from core import ConfigManager, Orchestrator

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

    console.print(f"Running {len(plugins_to_run)} plugin(s)...")

    # Create orchestrator
    orchestrator = Orchestrator(dry_run=dry_run, continue_on_error=continue_on_error)

    # Run with progress display
    async with ProgressDisplay(console) as progress:
        # Start tracking all plugins
        for plugin in plugins_to_run:
            progress.start_plugin(plugin.name)

        # Run plugins sequentially
        summary = await orchestrator.run_all(plugins_to_run, config.plugins)

        # Update progress display with results
        for result in summary.results:
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


if __name__ == "__main__":
    app()
