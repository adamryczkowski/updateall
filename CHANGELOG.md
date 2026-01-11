# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ui/ui/models.py` - New module for data models (extracted from interactive_tabbed_run.py)
- `ui/ui/messages.py` - New module for Textual message classes (extracted from interactive_tabbed_run.py)
- `ui/tests/test_regression_bugs.py` - Consolidated regression tests for bug fixes
- `docs/README.md` - Documentation index with categorized document listing
- `docs/archive/` - Archive directory for completed implementation plans
- `plugins/plugins/mocks/` - Dedicated subpackage for mock plugins

### Changed
- **UI Module Architecture Refactoring**
  - Extracted `InteractiveTabData` to `ui/ui/models.py`
  - Extracted `AllPluginsCompleted` message to `ui/ui/messages.py`
  - Expanded `ui/ui/progress.py` with `ProgressBar` widget
  - Expanded `ui/ui/metrics.py` with all metrics classes (`MetricsCollector`, `MetricsSnapshot`, `PhaseMetrics`, `PhaseStats`, `RunningProgress`)
  - Reduced `ui/ui/phase_status_bar.py` to contain only the `PhaseStatusBar` widget
  - Added comprehensive docstrings to `phase_controller.py` and `tabbed_run.py`

- **Core Module Cleanup**
  - Added comprehensive docstrings to `orchestrator.py` and `parallel_orchestrator.py` explaining when to use each
  - Added comprehensive docstrings to `core/metrics.py` distinguishing it from `ui/metrics.py`
  - Enhanced `core/__init__.py` with module overview documentation

- **Plugins Module Cleanup**
  - Moved mock plugins (`mock_alpha.py`, `mock_beta.py`) to `plugins/plugins/mocks/` subpackage
  - Enhanced docstrings for apt, atuin, cargo, flatpak, npm, pipx, r, snap plugins
  - Enhanced `registry.py` with usage examples and entry point documentation

- **Test Suite Rationalization**
  - Consolidated bug verification tests into `test_regression_bugs.py`
  - Updated test docstrings with clear categorization (unit, integration, E2E, regression)
  - Fixed flaky timing test in `test_e2e_phase_stats_preservation.py`

- **Cross-Module Consistency**
  - Standardized `pytest-asyncio` version to `^1.3.0` across all subprojects
  - Added `asyncio_mode = "auto"` to ui and stats pyproject.toml
  - Renamed `DownloadError` to `PluginDownloadError` in plugins/repository.py to avoid naming conflict

- **Documentation Consolidation**
  - Archived 5 completed implementation plans to `docs/archive/`
  - Updated `bug-investigation-report.md` status to RESOLVED
  - Created `docs/README.md` with documentation index

### Removed
- Debug scripts from `scripts/` directory:
  - `add_debug_logging.py`
  - `debug_app.py`
  - `debug_metrics_preservation.py`
  - `debug_phase_reset.py`
  - `debug_phase_stats.py`
  - `poc_bug_verification.py`
  - `trace_phase_stats.py`

### Fixed
- **Bug 1: CPU statistics not updating** - Metrics now properly aggregate child process metrics
- **Bug 2: Phase counters reset** - Phase statistics are preserved across phase transitions
- **Bug 3: Scrolling not working** - Scrolling now responds immediately without waiting for update interval

## [0.1.0] - 2025-01-08

### Added
- Initial release with core functionality
- Plugin system with support for apt, flatpak, snap, pipx, cargo, npm, rustup
- Interactive tabbed UI with PTY terminal emulation
- Multi-phase plugin execution (check, download, execute)
- Statistics tracking with DuckDB integration
- Configuration management via YAML
- Update history tracking
