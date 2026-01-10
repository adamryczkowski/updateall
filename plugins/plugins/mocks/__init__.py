"""Mock plugins for debugging and testing the interactive UI.

This package contains mock plugins that simulate real update operations
with configurable behavior. They are used for:

1. **Development/Debugging**: Test the interactive UI without running real updates
2. **Integration Testing**: Verify phase transitions and metrics collection
3. **Performance Testing**: Generate real CPU/network load for benchmarking

Mock plugins are always available and can be used exclusively by setting
the environment variable UPDATE_ALL_DEBUG_MOCK_ONLY=1.

Usage:
    # Run with only mock plugins
    just run-mock-interactive

    # Or manually:
    UPDATE_ALL_DEBUG_MOCK_ONLY=1 poetry run update-all run --interactive

Available Plugins:
    - MockAlphaPlugin: Multi-phase update simulation
    - MockBetaPlugin: Multi-phase update simulation (different timing)
"""

from __future__ import annotations

from plugins.mocks.mock_alpha import MockAlphaPlugin
from plugins.mocks.mock_beta import MockBetaPlugin

__all__ = [
    "MockAlphaPlugin",
    "MockBetaPlugin",
]
