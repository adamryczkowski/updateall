"""Table components for displaying results using Rich."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from core.models import PluginResult, UpdateStatus


class ResultsTable:
    """Formatted table for displaying update results.

    Displays plugin results in a nicely formatted table with
    status, timing, and package count information.
    """

    def __init__(self, console: Console | None = None, title: str = "Update Results") -> None:
        """Initialize the results table.

        Args:
            console: Optional Rich console to use.
            title: Table title.
        """
        self.console = console or Console()
        self.title = title
        self._results: list[PluginResult] = []

    def add_result(self, result: PluginResult) -> None:
        """Add a plugin result to the table.

        Args:
            result: Plugin result to add.
        """
        self._results.append(result)

    def add_results(self, results: list[PluginResult]) -> None:
        """Add multiple plugin results to the table.

        Args:
            results: List of plugin results to add.
        """
        self._results.extend(results)

    def clear(self) -> None:
        """Clear all results from the table."""
        self._results.clear()

    def _get_status_style(self, status: UpdateStatus) -> tuple[str, str]:
        """Get the display text and style for a status.

        Args:
            status: Update status.

        Returns:
            Tuple of (display_text, style).
        """
        from core.models import UpdateStatus

        status_map = {
            UpdateStatus.SUCCESS: ("✓ Success", "green"),
            UpdateStatus.FAILED: ("✗ Failed", "red"),
            UpdateStatus.TIMEOUT: ("⏱ Timeout", "yellow"),
            UpdateStatus.SKIPPED: ("⊘ Skipped", "dim"),
            UpdateStatus.RUNNING: ("⟳ Running", "blue"),
            UpdateStatus.PENDING: ("○ Pending", "dim"),
        }
        return status_map.get(status, (str(status), "white"))

    def _format_duration(self, result: PluginResult) -> str:
        """Format the duration of an update.

        Args:
            result: Plugin result.

        Returns:
            Formatted duration string.
        """
        if result.start_time and result.end_time:
            duration = (result.end_time - result.start_time).total_seconds()
            if duration < 60:
                return f"{duration:.1f}s"
            minutes = int(duration // 60)
            seconds = duration % 60
            return f"{minutes}m {seconds:.0f}s"
        return "-"

    def build_table(self) -> Table:
        """Build the Rich table.

        Returns:
            Rich Table object.
        """
        table = Table(title=self.title, show_header=True, header_style="bold")

        table.add_column("Plugin", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Duration", justify="right")
        table.add_column("Packages", justify="right")
        table.add_column("Message", style="dim")

        for result in self._results:
            status_text, status_style = self._get_status_style(result.status)
            duration = self._format_duration(result)
            packages = str(result.packages_updated) if result.packages_updated > 0 else "-"
            message = result.error_message or ""

            # Truncate long messages
            if len(message) > 50:
                message = message[:47] + "..."

            table.add_row(
                result.plugin_name,
                f"[{status_style}]{status_text}[/{status_style}]",
                duration,
                packages,
                message,
            )

        return table

    def render(self) -> None:
        """Render the table to the console."""
        table = self.build_table()
        self.console.print(table)

    def __rich__(self) -> Table:
        """Rich protocol support."""
        return self.build_table()
