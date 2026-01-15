"""Tests for LSQM CLI commands."""

import pytest
from click.testing import CliRunner

from lsqm.cli import main


@pytest.fixture
def cli_runner():
    """Create a Click CLI test runner."""
    return CliRunner()


class TestMainCLI:
    """Tests for main CLI entry point."""

    def test_cli_version(self, cli_runner):
        """Test --version flag."""
        result = cli_runner.invoke(main, ["--version"])

        assert result.exit_code == 0
        assert "lsqm" in result.output
        assert "1.0.0" in result.output

    def test_cli_help(self, cli_runner):
        """Test --help flag."""
        result = cli_runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "LocalStack Quality Monitor" in result.output
        assert "--config" in result.output
        assert "--verbose" in result.output
        assert "--dry-run" in result.output

    def test_cli_commands_listed(self, cli_runner):
        """Test that all commands are listed in help."""
        result = cli_runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "run" in result.output
        assert "sync" in result.output
        assert "mine" in result.output
        assert "generate" in result.output
        assert "validate" in result.output
        assert "report" in result.output
        assert "push" in result.output
        assert "compare" in result.output
        assert "notify" in result.output
        assert "status" in result.output
        assert "clean" in result.output


class TestSyncCommand:
    """Tests for sync command."""

    def test_sync_help(self, cli_runner):
        """Test sync --help."""
        result = cli_runner.invoke(main, ["sync", "--help"])

        assert result.exit_code == 0
        assert "Sync" in result.output or "sync" in result.output

    def test_sync_dry_run(self, cli_runner):
        """Test sync in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "sync"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "sync" in result.output.lower()


class TestMineCommand:
    """Tests for mine command."""

    def test_mine_help(self, cli_runner):
        """Test mine --help."""
        result = cli_runner.invoke(main, ["mine", "--help"])

        assert result.exit_code == 0
        assert "Discover" in result.output or "mine" in result.output

    def test_mine_dry_run(self, cli_runner):
        """Test mine in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "mine", "--limit", "5"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "5" in result.output

    def test_mine_with_sources(self, cli_runner):
        """Test mine with specific sources."""
        result = cli_runner.invoke(main, ["--dry-run", "mine", "--source", "github_orgs"])

        assert result.exit_code == 0
        assert "github_orgs" in result.output


class TestGenerateCommand:
    """Tests for generate command."""

    def test_generate_help(self, cli_runner):
        """Test generate --help."""
        result = cli_runner.invoke(main, ["generate", "--help"])

        assert result.exit_code == 0
        assert "Generate" in result.output or "generate" in result.output
        assert "--budget" in result.output

    def test_generate_dry_run(self, cli_runner):
        """Test generate in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "generate", "--budget", "50000"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "50000" in result.output


class TestValidateCommand:
    """Tests for validate command."""

    def test_validate_help(self, cli_runner):
        """Test validate --help."""
        result = cli_runner.invoke(main, ["validate", "--help"])

        assert result.exit_code == 0
        assert "Validate" in result.output or "validate" in result.output

    def test_validate_dry_run(self, cli_runner):
        """Test validate in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "validate"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    def test_validate_with_parallel(self, cli_runner):
        """Test validate with parallel setting."""
        result = cli_runner.invoke(main, ["--parallel", "2", "--dry-run", "validate"])

        assert result.exit_code == 0
        assert "Parallel: 2" in result.output


class TestReportCommand:
    """Tests for report command."""

    def test_report_help(self, cli_runner):
        """Test report --help."""
        result = cli_runner.invoke(main, ["report", "--help"])

        assert result.exit_code == 0
        assert "report" in result.output.lower()

    def test_report_dry_run(self, cli_runner):
        """Test report in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "report"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output


class TestPushCommand:
    """Tests for push command."""

    def test_push_help(self, cli_runner):
        """Test push --help."""
        result = cli_runner.invoke(main, ["push", "--help"])

        assert result.exit_code == 0
        assert "Push" in result.output or "push" in result.output

    def test_push_dry_run(self, cli_runner):
        """Test push in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "push"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output


class TestCompareCommand:
    """Tests for compare command."""

    def test_compare_help(self, cli_runner):
        """Test compare --help."""
        result = cli_runner.invoke(main, ["compare", "--help"])

        assert result.exit_code == 0
        assert "Compare" in result.output or "compare" in result.output

    def test_compare_dry_run(self, cli_runner):
        """Test compare in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "compare"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output


class TestNotifyCommand:
    """Tests for notify command."""

    def test_notify_help(self, cli_runner):
        """Test notify --help."""
        result = cli_runner.invoke(main, ["notify", "--help"])

        assert result.exit_code == 0
        assert "notify" in result.output.lower()

    def test_notify_dry_run(self, cli_runner):
        """Test notify in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "notify"])

        assert result.exit_code == 0
        # Notify may show DRY RUN or skip if no webhook configured
        assert "DRY RUN" in result.output or "not configured" in result.output


class TestStatusCommand:
    """Tests for status command."""

    def test_status_help(self, cli_runner):
        """Test status --help."""
        result = cli_runner.invoke(main, ["status", "--help"])

        assert result.exit_code == 0
        assert "status" in result.output.lower()

    def test_status_output(self, cli_runner):
        """Test status command output."""
        result = cli_runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "LocalStack Quality Monitor Status" in result.output
        assert "Architectures:" in result.output

    def test_status_dry_run(self, cli_runner):
        """Test status in dry-run mode (should show actual status)."""
        result = cli_runner.invoke(main, ["--dry-run", "status"])

        assert result.exit_code == 0
        # Status command shows actual data even in dry-run
        assert "Architectures:" in result.output


class TestCleanCommand:
    """Tests for clean command."""

    def test_clean_help(self, cli_runner):
        """Test clean --help."""
        result = cli_runner.invoke(main, ["clean", "--help"])

        assert result.exit_code == 0
        assert "clean" in result.output.lower()
        assert "--containers" in result.output
        assert "--cache" in result.output

    def test_clean_dry_run(self, cli_runner):
        """Test clean in dry-run mode."""
        result = cli_runner.invoke(main, ["--dry-run", "clean"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output


class TestRunCommand:
    """Tests for run command (full pipeline)."""

    def test_run_help(self, cli_runner):
        """Test run --help."""
        result = cli_runner.invoke(main, ["run", "--help"])

        assert result.exit_code == 0
        assert "pipeline" in result.output.lower() or "run" in result.output.lower()

    def test_run_requires_config(self, cli_runner, monkeypatch):
        """Test that run command requires configuration."""
        # Clear any existing env vars
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("ARTIFACT_REPO", raising=False)

        result = cli_runner.invoke(main, ["run"])

        # Should fail with config error (exit code 3)
        assert result.exit_code == 3
        assert "Configuration error" in result.output or "required" in result.output.lower()

    def test_run_dry_run_with_config(self, cli_runner, mock_env):
        """Test run in dry-run mode with valid config."""
        result = cli_runner.invoke(main, ["--dry-run", "run"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output


class TestCLIGlobalOptions:
    """Tests for global CLI options."""

    def test_verbose_flag(self, cli_runner):
        """Test --verbose flag is accepted."""
        result = cli_runner.invoke(main, ["--verbose", "status"])

        assert result.exit_code == 0

    def test_config_option(self, cli_runner, temp_dir):
        """Test --config option with valid file."""
        import yaml

        config_file = temp_dir / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump({"parallel": 8}, f)

        result = cli_runner.invoke(main, ["--config", str(config_file), "status"])

        assert result.exit_code == 0

    def test_config_option_invalid_file(self, cli_runner):
        """Test --config option with non-existent file."""
        result = cli_runner.invoke(main, ["--config", "/nonexistent/config.yaml", "status"])

        assert result.exit_code != 0

    def test_localstack_version_option(self, cli_runner):
        """Test --localstack-version option."""
        result = cli_runner.invoke(main, ["--localstack-version", "3.0.0", "--dry-run", "validate"])

        assert result.exit_code == 0
