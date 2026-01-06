"""Tests for CLI main module."""

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


class TestMainApp:
    """Tests for the main CLI application."""

    def test_version(self) -> None:
        """Test --version flag."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "update-all" in result.stdout
        assert "version" in result.stdout

    def test_help(self) -> None:
        """Test --help flag."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "update-all" in result.stdout.lower() or "Update-All" in result.stdout

    def test_no_args_shows_help(self) -> None:
        """Test that no arguments shows help.

        Note: Typer returns exit code 2 when showing help due to no_args_is_help=True.
        """
        result = runner.invoke(app, [])
        # Typer returns exit code 2 when showing help due to missing args
        assert result.exit_code == 2
        assert "Usage" in result.stdout or "usage" in result.stdout.lower()


class TestRunCommand:
    """Tests for the run command."""

    def test_run_basic(self) -> None:
        """Test basic run command."""
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 0
        assert "Running all enabled plugins" in result.stdout

    def test_run_dry_run(self) -> None:
        """Test run with --dry-run flag."""
        result = runner.invoke(app, ["run", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run mode" in result.stdout

    def test_run_specific_plugins(self) -> None:
        """Test run with specific plugins."""
        result = runner.invoke(app, ["run", "--plugin", "apt", "--plugin", "pipx"])
        assert result.exit_code == 0
        assert "apt" in result.stdout
        assert "pipx" in result.stdout


class TestStatusCommand:
    """Tests for the status command."""

    def test_status(self) -> None:
        """Test status command."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "System Status" in result.stdout


class TestHistoryCommand:
    """Tests for the history command."""

    def test_history(self) -> None:
        """Test history command."""
        result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "Update History" in result.stdout

    def test_history_with_limit(self) -> None:
        """Test history with --limit flag."""
        result = runner.invoke(app, ["history", "--limit", "5"])
        assert result.exit_code == 0
        assert "5" in result.stdout


class TestPluginsCommands:
    """Tests for plugins subcommands."""

    def test_plugins_list(self) -> None:
        """Test plugins list command."""
        result = runner.invoke(app, ["plugins", "list"])
        assert result.exit_code == 0
        assert "Available Plugins" in result.stdout

    def test_plugins_enable(self) -> None:
        """Test plugins enable command."""
        result = runner.invoke(app, ["plugins", "enable", "apt"])
        assert result.exit_code == 0
        assert "Enabling plugin" in result.stdout

    def test_plugins_disable(self) -> None:
        """Test plugins disable command."""
        result = runner.invoke(app, ["plugins", "disable", "apt"])
        assert result.exit_code == 0
        assert "Disabling plugin" in result.stdout


class TestConfigCommands:
    """Tests for config subcommands."""

    def test_config_show(self) -> None:
        """Test config show command."""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Configuration" in result.stdout

    def test_config_init(self) -> None:
        """Test config init command."""
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        assert "Initializing" in result.stdout
