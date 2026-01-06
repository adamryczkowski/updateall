"""Tests for KeyBindings - Configurable key binding system.

Phase 3 - Input Handling
See docs/interactive-tabs-implementation-plan.md section 5.2.4
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestKeyBindingCreation:
    """Tests for KeyBinding creation and initialization."""

    def test_create_default_bindings(self) -> None:
        """Test creating KeyBindings with default configuration."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        # Should have default navigation bindings
        assert bindings.get_action("ctrl+tab") == "next_tab"
        assert bindings.get_action("ctrl+shift+tab") == "prev_tab"

    def test_create_bindings_with_custom_config(self) -> None:
        """Test creating KeyBindings with custom configuration."""
        from ui.key_bindings import KeyBindings

        custom = {
            "next_tab": "alt+right",
            "prev_tab": "alt+left",
        }
        bindings = KeyBindings(custom_bindings=custom)
        assert bindings.get_action("alt+right") == "next_tab"
        assert bindings.get_action("alt+left") == "prev_tab"

    def test_default_bindings_include_tab_numbers(self) -> None:
        """Test that default bindings include Alt+1 through Alt+9."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        for i in range(1, 10):
            assert bindings.get_action(f"alt+{i}") == f"tab_{i}"


class TestKeyBindingActions:
    """Tests for key binding action lookup."""

    def test_get_action_for_bound_key(self) -> None:
        """Test getting action for a bound key."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        action = bindings.get_action("ctrl+tab")
        assert action == "next_tab"

    def test_get_action_for_unbound_key(self) -> None:
        """Test getting action for an unbound key returns None."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        action = bindings.get_action("ctrl+x")
        assert action is None

    def test_is_navigation_key(self) -> None:
        """Test checking if a key is a navigation key."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        assert bindings.is_navigation_key("ctrl+tab") is True
        assert bindings.is_navigation_key("ctrl+shift+tab") is True
        assert bindings.is_navigation_key("alt+1") is True
        assert bindings.is_navigation_key("a") is False
        assert bindings.is_navigation_key("ctrl+c") is False

    def test_get_key_for_action(self) -> None:
        """Test getting key binding for an action."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        key = bindings.get_key_for_action("next_tab")
        assert key == "ctrl+tab"

    def test_get_key_for_unknown_action(self) -> None:
        """Test getting key for unknown action returns None."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        key = bindings.get_key_for_action("unknown_action")
        assert key is None


class TestKeyBindingConfiguration:
    """Tests for key binding configuration."""

    def test_custom_tab_switch_binding(self) -> None:
        """Test custom tab switching key binding."""
        from ui.key_bindings import KeyBindings

        # Given: Custom binding Alt+n for next tab
        custom = {"next_tab": "alt+n"}
        bindings = KeyBindings(custom_bindings=custom)

        # When: Checking the binding
        # Then: Should use custom binding
        assert bindings.get_action("alt+n") == "next_tab"
        # Default binding should be overridden
        assert bindings.get_action("ctrl+tab") is None

    def test_binding_override(self) -> None:
        """Test overriding default bindings."""
        from ui.key_bindings import KeyBindings

        # Given: Override Ctrl+Tab to do nothing (disabled)
        custom: dict[str, str | None] = {"next_tab": None}
        bindings = KeyBindings(custom_bindings=custom)

        # When: Pressing Ctrl+Tab
        # Then: Key should not be bound
        assert bindings.get_action("ctrl+tab") is None

    def test_add_custom_binding(self) -> None:
        """Test adding a custom binding at runtime."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("ctrl+shift+q", "quit")
        assert bindings.get_action("ctrl+shift+q") == "quit"

    def test_remove_binding(self) -> None:
        """Test removing a binding."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.remove_binding("ctrl+tab")
        assert bindings.get_action("ctrl+tab") is None

    def test_reset_to_defaults(self) -> None:
        """Test resetting bindings to defaults."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("ctrl+tab", "custom_action")
        bindings.reset_to_defaults()
        assert bindings.get_action("ctrl+tab") == "next_tab"


class TestKeyBindingNormalization:
    """Tests for key binding normalization."""

    def test_normalize_key_case_insensitive(self) -> None:
        """Test that key names are case-insensitive."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        # All these should refer to the same key
        assert bindings.get_action("Ctrl+Tab") == "next_tab"
        assert bindings.get_action("CTRL+TAB") == "next_tab"
        assert bindings.get_action("ctrl+tab") == "next_tab"

    def test_normalize_modifier_order(self) -> None:
        """Test that modifier order is normalized."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        # These should be equivalent
        assert bindings.get_action("ctrl+shift+tab") == "prev_tab"
        assert bindings.get_action("shift+ctrl+tab") == "prev_tab"

    def test_normalize_key_aliases(self) -> None:
        """Test that key aliases are normalized."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("escape", "cancel")
        # Both should work
        assert bindings.get_action("escape") == "cancel"
        assert bindings.get_action("esc") == "cancel"


class TestKeyBindingPersistence:
    """Tests for key binding persistence."""

    def test_save_bindings_to_file(self) -> None:
        """Test saving bindings to a TOML file."""
        from ui.key_bindings import KeyBindings

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "keybindings.toml"
            bindings = KeyBindings()
            bindings.set_binding("ctrl+shift+q", "quit")
            bindings.save(config_path)

            assert config_path.exists()
            content = config_path.read_text()
            assert "quit" in content

    def test_load_bindings_from_file(self) -> None:
        """Test loading bindings from a TOML file."""
        from ui.key_bindings import KeyBindings

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "keybindings.toml"
            # Write a config file
            config_path.write_text(
                """
[tab_navigation]
next_tab = "alt+right"
prev_tab = "alt+left"
"""
            )

            bindings = KeyBindings.load(config_path)
            assert bindings.get_action("alt+right") == "next_tab"
            assert bindings.get_action("alt+left") == "prev_tab"

    def test_load_nonexistent_file_uses_defaults(self) -> None:
        """Test that loading nonexistent file uses defaults."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings.load(Path("/nonexistent/path/keybindings.toml"))
        # Should have default bindings
        assert bindings.get_action("ctrl+tab") == "next_tab"

    def test_binding_persistence_roundtrip(self) -> None:
        """Test that bindings persist correctly through save/load cycle."""
        from ui.key_bindings import KeyBindings

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "keybindings.toml"

            # Given: Custom bindings saved to config
            original = KeyBindings()
            original.set_binding("f5", "refresh")
            original.set_binding("ctrl+shift+r", "reload_all")
            original.save(config_path)

            # When: Reloading bindings
            loaded = KeyBindings.load(config_path)

            # Then: Custom bindings should be loaded
            assert loaded.get_action("f5") == "refresh"
            assert loaded.get_action("ctrl+shift+r") == "reload_all"


class TestKeyBindingSpecialKeys:
    """Tests for special key handling."""

    def test_function_keys(self) -> None:
        """Test function key bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("f1", "help")
        bindings.set_binding("f12", "debug")
        assert bindings.get_action("f1") == "help"
        assert bindings.get_action("f12") == "debug"

    def test_arrow_keys(self) -> None:
        """Test arrow key bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("ctrl+left", "prev_word")
        bindings.set_binding("ctrl+right", "next_word")
        assert bindings.get_action("ctrl+left") == "prev_word"
        assert bindings.get_action("ctrl+right") == "next_word"

    def test_page_keys(self) -> None:
        """Test page up/down key bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("shift+pageup", "scroll_up")
        bindings.set_binding("shift+pagedown", "scroll_down")
        assert bindings.get_action("shift+pageup") == "scroll_up"
        assert bindings.get_action("shift+pagedown") == "scroll_down"

    def test_home_end_keys(self) -> None:
        """Test home/end key bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        bindings.set_binding("shift+home", "scroll_top")
        bindings.set_binding("shift+end", "scroll_bottom")
        assert bindings.get_action("shift+home") == "scroll_top"
        assert bindings.get_action("shift+end") == "scroll_bottom"


class TestKeyBindingDefaultActions:
    """Tests for default action bindings."""

    def test_default_quit_binding(self) -> None:
        """Test default quit key binding."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        assert bindings.get_action("ctrl+q") == "quit"

    def test_default_help_binding(self) -> None:
        """Test default help key binding."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        assert bindings.get_action("f1") == "help"

    def test_default_scroll_bindings(self) -> None:
        """Test default scroll key bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        assert bindings.get_action("shift+pageup") == "scroll_up"
        assert bindings.get_action("shift+pagedown") == "scroll_down"
        assert bindings.get_action("shift+home") == "scroll_top"
        assert bindings.get_action("shift+end") == "scroll_bottom"


class TestKeyBindingListAll:
    """Tests for listing all bindings."""

    def test_list_all_bindings(self) -> None:
        """Test listing all current bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        all_bindings = bindings.list_all()
        assert isinstance(all_bindings, dict)
        assert "next_tab" in all_bindings
        assert "prev_tab" in all_bindings
        assert all_bindings["next_tab"] == "ctrl+tab"

    def test_list_navigation_bindings(self) -> None:
        """Test listing only navigation bindings."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        nav_bindings = bindings.list_navigation_bindings()
        assert "next_tab" in nav_bindings
        assert "prev_tab" in nav_bindings
        # Tab number bindings
        for i in range(1, 10):
            assert f"tab_{i}" in nav_bindings


class TestKeyBindingValidation:
    """Tests for key binding validation."""

    def test_invalid_key_raises_error(self) -> None:
        """Test that invalid key format raises an error."""
        from ui.key_bindings import InvalidKeyError, KeyBindings

        bindings = KeyBindings()
        with pytest.raises(InvalidKeyError):
            bindings.set_binding("invalid++key", "action")

    def test_empty_key_raises_error(self) -> None:
        """Test that empty key raises an error."""
        from ui.key_bindings import InvalidKeyError, KeyBindings

        bindings = KeyBindings()
        with pytest.raises(InvalidKeyError):
            bindings.set_binding("", "action")

    def test_valid_key_formats(self) -> None:
        """Test various valid key formats."""
        from ui.key_bindings import KeyBindings

        bindings = KeyBindings()
        # All these should be valid
        bindings.set_binding("a", "action_a")
        bindings.set_binding("ctrl+a", "action_ctrl_a")
        bindings.set_binding("ctrl+shift+a", "action_ctrl_shift_a")
        bindings.set_binding("alt+ctrl+shift+a", "action_all_mods")
        bindings.set_binding("f1", "action_f1")
        bindings.set_binding("escape", "action_escape")
        bindings.set_binding("space", "action_space")
        bindings.set_binding("enter", "action_enter")
        bindings.set_binding("tab", "action_tab")
        bindings.set_binding("backspace", "action_backspace")
        bindings.set_binding("delete", "action_delete")

        assert bindings.get_action("a") == "action_a"
        assert bindings.get_action("ctrl+a") == "action_ctrl_a"
