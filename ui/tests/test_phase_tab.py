"""Tests for phase_tab module.

Phase 2 - Visual Enhancements
See docs/UI-revision-plan.md section 5.2
"""

from __future__ import annotations

from ui.phase_tab import (
    PHASE_TAB_CSS,
    TAB_STATUS_COLORS,
    TAB_STATUS_CSS_CLASSES,
    TAB_STATUS_ICONS,
    DisplayPhase,
    TabStatus,
    determine_tab_status,
    determine_tab_status_from_pane_state,
    get_display_phase,
    get_tab_css_class,
    get_tab_label,
)
from ui.terminal_pane import PaneState


class TestDisplayPhase:
    """Tests for DisplayPhase enum."""

    def test_display_phase_values(self) -> None:
        """Test that DisplayPhase has expected values."""
        assert DisplayPhase.UPDATE.value == "Update"
        assert DisplayPhase.DOWNLOAD.value == "Download"
        assert DisplayPhase.UPGRADE.value == "Upgrade"
        assert DisplayPhase.PENDING.value == "Pending"
        assert DisplayPhase.COMPLETE.value == "Complete"

    def test_display_phase_is_string_enum(self) -> None:
        """Test that DisplayPhase values are strings."""
        for phase in DisplayPhase:
            assert isinstance(phase.value, str)


class TestGetDisplayPhase:
    """Tests for get_display_phase function."""

    def test_none_returns_pending(self) -> None:
        """Test that None phase returns PENDING."""
        result = get_display_phase(None)
        assert result == DisplayPhase.PENDING

    def test_check_phase_returns_update(self) -> None:
        """Test that CHECK phase maps to UPDATE."""
        from core.streaming import Phase

        result = get_display_phase(Phase.CHECK)
        assert result == DisplayPhase.UPDATE

    def test_download_phase_returns_download(self) -> None:
        """Test that DOWNLOAD phase maps to DOWNLOAD."""
        from core.streaming import Phase

        result = get_display_phase(Phase.DOWNLOAD)
        assert result == DisplayPhase.DOWNLOAD

    def test_execute_phase_returns_upgrade(self) -> None:
        """Test that EXECUTE phase maps to UPGRADE."""
        from core.streaming import Phase

        result = get_display_phase(Phase.EXECUTE)
        assert result == DisplayPhase.UPGRADE


class TestTabStatus:
    """Tests for TabStatus enum."""

    def test_tab_status_values(self) -> None:
        """Test that TabStatus has expected values."""
        assert TabStatus.COMPLETED.value == "completed"
        assert TabStatus.RUNNING.value == "running"
        assert TabStatus.ERROR.value == "error"
        assert TabStatus.PENDING.value == "pending"
        assert TabStatus.LOCKED.value == "locked"

    def test_all_statuses_have_colors(self) -> None:
        """Test that all statuses have color mappings."""
        for status in TabStatus:
            assert status in TAB_STATUS_COLORS
            assert isinstance(TAB_STATUS_COLORS[status], str)

    def test_all_statuses_have_icons(self) -> None:
        """Test that all statuses have icon mappings."""
        for status in TabStatus:
            assert status in TAB_STATUS_ICONS
            assert isinstance(TAB_STATUS_ICONS[status], str)
            # Icons should be non-empty
            assert len(TAB_STATUS_ICONS[status]) > 0

    def test_all_statuses_have_css_classes(self) -> None:
        """Test that all statuses have CSS class mappings."""
        for status in TabStatus:
            assert status in TAB_STATUS_CSS_CLASSES
            css_class = TAB_STATUS_CSS_CLASSES[status]
            assert isinstance(css_class, str)
            assert css_class.startswith("tab-")


class TestTabStatusColors:
    """Tests for TAB_STATUS_COLORS mapping."""

    def test_completed_is_green(self) -> None:
        """Test completed status shows green."""
        assert TAB_STATUS_COLORS[TabStatus.COMPLETED] == "green"

    def test_running_is_yellow(self) -> None:
        """Test running status shows yellow."""
        assert TAB_STATUS_COLORS[TabStatus.RUNNING] == "yellow"

    def test_error_is_red(self) -> None:
        """Test error status shows red."""
        assert TAB_STATUS_COLORS[TabStatus.ERROR] == "red"

    def test_pending_is_grey(self) -> None:
        """Test pending status shows grey."""
        assert TAB_STATUS_COLORS[TabStatus.PENDING] == "grey"

    def test_locked_is_dim_grey(self) -> None:
        """Test locked status shows dim grey."""
        assert TAB_STATUS_COLORS[TabStatus.LOCKED] == "dim grey"


class TestTabStatusIcons:
    """Tests for TAB_STATUS_ICONS mapping."""

    def test_completed_icon(self) -> None:
        """Test completed status has green circle icon."""
        assert TAB_STATUS_ICONS[TabStatus.COMPLETED] == "🟢"

    def test_running_icon(self) -> None:
        """Test running status has yellow circle icon."""
        assert TAB_STATUS_ICONS[TabStatus.RUNNING] == "🟡"

    def test_error_icon(self) -> None:
        """Test error status has red circle icon."""
        assert TAB_STATUS_ICONS[TabStatus.ERROR] == "🔴"

    def test_pending_icon(self) -> None:
        """Test pending status has white square icon."""
        assert TAB_STATUS_ICONS[TabStatus.PENDING] == "⬜"

    def test_locked_icon(self) -> None:
        """Test locked status has lock icon."""
        assert TAB_STATUS_ICONS[TabStatus.LOCKED] == "🔒"


class TestGetTabLabel:
    """Tests for get_tab_label function."""

    def test_label_with_phase(self) -> None:
        """Test tab label includes phase when provided."""
        label = get_tab_label("apt", TabStatus.RUNNING, DisplayPhase.UPGRADE)
        assert "apt" in label
        assert "Upgrade" in label
        assert "🟡" in label

    def test_label_without_phase(self) -> None:
        """Test tab label omits phase when None."""
        label = get_tab_label("flatpak", TabStatus.COMPLETED, None)
        assert "flatpak" in label
        assert "🟢" in label
        # Should not have parentheses for phase
        assert "(" not in label

    def test_label_format_with_phase(self) -> None:
        """Test label format matches expected pattern."""
        label = get_tab_label("pipx", TabStatus.PENDING, DisplayPhase.PENDING)
        # Format: [icon] name (phase)
        assert label == "⬜ pipx (Pending)"

    def test_label_format_without_phase(self) -> None:
        """Test label format without phase."""
        label = get_tab_label("snap", TabStatus.ERROR, None)
        assert label == "🔴 snap"

    def test_all_status_icons_appear_in_labels(self) -> None:
        """Test that all status icons appear correctly in labels."""
        for status in TabStatus:
            label = get_tab_label("test", status, None)
            assert TAB_STATUS_ICONS[status] in label


class TestGetTabCssClass:
    """Tests for get_tab_css_class function."""

    def test_completed_css_class(self) -> None:
        """Test completed status returns correct CSS class."""
        assert get_tab_css_class(TabStatus.COMPLETED) == "tab-completed"

    def test_running_css_class(self) -> None:
        """Test running status returns correct CSS class."""
        assert get_tab_css_class(TabStatus.RUNNING) == "tab-running"

    def test_error_css_class(self) -> None:
        """Test error status returns correct CSS class."""
        assert get_tab_css_class(TabStatus.ERROR) == "tab-error"

    def test_pending_css_class(self) -> None:
        """Test pending status returns correct CSS class."""
        assert get_tab_css_class(TabStatus.PENDING) == "tab-pending"

    def test_locked_css_class(self) -> None:
        """Test locked status returns correct CSS class."""
        assert get_tab_css_class(TabStatus.LOCKED) == "tab-locked"


class TestDetermineTabStatusFromPaneState:
    """Tests for determine_tab_status_from_pane_state function."""

    def test_success_state_returns_completed(self) -> None:
        """Test SUCCESS pane state returns COMPLETED tab status."""
        result = determine_tab_status_from_pane_state(PaneState.SUCCESS.value)
        assert result == TabStatus.COMPLETED

    def test_running_state_returns_running(self) -> None:
        """Test RUNNING pane state returns RUNNING tab status."""
        result = determine_tab_status_from_pane_state(PaneState.RUNNING.value)
        assert result == TabStatus.RUNNING

    def test_failed_state_returns_error(self) -> None:
        """Test FAILED pane state returns ERROR tab status."""
        result = determine_tab_status_from_pane_state(PaneState.FAILED.value)
        assert result == TabStatus.ERROR

    def test_exited_state_returns_error(self) -> None:
        """Test EXITED pane state returns ERROR tab status."""
        result = determine_tab_status_from_pane_state(PaneState.EXITED.value)
        assert result == TabStatus.ERROR

    def test_idle_state_returns_pending(self) -> None:
        """Test IDLE pane state returns PENDING tab status."""
        result = determine_tab_status_from_pane_state(PaneState.IDLE.value)
        assert result == TabStatus.PENDING

    def test_unknown_state_returns_pending(self) -> None:
        """Test unknown pane state returns PENDING tab status."""
        result = determine_tab_status_from_pane_state("unknown")
        assert result == TabStatus.PENDING


class TestDetermineTabStatus:
    """Tests for determine_tab_status function."""

    def test_completed_status(self) -> None:
        """Test completed tab shows green."""
        result = determine_tab_status(PaneState.SUCCESS.value)
        assert result == TabStatus.COMPLETED

    def test_running_status(self) -> None:
        """Test running tab shows yellow."""
        result = determine_tab_status(PaneState.RUNNING.value)
        assert result == TabStatus.RUNNING

    def test_error_status_from_failed(self) -> None:
        """Test error tab shows red for failed state."""
        result = determine_tab_status(PaneState.FAILED.value)
        assert result == TabStatus.ERROR

    def test_error_status_from_exited(self) -> None:
        """Test error tab shows red for exited state."""
        result = determine_tab_status(PaneState.EXITED.value)
        assert result == TabStatus.ERROR

    def test_locked_due_to_dependency(self) -> None:
        """Test tab locked by unmet dependency shows dark grey."""
        result = determine_tab_status(
            PaneState.IDLE.value,
            has_unmet_dependencies=True,
        )
        assert result == TabStatus.LOCKED

    def test_locked_due_to_mutex(self) -> None:
        """Test tab locked by mutex shows dark grey."""
        result = determine_tab_status(
            PaneState.IDLE.value,
            is_mutex_blocked=True,
        )
        assert result == TabStatus.LOCKED

    def test_locked_due_to_both(self) -> None:
        """Test tab locked by both dependency and mutex."""
        result = determine_tab_status(
            PaneState.IDLE.value,
            has_unmet_dependencies=True,
            is_mutex_blocked=True,
        )
        assert result == TabStatus.LOCKED

    def test_pending_when_idle_no_locks(self) -> None:
        """Test pending status when idle with no locks."""
        result = determine_tab_status(PaneState.IDLE.value)
        assert result == TabStatus.PENDING

    def test_running_overrides_locks(self) -> None:
        """Test running status is not affected by lock flags."""
        # Once running, the lock flags shouldn't matter
        result = determine_tab_status(
            PaneState.RUNNING.value,
            has_unmet_dependencies=True,
            is_mutex_blocked=True,
        )
        assert result == TabStatus.RUNNING

    def test_completed_overrides_locks(self) -> None:
        """Test completed status is not affected by lock flags."""
        result = determine_tab_status(
            PaneState.SUCCESS.value,
            has_unmet_dependencies=True,
        )
        assert result == TabStatus.COMPLETED


class TestPhaseTabCss:
    """Tests for PHASE_TAB_CSS constant."""

    def test_css_contains_all_status_classes(self) -> None:
        """Test that CSS contains all tab status classes."""
        for status in TabStatus:
            css_class = TAB_STATUS_CSS_CLASSES[status]
            assert f".{css_class}" in PHASE_TAB_CSS

    def test_css_contains_focus_states(self) -> None:
        """Test that CSS contains focus states for accessibility."""
        assert ":focus" in PHASE_TAB_CSS

    def test_css_contains_color_variables(self) -> None:
        """Test that CSS uses Textual color variables."""
        assert "$success" in PHASE_TAB_CSS
        assert "$warning" in PHASE_TAB_CSS
        assert "$error" in PHASE_TAB_CSS
        assert "$surface" in PHASE_TAB_CSS

    def test_css_is_valid_string(self) -> None:
        """Test that CSS is a non-empty string."""
        assert isinstance(PHASE_TAB_CSS, str)
        assert len(PHASE_TAB_CSS) > 0
