"""Input routing for interactive terminal tabs.

This module provides an InputRouter class that handles keyboard input routing
between the application (for navigation) and PTY sessions (for terminal input).

Phase 3 - Input Handling
See docs/interactive-tabs-implementation-plan.md section 3.2.4
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from enum import Enum, auto
from typing import TYPE_CHECKING

from ui.key_bindings import KeyBindings, normalize_key

if TYPE_CHECKING:
    from collections.abc import Awaitable


class RouteTarget(Enum):
    """Target for routing a key event."""

    APP = auto()  # Key should be handled by the application (navigation, etc.)
    PTY = auto()  # Key should be sent to the active PTY session


# Control character mappings for Ctrl+letter combinations
# Ctrl+A = 1, Ctrl+B = 2, ..., Ctrl+Z = 26
CTRL_CHAR_MAP: dict[str, bytes] = {f"ctrl+{chr(ord('a') + i)}": bytes([i + 1]) for i in range(26)}

# Special key to bytes mappings
SPECIAL_KEY_BYTES: dict[str, bytes] = {
    # Basic keys
    "enter": b"\r",
    "tab": b"\t",
    "escape": b"\x1b",
    "backspace": b"\x7f",
    "space": b" ",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    # Arrow keys
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    # Navigation keys
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    # Function keys (F1-F4 use different sequences)
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "f5": b"\x1b[15~",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "f11": b"\x1b[23~",
    "f12": b"\x1b[24~",
}

# Shift+arrow key mappings (CSI 1;2 sequences)
SHIFT_ARROW_BYTES: dict[str, bytes] = {
    "shift+up": b"\x1b[1;2A",
    "shift+down": b"\x1b[1;2B",
    "shift+right": b"\x1b[1;2C",
    "shift+left": b"\x1b[1;2D",
}

# Ctrl+arrow key mappings (CSI 1;5 sequences)
CTRL_ARROW_BYTES: dict[str, bytes] = {
    "ctrl+up": b"\x1b[1;5A",
    "ctrl+down": b"\x1b[1;5B",
    "ctrl+right": b"\x1b[1;5C",
    "ctrl+left": b"\x1b[1;5D",
}

# Alt+arrow key mappings (CSI 1;3 sequences)
ALT_ARROW_BYTES: dict[str, bytes] = {
    "alt+up": b"\x1b[1;3A",
    "alt+down": b"\x1b[1;3B",
    "alt+right": b"\x1b[1;3C",
    "alt+left": b"\x1b[1;3D",
}

# Bracketed paste mode sequences
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"


# Type for PTY input callback - can accept just data or data + tab_id
PTYInputCallback = Callable[..., "Awaitable[None]"]
AppActionCallback = Callable[[str], "Awaitable[None]"]


class InputRouter:
    """Routes keyboard input between application and PTY sessions.

    This class provides:
    - Key routing based on configurable bindings
    - Conversion of key events to PTY-compatible bytes
    - Callback-based routing to PTY or app handlers
    - Active tab management
    - Bracketed paste mode support

    Example:
        async def on_pty_input(data: bytes) -> None:
            await pty_session.write(data)

        async def on_app_action(action: str) -> None:
            if action == "next_tab":
                switch_to_next_tab()

        router = InputRouter(
            on_pty_input=on_pty_input,
            on_app_action=on_app_action,
        )

        await router.route_key("ctrl+tab")  # Calls on_app_action("next_tab")
        await router.route_key("a")  # Calls on_pty_input(b"a")
    """

    def __init__(
        self,
        key_bindings: KeyBindings | None = None,
        on_pty_input: PTYInputCallback | None = None,
        on_app_action: AppActionCallback | None = None,
        bracketed_paste: bool = False,
    ) -> None:
        """Initialize the input router.

        Args:
            key_bindings: Key bindings configuration. Uses defaults if None.
            on_pty_input: Async callback for PTY input (receives bytes).
            on_app_action: Async callback for app actions (receives action name).
            bracketed_paste: Whether to use bracketed paste mode.
        """
        self._key_bindings = key_bindings or KeyBindings()
        self._on_pty_input = on_pty_input
        self._on_app_action = on_app_action
        self._bracketed_paste = bracketed_paste
        self._active_tab: str | None = None
        self._enabled = True

    @property
    def key_bindings(self) -> KeyBindings:
        """Get the key bindings configuration."""
        return self._key_bindings

    @property
    def active_tab(self) -> str | None:
        """Get the active tab ID."""
        return self._active_tab

    @property
    def is_enabled(self) -> bool:
        """Check if routing is enabled."""
        return self._enabled

    def set_active_tab(self, tab_id: str | None) -> None:
        """Set the active tab.

        Args:
            tab_id: ID of the active tab, or None for no active tab.
        """
        self._active_tab = tab_id

    def enable(self) -> None:
        """Enable input routing."""
        self._enabled = True

    def disable(self) -> None:
        """Disable input routing."""
        self._enabled = False

    def get_route_target(self, key: str) -> RouteTarget:
        """Determine where a key should be routed.

        Args:
            key: Key string (e.g., "ctrl+tab", "a").

        Returns:
            RouteTarget indicating where the key should go.
        """
        if self._key_bindings.is_navigation_key(key):
            return RouteTarget.APP
        return RouteTarget.PTY

    def get_action(self, key: str) -> str | None:
        """Get the action for a key, if it's a navigation key.

        Args:
            key: Key string.

        Returns:
            Action name, or None if not a navigation key.
        """
        return self._key_bindings.get_action(key)

    def key_to_bytes(self, key: str) -> bytes:
        """Convert a key to bytes for PTY input.

        Args:
            key: Key string (e.g., "a", "ctrl+c", "enter").

        Returns:
            Bytes to send to PTY.
        """
        # Normalize the key
        try:
            normalized = normalize_key(key)
        except Exception:
            # If normalization fails, try to use the key as-is
            normalized = key.lower()

        # Check special key mappings first
        if normalized in SPECIAL_KEY_BYTES:
            return SPECIAL_KEY_BYTES[normalized]

        # Check Ctrl+letter combinations
        if normalized in CTRL_CHAR_MAP:
            return CTRL_CHAR_MAP[normalized]

        # Check Shift+arrow combinations
        if normalized in SHIFT_ARROW_BYTES:
            return SHIFT_ARROW_BYTES[normalized]

        # Check Ctrl+arrow combinations
        if normalized in CTRL_ARROW_BYTES:
            return CTRL_ARROW_BYTES[normalized]

        # Check Alt+arrow combinations
        if normalized in ALT_ARROW_BYTES:
            return ALT_ARROW_BYTES[normalized]

        # Handle Alt+letter (ESC followed by letter)
        if normalized.startswith("alt+") and len(normalized) == 5:
            letter = normalized[4]
            return b"\x1b" + letter.encode("utf-8")

        # Handle single characters
        if len(key) == 1:
            return key.encode("utf-8")

        # Handle uppercase single characters (preserve case)
        if len(normalized) == 1:
            return key.encode("utf-8")

        # Unknown key - return empty bytes
        return b""

    async def route_key(self, key: str) -> None:
        """Route a key to the appropriate handler.

        Args:
            key: Key string to route.
        """
        if not self._enabled:
            return

        target = self.get_route_target(key)

        if target == RouteTarget.APP:
            action = self.get_action(key)
            if action and self._on_app_action:
                await self._on_app_action(action)
        else:
            data = self.key_to_bytes(key)
            if data and self._on_pty_input:
                await self._call_pty_callback(data)

    async def _call_pty_callback(self, data: bytes) -> None:
        """Call the PTY callback with appropriate arguments.

        Args:
            data: Bytes to send to PTY.
        """
        if not self._on_pty_input:
            return

        # Check if callback accepts tab_id parameter
        sig = inspect.signature(self._on_pty_input)
        params = list(sig.parameters.keys())

        if len(params) >= 2 or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            # Callback accepts tab_id
            await self._on_pty_input(data, tab_id=self._active_tab)
        else:
            # Callback only accepts data
            await self._on_pty_input(data)

    async def route_text(self, text: str) -> None:
        """Route a text string to PTY.

        Args:
            text: Text string to send.
        """
        if not self._enabled:
            return

        data = text.encode("utf-8")
        if self._on_pty_input:
            await self._call_pty_callback(data)

    async def paste(self, text: str) -> None:
        """Paste text to PTY, optionally using bracketed paste mode.

        Args:
            text: Text to paste.
        """
        if not self._enabled:
            return

        data = text.encode("utf-8")

        if self._bracketed_paste:
            data = PASTE_START + data + PASTE_END

        if self._on_pty_input:
            await self._call_pty_callback(data)
