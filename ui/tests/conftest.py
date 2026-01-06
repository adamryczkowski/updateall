"""Test fixtures and utilities for UI tests.

Phase 5 - Polish and Documentation
See docs/interactive-tabs-implementation-plan.md section 5.3
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class MockPTYSession:
    """Mock PTY session for testing without real PTY allocation.

    This mock provides a controlled environment for testing PTY-related
    functionality without requiring actual PTY allocation.
    """

    def __init__(
        self,
        responses: list[bytes] | None = None,
        *,
        exit_code: int = 0,
    ) -> None:
        """Initialize the mock PTY session.

        Args:
            responses: List of responses to return from read().
            exit_code: Exit code to return when process exits.
        """
        self._responses = responses or []
        self._response_index = 0
        self._input_buffer: list[bytes] = []
        self._exit_code = exit_code
        self._is_alive = True
        self._cols = 80
        self._rows = 24

    @property
    def is_alive(self) -> bool:
        """Check if the mock process is alive."""
        return self._is_alive

    @property
    def exit_code(self) -> int | None:
        """Get the exit code."""
        return None if self._is_alive else self._exit_code

    async def read(
        self,
        size: int = 1024,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
    ) -> bytes:
        """Return next mock response.

        Args:
            size: Maximum bytes to read (unused in mock).
            timeout: Read timeout (unused in mock).

        Returns:
            Next response from the response list, or empty bytes.
        """
        if self._response_index < len(self._responses):
            response = self._responses[self._response_index]
            self._response_index += 1
            return response
        # No more responses - simulate process exit
        self._is_alive = False
        return b""

    async def write(self, data: bytes) -> int:
        """Record input for verification.

        Args:
            data: Data to write.

        Returns:
            Number of bytes written.
        """
        self._input_buffer.append(data)
        return len(data)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the mock terminal.

        Args:
            cols: New column count.
            rows: New row count.
        """
        self._cols = cols
        self._rows = rows

    async def close(self) -> None:
        """Close the mock session."""
        self._is_alive = False

    def get_input_history(self) -> list[bytes]:
        """Get all input that was written.

        Returns:
            List of all input data.
        """
        return list(self._input_buffer)


class MockTerminalScreen:
    """Mock terminal screen for testing without pyte."""

    def __init__(self, columns: int = 80, lines: int = 24) -> None:
        """Initialize the mock screen.

        Args:
            columns: Screen width.
            lines: Screen height.
        """
        self.columns = columns
        self.lines = lines
        self._buffer: list[str] = ["" for _ in range(lines)]
        self._cursor_x = 0
        self._cursor_y = 0
        self._feed_history: list[str] = []

    def feed(self, data: str) -> None:
        """Feed data to the screen.

        Args:
            data: Data to process.
        """
        self._feed_history.append(data)
        # Simple implementation - just append to current line
        for char in data:
            if char == "\n":
                self._cursor_y = min(self._cursor_y + 1, self.lines - 1)
                self._cursor_x = 0
            elif char == "\r":
                self._cursor_x = 0
            else:
                if self._cursor_y < self.lines:
                    line = self._buffer[self._cursor_y]
                    # Extend line if needed
                    while len(line) <= self._cursor_x:
                        line += " "
                    # Replace character at cursor position
                    line = line[: self._cursor_x] + char + line[self._cursor_x + 1 :]
                    self._buffer[self._cursor_y] = line
                    self._cursor_x += 1

    def get_line(self, index: int) -> str:
        """Get a line from the buffer.

        Args:
            index: Line index.

        Returns:
            Line content.
        """
        if 0 <= index < self.lines:
            return self._buffer[index]
        return ""

    def get_display(self) -> list[str]:
        """Get the entire display buffer.

        Returns:
            List of all lines.
        """
        return list(self._buffer)

    def get_feed_history(self) -> list[str]:
        """Get all data that was fed to the screen.

        Returns:
            List of all fed data.
        """
        return list(self._feed_history)


@pytest.fixture
def mock_pty_session() -> MockPTYSession:
    """Create a mock PTY session for testing.

    Returns:
        MockPTYSession instance.
    """
    return MockPTYSession()


@pytest.fixture
def mock_pty_session_with_output() -> MockPTYSession:
    """Create a mock PTY session with sample output.

    Returns:
        MockPTYSession instance with predefined responses.
    """
    return MockPTYSession(
        responses=[
            b"Hello, World!\r\n",
            b"Line 2\r\n",
            b"Line 3\r\n",
        ],
        exit_code=0,
    )


@pytest.fixture
def mock_terminal_screen() -> MockTerminalScreen:
    """Create a mock terminal screen for testing.

    Returns:
        MockTerminalScreen instance.
    """
    return MockTerminalScreen()


@pytest.fixture
def sample_ansi_output() -> str:
    """Sample ANSI-formatted output for testing.

    Returns:
        String with ANSI escape codes.
    """
    return "\x1b[31mRed\x1b[0m \x1b[32mGreen\x1b[0m \x1b[34mBlue\x1b[0m"


@pytest.fixture
def sample_ansi_output_bytes() -> bytes:
    """Sample ANSI-formatted output as bytes.

    Returns:
        Bytes with ANSI escape codes.
    """
    return b"\x1b[31mRed\x1b[0m \x1b[32mGreen\x1b[0m \x1b[34mBlue\x1b[0m"


@pytest.fixture
def mock_plugin() -> MagicMock:
    """Create a mock plugin for testing.

    Returns:
        Mock plugin object.
    """
    plugin = MagicMock()
    plugin.name = "test-plugin"
    plugin.supports_interactive = True
    plugin.get_interactive_command.return_value = ["/bin/echo", "test"]
    plugin.check_available = AsyncMock(return_value=True)
    plugin.pre_execute = AsyncMock()
    plugin.post_execute = AsyncMock()
    return plugin


@pytest.fixture
def mock_plugins() -> list[MagicMock]:
    """Create multiple mock plugins for testing.

    Returns:
        List of mock plugin objects.
    """
    plugins = []
    for name in ["apt", "flatpak", "pipx"]:
        plugin = MagicMock()
        plugin.name = name
        plugin.supports_interactive = True
        plugin.get_interactive_command.return_value = ["/bin/echo", name]
        plugin.check_available = AsyncMock(return_value=True)
        plugin.pre_execute = AsyncMock()
        plugin.post_execute = AsyncMock()
        plugins.append(plugin)
    return plugins


@pytest.fixture
def mock_plugin_config() -> MagicMock:
    """Create a mock plugin config for testing.

    Returns:
        Mock plugin config object.
    """
    config = MagicMock()
    config.name = "test-plugin"
    config.enabled = True
    config.requires_sudo = False
    config.timeout_seconds = 300
    return config


@pytest.fixture
def cursor_movement_sequences() -> dict[str, bytes]:
    """Common cursor movement escape sequences.

    Returns:
        Dictionary of escape sequences.
    """
    return {
        "cursor_up": b"\x1b[A",
        "cursor_down": b"\x1b[B",
        "cursor_forward": b"\x1b[C",
        "cursor_back": b"\x1b[D",
        "cursor_home": b"\x1b[H",
        "cursor_position": b"\x1b[10;20H",  # Row 10, Column 20
        "clear_screen": b"\x1b[2J",
        "clear_line": b"\x1b[2K",
        "save_cursor": b"\x1b[s",
        "restore_cursor": b"\x1b[u",
    }


@pytest.fixture
def color_sequences() -> dict[str, bytes]:
    """Common color escape sequences.

    Returns:
        Dictionary of color sequences.
    """
    return {
        "reset": b"\x1b[0m",
        "bold": b"\x1b[1m",
        "dim": b"\x1b[2m",
        "italic": b"\x1b[3m",
        "underline": b"\x1b[4m",
        "red_fg": b"\x1b[31m",
        "green_fg": b"\x1b[32m",
        "blue_fg": b"\x1b[34m",
        "red_bg": b"\x1b[41m",
        "green_bg": b"\x1b[42m",
        "blue_bg": b"\x1b[44m",
        "256_color_fg": b"\x1b[38;5;196m",  # Bright red
        "256_color_bg": b"\x1b[48;5;21m",  # Blue
        "rgb_fg": b"\x1b[38;2;255;128;0m",  # Orange
        "rgb_bg": b"\x1b[48;2;0;128;255m",  # Light blue
    }


@pytest.fixture
def apt_like_output() -> list[bytes]:
    """Sample output similar to apt update.

    Returns:
        List of output lines.
    """
    return [
        b"Hit:1 http://archive.ubuntu.com/ubuntu jammy InRelease\r\n",
        b"Get:2 http://archive.ubuntu.com/ubuntu jammy-updates InRelease [119 kB]\r\n",
        b"Get:3 http://security.ubuntu.com/ubuntu jammy-security InRelease [110 kB]\r\n",
        b"Fetched 229 kB in 1s (229 kB/s)\r\n",
        b"Reading package lists... Done\r\n",
        b"Building dependency tree... Done\r\n",
        b"Reading state information... Done\r\n",
        b"All packages are up to date.\r\n",
    ]


@pytest.fixture
def progress_bar_output() -> list[bytes]:
    """Sample output with progress bar.

    Returns:
        List of output lines with progress indicators.
    """
    return [
        b"Downloading packages...\r\n",
        b"[==>                    ] 10%\r",
        b"[=====>                 ] 25%\r",
        b"[==========>           ] 50%\r",
        b"[===============>      ] 75%\r",
        b"[====================] 100%\r\n",
        b"Download complete.\r\n",
    ]
