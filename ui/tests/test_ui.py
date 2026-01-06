"""Tests for UI components."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from rich.console import Console

from core.models import PluginResult, UpdateStatus
from ui.panels import SummaryPanel
from ui.progress import ProgressDisplay
from ui.tables import ResultsTable


def make_result(
    plugin_name: str,
    status: UpdateStatus,
    packages: int = 0,
    duration_seconds: float = 10.0,
    error: str | None = None,
) -> PluginResult:
    """Create a test PluginResult."""
    start = datetime.now(tz=UTC)
    end = start + timedelta(seconds=duration_seconds)
    return PluginResult(
        plugin_name=plugin_name,
        status=status,
        start_time=start,
        end_time=end,
        output="test output",
        error_message=error,
        packages_updated=packages,
    )


class TestResultsTable:
    """Tests for ResultsTable."""

    def test_add_result(self) -> None:
        """Test adding a result."""
        table = ResultsTable()
        result = make_result("apt", UpdateStatus.SUCCESS, packages=5)

        table.add_result(result)

        assert len(table._results) == 1

    def test_add_results(self) -> None:
        """Test adding multiple results."""
        table = ResultsTable()
        results = [
            make_result("apt", UpdateStatus.SUCCESS),
            make_result("pipx", UpdateStatus.FAILED),
        ]

        table.add_results(results)

        assert len(table._results) == 2

    def test_clear(self) -> None:
        """Test clearing results."""
        table = ResultsTable()
        table.add_result(make_result("apt", UpdateStatus.SUCCESS))

        table.clear()

        assert len(table._results) == 0

    def test_build_table(self) -> None:
        """Test building the Rich table."""
        table = ResultsTable(title="Test Results")
        table.add_result(make_result("apt", UpdateStatus.SUCCESS, packages=5))

        rich_table = table.build_table()

        assert rich_table.title == "Test Results"
        assert rich_table.row_count == 1

    def test_render_to_console(self) -> None:
        """Test rendering to console."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=100)
        table = ResultsTable(console=console)
        table.add_result(make_result("apt", UpdateStatus.SUCCESS, packages=5))

        table.render()

        rendered = output.getvalue()
        assert "apt" in rendered
        assert "Success" in rendered


class TestSummaryPanel:
    """Tests for SummaryPanel."""

    def test_count_by_status(self) -> None:
        """Test counting results by status."""
        panel = SummaryPanel()
        panel.add_result(make_result("apt", UpdateStatus.SUCCESS))
        panel.add_result(make_result("pipx", UpdateStatus.SUCCESS))
        panel.add_result(make_result("flatpak", UpdateStatus.FAILED))

        counts = panel._count_by_status()

        assert counts["success"] == 2
        assert counts["failed"] == 1
        assert counts["timeout"] == 0

    def test_total_packages(self) -> None:
        """Test total packages calculation."""
        panel = SummaryPanel()
        panel.add_result(make_result("apt", UpdateStatus.SUCCESS, packages=5))
        panel.add_result(make_result("pipx", UpdateStatus.SUCCESS, packages=3))

        total = panel._total_packages()

        assert total == 8

    def test_total_duration(self) -> None:
        """Test total duration calculation."""
        panel = SummaryPanel()
        panel.add_result(make_result("apt", UpdateStatus.SUCCESS, duration_seconds=10.0))
        panel.add_result(make_result("pipx", UpdateStatus.SUCCESS, duration_seconds=5.0))

        duration = panel._total_duration()

        assert duration == pytest.approx(15.0, rel=0.1)

    def test_format_duration_seconds(self) -> None:
        """Test duration formatting for seconds."""
        panel = SummaryPanel()

        result = panel._format_duration(45.5)

        assert "45.5" in result
        assert "second" in result

    def test_format_duration_minutes(self) -> None:
        """Test duration formatting for minutes."""
        panel = SummaryPanel()

        result = panel._format_duration(125.0)

        assert "2m" in result

    def test_build_panel(self) -> None:
        """Test building the Rich panel."""
        panel = SummaryPanel()
        panel.add_result(make_result("apt", UpdateStatus.SUCCESS, packages=5))

        rich_panel = panel.build_panel()

        assert rich_panel is not None

    def test_render_to_console(self) -> None:
        """Test rendering to console."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=100)
        panel = SummaryPanel(console=console)
        panel.add_result(make_result("apt", UpdateStatus.SUCCESS, packages=5))

        panel.render()

        rendered = output.getvalue()
        assert "Summary" in rendered


class TestProgressDisplay:
    """Tests for ProgressDisplay."""

    def test_start_plugin(self) -> None:
        """Test starting a plugin."""
        display = ProgressDisplay()

        display.start_plugin("apt")

        assert "apt" in display._tasks

    def test_update_status(self) -> None:
        """Test updating status."""
        display = ProgressDisplay()
        display.start_plugin("apt")

        # Should not raise
        display.update_status("apt", "Updating...")

    def test_complete_plugin_success(self) -> None:
        """Test completing a plugin successfully."""
        display = ProgressDisplay()
        display.start_plugin("apt")

        # Should not raise
        display.complete_plugin("apt", success=True)

    def test_complete_plugin_failure(self) -> None:
        """Test completing a plugin with failure."""
        display = ProgressDisplay()
        display.start_plugin("apt")

        # Should not raise
        display.complete_plugin("apt", success=False, message="Error occurred")

    def test_skip_plugin(self) -> None:
        """Test skipping a plugin."""
        display = ProgressDisplay()
        display.start_plugin("apt")

        # Should not raise
        display.skip_plugin("apt", reason="Not available")
