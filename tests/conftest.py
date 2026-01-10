"""Shared pytest fixtures for LSQM tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_env(monkeypatch):
    """Set up mock environment variables for testing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("ARTIFACT_REPO", "test-org/test-artifacts")
    yield


@pytest.fixture
def sample_architecture():
    """Return a sample architecture metadata dictionary."""
    return {
        "hash": "a1b2c3d4e5f67890",
        "source_url": "https://registry.terraform.io/modules/terraform-aws-modules/vpc/aws/5.1.0",
        "source_type": "terraform_registry",
        "discovered_at": "2026-01-10T00:00:00Z",
        "services": ["ec2", "vpc"],
        "resource_count": 23,
        "name": "terraform-aws-vpc",
        "description": "Terraform module for creating AWS VPC resources",
        "version": "5.1.0",
        "skipped": False,
    }


@pytest.fixture
def sample_validation_result():
    """Return a sample validation result dictionary."""
    return {
        "arch_hash": "a1b2c3d4e5f67890",
        "run_id": "550e8400-e29b-41d4-a716-446655440000",
        "status": "PASSED",
        "started_at": "2026-01-10T01:00:00Z",
        "completed_at": "2026-01-10T01:00:45Z",
        "duration_seconds": 45.0,
        "terraform_apply": {
            "success": True,
            "resources_created": 5,
            "outputs": {"vpc_id": "vpc-12345"},
            "logs": "",
        },
        "pytest_results": {
            "total": 5,
            "passed": 5,
            "failed": 0,
            "skipped": 0,
            "output": "",
        },
    }
