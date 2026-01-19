"""Shared test fixtures for CLI tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """Isolate tests from the real user data directory.

    Sets XDG_DATA_HOME to a temporary directory so that tests don't
    access or modify the real history database at ~/.local/share/update-all/.

    This fixture is applied automatically to all tests in this module.
    """
    data_home = tmp_path / "xdg_data"
    data_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    yield data_home
