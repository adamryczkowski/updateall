"""Main CLI entry point for update-all.

This module defines the Typer application and main commands.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from . import __version__

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
    verbose: Annotated[  # noqa: ARG001
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output.",
        ),
    ] = False,
) -> None:
    """Run system updates.

    Execute updates for all enabled plugins or specific plugins if specified.
    """
    if dry_run:
        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")

    if plugins:
        console.print(f"Running plugins: {', '.join(plugins)}")
    else:
        console.print("Running all enabled plugins...")

    # TODO: Implement actual update execution
    console.print("[green]Update complete![/green]")


@app.command()
def status() -> None:
    """Show current system status.

    Display information about available plugins and their status.
    """
    console.print("[bold]System Status[/bold]")
    console.print("─" * 40)
    # TODO: Implement status display
    console.print("No plugins configured yet.")


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
    console.print(f"[bold]Update History[/bold] (last {limit} entries)")
    console.print("─" * 40)
    # TODO: Implement history display
    console.print("No history available yet.")


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
    console.print("[bold]Available Plugins[/bold]")
    console.print("─" * 40)
    # TODO: Implement plugin listing
    console.print("No plugins registered yet.")


@plugins_app.command("enable")
def plugins_enable(
    name: Annotated[str, typer.Argument(help="Plugin name to enable.")],
) -> None:
    """Enable a plugin."""
    console.print(f"Enabling plugin: {name}")
    # TODO: Implement plugin enabling


@plugins_app.command("disable")
def plugins_disable(
    name: Annotated[str, typer.Argument(help="Plugin name to disable.")],
) -> None:
    """Disable a plugin."""
    console.print(f"Disabling plugin: {name}")
    # TODO: Implement plugin disabling


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
    console.print("[bold]Current Configuration[/bold]")
    console.print("─" * 40)
    # TODO: Implement config display
    console.print("No configuration file found.")


@config_app.command("init")
def config_init(
    force: Annotated[  # noqa: ARG001
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing configuration.",
        ),
    ] = False,
) -> None:
    """Initialize configuration file."""
    console.print("Initializing configuration...")
    # TODO: Implement config initialization


if __name__ == "__main__":
    app()
