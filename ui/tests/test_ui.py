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

    def test_add_plugin_pending(self) -> None:
        """Test adding a plugin in pending state."""
        display = ProgressDisplay()

        display.add_plugin_pending("apt")

        assert "apt" in display._tasks

    def test_start_pending_plugin(self) -> None:
        """Test starting a plugin that was added as pending."""
        display = ProgressDisplay()
        display.add_plugin_pending("apt")

        # Starting should not create a new task, just update the existing one
        display.start_plugin("apt")

        assert "apt" in display._tasks


class TestPluginState:
    """Tests for PluginState enum."""

    def test_plugin_states(self) -> None:
        """Test all plugin states exist."""
        from ui.tabbed_run import PluginState

        assert PluginState.PENDING.value == "pending"
        assert PluginState.RUNNING.value == "running"
        assert PluginState.SUCCESS.value == "success"
        assert PluginState.FAILED.value == "failed"
        assert PluginState.SKIPPED.value == "skipped"
        assert PluginState.TIMEOUT.value == "timeout"


class TestPluginTab:
    """Tests for PluginTab dataclass."""

    def test_plugin_tab_creation(self) -> None:
        """Test creating a PluginTab."""
        from unittest.mock import MagicMock

        from ui.tabbed_run import PluginState, PluginTab

        mock_plugin = MagicMock()
        mock_plugin.name = "apt"

        tab = PluginTab(name="apt", plugin=mock_plugin)

        assert tab.name == "apt"
        assert tab.state == PluginState.PENDING
        assert tab.output_lines == []
        assert tab.packages_updated == 0


class TestPluginMessages:
    """Tests for plugin message classes."""

    def test_plugin_output_message(self) -> None:
        """Test PluginOutputMessage creation."""
        from ui.tabbed_run import PluginOutputMessage

        msg = PluginOutputMessage("apt", "Installing packages...")

        assert msg.plugin_name == "apt"
        assert msg.line == "Installing packages..."

    def test_plugin_state_changed(self) -> None:
        """Test PluginStateChanged creation."""
        from ui.tabbed_run import PluginState, PluginStateChanged

        msg = PluginStateChanged("apt", PluginState.RUNNING)

        assert msg.plugin_name == "apt"
        assert msg.state == PluginState.RUNNING

    def test_plugin_completed(self) -> None:
        """Test PluginCompleted creation."""
        from ui.tabbed_run import PluginCompleted

        msg = PluginCompleted("apt", success=True, packages_updated=5)

        assert msg.plugin_name == "apt"
        assert msg.success is True
        assert msg.packages_updated == 5
        assert msg.error_message is None

    def test_plugin_completed_with_error(self) -> None:
        """Test PluginCompleted with error."""
        from ui.tabbed_run import PluginCompleted

        msg = PluginCompleted("apt", success=False, error_message="Command failed")

        assert msg.plugin_name == "apt"
        assert msg.success is False
        assert msg.error_message == "Command failed"


# =============================================================================
# Phase 3 - UI Integration Tests
# =============================================================================


class TestPluginProgressMessage:
    """Tests for PluginProgressMessage (Phase 3)."""

    def test_progress_message_creation(self) -> None:
        """Test PluginProgressMessage creation."""
        from ui.tabbed_run import PluginProgressMessage

        msg = PluginProgressMessage(
            plugin_name="apt",
            phase="download",
            percent=45.5,
            message="Downloading packages...",
            bytes_downloaded=1024000,
            bytes_total=2048000,
        )

        assert msg.plugin_name == "apt"
        assert msg.phase == "download"
        assert msg.percent == 45.5
        assert msg.message == "Downloading packages..."
        assert msg.bytes_downloaded == 1024000
        assert msg.bytes_total == 2048000

    def test_progress_message_optional_fields(self) -> None:
        """Test PluginProgressMessage with optional fields."""
        from ui.tabbed_run import PluginProgressMessage

        msg = PluginProgressMessage(
            plugin_name="apt",
            phase="execute",
        )

        assert msg.plugin_name == "apt"
        assert msg.phase == "execute"
        assert msg.percent is None
        assert msg.message is None


class TestBatchedEvent:
    """Tests for BatchedEvent (Phase 3)."""

    def test_batched_event_creation(self) -> None:
        """Test BatchedEvent creation."""
        from ui.event_handler import BatchedEvent

        event = BatchedEvent(
            plugin_name="apt",
            event_type="output",
            data={"line": "Installing packages..."},
        )

        assert event.plugin_name == "apt"
        assert event.event_type == "output"
        assert event.data["line"] == "Installing packages..."
        assert event.timestamp is not None


class TestCallbackEventHandler:
    """Tests for CallbackEventHandler (Phase 3)."""

    def test_callback_handler_output(self) -> None:
        """Test CallbackEventHandler output handling."""
        from ui.event_handler import CallbackEventHandler

        outputs: list[tuple[str, str, str]] = []

        def on_output(plugin_name: str, line: str, stream: str) -> None:
            outputs.append((plugin_name, line, stream))

        handler = CallbackEventHandler(on_output=on_output)
        handler.handle_output("apt", "Installing...", "stdout")

        assert len(outputs) == 1
        assert outputs[0] == ("apt", "Installing...", "stdout")

    def test_callback_handler_progress(self) -> None:
        """Test CallbackEventHandler progress handling."""
        from ui.event_handler import CallbackEventHandler

        progress_updates: list[tuple[str, str, float | None, str | None]] = []

        def on_progress(
            plugin_name: str, phase: str, percent: float | None, message: str | None
        ) -> None:
            progress_updates.append((plugin_name, phase, percent, message))

        handler = CallbackEventHandler(on_progress=on_progress)
        handler.handle_progress("apt", "download", percent=50.0, message="Downloading...")

        assert len(progress_updates) == 1
        assert progress_updates[0] == ("apt", "download", 50.0, "Downloading...")

    def test_callback_handler_completion(self) -> None:
        """Test CallbackEventHandler completion handling."""
        from ui.event_handler import CallbackEventHandler

        completions: list[tuple[str, bool, int, int, str | None]] = []

        def on_completion(
            plugin_name: str,
            success: bool,
            exit_code: int,
            packages: int,
            error: str | None,
        ) -> None:
            completions.append((plugin_name, success, exit_code, packages, error))

        handler = CallbackEventHandler(on_completion=on_completion)
        handler.handle_completion("apt", success=True, exit_code=0, packages_updated=5)

        assert len(completions) == 1
        assert completions[0] == ("apt", True, 0, 5, None)


class TestStreamEventAdapter:
    """Tests for StreamEventAdapter (Phase 3)."""

    def test_adapter_handles_output_event(self) -> None:
        """Test StreamEventAdapter handles OutputEvent."""
        from datetime import UTC, datetime

        from core.streaming import EventType, OutputEvent
        from ui.event_handler import CallbackEventHandler, StreamEventAdapter

        outputs: list[tuple[str, str, str]] = []

        def on_output(plugin_name: str, line: str, stream: str) -> None:
            outputs.append((plugin_name, line, stream))

        handler = CallbackEventHandler(on_output=on_output)
        adapter = StreamEventAdapter(handler)

        event = OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name="apt",
            timestamp=datetime.now(tz=UTC),
            line="Installing...",
            stream="stdout",
        )

        adapter.handle_event(event)

        assert len(outputs) == 1
        assert outputs[0] == ("apt", "Installing...", "stdout")

    def test_adapter_handles_progress_event(self) -> None:
        """Test StreamEventAdapter handles ProgressEvent."""
        from datetime import UTC, datetime

        from core.streaming import EventType, Phase, ProgressEvent
        from ui.event_handler import CallbackEventHandler, StreamEventAdapter

        progress_updates: list[tuple[str, str, float | None, str | None]] = []

        def on_progress(
            plugin_name: str, phase: str, percent: float | None, message: str | None
        ) -> None:
            progress_updates.append((plugin_name, phase, percent, message))

        handler = CallbackEventHandler(on_progress=on_progress)
        adapter = StreamEventAdapter(handler)

        event = ProgressEvent(
            event_type=EventType.PROGRESS,
            plugin_name="apt",
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            percent=75.0,
            message="Downloading...",
        )

        adapter.handle_event(event)

        assert len(progress_updates) == 1
        assert progress_updates[0] == ("apt", "download", 75.0, "Downloading...")


class TestSudoStatus:
    """Tests for SudoStatus enum (Phase 3)."""

    def test_sudo_status_values(self) -> None:
        """Test SudoStatus enum values."""
        from ui.sudo import SudoStatus

        assert SudoStatus.AUTHENTICATED.value == "authenticated"
        assert SudoStatus.NOT_AUTHENTICATED.value == "not_authenticated"
        assert SudoStatus.NOT_AVAILABLE.value == "not_available"
        assert SudoStatus.PASSWORD_REQUIRED.value == "password_required"
        assert SudoStatus.NO_SUDO_REQUIRED.value == "no_sudo_required"


class TestSudoCheckResult:
    """Tests for SudoCheckResult (Phase 3)."""

    def test_sudo_check_result_creation(self) -> None:
        """Test SudoCheckResult creation."""
        from ui.sudo import SudoCheckResult, SudoStatus

        result = SudoCheckResult(
            status=SudoStatus.AUTHENTICATED,
            message="Sudo credentials are cached",
            user="testuser",
        )

        assert result.status == SudoStatus.AUTHENTICATED
        assert result.message == "Sudo credentials are cached"
        assert result.user == "testuser"


class TestStatusBarProgress:
    """Tests for StatusBar progress features (Phase 3)."""

    def test_status_bar_progress_bar_rendering(self) -> None:
        """Test StatusBar progress bar rendering."""
        from ui.tabbed_run import StatusBar

        bar = StatusBar("apt")

        # Test progress bar rendering
        result = bar._render_progress_bar(50.0, width=10)

        assert "█" in result
        assert "░" in result
        assert len(result) == 12  # 10 chars + 2 brackets

    def test_status_bar_progress_bar_full(self) -> None:
        """Test StatusBar progress bar at 100%."""
        from ui.tabbed_run import StatusBar

        bar = StatusBar("apt")

        result = bar._render_progress_bar(100.0, width=10)

        assert "░" not in result
        assert result.count("█") == 10

    def test_status_bar_progress_bar_empty(self) -> None:
        """Test StatusBar progress bar at 0%."""
        from ui.tabbed_run import StatusBar

        bar = StatusBar("apt")

        result = bar._render_progress_bar(0.0, width=10)

        assert "█" not in result
        assert result.count("░") == 10


class TestProgressPanelDownload:
    """Tests for ProgressPanel download features (Phase 3)."""

    def test_progress_panel_download_fields(self) -> None:
        """Test ProgressPanel download progress fields.

        Note: We can't call update_download_progress directly because it
        triggers _refresh_display() which requires an active Textual app.
        Instead, we test that the fields can be set and read correctly.
        """
        from ui.tabbed_run import ProgressPanel

        panel = ProgressPanel(total_plugins=3)

        # Set fields directly (as update_download_progress would)
        panel.total_bytes_downloaded = 50 * 1024 * 1024  # 50 MB
        panel.total_bytes_to_download = 100 * 1024 * 1024  # 100 MB

        assert panel.total_bytes_downloaded == 50 * 1024 * 1024
        assert panel.total_bytes_to_download == 100 * 1024 * 1024

    def test_progress_panel_initial_values(self) -> None:
        """Test ProgressPanel initial download values."""
        from ui.tabbed_run import ProgressPanel

        panel = ProgressPanel(total_plugins=5)

        assert panel.total_plugins == 5
        assert panel.completed_plugins == 0
        assert panel.successful_plugins == 0
        assert panel.failed_plugins == 0
        assert panel.total_bytes_downloaded == 0
        assert panel.total_bytes_to_download == 0


class TestPluginTabProgress:
    """Tests for PluginTab progress fields (Phase 3)."""

    def test_plugin_tab_progress_fields(self) -> None:
        """Test PluginTab progress tracking fields."""
        from unittest.mock import MagicMock

        from ui.tabbed_run import PluginTab

        mock_plugin = MagicMock()
        mock_plugin.name = "apt"

        tab = PluginTab(name="apt", plugin=mock_plugin)

        # Check default values
        assert tab.current_phase == ""
        assert tab.progress_percent == 0.0
        assert tab.progress_message == ""
        assert tab.bytes_downloaded == 0
        assert tab.bytes_total == 0

        # Update values
        tab.current_phase = "download"
        tab.progress_percent = 50.0
        tab.progress_message = "Downloading..."
        tab.bytes_downloaded = 1024000
        tab.bytes_total = 2048000

        assert tab.current_phase == "download"
        assert tab.progress_percent == 50.0
        assert tab.progress_message == "Downloading..."
        assert tab.bytes_downloaded == 1024000
        assert tab.bytes_total == 2048000
