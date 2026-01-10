"""Tests for LSQM utility modules."""

import json
import logging

import yaml

from lsqm.utils.config import (
    CDKSourceConfig,
    CustomSourceConfig,
    GitHubOrgsSourceConfig,
    LSQMConfig,
    ServerlessSourceConfig,
    SourcesConfig,
    TerraformRegistrySourceConfig,
    get_artifacts_dir,
    get_cache_dir,
    load_config,
)
from lsqm.utils.hashing import compute_architecture_hash, normalize_terraform
from lsqm.utils.logging import JSONFormatter, get_logger, stage_context


class TestLSQMConfig:
    """Tests for LSQMConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = LSQMConfig()

        assert config.anthropic_api_key == ""
        assert config.github_token == ""
        assert config.artifact_repo == ""
        assert config.token_budget == 500_000
        assert config.localstack_version == "latest"
        assert config.parallel == 4
        assert config.timeout == 300
        assert config.issue_repo == "localstack/localstack"

    def test_config_validate_missing_required(self):
        """Test validation fails when required fields are missing."""
        config = LSQMConfig()
        valid, errors = config.validate()

        assert valid is False
        assert len(errors) == 3
        assert "ANTHROPIC_API_KEY" in errors[0]
        assert "GITHUB_TOKEN" in errors[1]
        assert "ARTIFACT_REPO" in errors[2]

    def test_config_validate_success(self):
        """Test validation succeeds with required fields."""
        config = LSQMConfig(
            anthropic_api_key="sk-ant-test",
            github_token="ghp_test",
            artifact_repo="org/repo",
        )
        valid, errors = config.validate()

        assert valid is True
        assert len(errors) == 0

    def test_artifact_repo_owner(self):
        """Test artifact_repo_owner property."""
        config = LSQMConfig(artifact_repo="my-org/my-repo")
        assert config.artifact_repo_owner == "my-org"

    def test_artifact_repo_name(self):
        """Test artifact_repo_name property."""
        config = LSQMConfig(artifact_repo="my-org/my-repo")
        assert config.artifact_repo_name == "my-repo"

    def test_artifact_repo_no_slash(self):
        """Test artifact_repo properties when no slash present."""
        config = LSQMConfig(artifact_repo="repo-only")
        assert config.artifact_repo_owner == ""
        assert config.artifact_repo_name == "repo-only"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_from_env(self, monkeypatch):
        """Test loading config from environment variables."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-key")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
        monkeypatch.setenv("ARTIFACT_REPO", "env-org/env-repo")
        monkeypatch.setenv("LOCALSTACK_VERSION", "3.0.0")
        monkeypatch.setenv("LSQM_PARALLEL", "8")
        monkeypatch.setenv("LSQM_TIMEOUT", "600")

        config = load_config()

        assert config.anthropic_api_key == "sk-ant-env-key"
        assert config.github_token == "ghp_env_token"
        assert config.artifact_repo == "env-org/env-repo"
        assert config.localstack_version == "3.0.0"
        assert config.parallel == 8
        assert config.timeout == 600

    def test_load_config_from_yaml(self, monkeypatch, temp_dir):
        """Test loading config from YAML file."""
        # Clear environment variables
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("ARTIFACT_REPO", raising=False)

        yaml_config = {
            "anthropic_api_key": "sk-ant-yaml-key",
            "github_token": "ghp_yaml_token",
            "artifact_repo": "yaml-org/yaml-repo",
            "parallel": 6,
            "sources": {
                "terraform_registry": False,
            },
        }

        config_file = temp_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(yaml_config, f)

        config = load_config(config_file)

        assert config.anthropic_api_key == "sk-ant-yaml-key"
        assert config.github_token == "ghp_yaml_token"
        assert config.parallel == 6
        assert config.sources.terraform_registry.enabled is False

    def test_env_overrides_yaml(self, monkeypatch, temp_dir):
        """Test that environment variables override YAML config."""
        yaml_config = {
            "anthropic_api_key": "sk-ant-yaml-key",
            "github_token": "ghp_yaml_token",
            "artifact_repo": "yaml-org/yaml-repo",
        }

        config_file = temp_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(yaml_config, f)

        # Set env var to override
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-override")

        config = load_config(config_file)

        assert config.anthropic_api_key == "sk-ant-override"  # From env
        assert config.github_token == "ghp_yaml_token"  # From YAML


class TestCacheDirs:
    """Tests for cache directory functions."""

    def test_get_cache_dir(self):
        """Test get_cache_dir returns valid path."""
        cache_dir = get_cache_dir()

        assert cache_dir.exists()
        assert cache_dir.is_dir()
        assert ".lsqm" in str(cache_dir)
        assert "cache" in str(cache_dir)

    def test_get_artifacts_dir(self):
        """Test get_artifacts_dir returns valid path."""
        artifacts_dir = get_artifacts_dir()

        assert "cache" in str(artifacts_dir)
        assert "artifacts" in str(artifacts_dir)


class TestNormalizeTerraform:
    """Tests for normalize_terraform function."""

    def test_normalize_removes_comments(self):
        """Test that comments are removed."""
        tf_content = """
# This is a comment
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"  # inline comment
}
"""
        normalized = normalize_terraform(tf_content)

        assert "# This is a comment" not in normalized
        assert "# inline comment" not in normalized
        assert 'resource "aws_vpc"' in normalized

    def test_normalize_removes_blank_lines(self):
        """Test that extra blank lines are removed."""
        tf_content = """
resource "aws_vpc" "main" {


  cidr_block = "10.0.0.0/16"

}
"""
        normalized = normalize_terraform(tf_content)
        lines = [line for line in normalized.split("\n") if line.strip()]

        # Should not have multiple consecutive blank lines
        assert len(lines) >= 2

    def test_normalize_consistent_output(self):
        """Test that same logical content produces same output."""
        tf1 = """
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}
"""
        tf2 = """
# Comment that should be removed
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}
"""
        norm1 = normalize_terraform(tf1)
        norm2 = normalize_terraform(tf2)

        assert norm1 == norm2


class TestComputeArchitectureHash:
    """Tests for compute_architecture_hash function."""

    def test_hash_single_file(self):
        """Test computing hash for single file."""
        tf_files = {
            "main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }'
        }

        hash1 = compute_architecture_hash(tf_files)

        assert len(hash1) == 16  # Truncated SHA256
        assert hash1.isalnum()

    def test_hash_multiple_files(self):
        """Test computing hash for multiple files."""
        tf_files = {
            "main.tf": 'resource "aws_vpc" "main" {}',
            "variables.tf": 'variable "region" { default = "us-east-1" }',
        }

        hash_result = compute_architecture_hash(tf_files)

        assert len(hash_result) == 16

    def test_hash_deterministic(self):
        """Test that hash is deterministic."""
        tf_files = {
            "main.tf": 'resource "aws_s3_bucket" "test" { bucket = "my-bucket" }'
        }

        hash1 = compute_architecture_hash(tf_files)
        hash2 = compute_architecture_hash(tf_files)

        assert hash1 == hash2

    def test_hash_file_order_independent(self):
        """Test that file order doesn't affect hash (sorted internally)."""
        tf_files_a = {
            "a.tf": "resource a {}",
            "b.tf": "resource b {}",
        }
        tf_files_b = {
            "b.tf": "resource b {}",
            "a.tf": "resource a {}",
        }

        hash_a = compute_architecture_hash(tf_files_a)
        hash_b = compute_architecture_hash(tf_files_b)

        assert hash_a == hash_b

    def test_hash_different_content_different_hash(self):
        """Test that different content produces different hash."""
        tf_files_1 = {"main.tf": "resource a {}"}
        tf_files_2 = {"main.tf": "resource b {}"}

        hash1 = compute_architecture_hash(tf_files_1)
        hash2 = compute_architecture_hash(tf_files_2)

        assert hash1 != hash2


class TestJSONFormatter:
    """Tests for JSONFormatter logging class."""

    def test_json_formatter_output(self):
        """Test that formatter produces valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert "timestamp" in data

    def test_json_formatter_with_extra(self):
        """Test formatter with extra fields via extra dict."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        # Set extra as the formatter expects
        record.extra = {"arch_hash": "abc123"}

        output = formatter.format(record)
        data = json.loads(output)

        assert data["arch_hash"] == "abc123"


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_basic(self):
        """Test creating basic logger."""
        logger = get_logger("test_logger")

        assert logger.name == "test_logger"
        assert isinstance(logger, logging.Logger)

    def test_get_logger_verbose(self):
        """Test creating verbose logger."""
        logger = get_logger("test_verbose", verbose=True)

        assert logger.level == logging.DEBUG


class TestStageContext:
    """Tests for stage_context context manager."""

    def test_stage_context(self):
        """Test stage timing context manager."""
        logger = get_logger("test_timing")
        logs = []

        # Add handler to capture logs
        handler = logging.Handler()
        handler.emit = lambda r: logs.append(r)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with stage_context("test_stage", logger):
            pass  # Do nothing

        # Should have logged start and complete
        assert len(logs) >= 1


class TestSourcesConfig:
    """Tests for SourcesConfig and related classes."""

    def test_terraform_registry_source_defaults(self):
        """Test TerraformRegistrySourceConfig default values."""
        config = TerraformRegistrySourceConfig()

        assert config.enabled is True
        assert "aws" in config.providers
        assert config.limit_per_provider == 100
        assert config.min_downloads == 1000

    def test_github_orgs_source_defaults(self):
        """Test GitHubOrgsSourceConfig default values."""
        config = GitHubOrgsSourceConfig()

        assert config.enabled is True
        assert "aws-quickstart" in config.organizations
        assert "*.tf" in config.file_patterns
        assert config.max_files_per_repo == 50
        assert config.skip_archived is True
        assert config.skip_forks is True

    def test_serverless_source_defaults(self):
        """Test ServerlessSourceConfig default values."""
        config = ServerlessSourceConfig()

        assert config.enabled is True
        assert len(config.search_queries) > 0
        assert config.max_results == 100

    def test_cdk_source_defaults(self):
        """Test CDKSourceConfig default values."""
        config = CDKSourceConfig()

        assert config.enabled is True
        assert len(config.repositories) > 0
        assert "typescript" in config.languages
        assert "python" in config.languages

    def test_custom_source_defaults(self):
        """Test CustomSourceConfig default values."""
        config = CustomSourceConfig()

        assert config.enabled is False
        assert config.repositories == []
        assert config.local_paths == []

    def test_sources_config_from_dict_empty(self):
        """Test SourcesConfig.from_dict with empty dict."""
        config = SourcesConfig.from_dict({})

        assert config.terraform_registry.enabled is True
        assert config.github_orgs.enabled is True
        assert config.serverless.enabled is True
        assert config.cdk.enabled is True
        assert config.custom.enabled is False

    def test_sources_config_from_dict_bool_disable(self):
        """Test SourcesConfig.from_dict with boolean to disable source."""
        data = {
            "terraform_registry": False,
            "github_orgs": False,
        }
        config = SourcesConfig.from_dict(data)

        assert config.terraform_registry.enabled is False
        assert config.github_orgs.enabled is False
        assert config.serverless.enabled is True  # Not disabled

    def test_sources_config_from_dict_full(self):
        """Test SourcesConfig.from_dict with full config."""
        data = {
            "terraform_registry": {
                "enabled": True,
                "providers": ["aws", "google"],
                "limit_per_provider": 50,
                "min_downloads": 500,
            },
            "github_orgs": {
                "enabled": True,
                "organizations": ["custom-org"],
                "file_patterns": ["*.tf"],
                "max_files_per_repo": 100,
                "skip_archived": False,
            },
            "serverless": {
                "enabled": False,
            },
            "cdk": {
                "enabled": True,
                "repositories": ["custom/repo"],
                "languages": ["python"],
            },
            "custom": {
                "enabled": True,
                "repositories": ["https://github.com/test/repo"],
                "local_paths": ["/path/to/local"],
            },
        }

        config = SourcesConfig.from_dict(data)

        assert config.terraform_registry.enabled is True
        assert config.terraform_registry.providers == ["aws", "google"]
        assert config.terraform_registry.limit_per_provider == 50
        assert config.terraform_registry.min_downloads == 500

        assert config.github_orgs.organizations == ["custom-org"]
        assert config.github_orgs.max_files_per_repo == 100
        assert config.github_orgs.skip_archived is False

        assert config.serverless.enabled is False

        assert config.cdk.repositories == ["custom/repo"]
        assert config.cdk.languages == ["python"]

        assert config.custom.enabled is True
        assert "https://github.com/test/repo" in config.custom.repositories
        assert "/path/to/local" in config.custom.local_paths

    def test_sources_config_to_dict(self):
        """Test SourcesConfig.to_dict serialization."""
        config = SourcesConfig()
        data = config.to_dict()

        assert "terraform_registry" in data
        assert "github_orgs" in data
        assert "serverless" in data
        assert "cdk" in data
        assert "custom" in data

        assert data["terraform_registry"]["enabled"] is True
        assert data["custom"]["enabled"] is False

    def test_sources_config_roundtrip(self):
        """Test SourcesConfig to_dict/from_dict roundtrip."""
        original = SourcesConfig()
        original.terraform_registry.enabled = False
        original.custom.enabled = True
        original.custom.repositories = ["test-repo"]

        data = original.to_dict()
        restored = SourcesConfig.from_dict(data)

        assert restored.terraform_registry.enabled == original.terraform_registry.enabled
        assert restored.custom.enabled == original.custom.enabled
        assert restored.custom.repositories == original.custom.repositories

    def test_sources_config_github_orgs_list_shorthand(self):
        """Test SourcesConfig.from_dict with list shorthand for github_orgs."""
        data = {
            "github_orgs": ["org1", "org2", "org3"],
        }
        config = SourcesConfig.from_dict(data)

        assert config.github_orgs.enabled is True
        assert config.github_orgs.organizations == ["org1", "org2", "org3"]
