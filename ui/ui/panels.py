"""Panel components for displaying summaries using Rich."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from core.models import PluginResult


class SummaryPanel:
    """Summary panel showing overall update status.

    Displays a summary of all update results including:
    - Total plugins run
    - Success/failure counts
    - Total packages updated
    - Total duration
    """

    def __init__(
        self,
        results: list[PluginResult] | None = None,
        console: Console | None = None,
    ) -> None:
        """Initialize the summary panel.

        Args:
            results: Optional list of plugin results.
            console: Optional Rich console to use.
        """
        self.console = console or Console()
        self._results: list[PluginResult] = results or []

    def add_result(self, result: PluginResult) -> None:
        """Add a plugin result.

        Args:
            result: Plugin result to add.
        """
        self._results.append(result)

    def set_results(self, results: list[PluginResult]) -> None:
        """Set all results.

        Args:
            results: List of plugin results.
        """
        self._results = list(results)

    def _count_by_status(self) -> dict[str, int]:
        """Count results by status.

        Returns:
            Dictionary mapping status names to counts.
        """
        from core.models import UpdateStatus

        counts: dict[str, int] = {
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "skipped": 0,
        }

        for result in self._results:
            if result.status == UpdateStatus.SUCCESS:
                counts["success"] += 1
            elif result.status == UpdateStatus.FAILED:
                counts["failed"] += 1
            elif result.status == UpdateStatus.TIMEOUT:
                counts["timeout"] += 1
            elif result.status == UpdateStatus.SKIPPED:
                counts["skipped"] += 1

        return counts

    def _total_packages(self) -> int:
        """Get total packages updated.

        Returns:
            Total number of packages updated.
        """
        return sum(r.packages_updated for r in self._results)

    def _total_duration(self) -> float:
        """Get total duration in seconds.

        Returns:
            Total duration of all updates.
        """
        total = 0.0
        for result in self._results:
            if result.start_time and result.end_time:
                total += (result.end_time - result.start_time).total_seconds()
        return total

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted duration string.
        """
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        minutes = int(seconds // 60)
        secs = seconds % 60
        if minutes < 60:
            return f"{minutes}m {secs:.0f}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"

    def build_panel(self) -> Panel:
        """Build the Rich panel.

        Returns:
            Rich Panel object.
        """
        counts = self._count_by_status()
        total_packages = self._total_packages()
        total_duration = self._total_duration()

        # Build summary text
        lines: list[Text] = []

        # Status line
        status_parts: list[str] = []
        if counts["success"] > 0:
            status_parts.append(f"[green]✓ {counts['success']} succeeded[/green]")
        if counts["failed"] > 0:
            status_parts.append(f"[red]✗ {counts['failed']} failed[/red]")
        if counts["timeout"] > 0:
            status_parts.append(f"[yellow]⏱ {counts['timeout']} timed out[/yellow]")
        if counts["skipped"] > 0:
            status_parts.append(f"[dim]⊘ {counts['skipped']} skipped[/dim]")

        status_line = Text.from_markup("  ".join(status_parts) if status_parts else "No results")
        lines.append(status_line)

        # Packages line
        if total_packages > 0:
            packages_line = Text.from_markup(f"\n📦 [bold]{total_packages}[/bold] packages updated")
            lines.append(packages_line)

        # Duration line
        duration_line = Text.from_markup(
            f"\n⏱  Total time: [bold]{self._format_duration(total_duration)}[/bold]"
        )
        lines.append(duration_line)

        # Determine overall status for panel style
        if counts["failed"] > 0 or counts["timeout"] > 0:
            border_style = "red" if counts["failed"] > 0 else "yellow"
            title = "⚠️  Update Summary"
        elif counts["success"] > 0:
            border_style = "green"
            title = "✅ Update Summary"
        else:
            border_style = "dim"
            title = "Update Summary"

        content = Group(*lines)
        return Panel(
            content,
            title=title,
            border_style=border_style,
            padding=(1, 2),
        )

    def render(self) -> None:
        """Render the panel to the console."""
        panel = self.build_panel()
        self.console.print(panel)

    def __rich__(self) -> Panel:
        """Rich protocol support."""
        return self.build_panel()
