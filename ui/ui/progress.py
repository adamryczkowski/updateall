"""Progress display component using Rich."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class ProgressDisplay:
    """Real-time progress display for update operations.

    Uses Rich's Live display to show progress bars and status
    updates for each plugin as updates run.
    """

    def __init__(self, console: Console | None = None) -> None:
        """Initialize the progress display.

        Args:
            console: Optional Rich console to use. Creates one if not provided.
        """
        self.console = console or Console()
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.fields[plugin_name]}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TextColumn("{task.fields[status]}"),
            TimeElapsedColumn(),
            console=self.console,
        )
        self._live: Live | None = None
        self._tasks: dict[str, TaskID] = {}

    async def __aenter__(self) -> ProgressDisplay:
        """Start the live display."""
        self._live = Live(
            self._progress,
            console=self.console,
            refresh_per_second=10,
        )
        self._live.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()
            self._live = None

    def add_plugin_pending(self, plugin_name: str, total: int = 100) -> None:
        """Add a plugin in pending state (waiting to start).

        Args:
            plugin_name: Name of the plugin.
            total: Total steps for progress bar (default 100 for percentage).
        """
        task_id = self._progress.add_task(
            plugin_name,
            total=total,
            plugin_name=plugin_name,
            status="[dim]⏳ Pending...[/dim]",
            start=False,  # Don't start the task yet
        )
        self._tasks[plugin_name] = task_id

    def start_plugin(self, plugin_name: str, total: int = 100) -> None:
        """Start tracking a plugin's progress.

        If the plugin was already added as pending, this will start it.
        Otherwise, it will add and start the plugin.

        Args:
            plugin_name: Name of the plugin.
            total: Total steps for progress bar (default 100 for percentage).
        """
        if plugin_name in self._tasks:
            # Plugin was already added as pending, start it now
            self._progress.start_task(self._tasks[plugin_name])
            self._progress.update(
                self._tasks[plugin_name],
                status="Starting...",
            )
            return

        task_id = self._progress.add_task(
            plugin_name,
            total=total,
            plugin_name=plugin_name,
            status="Starting...",
        )
        self._tasks[plugin_name] = task_id

    def update_status(
        self,
        plugin_name: str,
        status: str,
        advance: int = 0,
    ) -> None:
        """Update a plugin's status message.

        Args:
            plugin_name: Name of the plugin.
            status: New status message.
            advance: Amount to advance the progress bar.
        """
        if plugin_name in self._tasks:
            self._progress.update(
                self._tasks[plugin_name],
                status=status,
                advance=advance,
            )

    def update_progress(self, plugin_name: str, completed: int) -> None:
        """Update a plugin's progress.

        Args:
            plugin_name: Name of the plugin.
            completed: Completed amount (out of total).
        """
        if plugin_name in self._tasks:
            self._progress.update(
                self._tasks[plugin_name],
                completed=completed,
            )

    def complete_plugin(
        self,
        plugin_name: str,
        *,
        success: bool,
        message: str | None = None,
    ) -> None:
        """Mark a plugin as complete.

        Args:
            plugin_name: Name of the plugin.
            success: Whether the update succeeded.
            message: Optional completion message.
        """
        if plugin_name in self._tasks:
            status = message or ("✓ Complete" if success else "✗ Failed")
            style = "green" if success else "red"
            self._progress.update(
                self._tasks[plugin_name],
                completed=100,
                status=f"[{style}]{status}[/{style}]",
            )

    def skip_plugin(self, plugin_name: str, reason: str = "Skipped") -> None:
        """Mark a plugin as skipped.

        Args:
            plugin_name: Name of the plugin.
            reason: Reason for skipping.
        """
        if plugin_name in self._tasks:
            self._progress.update(
                self._tasks[plugin_name],
                completed=100,
                status=f"[yellow]⊘ {reason}[/yellow]",
            )


@asynccontextmanager
async def progress_display(
    console: Console | None = None,
) -> AsyncIterator[ProgressDisplay]:
    """Context manager for progress display.

    Args:
        console: Optional Rich console to use.

    Yields:
        ProgressDisplay instance.
    """
    display = ProgressDisplay(console)
    async with display:
        yield display
