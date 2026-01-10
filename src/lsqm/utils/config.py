"""Configuration loading from environment and YAML file."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TerraformRegistrySourceConfig:
    """Configuration for Terraform Registry discovery source."""

    enabled: bool = True
    providers: list[str] = field(default_factory=lambda: ["aws"])
    limit_per_provider: int = 100
    min_downloads: int = 1000  # Only modules with at least this many downloads


@dataclass
class GitHubOrgsSourceConfig:
    """Configuration for GitHub Organizations discovery source."""

    enabled: bool = True
    organizations: list[str] = field(default_factory=lambda: [
        "aws-quickstart",
        "aws-solutions",
        "aws-samples",
    ])
    file_patterns: list[str] = field(default_factory=lambda: ["*.tf", "**/*.tf"])
    max_files_per_repo: int = 50
    skip_archived: bool = True
    skip_forks: bool = True


@dataclass
class ServerlessSourceConfig:
    """Configuration for Serverless Framework discovery source."""

    enabled: bool = True
    search_queries: list[str] = field(default_factory=lambda: [
        "serverless.yml aws",
        "serverless.yaml aws lambda",
    ])
    max_results: int = 100


@dataclass
class CDKSourceConfig:
    """Configuration for AWS CDK Examples discovery source."""

    enabled: bool = True
    repositories: list[str] = field(default_factory=lambda: [
        "aws-samples/aws-cdk-examples",
        "cdk-patterns/serverless",
    ])
    languages: list[str] = field(default_factory=lambda: ["typescript", "python"])


@dataclass
class CustomSourceConfig:
    """Configuration for custom/manual architecture sources."""

    enabled: bool = False
    repositories: list[str] = field(default_factory=list)  # List of repo URLs
    local_paths: list[str] = field(default_factory=list)  # Local directories


@dataclass
class SourcesConfig:
    """Combined configuration for all discovery sources."""

    terraform_registry: TerraformRegistrySourceConfig = field(
        default_factory=TerraformRegistrySourceConfig
    )
    github_orgs: GitHubOrgsSourceConfig = field(
        default_factory=GitHubOrgsSourceConfig
    )
    serverless: ServerlessSourceConfig = field(
        default_factory=ServerlessSourceConfig
    )
    cdk: CDKSourceConfig = field(
        default_factory=CDKSourceConfig
    )
    custom: CustomSourceConfig = field(
        default_factory=CustomSourceConfig
    )

    @classmethod
    def from_dict(cls, data: dict) -> "SourcesConfig":
        """Create SourcesConfig from dictionary."""
        config = cls()

        if "terraform_registry" in data:
            tr = data["terraform_registry"]
            if isinstance(tr, bool):
                config.terraform_registry.enabled = tr
            elif isinstance(tr, dict):
                config.terraform_registry.enabled = tr.get("enabled", True)
                if "providers" in tr:
                    config.terraform_registry.providers = tr["providers"]
                if "limit_per_provider" in tr:
                    config.terraform_registry.limit_per_provider = tr["limit_per_provider"]
                if "min_downloads" in tr:
                    config.terraform_registry.min_downloads = tr["min_downloads"]

        if "github_orgs" in data:
            gh = data["github_orgs"]
            if isinstance(gh, bool):
                config.github_orgs.enabled = gh
            elif isinstance(gh, list):
                config.github_orgs.organizations = gh
            elif isinstance(gh, dict):
                config.github_orgs.enabled = gh.get("enabled", True)
                if "organizations" in gh:
                    config.github_orgs.organizations = gh["organizations"]
                if "file_patterns" in gh:
                    config.github_orgs.file_patterns = gh["file_patterns"]
                if "max_files_per_repo" in gh:
                    config.github_orgs.max_files_per_repo = gh["max_files_per_repo"]
                if "skip_archived" in gh:
                    config.github_orgs.skip_archived = gh["skip_archived"]
                if "skip_forks" in gh:
                    config.github_orgs.skip_forks = gh["skip_forks"]

        if "serverless" in data:
            sl = data["serverless"]
            if isinstance(sl, bool):
                config.serverless.enabled = sl
            elif isinstance(sl, dict):
                config.serverless.enabled = sl.get("enabled", True)
                if "search_queries" in sl:
                    config.serverless.search_queries = sl["search_queries"]
                if "max_results" in sl:
                    config.serverless.max_results = sl["max_results"]

        if "cdk" in data:
            cdk = data["cdk"]
            if isinstance(cdk, bool):
                config.cdk.enabled = cdk
            elif isinstance(cdk, dict):
                config.cdk.enabled = cdk.get("enabled", True)
                if "repositories" in cdk:
                    config.cdk.repositories = cdk["repositories"]
                if "languages" in cdk:
                    config.cdk.languages = cdk["languages"]

        if "custom" in data:
            custom = data["custom"]
            if isinstance(custom, dict):
                config.custom.enabled = custom.get("enabled", False)
                if "repositories" in custom:
                    config.custom.repositories = custom["repositories"]
                if "local_paths" in custom:
                    config.custom.local_paths = custom["local_paths"]

        return config

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "terraform_registry": {
                "enabled": self.terraform_registry.enabled,
                "providers": self.terraform_registry.providers,
                "limit_per_provider": self.terraform_registry.limit_per_provider,
                "min_downloads": self.terraform_registry.min_downloads,
            },
            "github_orgs": {
                "enabled": self.github_orgs.enabled,
                "organizations": self.github_orgs.organizations,
                "file_patterns": self.github_orgs.file_patterns,
                "max_files_per_repo": self.github_orgs.max_files_per_repo,
                "skip_archived": self.github_orgs.skip_archived,
                "skip_forks": self.github_orgs.skip_forks,
            },
            "serverless": {
                "enabled": self.serverless.enabled,
                "search_queries": self.serverless.search_queries,
                "max_results": self.serverless.max_results,
            },
            "cdk": {
                "enabled": self.cdk.enabled,
                "repositories": self.cdk.repositories,
                "languages": self.cdk.languages,
            },
            "custom": {
                "enabled": self.custom.enabled,
                "repositories": self.custom.repositories,
                "local_paths": self.custom.local_paths,
            },
        }


@dataclass
class LSQMConfig:
    """LSQM configuration from environment and config file."""

    # Required
    anthropic_api_key: str = ""
    github_token: str = ""
    artifact_repo: str = ""

    # Optional with defaults
    token_budget: int = 500_000
    localstack_version: str = "latest"
    parallel: int = 4
    timeout: int = 300
    slack_webhook_url: str | None = None
    issue_repo: str = "localstack/localstack"

    # Runtime
    config_path: Path | None = None
    verbose: bool = False
    dry_run: bool = False

    # Sources configuration (detailed)
    sources: SourcesConfig = field(default_factory=SourcesConfig)

    def validate(self) -> tuple[bool, list[str]]:
        """Validate required configuration is present."""
        errors = []
        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY is required")
        if not self.github_token:
            errors.append("GITHUB_TOKEN is required")
        if not self.artifact_repo:
            errors.append("ARTIFACT_REPO is required")
        return len(errors) == 0, errors

    @property
    def artifact_repo_owner(self) -> str:
        """Get the owner portion of artifact_repo."""
        if "/" in self.artifact_repo:
            return self.artifact_repo.split("/")[0]
        return ""

    @property
    def artifact_repo_name(self) -> str:
        """Get the repository name portion of artifact_repo."""
        if "/" in self.artifact_repo:
            return self.artifact_repo.split("/")[1]
        return self.artifact_repo


def load_config(config_path: Path | None = None) -> LSQMConfig:
    """Load configuration from environment variables and optional YAML file.

    Environment variables take precedence over YAML file values.
    """
    config = LSQMConfig()

    # Default config path
    if config_path is None:
        default_path = Path.home() / ".lsqm" / "config.yaml"
        if default_path.exists():
            config_path = default_path

    # Load from YAML if available
    if config_path and config_path.exists():
        config.config_path = config_path
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

        # Map YAML keys to config attributes
        if "anthropic_api_key" in yaml_config:
            config.anthropic_api_key = yaml_config["anthropic_api_key"]
        if "github_token" in yaml_config:
            config.github_token = yaml_config["github_token"]
        if "artifact_repo" in yaml_config:
            config.artifact_repo = yaml_config["artifact_repo"]
        if "token_budget" in yaml_config:
            config.token_budget = yaml_config["token_budget"]
        if "localstack_version" in yaml_config:
            config.localstack_version = yaml_config["localstack_version"]
        if "parallel" in yaml_config:
            config.parallel = yaml_config["parallel"]
        if "timeout" in yaml_config:
            config.timeout = yaml_config["timeout"]
        if "slack_webhook_url" in yaml_config:
            config.slack_webhook_url = yaml_config["slack_webhook_url"]
        if "issue_repo" in yaml_config:
            config.issue_repo = yaml_config["issue_repo"]
        if "sources" in yaml_config:
            config.sources = SourcesConfig.from_dict(yaml_config["sources"])

    # Override with environment variables (strip whitespace to handle common input errors)
    if env_key := os.getenv("ANTHROPIC_API_KEY"):
        config.anthropic_api_key = env_key.strip()
    if env_token := os.getenv("GITHUB_TOKEN"):
        config.github_token = env_token.strip()
    if env_repo := os.getenv("ARTIFACT_REPO"):
        config.artifact_repo = env_repo.strip()
    if env_budget := os.getenv("ANTHROPIC_TOKEN_BUDGET"):
        config.token_budget = int(env_budget)
    if env_version := os.getenv("LOCALSTACK_VERSION"):
        config.localstack_version = env_version
    if env_parallel := os.getenv("LSQM_PARALLEL"):
        config.parallel = int(env_parallel)
    if env_timeout := os.getenv("LSQM_TIMEOUT"):
        config.timeout = int(env_timeout)
    if env_slack := os.getenv("SLACK_WEBHOOK_URL"):
        config.slack_webhook_url = env_slack
    if env_issue_repo := os.getenv("ISSUE_REPO"):
        config.issue_repo = env_issue_repo

    return config


def get_cache_dir() -> Path:
    """Get the local cache directory for LSQM."""
    cache_dir = Path.home() / ".lsqm" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_artifacts_dir() -> Path:
    """Get the local artifacts directory (cloned repository)."""
    return get_cache_dir() / "artifacts"
