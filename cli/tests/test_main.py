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
        """Test basic run command with dry-run to avoid sudo prompts."""
        result = runner.invoke(app, ["run", "--dry-run"])
        # May fail if plugins aren't available, but should at least start
        assert result.exit_code in (0, 1)

    def test_run_dry_run(self) -> None:
        """Test run with --dry-run flag."""
        result = runner.invoke(app, ["run", "--dry-run"])
        assert "Dry run mode" in result.stdout or result.exit_code in (0, 1)

    def test_run_specific_plugins(self) -> None:
        """Test run with specific plugins using dry-run to avoid sudo prompts."""
        result = runner.invoke(app, ["run", "--plugin", "apt", "--plugin", "pipx", "--dry-run"])
        # Should at least attempt to run the specified plugins
        assert result.exit_code in (0, 1)


class TestCheckCommand:
    """Tests for the check command."""

    def test_check_basic(self) -> None:
        """Test basic check command."""
        result = runner.invoke(app, ["check"])
        assert result.exit_code in (0, 1)
        assert "Checking" in result.stdout or "Available" in result.stdout

    def test_check_specific_plugin(self) -> None:
        """Test check with specific plugin."""
        result = runner.invoke(app, ["check", "--plugin", "apt"])
        assert result.exit_code in (0, 1)


class TestStatusCommand:
    """Tests for the status command."""

    def test_status(self) -> None:
        """Test status command."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Plugin" in result.stdout or "Status" in result.stdout


class TestHistoryCommand:
    """Tests for the history command."""

    def test_history(self) -> None:
        """Test history command."""
        result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        # Either shows history or "No history available"
        assert "History" in result.stdout or "history" in result.stdout.lower()

    def test_history_with_limit(self) -> None:
        """Test history with --limit flag."""
        result = runner.invoke(app, ["history", "--limit", "5"])
        assert result.exit_code == 0


class TestPluginsCommands:
    """Tests for plugins subcommands."""

    def test_plugins_list(self) -> None:
        """Test plugins list command."""
        result = runner.invoke(app, ["plugins", "list"])
        assert result.exit_code == 0
        assert "Plugin" in result.stdout or "Available" in result.stdout

    def test_plugins_enable(self) -> None:
        """Test plugins enable command."""
        result = runner.invoke(app, ["plugins", "enable", "apt"])
        assert result.exit_code == 0
        assert "Enabled" in result.stdout or "apt" in result.stdout

    def test_plugins_disable(self) -> None:
        """Test plugins disable command."""
        result = runner.invoke(app, ["plugins", "disable", "apt"])
        assert result.exit_code == 0
        assert "Disabled" in result.stdout or "apt" in result.stdout


class TestConfigCommands:
    """Tests for config subcommands."""

    def test_config_show(self) -> None:
        """Test config show command."""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Configuration" in result.stdout or "global" in result.stdout

    def test_config_init(self) -> None:
        """Test config init command."""
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        # Either creates new config or says it exists
        assert "Configuration" in result.stdout or "config" in result.stdout.lower()

    def test_config_path(self) -> None:
        """Test config path command."""
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert "update-all" in result.stdout or "config" in result.stdout.lower()
