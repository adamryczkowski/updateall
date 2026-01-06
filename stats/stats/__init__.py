"""Update-All Stats package.

Statistics and history tracking for the update-all system.
"""

from stats.calculator import StatsCalculator
from stats.history import HistoryStore

__all__ = ["HistoryStore", "StatsCalculator"]
