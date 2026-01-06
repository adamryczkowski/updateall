"""Tests for InputRouter - Keyboard input routing for interactive tabs.

Phase 3 - Input Handling
See docs/interactive-tabs-implementation-plan.md section 5.2.4
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestInputRouterCreation:
    """Tests for InputRouter creation and initialization."""

    def test_create_router_with_default_bindings(self) -> None:
        """Test creating InputRouter with default key bindings."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_bindings is not None

    def test_create_router_with_custom_bindings(self) -> None:
        """Test creating InputRouter with custom key bindings."""
        from ui.input_router import InputRouter
        from ui.key_bindings import KeyBindings

        custom_bindings = KeyBindings(custom_bindings={"next_tab": "alt+right"})
        router = InputRouter(key_bindings=custom_bindings)
        assert router.key_bindings.get_action("alt+right") == "next_tab"


class TestInputRouterKeyRouting:
    """Tests for key routing logic."""

    def test_navigation_keys_go_to_app(self) -> None:
        """Test that navigation keys are routed to app."""
        from ui.input_router import InputRouter, RouteTarget

        router = InputRouter()

        # Given: An InputRouter with Ctrl+Tab as navigation key
        # When: Checking where Ctrl+Tab should go
        target = router.get_route_target("ctrl+tab")

        # Then: Key should be handled by app, not PTY
        assert target == RouteTarget.APP

    def test_regular_keys_go_to_active_pty(self) -> None:
        """Test that regular keys go to active PTY."""
        from ui.input_router import InputRouter, RouteTarget

        router = InputRouter()

        # Given: An InputRouter
        # When: Checking where regular key 'a' should go
        target = router.get_route_target("a")

        # Then: 'a' should be sent to active PTY
        assert target == RouteTarget.PTY

    def test_special_keys_go_to_pty(self) -> None:
        """Test that special keys (Ctrl+C) go to PTY."""
        from ui.input_router import InputRouter, RouteTarget

        router = InputRouter()

        # Given: An InputRouter
        # When: Checking where Ctrl+C should go
        target = router.get_route_target("ctrl+c")

        # Then: Ctrl+C should be sent to PTY (for SIGINT)
        assert target == RouteTarget.PTY

    def test_ctrl_d_goes_to_pty(self) -> None:
        """Test that Ctrl+D goes to PTY (for EOF)."""
        from ui.input_router import InputRouter, RouteTarget

        router = InputRouter()
        target = router.get_route_target("ctrl+d")
        assert target == RouteTarget.PTY

    def test_ctrl_z_goes_to_pty(self) -> None:
        """Test that Ctrl+Z goes to PTY (for SIGTSTP)."""
        from ui.input_router import InputRouter, RouteTarget

        router = InputRouter()
        target = router.get_route_target("ctrl+z")
        assert target == RouteTarget.PTY

    def test_tab_numbers_go_to_app(self) -> None:
        """Test that Alt+1 through Alt+9 go to app."""
        from ui.input_router import InputRouter, RouteTarget

        router = InputRouter()
        for i in range(1, 10):
            target = router.get_route_target(f"alt+{i}")
            assert target == RouteTarget.APP, f"Alt+{i} should go to app"


class TestInputRouterKeyConversion:
    """Tests for converting keys to PTY bytes."""

    def test_convert_regular_char(self) -> None:
        """Test converting regular character to bytes."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("a")
        assert result == b"a"

    def test_convert_uppercase_char(self) -> None:
        """Test converting uppercase character to bytes."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("A")
        assert result == b"A"

    def test_convert_enter(self) -> None:
        """Test converting Enter key to bytes."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("enter")
        assert result == b"\r"

    def test_convert_tab(self) -> None:
        """Test converting Tab key to bytes."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("tab")
        assert result == b"\t"

    def test_convert_escape(self) -> None:
        """Test converting Escape key to bytes."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("escape")
        assert result == b"\x1b"

    def test_convert_backspace(self) -> None:
        """Test converting Backspace key to bytes."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("backspace")
        assert result == b"\x7f"

    def test_convert_ctrl_c(self) -> None:
        """Test converting Ctrl+C to bytes (ETX)."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("ctrl+c")
        assert result == b"\x03"

    def test_convert_ctrl_d(self) -> None:
        """Test converting Ctrl+D to bytes (EOT)."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("ctrl+d")
        assert result == b"\x04"

    def test_convert_ctrl_z(self) -> None:
        """Test converting Ctrl+Z to bytes (SUB)."""
        from ui.input_router import InputRouter

        router = InputRouter()
        result = router.key_to_bytes("ctrl+z")
        assert result == b"\x1a"

    def test_convert_arrow_keys(self) -> None:
        """Test converting arrow keys to ANSI escape sequences."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_to_bytes("up") == b"\x1b[A"
        assert router.key_to_bytes("down") == b"\x1b[B"
        assert router.key_to_bytes("right") == b"\x1b[C"
        assert router.key_to_bytes("left") == b"\x1b[D"

    def test_convert_function_keys(self) -> None:
        """Test converting function keys to ANSI escape sequences."""
        from ui.input_router import InputRouter

        router = InputRouter()
        # F1-F4 use different sequences than F5-F12
        assert router.key_to_bytes("f1") == b"\x1bOP"
        assert router.key_to_bytes("f2") == b"\x1bOQ"
        assert router.key_to_bytes("f3") == b"\x1bOR"
        assert router.key_to_bytes("f4") == b"\x1bOS"
        assert router.key_to_bytes("f5") == b"\x1b[15~"

    def test_convert_home_end(self) -> None:
        """Test converting Home/End keys."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_to_bytes("home") == b"\x1b[H"
        assert router.key_to_bytes("end") == b"\x1b[F"

    def test_convert_page_keys(self) -> None:
        """Test converting Page Up/Down keys."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_to_bytes("pageup") == b"\x1b[5~"
        assert router.key_to_bytes("pagedown") == b"\x1b[6~"

    def test_convert_delete(self) -> None:
        """Test converting Delete key."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_to_bytes("delete") == b"\x1b[3~"

    def test_convert_insert(self) -> None:
        """Test converting Insert key."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_to_bytes("insert") == b"\x1b[2~"

    def test_convert_space(self) -> None:
        """Test converting Space key."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.key_to_bytes("space") == b" "


class TestInputRouterActionHandling:
    """Tests for action handling."""

    def test_get_action_for_navigation_key(self) -> None:
        """Test getting action for navigation key."""
        from ui.input_router import InputRouter

        router = InputRouter()
        action = router.get_action("ctrl+tab")
        assert action == "next_tab"

    def test_get_action_for_non_navigation_key(self) -> None:
        """Test getting action for non-navigation key returns None."""
        from ui.input_router import InputRouter

        router = InputRouter()
        action = router.get_action("a")
        assert action is None

    def test_get_action_for_quit(self) -> None:
        """Test getting action for quit key."""
        from ui.input_router import InputRouter

        router = InputRouter()
        action = router.get_action("ctrl+q")
        assert action == "quit"


class TestInputRouterCallbacks:
    """Tests for callback-based routing."""

    @pytest.mark.asyncio
    async def test_route_to_pty_callback(self) -> None:
        """Test routing key to PTY via callback."""
        from ui.input_router import InputRouter

        # Given: An InputRouter with PTY callback
        pty_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback)

        # When: Routing a regular key
        await router.route_key("a")

        # Then: PTY callback should be called with bytes
        pty_callback.assert_called_once()
        call_args = pty_callback.call_args
        assert call_args[0][0] == b"a"

    @pytest.mark.asyncio
    async def test_route_to_app_callback(self) -> None:
        """Test routing navigation key to app via callback."""
        from ui.input_router import InputRouter

        # Given: An InputRouter with app callback
        app_callback = AsyncMock()
        router = InputRouter(on_app_action=app_callback)

        # When: Routing a navigation key
        await router.route_key("ctrl+tab")

        # Then: App callback should be called with action
        app_callback.assert_called_once_with("next_tab")

    @pytest.mark.asyncio
    async def test_no_callback_does_not_raise(self) -> None:
        """Test that routing without callbacks doesn't raise."""
        from ui.input_router import InputRouter

        router = InputRouter()
        # Should not raise
        await router.route_key("a")
        await router.route_key("ctrl+tab")

    @pytest.mark.asyncio
    async def test_route_special_key_to_pty(self) -> None:
        """Test routing Ctrl+C to PTY."""
        from ui.input_router import InputRouter

        pty_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback)

        await router.route_key("ctrl+c")

        pty_callback.assert_called_once()
        call_args = pty_callback.call_args
        assert call_args[0][0] == b"\x03"


class TestInputRouterActiveTab:
    """Tests for active tab management."""

    def test_set_active_tab(self) -> None:
        """Test setting active tab."""
        from ui.input_router import InputRouter

        router = InputRouter()
        router.set_active_tab("tab_1")
        assert router.active_tab == "tab_1"

    def test_default_active_tab_is_none(self) -> None:
        """Test that default active tab is None."""
        from ui.input_router import InputRouter

        router = InputRouter()
        assert router.active_tab is None

    @pytest.mark.asyncio
    async def test_pty_callback_receives_tab_id(self) -> None:
        """Test that PTY callback receives active tab ID."""
        from ui.input_router import InputRouter

        # Given: Router with callback that receives tab ID
        received_tab: list[str | None] = []

        async def pty_callback(data: bytes, tab_id: str | None = None) -> None:  # noqa: ARG001
            received_tab.append(tab_id)

        router = InputRouter(on_pty_input=pty_callback)
        router.set_active_tab("apt_tab")

        # When: Routing a key
        await router.route_key("a")

        # Then: Callback should receive tab ID
        assert received_tab == ["apt_tab"]


class TestInputRouterDisabled:
    """Tests for disabling input routing."""

    def test_disable_routing(self) -> None:
        """Test disabling input routing."""
        from ui.input_router import InputRouter

        router = InputRouter()
        router.disable()
        assert router.is_enabled is False

    def test_enable_routing(self) -> None:
        """Test enabling input routing."""
        from ui.input_router import InputRouter

        router = InputRouter()
        router.disable()
        router.enable()
        assert router.is_enabled is True

    @pytest.mark.asyncio
    async def test_disabled_router_ignores_keys(self) -> None:
        """Test that disabled router ignores all keys."""
        from ui.input_router import InputRouter

        pty_callback = AsyncMock()
        app_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback, on_app_action=app_callback)
        router.disable()

        await router.route_key("a")
        await router.route_key("ctrl+tab")

        pty_callback.assert_not_called()
        app_callback.assert_not_called()


class TestInputRouterModifierKeys:
    """Tests for modifier key handling."""

    def test_alt_modifier_with_letter(self) -> None:
        """Test Alt+letter key conversion."""
        from ui.input_router import InputRouter

        router = InputRouter()
        # Alt+a should produce ESC followed by 'a'
        result = router.key_to_bytes("alt+a")
        assert result == b"\x1ba"

    def test_ctrl_modifier_with_letter(self) -> None:
        """Test Ctrl+letter key conversion."""
        from ui.input_router import InputRouter

        router = InputRouter()
        # Ctrl+a is ASCII 1
        assert router.key_to_bytes("ctrl+a") == b"\x01"
        # Ctrl+b is ASCII 2
        assert router.key_to_bytes("ctrl+b") == b"\x02"
        # Ctrl+l is ASCII 12 (form feed, clears screen)
        assert router.key_to_bytes("ctrl+l") == b"\x0c"

    def test_shift_modifier_with_arrow(self) -> None:
        """Test Shift+arrow key conversion."""
        from ui.input_router import InputRouter

        router = InputRouter()
        # Shift+Up uses modified escape sequence
        result = router.key_to_bytes("shift+up")
        assert result == b"\x1b[1;2A"


class TestInputRouterTextInput:
    """Tests for text input handling."""

    @pytest.mark.asyncio
    async def test_route_text_string(self) -> None:
        """Test routing a text string to PTY."""
        from ui.input_router import InputRouter

        pty_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback)

        await router.route_text("hello")

        pty_callback.assert_called_once()
        call_args = pty_callback.call_args
        assert call_args[0][0] == b"hello"

    @pytest.mark.asyncio
    async def test_route_unicode_text(self) -> None:
        """Test routing unicode text to PTY."""
        from ui.input_router import InputRouter

        pty_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback)

        await router.route_text("héllo 世界")

        pty_callback.assert_called_once()
        call_args = pty_callback.call_args
        assert call_args[0][0] == "héllo 世界".encode()


class TestInputRouterPasteMode:
    """Tests for bracketed paste mode."""

    @pytest.mark.asyncio
    async def test_paste_with_bracketed_mode(self) -> None:
        """Test pasting text with bracketed paste mode enabled."""
        from ui.input_router import InputRouter

        pty_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback, bracketed_paste=True)

        await router.paste("pasted text")

        # Should be wrapped in bracketed paste sequences
        pty_callback.assert_called_once()
        call_data = pty_callback.call_args[0][0]
        assert call_data.startswith(b"\x1b[200~")
        assert b"pasted text" in call_data
        assert call_data.endswith(b"\x1b[201~")

    @pytest.mark.asyncio
    async def test_paste_without_bracketed_mode(self) -> None:
        """Test pasting text without bracketed paste mode."""
        from ui.input_router import InputRouter

        pty_callback = AsyncMock()
        router = InputRouter(on_pty_input=pty_callback, bracketed_paste=False)

        await router.paste("pasted text")

        # Should be sent as-is
        pty_callback.assert_called_once()
        call_args = pty_callback.call_args
        assert call_args[0][0] == b"pasted text"
