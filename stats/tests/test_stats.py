"""Tests for stats components.

Note: HistoryStore tests have been moved to test_history.py.
This file now focuses on StatsCalculator and UpdateStats tests.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from stats.calculator import StatsCalculator, UpdateStats
from stats.history import HistoryStore

if TYPE_CHECKING:
    from pathlib import Path


class TestHistoryStoreLegacy:
    """Legacy tests for HistoryStore (deprecated).

    These tests verify backward compatibility of the deprecated HistoryStore.
    New tests should use DuckDBHistoryStore - see test_history.py.
    """

    def test_init_creates_file(self, tmp_path: Path) -> None:
        """Test that init creates the history file."""
        history_file = tmp_path / "history.json"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            HistoryStore(history_file)

        assert history_file.exists()

    def test_get_recent_runs_empty(self, tmp_path: Path) -> None:
        """Test getting recent runs from empty history."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(tmp_path / "history.json")

        runs = store.get_recent_runs()

        assert runs == []

    def test_get_total_runs_empty(self, tmp_path: Path) -> None:
        """Test total runs count on empty history."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(tmp_path / "history.json")

        count = store.get_total_runs()

        assert count == 0

    def test_clear_history(self, tmp_path: Path) -> None:
        """Test clearing history."""
        history_file = tmp_path / "history.json"
        history_file.write_text('[{"id": "test"}]')
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)

        store.clear_history()

        assert store.get_total_runs() == 0

    def test_get_recent_runs_sorted(self, tmp_path: Path) -> None:
        """Test that recent runs are sorted by time."""
        history_file = tmp_path / "history.json"
        now = datetime.now(tz=UTC)
        history = [
            {"id": "old", "start_time": (now - timedelta(days=2)).isoformat()},
            {"id": "new", "start_time": now.isoformat()},
            {"id": "mid", "start_time": (now - timedelta(days=1)).isoformat()},
        ]
        history_file.write_text(json.dumps(history))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)

        runs = store.get_recent_runs(limit=3)

        assert runs[0]["id"] == "new"
        assert runs[1]["id"] == "mid"
        assert runs[2]["id"] == "old"

    def test_get_runs_by_plugin(self, tmp_path: Path) -> None:
        """Test filtering runs by plugin."""
        history_file = tmp_path / "history.json"
        now = datetime.now(tz=UTC)
        history = [
            {
                "id": "run1",
                "start_time": now.isoformat(),
                "plugins": [{"name": "apt"}, {"name": "pipx"}],
            },
            {
                "id": "run2",
                "start_time": now.isoformat(),
                "plugins": [{"name": "flatpak"}],
            },
        ]
        history_file.write_text(json.dumps(history))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)

        runs = store.get_runs_by_plugin("apt")

        assert len(runs) == 1
        assert runs[0]["id"] == "run1"

    def test_get_runs_in_range(self, tmp_path: Path) -> None:
        """Test getting runs in a date range."""
        history_file = tmp_path / "history.json"
        now = datetime.now(tz=UTC)
        history = [
            {"id": "old", "start_time": (now - timedelta(days=10)).isoformat()},
            {"id": "recent", "start_time": (now - timedelta(days=2)).isoformat()},
            {"id": "today", "start_time": now.isoformat()},
        ]
        history_file.write_text(json.dumps(history))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)

        runs = store.get_runs_in_range(now - timedelta(days=5), now)

        assert len(runs) == 2
        ids = {r["id"] for r in runs}
        assert ids == {"recent", "today"}


class TestStatsCalculator:
    """Tests for StatsCalculator."""

    def test_calculate_stats_empty(self, tmp_path: Path) -> None:
        """Test calculating stats on empty history."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(tmp_path / "history.json")
        calc = StatsCalculator(store)

        stats = calc.calculate_stats(days=30)

        assert stats.total_runs == 0
        assert stats.success_rate == 0.0

    def test_calculate_stats_with_data(self, tmp_path: Path) -> None:
        """Test calculating stats with data."""
        history_file = tmp_path / "history.json"
        now = datetime.now(tz=UTC)
        start = now - timedelta(minutes=5)
        history = [
            {
                "id": "run1",
                "start_time": now.isoformat(),
                "plugins": [
                    {
                        "name": "apt",
                        "status": "success",
                        "packages_updated": 5,
                        "start_time": start.isoformat(),
                        "end_time": now.isoformat(),
                    },
                    {
                        "name": "pipx",
                        "status": "success",
                        "packages_updated": 2,
                        "start_time": start.isoformat(),
                        "end_time": now.isoformat(),
                    },
                ],
            },
        ]
        history_file.write_text(json.dumps(history))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)
        calc = StatsCalculator(store)

        stats = calc.calculate_stats(days=30)

        assert stats.total_runs == 1
        assert stats.successful_runs == 2
        assert stats.total_packages_updated == 7
        assert stats.success_rate == 1.0

    def test_calculate_plugin_stats(self, tmp_path: Path) -> None:
        """Test calculating stats for a specific plugin."""
        history_file = tmp_path / "history.json"
        now = datetime.now(tz=UTC)
        start = now - timedelta(seconds=30)
        history = [
            {
                "id": "run1",
                "start_time": now.isoformat(),
                "plugins": [
                    {
                        "name": "apt",
                        "status": "success",
                        "packages_updated": 5,
                        "start_time": start.isoformat(),
                        "end_time": now.isoformat(),
                    },
                ],
            },
            {
                "id": "run2",
                "start_time": now.isoformat(),
                "plugins": [
                    {
                        "name": "apt",
                        "status": "failed",
                        "packages_updated": 0,
                        "start_time": start.isoformat(),
                        "end_time": now.isoformat(),
                    },
                ],
            },
        ]
        history_file.write_text(json.dumps(history))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)
        calc = StatsCalculator(store)

        stats = calc.calculate_plugin_stats("apt", days=30)

        assert stats.plugin_name == "apt"
        assert stats.total_runs == 2
        assert stats.successful_runs == 1
        assert stats.failed_runs == 1
        assert stats.success_rate == 0.5


class TestUpdateStats:
    """Tests for UpdateStats dataclass."""

    def test_avg_packages_per_run(self) -> None:
        """Test average packages per run calculation."""
        stats = UpdateStats(
            total_runs=10,
            successful_runs=8,
            failed_runs=2,
            timeout_runs=0,
            skipped_runs=0,
            total_packages_updated=50,
            total_duration_seconds=300.0,
            avg_duration_seconds=30.0,
            success_rate=0.8,
            period_days=30,
        )

        assert stats.avg_packages_per_run == 5.0

    def test_avg_packages_per_run_zero_runs(self) -> None:
        """Test average packages when no runs."""
        stats = UpdateStats(
            total_runs=0,
            successful_runs=0,
            failed_runs=0,
            timeout_runs=0,
            skipped_runs=0,
            total_packages_updated=0,
            total_duration_seconds=0.0,
            avg_duration_seconds=0.0,
            success_rate=0.0,
            period_days=30,
        )

        assert stats.avg_packages_per_run == 0.0
