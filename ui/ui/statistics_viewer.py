"""Statistics viewer Textual application.

This module provides an interactive TUI for viewing historical update statistics
stored in the database. It allows browsing through previous updates, downloads,
and upgrades with detailed metrics.

Task 3: Add another mode for viewing database statistics.
Available via: `update-all statistics`
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import MouseScrollDown, MouseScrollUp  # noqa: TC002 - Required at runtime
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static

if TYPE_CHECKING:
    from stats.retrieval.queries import PluginStats


class StatsSummaryPanel(Static):
    """Panel showing summary statistics for all plugins."""

    DEFAULT_CSS = """
    StatsSummaryPanel {
        height: auto;
        padding: 1;
        background: $surface;
        border: solid $primary;
        margin-bottom: 1;
    }

    StatsSummaryPanel .title {
        text-style: bold;
        color: $primary;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the summary panel."""
        super().__init__(name=name, id=id, classes=classes)
        self._stats: list[PluginStats] = []

    def update_stats(self, stats: list[PluginStats]) -> None:
        """Update the summary with new statistics.

        Args:
            stats: List of PluginStats for all plugins.
        """
        self._stats = stats
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the summary display."""
        if not self._stats:
            self.update("No statistics available. Run some updates first!")
            return

        total_executions = sum(s.execution_count for s in self._stats)
        total_success = sum(s.success_count for s in self._stats)
        total_packages = sum(s.total_packages_updated for s in self._stats)
        overall_success_rate = total_success / total_executions if total_executions > 0 else 0.0

        text = Text()
        text.append("📊 Statistics Summary\n", style="bold cyan")
        text.append(f"  Plugins tracked: {len(self._stats)}\n")
        text.append(f"  Total executions: {total_executions}\n")
        text.append(f"  Overall success rate: {overall_success_rate:.1%}\n")
        text.append(f"  Total packages updated: {total_packages}\n")

        self.update(text)


class ExecutionDetailsPanel(Static):
    """Panel showing details for a selected execution."""

    DEFAULT_CSS = """
    ExecutionDetailsPanel {
        height: auto;
        min-height: 10;
        padding: 1;
        background: $surface;
        border: solid $primary;
    }

    ExecutionDetailsPanel .title {
        text-style: bold;
        color: $primary;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the details panel."""
        super().__init__(name=name, id=id, classes=classes)
        self._execution: dict[str, object] | None = None

    def update_execution(self, execution: dict[str, object] | None) -> None:
        """Update the panel with execution details.

        Args:
            execution: Dictionary containing execution details.
        """
        self._execution = execution
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the details display."""
        if not self._execution:
            self.update("Select an execution to view details")
            return

        text = Text()
        text.append("📋 Execution Details\n\n", style="bold cyan")

        # Basic info
        text.append("Plugin: ", style="bold")
        text.append(f"{self._execution.get('plugin_name', 'N/A')}\n")

        text.append("Status: ", style="bold")
        status = self._execution.get("status", "unknown")
        status_style = "green" if status == "success" else "red"
        text.append(f"{status}\n", style=status_style)

        text.append("Execution ID: ", style="bold")
        text.append(f"{self._execution.get('execution_id', 'N/A')}\n")

        text.append("Run ID: ", style="bold")
        text.append(f"{self._execution.get('run_id', 'N/A')}\n\n")

        # Timing
        text.append("⏱️ Timing\n", style="bold yellow")
        start_time = self._execution.get("start_time")
        end_time = self._execution.get("end_time")
        if isinstance(start_time, datetime):
            text.append(f"  Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        if isinstance(end_time, datetime):
            text.append(f"  End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        wall_clock = self._execution.get("wall_clock_seconds")
        if wall_clock is not None:
            text.append(f"  Wall clock: {wall_clock:.1f}s\n")

        cpu_seconds = self._execution.get("cpu_user_seconds")
        if cpu_seconds is not None:
            text.append(f"  CPU time: {cpu_seconds:.1f}s\n")

        text.append("\n")

        # Resources
        text.append("💾 Resources\n", style="bold yellow")
        download_bytes = self._execution.get("download_size_bytes")
        if download_bytes is not None and isinstance(download_bytes, (int, float)):
            text.append(f"  Download: {self._format_bytes(download_bytes)}\n")

        memory_bytes = self._execution.get("memory_peak_bytes")
        if memory_bytes is not None and isinstance(memory_bytes, (int, float)):
            text.append(f"  Peak memory: {self._format_bytes(memory_bytes)}\n")

        text.append("\n")

        # Packages
        text.append("📦 Packages\n", style="bold yellow")
        text.append(f"  Updated: {self._execution.get('packages_updated', 0)}\n")
        text.append(f"  Total: {self._execution.get('packages_total', 'N/A')}\n")

        # Error message if present
        error_msg = self._execution.get("error_message")
        if error_msg:
            text.append("\n")
            text.append("❌ Error\n", style="bold red")
            text.append(f"  {error_msg}\n", style="red")

        self.update(text)

    def _format_bytes(self, byte_count: int | float | None) -> str:
        """Format byte count with appropriate unit."""
        if byte_count is None:
            return "N/A"
        byte_count = int(byte_count)
        if byte_count < 1024:
            return f"{byte_count} B"
        if byte_count < 1024 * 1024:
            return f"{byte_count / 1024:.1f} KB"
        if byte_count < 1024 * 1024 * 1024:
            return f"{byte_count / (1024 * 1024):.1f} MB"
        return f"{byte_count / (1024 * 1024 * 1024):.2f} GB"


class StatisticsViewerApp(App[None]):
    """Textual application for viewing historical update statistics.

    This app provides an interactive interface to browse through previous
    updates, downloads, and upgrades with detailed metrics for each execution.

    Key bindings:
    - q: Quit the application
    - r: Refresh data from database
    - Up/Down: Navigate through executions
    - Page Up/Down: Navigate faster
    - Home/End: Jump to first/last execution
    """

    TITLE = "Update-All Statistics Viewer"
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2;
        grid-columns: 2fr 1fr;
    }

    #left-panel {
        height: 100%;
        padding: 1;
    }

    #right-panel {
        height: 100%;
        padding: 1;
    }

    #executions-table {
        height: 1fr;
        border: solid $primary;
    }

    DataTable > .datatable--cursor {
        background: $accent;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "quit", "Quit", show=False),
    ]

    # Reactive properties
    selected_execution: reactive[dict[str, object] | None] = reactive(None)

    def __init__(self, days: int = 90) -> None:
        """Initialize the statistics viewer.

        Args:
            days: Number of days to look back for statistics.
        """
        super().__init__()
        self._days = days
        self._executions: list[dict[str, object]] = []
        self._plugin_stats: list[PluginStats] = []

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()

        with Horizontal():
            with Vertical(id="left-panel"):
                yield StatsSummaryPanel(id="summary-panel")
                yield DataTable(id="executions-table")

            with Vertical(id="right-panel"):
                yield ExecutionDetailsPanel(id="details-panel")

        yield Footer()

    async def on_mount(self) -> None:
        """Handle mount event - load initial data."""
        await self._load_data()

    async def _load_data(self) -> None:
        """Load data from the database."""
        from stats.retrieval.queries import HistoricalDataQuery

        query = HistoricalDataQuery()

        # Load plugin statistics
        self._plugin_stats = query.get_all_plugins_summary(days=self._days)

        # Load recent executions
        self._executions = query.get_recent_executions(limit=500)

        # Update summary panel
        summary_panel = self.query_one("#summary-panel", StatsSummaryPanel)
        summary_panel.update_stats(self._plugin_stats)

        # Populate executions table
        table = self.query_one("#executions-table", DataTable)
        table.clear(columns=True)

        # Add columns
        table.add_columns(
            "Plugin",
            "Status",
            "Date",
            "Wall Time",
            "CPU Time",
            "Download",
            "Packages",
        )

        # Add rows
        for execution in self._executions:
            plugin_name = str(execution.get("plugin_name", ""))
            status = str(execution.get("status", ""))
            status_text = Text(status, style="green" if status == "success" else "red")

            start_time = execution.get("start_time")
            date_str = ""
            if isinstance(start_time, datetime):
                date_str = start_time.strftime("%Y-%m-%d %H:%M")

            wall_clock = execution.get("wall_clock_seconds")
            wall_str = f"{wall_clock:.1f}s" if wall_clock is not None else "N/A"

            cpu_seconds = execution.get("cpu_user_seconds")
            cpu_str = f"{cpu_seconds:.1f}s" if cpu_seconds is not None else "N/A"

            download_bytes = execution.get("download_size_bytes")
            if isinstance(download_bytes, (int, float)):
                download_str = self._format_bytes(download_bytes)
            else:
                download_str = "N/A"

            packages = execution.get("packages_updated", 0)

            table.add_row(
                plugin_name,
                status_text,
                date_str,
                wall_str,
                cpu_str,
                download_str,
                str(packages),
            )

        # Select first row if available
        if self._executions:
            table.cursor_coordinate = (0, 0)
            self.selected_execution = self._executions[0]

    def _format_bytes(self, byte_count: int | float | None) -> str:
        """Format byte count with appropriate unit."""
        if byte_count is None:
            return "N/A"
        byte_count = int(byte_count)
        if byte_count < 1024:
            return f"{byte_count} B"
        if byte_count < 1024 * 1024:
            return f"{byte_count / 1024:.1f} KB"
        if byte_count < 1024 * 1024 * 1024:
            return f"{byte_count / (1024 * 1024):.1f} MB"
        return f"{byte_count / (1024 * 1024 * 1024):.2f} GB"

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the executions table.

        Args:
            event: The row selection event.
        """
        row_index = event.cursor_row
        if 0 <= row_index < len(self._executions):
            self.selected_execution = self._executions[row_index]

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight in the executions table.

        Args:
            event: The row highlight event.
        """
        row_index = event.cursor_row
        if 0 <= row_index < len(self._executions):
            self.selected_execution = self._executions[row_index]

    def watch_selected_execution(self, execution: dict[str, object] | None) -> None:
        """React to selected execution changes.

        Args:
            execution: The newly selected execution.
        """
        details_panel = self.query_one("#details-panel", ExecutionDetailsPanel)
        details_panel.update_execution(execution)

    async def action_refresh(self) -> None:
        """Refresh data from the database."""
        await self._load_data()
        self.notify("Data refreshed", severity="information")

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Handle mouse scroll up for table navigation.

        Args:
            event: The mouse scroll up event.
        """
        table = self.query_one("#executions-table", DataTable)
        if table.has_focus:
            table.action_cursor_up()
            event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Handle mouse scroll down for table navigation.

        Args:
            event: The mouse scroll down event.
        """
        table = self.query_one("#executions-table", DataTable)
        if table.has_focus:
            table.action_cursor_down()
            event.stop()


def run_statistics_viewer(days: int = 90) -> None:
    """Run the statistics viewer application.

    Args:
        days: Number of days to look back for statistics.
    """
    app = StatisticsViewerApp(days=days)
    app.run()
