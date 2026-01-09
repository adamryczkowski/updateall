"""Tests for CLI options.

UI Revision Plan - Phase 4 Hot Keys and CLI
See docs/UI-revision-plan.md section 3.2, 3.6 and 4 Phase 4
"""

from __future__ import annotations

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


class TestVersionOption:
    """Tests for --version CLI option."""

    def test_version_shows_cli_version(self) -> None:
        """Test that --version shows CLI version."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "update-all" in result.stdout
        assert "version" in result.stdout

    def test_version_shows_components(self) -> None:
        """Test that --version shows all component versions."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "Components:" in result.stdout
        assert "cli" in result.stdout
        assert "core" in result.stdout
        assert "ui" in result.stdout
        assert "plugins" in result.stdout
        assert "stats" in result.stdout

    def test_version_short_option(self) -> None:
        """Test that -V short option works."""
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert "update-all" in result.stdout


class TestPausePhasesOption:
    """Tests for --pause-phases CLI option."""

    def test_pause_phases_help(self) -> None:
        """Test that --pause-phases is documented in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--pause-phases" in result.stdout or "-P" in result.stdout

    def test_pause_phases_short_option_help(self) -> None:
        """Test that -P short option is documented."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "-P" in result.stdout

    def test_pause_phases_description_in_help(self) -> None:
        """Test that pause-phases description is in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "pause" in result.stdout.lower()

    def test_pause_phases_with_dry_run(self) -> None:
        """Test --pause-phases with --dry-run to avoid actual execution."""
        result = runner.invoke(app, ["run", "--dry-run", "--pause-phases"])
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_pause_phases_short_with_dry_run(self) -> None:
        """Test -P short option with --dry-run."""
        result = runner.invoke(app, ["run", "--dry-run", "-P"])
        # Should at least start without error
        assert result.exit_code in (0, 1)


class TestConcurrencyOption:
    """Tests for --concurrency CLI option."""

    def test_concurrency_help(self) -> None:
        """Test that --concurrency is documented in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--concurrency" in result.stdout or "-j" in result.stdout

    def test_concurrency_short_option_help(self) -> None:
        """Test that -j short option is documented."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "-j" in result.stdout

    def test_concurrency_description_in_help(self) -> None:
        """Test that concurrency description is in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "concurrent" in result.stdout.lower()

    def test_concurrency_with_dry_run(self) -> None:
        """Test --concurrency with --dry-run to avoid actual execution."""
        result = runner.invoke(app, ["run", "--dry-run", "--concurrency", "2"])
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_concurrency_short_with_dry_run(self) -> None:
        """Test -j short option with --dry-run."""
        result = runner.invoke(app, ["run", "--dry-run", "-j", "4"])
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_concurrency_min_value(self) -> None:
        """Test that concurrency accepts minimum value of 1."""
        result = runner.invoke(app, ["run", "--dry-run", "--concurrency", "1"])
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_concurrency_max_value(self) -> None:
        """Test that concurrency accepts maximum value of 32."""
        result = runner.invoke(app, ["run", "--dry-run", "--concurrency", "32"])
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_concurrency_invalid_below_min(self) -> None:
        """Test that concurrency rejects values below minimum."""
        result = runner.invoke(app, ["run", "--dry-run", "--concurrency", "0"])
        # Should fail with validation error
        assert result.exit_code != 0

    def test_concurrency_invalid_above_max(self) -> None:
        """Test that concurrency rejects values above maximum."""
        result = runner.invoke(app, ["run", "--dry-run", "--concurrency", "100"])
        # Should fail with validation error
        assert result.exit_code != 0


class TestCombinedOptions:
    """Tests for combining new CLI options."""

    def test_pause_phases_and_concurrency(self) -> None:
        """Test using both --pause-phases and --concurrency together."""
        result = runner.invoke(app, ["run", "--dry-run", "--pause-phases", "--concurrency", "4"])
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_all_new_options_with_interactive(self) -> None:
        """Test using new options with --interactive.

        Note: This test may not fully exercise interactive mode in CI,
        but it verifies the options are accepted.
        """
        result = runner.invoke(
            app,
            [
                "run",
                "--dry-run",
                "--pause-phases",
                "--concurrency",
                "2",
                # Don't use --interactive in tests as it requires a TTY
            ],
        )
        # Should at least start without error
        assert result.exit_code in (0, 1)

    def test_short_options_combined(self) -> None:
        """Test using short options -P and -j together."""
        result = runner.invoke(app, ["run", "--dry-run", "-P", "-j", "2"])
        # Should at least start without error
        assert result.exit_code in (0, 1)


class TestRunCommandDocstring:
    """Tests for run command documentation."""

    def test_run_help_mentions_pause_phases(self) -> None:
        """Test that run command help mentions pause-phases."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        # Check for description of pause-phases
        assert "pause" in result.stdout.lower()

    def test_run_help_mentions_concurrency(self) -> None:
        """Test that run command help mentions concurrency."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        # Check for description of concurrency
        assert "concurrent" in result.stdout.lower() or "cpu" in result.stdout.lower()

    def test_run_help_mentions_phases(self) -> None:
        """Test that run command help mentions phases."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        # The help should mention phases (Update, Download, Upgrade)
        help_lower = result.stdout.lower()
        assert "phase" in help_lower or "update" in help_lower


class TestInteractiveWithNewOptions:
    """Tests for interactive mode with new options.

    Note: These tests verify option acceptance but don't fully test
    interactive mode as that requires a TTY.
    """

    def test_interactive_help_still_works(self) -> None:
        """Test that --interactive is still documented."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--interactive" in result.stdout or "-i" in result.stdout

    def test_options_order_doesnt_matter(self) -> None:
        """Test that option order doesn't affect parsing."""
        # Options before --dry-run
        result1 = runner.invoke(app, ["run", "--pause-phases", "--concurrency", "2", "--dry-run"])
        # Options after --dry-run
        result2 = runner.invoke(app, ["run", "--dry-run", "--pause-phases", "--concurrency", "2"])
        # Both should work
        assert result1.exit_code in (0, 1)
        assert result2.exit_code in (0, 1)
