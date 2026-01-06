"""Configurable key binding system for interactive terminal tabs.

This module provides a KeyBindings class for managing keyboard shortcuts
with support for customization, persistence, and normalization.

Phase 3 - Input Handling
See docs/interactive-tabs-implementation-plan.md section 3.2.4
"""

from __future__ import annotations

import re
from collections.abc import Mapping  # noqa: TC003 - Mapping is used at runtime
from pathlib import Path  # noqa: TC003 - Path is used at runtime in save/load methods


class InvalidKeyError(Exception):
    """Raised when an invalid key format is provided."""


# Key aliases for normalization
KEY_ALIASES: dict[str, str] = {
    "esc": "escape",
    "return": "enter",
    "cr": "enter",
    "lf": "enter",
    "del": "delete",
    "bs": "backspace",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "pgdown": "pagedown",
    "ins": "insert",
    "spacebar": "space",
}

# Valid modifier keys
VALID_MODIFIERS = frozenset({"ctrl", "alt", "shift", "meta", "super", "cmd"})

# Valid special keys
VALID_SPECIAL_KEYS = frozenset(
    {
        "escape",
        "enter",
        "tab",
        "space",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "pageup",
        "pagedown",
        "up",
        "down",
        "left",
        "right",
        "f1",
        "f2",
        "f3",
        "f4",
        "f5",
        "f6",
        "f7",
        "f8",
        "f9",
        "f10",
        "f11",
        "f12",
    }
)

# Default key bindings
DEFAULT_BINDINGS: dict[str, str] = {
    # Tab navigation
    "next_tab": "ctrl+tab",
    "prev_tab": "ctrl+shift+tab",
    # Tab number shortcuts
    "tab_1": "alt+1",
    "tab_2": "alt+2",
    "tab_3": "alt+3",
    "tab_4": "alt+4",
    "tab_5": "alt+5",
    "tab_6": "alt+6",
    "tab_7": "alt+7",
    "tab_8": "alt+8",
    "tab_9": "alt+9",
    # Application actions
    "quit": "ctrl+q",
    "help": "f1",
    # Scroll actions
    "scroll_up": "shift+pageup",
    "scroll_down": "shift+pagedown",
    "scroll_top": "shift+home",
    "scroll_bottom": "shift+end",
}

# Navigation actions (keys that should be intercepted by the app, not sent to PTY)
NAVIGATION_ACTIONS = frozenset(
    {
        "next_tab",
        "prev_tab",
        "tab_1",
        "tab_2",
        "tab_3",
        "tab_4",
        "tab_5",
        "tab_6",
        "tab_7",
        "tab_8",
        "tab_9",
        "quit",
        "help",
        "scroll_up",
        "scroll_down",
        "scroll_top",
        "scroll_bottom",
    }
)


def normalize_key(key: str) -> str:
    """Normalize a key string to a canonical form.

    This handles:
    - Case normalization (all lowercase)
    - Modifier order normalization (ctrl+alt+shift order)
    - Key aliases (esc -> escape, etc.)

    Args:
        key: Key string to normalize.

    Returns:
        Normalized key string.

    Raises:
        InvalidKeyError: If the key format is invalid.
    """
    if not key or not key.strip():
        raise InvalidKeyError("Key cannot be empty")

    key = key.lower().strip()

    # Split into parts
    parts = key.split("+")

    # Check for invalid format (empty parts, double +, etc.)
    if any(not part.strip() for part in parts):
        raise InvalidKeyError(f"Invalid key format: {key}")

    # Separate modifiers from the main key
    modifiers: list[str] = []
    main_key: str | None = None

    for part in parts:
        part = part.strip()
        # Apply aliases
        part = KEY_ALIASES.get(part, part)

        if part in VALID_MODIFIERS:
            modifiers.append(part)
        elif main_key is None:
            main_key = part
        else:
            raise InvalidKeyError(f"Multiple main keys in binding: {key}")

    if main_key is None:
        raise InvalidKeyError(f"No main key in binding: {key}")

    # Validate main key
    if (
        len(main_key) > 1
        and main_key not in VALID_SPECIAL_KEYS
        and not re.match(r"^f\d{1,2}$", main_key)
    ):
        raise InvalidKeyError(f"Invalid key: {main_key}")

    # Sort modifiers in canonical order: ctrl, alt, shift, meta
    modifier_order = {"ctrl": 0, "alt": 1, "shift": 2, "meta": 3, "super": 4, "cmd": 5}
    modifiers.sort(key=lambda m: modifier_order.get(m, 99))

    # Reconstruct the key string
    if modifiers:
        return "+".join([*modifiers, main_key])
    return main_key


class KeyBindings:
    """Configurable key binding system.

    This class provides:
    - Default key bindings for tab navigation and app actions
    - Custom key binding configuration
    - Key normalization and validation
    - Persistence to/from TOML files

    Example:
        bindings = KeyBindings()
        action = bindings.get_action("ctrl+tab")  # Returns "next_tab"

        # Custom bindings
        bindings.set_binding("alt+n", "next_tab")
        bindings.save(Path("~/.config/update-all/keybindings.toml"))
    """

    def __init__(self, custom_bindings: Mapping[str, str | None] | None = None) -> None:
        """Initialize key bindings.

        Args:
            custom_bindings: Optional mapping of action names to key strings.
                If a key string is None, the action is disabled.
        """
        # Map from normalized key -> action
        self._key_to_action: dict[str, str] = {}
        # Map from action -> normalized key
        self._action_to_key: dict[str, str] = {}

        # Start with defaults
        self._apply_bindings(DEFAULT_BINDINGS)

        # Apply custom bindings (overrides defaults)
        if custom_bindings:
            self._apply_custom_bindings(custom_bindings)

    def _apply_bindings(self, bindings: Mapping[str, str]) -> None:
        """Apply a set of bindings (action -> key mapping).

        Args:
            bindings: Mapping of action names to key strings.
        """
        for action, key in bindings.items():
            normalized = normalize_key(key)
            self._key_to_action[normalized] = action
            self._action_to_key[action] = normalized

    def _apply_custom_bindings(self, custom: Mapping[str, str | None]) -> None:
        """Apply custom bindings, which may override or disable defaults.

        Args:
            custom: Mapping of action names to key strings or None (to disable).
        """
        for action, key in custom.items():
            # Remove old binding for this action if it exists
            if action in self._action_to_key:
                old_key = self._action_to_key[action]
                if old_key in self._key_to_action:
                    del self._key_to_action[old_key]
                del self._action_to_key[action]

            # Add new binding if key is not None
            if key is not None:
                normalized = normalize_key(key)
                self._key_to_action[normalized] = action
                self._action_to_key[action] = normalized

    def get_action(self, key: str) -> str | None:
        """Get the action bound to a key.

        Args:
            key: Key string (e.g., "ctrl+tab", "alt+1").

        Returns:
            Action name, or None if the key is not bound.
        """
        try:
            normalized = normalize_key(key)
            return self._key_to_action.get(normalized)
        except InvalidKeyError:
            return None

    def get_key_for_action(self, action: str) -> str | None:
        """Get the key bound to an action.

        Args:
            action: Action name (e.g., "next_tab").

        Returns:
            Key string, or None if the action is not bound.
        """
        return self._action_to_key.get(action)

    def is_navigation_key(self, key: str) -> bool:
        """Check if a key is bound to a navigation action.

        Navigation keys are intercepted by the app and not sent to PTY.

        Args:
            key: Key string to check.

        Returns:
            True if the key is bound to a navigation action.
        """
        action = self.get_action(key)
        return action in NAVIGATION_ACTIONS if action else False

    def set_binding(self, key: str, action: str) -> None:
        """Set a key binding.

        Args:
            key: Key string (e.g., "ctrl+tab").
            action: Action name (e.g., "next_tab").

        Raises:
            InvalidKeyError: If the key format is invalid.
        """
        normalized = normalize_key(key)

        # Remove any existing binding for this key
        if normalized in self._key_to_action:
            old_action = self._key_to_action[normalized]
            if old_action in self._action_to_key:
                del self._action_to_key[old_action]

        # Remove any existing key for this action
        if action in self._action_to_key:
            old_key = self._action_to_key[action]
            if old_key in self._key_to_action:
                del self._key_to_action[old_key]

        # Set new binding
        self._key_to_action[normalized] = action
        self._action_to_key[action] = normalized

    def remove_binding(self, key: str) -> None:
        """Remove a key binding.

        Args:
            key: Key string to unbind.
        """
        try:
            normalized = normalize_key(key)
            if normalized in self._key_to_action:
                action = self._key_to_action[normalized]
                del self._key_to_action[normalized]
                if action in self._action_to_key:
                    del self._action_to_key[action]
        except InvalidKeyError:
            pass

    def reset_to_defaults(self) -> None:
        """Reset all bindings to defaults."""
        self._key_to_action.clear()
        self._action_to_key.clear()
        self._apply_bindings(DEFAULT_BINDINGS)

    def list_all(self) -> dict[str, str]:
        """List all current bindings.

        Returns:
            Dict mapping action names to key strings.
        """
        return dict(self._action_to_key)

    def list_navigation_bindings(self) -> dict[str, str]:
        """List only navigation bindings.

        Returns:
            Dict mapping navigation action names to key strings.
        """
        return {
            action: key
            for action, key in self._action_to_key.items()
            if action in NAVIGATION_ACTIONS
        }

    def save(self, path: Path) -> None:
        """Save bindings to a TOML file.

        Args:
            path: Path to the TOML file.
        """
        # Group bindings by category
        tab_nav = {}
        terminal = {}
        app = {}

        for action, key in self._action_to_key.items():
            if action.startswith("tab_") or action in ("next_tab", "prev_tab"):
                tab_nav[action] = key
            elif action.startswith("scroll_"):
                terminal[action] = key
            else:
                app[action] = key

        # Build TOML content
        lines = []
        if tab_nav:
            lines.append("[tab_navigation]")
            for action, key in sorted(tab_nav.items()):
                lines.append(f'{action} = "{key}"')
            lines.append("")

        if terminal:
            lines.append("[terminal]")
            for action, key in sorted(terminal.items()):
                lines.append(f'{action} = "{key}"')
            lines.append("")

        if app:
            lines.append("[app]")
            for action, key in sorted(app.items()):
                lines.append(f'{action} = "{key}"')
            lines.append("")

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        path.write_text("\n".join(lines))

    @classmethod
    def load(cls, path: Path) -> KeyBindings:
        """Load bindings from a TOML file.

        If the file doesn't exist, returns default bindings.

        Args:
            path: Path to the TOML file.

        Returns:
            KeyBindings instance with loaded configuration.
        """
        if not path.exists():
            return cls()

        try:
            import tomllib

            content = path.read_text()
            data = tomllib.loads(content)

            # Collect all bindings from all sections
            custom: dict[str, str] = {}

            for section in ("tab_navigation", "terminal", "app"):
                if section in data and isinstance(data[section], dict):
                    for action, key in data[section].items():
                        if isinstance(key, str):
                            custom[action] = key

            return cls(custom_bindings=custom)

        except Exception:
            # On any error, return defaults
            return cls()
