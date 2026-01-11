"""Phase status bar widget with per-tab metrics display.

This module provides a PhaseStatusBar widget that displays runtime metrics
for each terminal pane, including status, ETA, resource usage, and progress.

UI Revision Plan - Phase 3 Status Bar
See docs/UI-revision-plan.md section 3.4

Milestone 3 - Textual Library Usage Review and Fixes
See docs/cleanup-and-refactoring-plan.md section 3.3.1

Milestone 4 - UI Module Architecture Refactoring
See docs/cleanup-and-refactoring-plan.md section 4.3.2

Enhanced to 5-line display with statistics table showing:
- Phase rows: Update, Download, Upgrade, Total
- Columns: Phase, Time, Data, CPU Time, Wall Time, Packages, Peak Memory
- Running progress summary with predictions

The metrics collection classes have been moved to ui/ui/metrics.py for
better separation of concerns. This module now focuses solely on the
PhaseStatusBar widget for displaying metrics.
"""

from __future__ import annotations

import logging

from textual.reactive import reactive
from textual.widgets import Static

from ui.metrics import (
    MetricsCollector,
    PhaseMetrics,
    PhaseStats,
    RunningProgress,
)

# Logger for UI latency debugging
# Enable with: logging.getLogger("ui.latency").setLevel(logging.DEBUG)
_latency_logger = logging.getLogger("ui.latency")

# CSS styles for the phase status bar (5 lines)
PHASE_STATUS_BAR_CSS = """
/* Phase Status Bar Styles - 5 lines with statistics table */
/* See docs/UI-revision-plan.md section 3.4 */

PhaseStatusBar {
    height: 6;
    dock: bottom;
    padding: 0 1;
    background: $surface;
    color: $text;
    border-top: solid $primary;
}

PhaseStatusBar.error {
    border-top: solid $error;
}

PhaseStatusBar.paused {
    border-top: solid $warning;
}

PhaseStatusBar .status-line {
    width: 100%;
    color: $text;
}

PhaseStatusBar .metrics-line {
    width: 100%;
    color: $text-muted;
}

PhaseStatusBar .error-indicator {
    color: $error;
}

PhaseStatusBar .table-header {
    color: $text;
    text-style: bold;
}

PhaseStatusBar .phase-running {
    color: $warning;
}

PhaseStatusBar .phase-complete {
    color: $success;
}
"""


class PhaseStatusBar(Static):
    """Status bar widget showing per-tab metrics in a 5-line table format.

    This widget displays runtime metrics for a terminal pane in a
    five-line format with a statistics table:
    - Line 1: Table header (Phase | Time | Data | CPU | Wall | Pkgs | Mem)
    - Line 2: Update phase row
    - Line 3: Download phase row
    - Line 4: Upgrade phase row
    - Line 5: Total row + Running progress summary

    Example:
        status_bar = PhaseStatusBar(pane_id="apt")
        status_bar.update_metrics(PhaseMetrics(
            status="In Progress",
            cpu_percent=45.0,
            memory_mb=128.0,
        ))
    """

    DEFAULT_CSS = PHASE_STATUS_BAR_CSS

    # Default UI refresh rate in Hz (30 Hz = ~33ms between refreshes)
    # This is the rate at which the UI reads cached metrics and updates display.
    # The actual metrics collection (psutil) happens at a lower frequency (1 Hz)
    # in a background thread to avoid blocking the UI.
    DEFAULT_UI_REFRESH_RATE: float = 30.0

    # Reactive properties for automatic refresh
    metrics: reactive[PhaseMetrics] = reactive(PhaseMetrics, always_update=True)

    def __init__(
        self,
        pane_id: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        ui_refresh_rate: float | None = None,
    ) -> None:
        """Initialize the status bar.

        Args:
            pane_id: ID of the associated terminal pane.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
            ui_refresh_rate: UI refresh rate in Hz (default: 30.0).
                This controls how often the status bar reads cached metrics
                and updates the display. The actual metrics collection
                happens at a lower frequency in a background thread.
        """
        super().__init__(name=name, id=id or f"status-bar-{pane_id}", classes=classes)
        self.pane_id = pane_id
        self._metrics_collector: MetricsCollector | None = None
        self._ui_refresh_rate = ui_refresh_rate or self.DEFAULT_UI_REFRESH_RATE

    def on_mount(self) -> None:
        """Called when the widget is mounted to the DOM.

        Sets up auto_refresh to enable high-frequency UI updates.
        The auto_refresh property tells Textual to call automatic_refresh()
        at the specified interval, allowing the status bar to update
        smoothly without waiting for metrics collection.
        """
        # Set auto_refresh to trigger at the configured UI refresh rate
        # This is 1/rate seconds (e.g., 1/30 = 0.033s for 30 Hz)
        self.auto_refresh = 1.0 / self._ui_refresh_rate

    def automatic_refresh(self) -> None:
        """Called automatically by Textual at the auto_refresh interval.

        This method reads cached metrics from the collector (fast, no psutil)
        and updates the display. The actual metrics collection happens in
        a background thread at a lower frequency (1 Hz).

        This decouples UI refresh rate from metrics collection rate,
        allowing smooth 30 Hz UI updates while expensive psutil calls
        happen only once per second.
        """
        if self._metrics_collector:
            # Read cached metrics (fast, no psutil call)
            self.metrics = self._metrics_collector.cached_metrics
            _latency_logger.debug(
                "UI refresh for pane %s (rate: %.1f Hz)",
                self.pane_id,
                self._ui_refresh_rate,
            )
        # Note: _refresh_display() is called automatically via watch_metrics

    def watch_metrics(self, metrics: PhaseMetrics) -> None:
        """React to metrics changes.

        Args:
            metrics: New metrics to display.
        """
        self._refresh_display()

        # Update CSS classes based on state
        self.remove_class("error", "paused")
        if metrics.error_message:
            self.add_class("error")
        if metrics.pause_after_phase:
            self.add_class("paused")

    def update_metrics(self, metrics: PhaseMetrics) -> None:
        """Update the displayed metrics.

        Args:
            metrics: New metrics to display.
        """
        self.metrics = metrics

    def set_metrics_collector(self, collector: MetricsCollector) -> None:
        """Set the metrics collector for automatic updates.

        Args:
            collector: MetricsCollector instance to use.
        """
        self._metrics_collector = collector

    def collect_and_update(self) -> None:
        """Collect metrics from the collector and update display."""
        if self._metrics_collector:
            self.metrics = self._metrics_collector.collect()

    def _refresh_display(self) -> None:
        """Refresh the status bar content with 5-line table format."""
        m = self.metrics

        # Get phase stats from collector if available
        if self._metrics_collector:
            phase_stats = self._metrics_collector.phase_stats
            total_stats = self._metrics_collector.get_total_stats()
            progress = self._metrics_collector.get_running_progress()
        else:
            # Default empty stats
            phase_stats = {
                "Update": PhaseStats("Update"),
                "Download": PhaseStats("Download"),
                "Upgrade": PhaseStats("Upgrade"),
            }
            total_stats = PhaseStats("Total")
            progress = RunningProgress()

        # Column widths for consistent alignment
        # Phase: 10 chars (includes 2-char status indicator space)
        # Wall: 8 chars, Data: 10 chars, CPU: 8 chars, Pkgs: 6 chars, Mem: 8 chars
        # Removed redundant "Time" column (was same as "Wall")
        col_phase = 10
        col_wall = 8
        col_data = 10
        col_cpu = 8
        col_pkgs = 6
        col_mem = 8

        # Build table header with column widths for alignment
        header = (
            f"{'Phase':<{col_phase}} │ {'Wall':>{col_wall}} │ {'Data':>{col_data}} │ "
            f"{'CPU':>{col_cpu}} │ {'Pkgs':>{col_pkgs}} │ {'Mem':>{col_mem}}"
        )

        # Format each phase row
        def format_phase_row(stats: PhaseStats) -> str:
            # Status indicator: 2 chars (indicator + space, or 2 spaces)
            if stats.is_running:
                status_indicator = "▶ "
            elif stats.is_complete:
                status_indicator = "✓ "
            else:
                status_indicator = "  "

            # Phase name: remaining chars after status indicator
            phase_width = col_phase - 2
            phase_cell = f"{status_indicator}{stats.phase_name:<{phase_width}}"

            # Format memory with consistent width
            mem_str = f"{stats.peak_memory_mb:.0f}MB"

            return (
                f"{phase_cell} │ "
                f"{self._format_duration(stats.wall_time_seconds):>{col_wall}} │ "
                f"{self._format_bytes(stats.data_bytes):>{col_data}} │ "
                f"{self._format_duration(stats.cpu_time_seconds):>{col_cpu}} │ "
                f"{stats.packages:>{col_pkgs}} │ "
                f"{mem_str:>{col_mem}}"
            )

        update_row = format_phase_row(phase_stats["Update"])
        download_row = format_phase_row(phase_stats["Download"])
        upgrade_row = format_phase_row(phase_stats["Upgrade"])

        # Total row
        total_row = format_phase_row(total_stats)

        # Running progress summary (only show meaningful items)
        progress_parts = []
        if progress.predicted_wall_time_left is not None:
            progress_parts.append(
                f"ETA: {self._format_duration(progress.predicted_wall_time_left)}"
            )
        if progress.predicted_download_left is not None and progress.predicted_download_left > 0:
            progress_parts.append(
                f"DL Left: {self._format_bytes(progress.predicted_download_left)}"
            )

        # Add error indicator if needed
        if m.error_message:
            progress_parts.append(f"[red]⚠ {m.error_message}[/red]")

        # Pause indicator
        if m.pause_after_phase:
            progress_parts.append("[yellow]⏸ Pause[/yellow]")

        # Build progress summary (may be empty if no predictions/errors)
        progress_summary = " │ ".join(progress_parts) if progress_parts else ""

        # Combine all lines
        if progress_summary:
            content = f"{header}\n{update_row}\n{download_row}\n{upgrade_row}\n{total_row} │ {progress_summary}"
        else:
            content = f"{header}\n{update_row}\n{download_row}\n{upgrade_row}\n{total_row}"

        self.update(content)

    def _format_eta(
        self,
        eta_seconds: float | None,
        error_seconds: float | None,
    ) -> str:
        """Format ETA with optional error margin.

        Args:
            eta_seconds: ETA in seconds, or None.
            error_seconds: Error margin in seconds, or None.

        Returns:
            Formatted ETA string.
        """
        if eta_seconds is None:
            return "N/A"

        eta_str = self._format_duration(eta_seconds)
        if error_seconds is not None:
            error_str = self._format_duration(error_seconds)
            return f"{eta_str} (±{error_str})"
        return eta_str

    def _format_items(self, completed: int, total: int | None) -> str:
        """Format items progress.

        Args:
            completed: Number of items completed.
            total: Total number of items, or None.

        Returns:
            Formatted items string.
        """
        if total is not None:
            return f"Items: {completed}/{total}"
        if completed > 0:
            return f"Items: {completed}"
        return "Items: --"

    def _format_bytes(self, byte_count: int) -> str:
        """Format byte count with appropriate unit.

        Args:
            byte_count: Number of bytes.

        Returns:
            Formatted string with unit (B, KB, MB, GB).
        """
        if byte_count < 1024:
            return f"{byte_count} B"
        if byte_count < 1024 * 1024:
            return f"{byte_count / 1024:.1f} KB"
        if byte_count < 1024 * 1024 * 1024:
            return f"{byte_count / (1024 * 1024):.1f} MB"
        return f"{byte_count / (1024 * 1024 * 1024):.2f} GB"

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted duration string (e.g., "2m 30s").
        """
        if seconds < 0:
            return "N/A"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
