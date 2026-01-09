"""Tests for hot keys functionality.

UI Revision Plan - Phase 4 Hot Keys and CLI
See docs/UI-revision-plan.md section 3.5 and 5
"""

from __future__ import annotations

from ui.key_bindings import DEFAULT_BINDINGS, NAVIGATION_ACTIONS, KeyBindings, normalize_key


class TestPhaseControlBindings:
    """Tests for phase control key bindings."""

    def test_pause_resume_binding_exists(self) -> None:
        """Test that pause_resume binding is defined."""
        assert "pause_resume" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["pause_resume"] == "ctrl+p"

    def test_pause_resume_alt_binding_exists(self) -> None:
        """Test that pause_resume_alt binding (F8) is defined."""
        assert "pause_resume_alt" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["pause_resume_alt"] == "f8"

    def test_retry_phase_binding_exists(self) -> None:
        """Test that retry_phase binding is defined."""
        assert "retry_phase" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["retry_phase"] == "ctrl+r"

    def test_retry_phase_alt_binding_exists(self) -> None:
        """Test that retry_phase_alt binding (F9) is defined."""
        assert "retry_phase_alt" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["retry_phase_alt"] == "f9"

    def test_save_logs_binding_exists(self) -> None:
        """Test that save_logs binding is defined."""
        assert "save_logs" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["save_logs"] == "ctrl+s"

    def test_save_logs_alt_binding_exists(self) -> None:
        """Test that save_logs_alt binding (F10) is defined."""
        assert "save_logs_alt" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["save_logs_alt"] == "f10"

    def test_show_help_binding_exists(self) -> None:
        """Test that show_help binding is defined."""
        assert "show_help" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["show_help"] == "ctrl+h"

    def test_help_binding_exists(self) -> None:
        """Test that help binding (F1) is defined.

        Note: F1 is bound to "help" action, not "show_help_alt",
        to maintain backward compatibility.
        """
        assert "help" in DEFAULT_BINDINGS
        assert DEFAULT_BINDINGS["help"] == "f1"


class TestPhaseControlNavigationActions:
    """Tests for phase control actions in NAVIGATION_ACTIONS."""

    def test_pause_resume_in_navigation_actions(self) -> None:
        """Test that pause_resume is in navigation actions."""
        assert "pause_resume" in NAVIGATION_ACTIONS

    def test_pause_resume_alt_in_navigation_actions(self) -> None:
        """Test that pause_resume_alt is in navigation actions."""
        assert "pause_resume_alt" in NAVIGATION_ACTIONS

    def test_retry_phase_in_navigation_actions(self) -> None:
        """Test that retry_phase is in navigation actions."""
        assert "retry_phase" in NAVIGATION_ACTIONS

    def test_retry_phase_alt_in_navigation_actions(self) -> None:
        """Test that retry_phase_alt is in navigation actions."""
        assert "retry_phase_alt" in NAVIGATION_ACTIONS

    def test_save_logs_in_navigation_actions(self) -> None:
        """Test that save_logs is in navigation actions."""
        assert "save_logs" in NAVIGATION_ACTIONS

    def test_save_logs_alt_in_navigation_actions(self) -> None:
        """Test that save_logs_alt is in navigation actions."""
        assert "save_logs_alt" in NAVIGATION_ACTIONS

    def test_show_help_in_navigation_actions(self) -> None:
        """Test that show_help is in navigation actions."""
        assert "show_help" in NAVIGATION_ACTIONS

    def test_help_in_navigation_actions(self) -> None:
        """Test that help is in navigation actions.

        Note: F1 is bound to "help" action for backward compatibility.
        """
        assert "help" in NAVIGATION_ACTIONS


class TestKeyBindingsPhaseControl:
    """Tests for KeyBindings class with phase control bindings."""

    def test_get_action_pause_resume(self) -> None:
        """Test getting pause_resume action from key."""
        bindings = KeyBindings()
        action = bindings.get_action("ctrl+p")
        assert action == "pause_resume"

    def test_get_action_pause_resume_alt(self) -> None:
        """Test getting pause_resume action from F8."""
        bindings = KeyBindings()
        action = bindings.get_action("f8")
        assert action == "pause_resume_alt"

    def test_get_action_retry_phase(self) -> None:
        """Test getting retry_phase action from key."""
        bindings = KeyBindings()
        action = bindings.get_action("ctrl+r")
        assert action == "retry_phase"

    def test_get_action_save_logs(self) -> None:
        """Test getting save_logs action from key."""
        bindings = KeyBindings()
        action = bindings.get_action("ctrl+s")
        assert action == "save_logs"

    def test_get_action_show_help(self) -> None:
        """Test getting show_help action from key."""
        bindings = KeyBindings()
        action = bindings.get_action("ctrl+h")
        assert action == "show_help"

    def test_is_navigation_key_pause_resume(self) -> None:
        """Test that Ctrl+P is recognized as navigation key."""
        bindings = KeyBindings()
        assert bindings.is_navigation_key("ctrl+p") is True

    def test_is_navigation_key_retry_phase(self) -> None:
        """Test that Ctrl+R is recognized as navigation key."""
        bindings = KeyBindings()
        assert bindings.is_navigation_key("ctrl+r") is True

    def test_is_navigation_key_save_logs(self) -> None:
        """Test that Ctrl+S is recognized as navigation key."""
        bindings = KeyBindings()
        assert bindings.is_navigation_key("ctrl+s") is True

    def test_is_navigation_key_show_help(self) -> None:
        """Test that Ctrl+H is recognized as navigation key."""
        bindings = KeyBindings()
        assert bindings.is_navigation_key("ctrl+h") is True

    def test_custom_binding_overrides_default(self) -> None:
        """Test that custom bindings can override phase control defaults."""
        custom = {"pause_resume": "ctrl+shift+p"}
        bindings = KeyBindings(custom_bindings=custom)

        # New binding should work
        assert bindings.get_action("ctrl+shift+p") == "pause_resume"
        # Old binding should not work
        assert bindings.get_action("ctrl+p") is None

    def test_list_all_includes_phase_control(self) -> None:
        """Test that list_all includes phase control bindings."""
        bindings = KeyBindings()
        all_bindings = bindings.list_all()

        assert "pause_resume" in all_bindings
        assert "retry_phase" in all_bindings
        assert "save_logs" in all_bindings
        assert "show_help" in all_bindings


class TestNormalizeKeyPhaseControl:
    """Tests for normalize_key with phase control keys."""

    def test_normalize_ctrl_p(self) -> None:
        """Test normalizing Ctrl+P."""
        assert normalize_key("ctrl+p") == "ctrl+p"
        assert normalize_key("CTRL+P") == "ctrl+p"
        assert normalize_key("Ctrl+P") == "ctrl+p"

    def test_normalize_f8(self) -> None:
        """Test normalizing F8."""
        assert normalize_key("f8") == "f8"
        assert normalize_key("F8") == "f8"

    def test_normalize_ctrl_r(self) -> None:
        """Test normalizing Ctrl+R."""
        assert normalize_key("ctrl+r") == "ctrl+r"

    def test_normalize_ctrl_s(self) -> None:
        """Test normalizing Ctrl+S."""
        assert normalize_key("ctrl+s") == "ctrl+s"

    def test_normalize_ctrl_h(self) -> None:
        """Test normalizing Ctrl+H."""
        assert normalize_key("ctrl+h") == "ctrl+h"


class TestInteractiveTabbedAppBindings:
    """Tests for InteractiveTabbedApp bindings.

    These tests verify that the BINDINGS class variable includes
    the phase control bindings.
    """

    def test_bindings_include_toggle_pause(self) -> None:
        """Test that BINDINGS includes toggle_pause action."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        binding_actions = [b.action for b in InteractiveTabbedApp.BINDINGS]
        assert "toggle_pause" in binding_actions

    def test_bindings_include_retry_phase(self) -> None:
        """Test that BINDINGS includes retry_phase action."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        binding_actions = [b.action for b in InteractiveTabbedApp.BINDINGS]
        assert "retry_phase" in binding_actions

    def test_bindings_include_save_logs(self) -> None:
        """Test that BINDINGS includes save_logs action."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        binding_actions = [b.action for b in InteractiveTabbedApp.BINDINGS]
        assert "save_logs" in binding_actions

    def test_bindings_include_show_help(self) -> None:
        """Test that BINDINGS includes show_help action."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        binding_actions = [b.action for b in InteractiveTabbedApp.BINDINGS]
        assert "show_help" in binding_actions

    def test_ctrl_p_bound_to_toggle_pause(self) -> None:
        """Test that Ctrl+P is bound to toggle_pause."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        ctrl_p_bindings = [b for b in InteractiveTabbedApp.BINDINGS if b.key == "ctrl+p"]
        assert len(ctrl_p_bindings) == 1
        assert ctrl_p_bindings[0].action == "toggle_pause"

    def test_f8_bound_to_toggle_pause(self) -> None:
        """Test that F8 is bound to toggle_pause."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        f8_bindings = [b for b in InteractiveTabbedApp.BINDINGS if b.key == "f8"]
        assert len(f8_bindings) == 1
        assert f8_bindings[0].action == "toggle_pause"

    def test_ctrl_r_bound_to_retry_phase(self) -> None:
        """Test that Ctrl+R is bound to retry_phase."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        ctrl_r_bindings = [b for b in InteractiveTabbedApp.BINDINGS if b.key == "ctrl+r"]
        assert len(ctrl_r_bindings) == 1
        assert ctrl_r_bindings[0].action == "retry_phase"

    def test_ctrl_s_bound_to_save_logs(self) -> None:
        """Test that Ctrl+S is bound to save_logs."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        ctrl_s_bindings = [b for b in InteractiveTabbedApp.BINDINGS if b.key == "ctrl+s"]
        assert len(ctrl_s_bindings) == 1
        assert ctrl_s_bindings[0].action == "save_logs"

    def test_ctrl_h_bound_to_show_help(self) -> None:
        """Test that Ctrl+H is bound to show_help."""
        from ui.interactive_tabbed_run import InteractiveTabbedApp

        ctrl_h_bindings = [b for b in InteractiveTabbedApp.BINDINGS if b.key == "ctrl+h"]
        assert len(ctrl_h_bindings) == 1
        assert ctrl_h_bindings[0].action == "show_help"


class TestInteractiveTabbedAppInit:
    """Tests for InteractiveTabbedApp initialization with new parameters."""

    def test_init_with_pause_phases(self) -> None:
        """Test initialization with pause_phases parameter."""
        from unittest.mock import MagicMock

        from ui.interactive_tabbed_run import InteractiveTabbedApp

        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(
            plugins=[mock_plugin],
            pause_phases=True,
        )

        assert app.pause_phases is True
        assert app._pause_enabled is True

    def test_init_with_max_concurrent(self) -> None:
        """Test initialization with max_concurrent parameter."""
        from unittest.mock import MagicMock

        from ui.interactive_tabbed_run import InteractiveTabbedApp

        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(
            plugins=[mock_plugin],
            max_concurrent=8,
        )

        assert app.max_concurrent == 8

    def test_init_default_values(self) -> None:
        """Test default values for new parameters."""
        from unittest.mock import MagicMock

        from ui.interactive_tabbed_run import InteractiveTabbedApp

        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        assert app.pause_phases is False
        assert app._pause_enabled is False
        assert app.max_concurrent == 4
