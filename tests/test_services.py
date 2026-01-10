"""Tests for LSQM service modules."""

import json
from unittest.mock import MagicMock, patch

from lsqm.models import ValidationStatus
from lsqm.services.comparator import compare_runs, create_regression_objects
from lsqm.services.localstack_services import (
    LOCALSTACK_COMMUNITY_SERVICES,
    extract_services_from_terraform,
    is_service_supported,
    is_standalone_architecture,
)
from lsqm.services.normalizer import (
    serverless_to_terraform,
)
from lsqm.services.reporter import generate_html_report


class TestLocalStackServices:
    """Tests for LocalStack services module."""

    def test_is_service_supported_valid(self):
        """Test that valid services are recognized."""
        assert is_service_supported("s3") is True
        assert is_service_supported("lambda") is True
        assert is_service_supported("dynamodb") is True
        assert is_service_supported("ec2") is True
        assert is_service_supported("sqs") is True

    def test_is_service_supported_invalid(self):
        """Test that invalid services are rejected."""
        assert is_service_supported("fake_service") is False
        assert is_service_supported("not_aws") is False
        assert is_service_supported("") is False

    def test_localstack_services_not_empty(self):
        """Test that LOCALSTACK_COMMUNITY_SERVICES set is populated."""
        assert len(LOCALSTACK_COMMUNITY_SERVICES) > 0
        assert "s3" in LOCALSTACK_COMMUNITY_SERVICES
        assert "lambda" in LOCALSTACK_COMMUNITY_SERVICES

    def test_extract_services_from_terraform_s3(self):
        """Test extracting S3 service from Terraform."""
        tf_content = '''
resource "aws_s3_bucket" "example" {
  bucket = "my-bucket"
}
'''
        services = extract_services_from_terraform(tf_content)
        assert "s3" in services

    def test_extract_services_from_terraform_lambda(self):
        """Test extracting Lambda service from Terraform."""
        tf_content = '''
resource "aws_lambda_function" "example" {
  function_name = "my-function"
  handler       = "index.handler"
  runtime       = "python3.9"
}
'''
        services = extract_services_from_terraform(tf_content)
        assert "lambda" in services

    def test_extract_services_from_terraform_multiple(self):
        """Test extracting multiple services from Terraform."""
        tf_content = '''
resource "aws_s3_bucket" "bucket" {
  bucket = "my-bucket"
}

resource "aws_lambda_function" "function" {
  function_name = "my-function"
}

resource "aws_dynamodb_table" "table" {
  name = "my-table"
}

resource "aws_sqs_queue" "queue" {
  name = "my-queue"
}
'''
        services = extract_services_from_terraform(tf_content)
        assert "s3" in services
        assert "lambda" in services
        assert "dynamodb" in services
        assert "sqs" in services

    def test_extract_services_empty_content(self):
        """Test extracting services from empty content."""
        services = extract_services_from_terraform("")
        assert len(services) == 0

    def test_extract_services_no_aws_resources(self):
        """Test extracting services when no AWS resources present."""
        tf_content = '''
variable "region" {
  default = "us-east-1"
}

output "message" {
  value = "hello"
}
'''
        services = extract_services_from_terraform(tf_content)
        assert len(services) == 0

    def test_is_standalone_with_resources(self):
        """Test that architecture with resources is standalone."""
        tf_content = '''
resource "aws_s3_bucket" "example" {
  bucket = "my-bucket"
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is True
        assert reason == ""

    def test_is_standalone_with_resources_and_defaults(self):
        """Test that architecture with defaulted variables is standalone."""
        tf_content = '''
variable "bucket_name" {
  default = "my-bucket"
}

resource "aws_s3_bucket" "example" {
  bucket = var.bucket_name
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is True

    def test_not_standalone_required_variables(self):
        """Test that architecture with required variables is not standalone."""
        tf_content = '''
variable "bucket_name" {
  description = "Required bucket name"
}

resource "aws_s3_bucket" "example" {
  bucket = var.bucket_name
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is False
        assert "Required variables" in reason

    def test_not_standalone_module_only(self):
        """Test that module-only composition is not standalone."""
        tf_content = '''
module "vpc" {
  source = "terraform-aws-modules/vpc/aws"
  version = "3.0.0"
}

module "lambda" {
  source = "./modules/lambda"
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is False
        assert "module composition" in reason.lower()

    def test_not_standalone_no_resources(self):
        """Test that empty config is not standalone."""
        tf_content = '''
variable "region" {
  default = "us-east-1"
}

output "message" {
  value = "hello"
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is False
        assert "No resources" in reason

    def test_not_standalone_remote_state(self):
        """Test that config with remote state dependency is not standalone."""
        tf_content = '''
data "terraform_remote_state" "vpc" {
  backend = "s3"
}

resource "aws_lambda_function" "example" {
  function_name = "test"
  subnet_ids    = data.terraform_remote_state.vpc.outputs.subnet_ids
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is False
        assert "external state" in reason.lower()

    def test_standalone_with_allowed_data_sources(self):
        """Test that architecture with non-problematic data sources is standalone."""
        tf_content = '''
data "aws_region" "current" {}
data "aws_availability_zones" "available" {}

resource "aws_s3_bucket" "example" {
  bucket = "my-bucket-${data.aws_region.current.name}"
}
'''
        is_standalone, reason = is_standalone_architecture(tf_content)
        assert is_standalone is True


class TestComparator:
    """Tests for comparator service."""

    def test_compare_runs_no_changes(self):
        """Test comparing runs with no status changes."""
        current = {
            "hash1": {"status": "PASSED", "services": ["s3"]},
            "hash2": {"status": "FAILED", "services": ["lambda"]},
        }
        previous = {
            "hash1": {"status": "PASSED", "services": ["s3"]},
            "hash2": {"status": "FAILED", "services": ["lambda"]},
        }

        result = compare_runs(current, previous, "run-2", "run-1")

        assert result["regressions_count"] == 0
        assert result["fixes_count"] == 0

    def test_compare_runs_regression_detected(self):
        """Test detecting a regression (passed -> failed)."""
        current = {
            "hash1": {"status": "FAILED", "name": "test-arch", "services": ["s3"]},
        }
        previous = {
            "hash1": {"status": "PASSED", "name": "test-arch", "services": ["s3"]},
        }

        result = compare_runs(current, previous, "run-2", "run-1")

        assert result["regressions_count"] == 1
        assert result["regressions"][0]["arch_hash"] == "hash1"
        assert result["regressions"][0]["from_status"] == "PASSED"
        assert result["regressions"][0]["to_status"] == "FAILED"

    def test_compare_runs_fix_detected(self):
        """Test detecting a fix (failed -> passed)."""
        current = {
            "hash1": {"status": "PASSED", "name": "test-arch", "services": ["s3"]},
        }
        previous = {
            "hash1": {"status": "FAILED", "name": "test-arch", "services": ["s3"]},
        }

        result = compare_runs(current, previous, "run-2", "run-1")

        assert result["fixes_count"] == 1
        assert result["fixes"][0]["arch_hash"] == "hash1"
        assert result["fixes"][0]["from_status"] == "FAILED"
        assert result["fixes"][0]["to_status"] == "PASSED"

    def test_compare_runs_partial_to_failed_is_regression(self):
        """Test that partial -> failed is a regression."""
        current = {
            "hash1": {"status": "FAILED", "services": ["s3"]},
        }
        previous = {
            "hash1": {"status": "PARTIAL", "services": ["s3"]},
        }

        result = compare_runs(current, previous, "run-2", "run-1")

        assert result["regressions_count"] == 1

    def test_compare_runs_new_architecture_not_counted(self):
        """Test that new architectures don't cause regressions."""
        current = {
            "hash1": {"status": "FAILED", "services": ["s3"]},
            "hash2": {"status": "PASSED", "services": ["lambda"]},  # New
        }
        previous = {
            "hash1": {"status": "FAILED", "services": ["s3"]},
        }

        result = compare_runs(current, previous, "run-2", "run-1")

        # hash2 is new, so no regression for it
        assert result["regressions_count"] == 0
        assert result["fixes_count"] == 0

    def test_create_regression_objects(self):
        """Test creating Regression model objects from comparison."""
        comparison = {
            "regressions": [
                {
                    "arch_hash": "hash123",
                    "from_run_id": "run-1",
                    "to_run_id": "run-2",
                    "from_status": "PASSED",
                    "to_status": "FAILED",
                    "detected_at": "2026-01-10T00:00:00",
                }
            ]
        }
        architecture_index = {
            "architectures": {
                "hash123": {
                    "name": "test-arch",
                    "services": ["s3", "lambda"],
                }
            }
        }

        regressions = create_regression_objects(comparison, architecture_index)

        assert len(regressions) == 1
        assert regressions[0].arch_hash == "hash123"
        assert regressions[0].from_status == ValidationStatus.PASSED
        assert regressions[0].to_status == ValidationStatus.FAILED
        assert "s3" in regressions[0].services_affected


class TestNormalizer:
    """Tests for normalizer service."""

    def test_serverless_to_terraform_basic(self):
        """Test basic Serverless Framework to Terraform conversion."""
        serverless_yml = """
service: my-service
provider:
  name: aws
  runtime: python3.9
functions:
  hello:
    handler: handler.hello
"""
        tf_files, services = serverless_to_terraform(serverless_yml)

        # Check that lambda function resource is generated
        if tf_files:  # May be empty if no functions
            combined_tf = "\n".join(tf_files.values())
            assert "aws_lambda_function" in combined_tf
        assert "lambda" in services

    def test_serverless_to_terraform_with_events(self):
        """Test Serverless with HTTP events."""
        serverless_yml = """
service: my-api
provider:
  name: aws
  runtime: python3.9
functions:
  api:
    handler: handler.api
    events:
      - http:
          path: /
          method: get
"""
        tf_files, services = serverless_to_terraform(serverless_yml)

        assert "lambda" in services
        # API Gateway should be added for HTTP events
        assert "apigateway" in services

    def test_serverless_to_terraform_with_sqs(self):
        """Test Serverless with SQS event."""
        serverless_yml = """
service: my-worker
provider:
  name: aws
  runtime: python3.9
functions:
  worker:
    handler: handler.process
    events:
      - sqs:
          arn: arn:aws:sqs:us-east-1:123456789:my-queue
"""
        tf_files, services = serverless_to_terraform(serverless_yml)

        assert "lambda" in services
        assert "sqs" in services


class TestReporter:
    """Tests for reporter service."""

    def test_generate_html_report(self, temp_dir):
        """Test generating HTML report."""
        # Setup artifacts directory structure
        artifacts_dir = temp_dir / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "architectures").mkdir()

        # Create index.json
        index = {
            "architectures": {
                "a1b2c3d4": {
                    "name": "test-arch",
                    "services": ["s3", "lambda"],
                }
            }
        }
        with open(artifacts_dir / "architectures" / "index.json", "w") as f:
            json.dump(index, f)

        run_data = {
            "run_id": "test-run-123",
            "started_at": "2026-01-10T00:00:00",
            "localstack_version": "3.0.0",
            "summary": {
                "total": 1,
                "passed": 1,
                "partial": 0,
                "failed": 0,
                "timeout": 0,
                "duration_seconds": 60.0,
            },
            "results": {
                "a1b2c3d4": {
                    "status": "PASSED",
                    "duration_seconds": 45.0,
                    "pytest_results": {"passed": 5, "failed": 0},
                }
            },
        }

        output_dir = temp_dir / "output"
        report_path = generate_html_report(
            run_data=run_data,
            artifacts_dir=artifacts_dir,
            output_dir=output_dir,
        )

        assert report_path.exists()
        assert report_path.name == "index.html"

        # Check report content
        with open(report_path) as f:
            content = f.read()
        assert "LocalStack Quality Monitor" in content
        assert "test-run-123" in content
        assert "test-arch" in content

    def test_generate_html_report_empty(self, temp_dir):
        """Test generating report with no results."""
        artifacts_dir = temp_dir / "artifacts"
        artifacts_dir.mkdir(parents=True)

        run_data = {
            "run_id": "empty-run",
            "started_at": "2026-01-10T00:00:00",
            "localstack_version": "3.0.0",
            "summary": {
                "total": 0,
                "passed": 0,
            },
            "results": {},
        }

        output_dir = temp_dir / "output"
        report_path = generate_html_report(
            run_data=run_data,
            artifacts_dir=artifacts_dir,
            output_dir=output_dir,
        )

        assert report_path.exists()


class TestGeneratorMocked:
    """Tests for generator service with mocked API."""

    def test_extract_files_from_response(self):
        """Test extracting files from Claude response."""
        from lsqm.services.generator import _extract_files_from_response

        response = '''
Here are the generated files:

```json
{
  "conftest.py": "import pytest",
  "app.py": "def hello(): pass",
  "test_app.py": "def test_hello(): pass",
  "requirements.txt": "pytest\\nboto3"
}
```
'''
        files = _extract_files_from_response(response)

        assert "conftest.py" in files
        assert "app.py" in files
        assert "test_app.py" in files
        assert "requirements.txt" in files

    def test_extract_files_invalid_json(self):
        """Test extracting files from invalid response."""
        from lsqm.services.generator import _extract_files_from_response

        response = "This is not valid JSON"
        files = _extract_files_from_response(response)

        assert files == {}

    def test_extract_files_missing_required(self):
        """Test extracting files when required files missing."""
        from lsqm.services.generator import _extract_files_from_response

        response = '{"app.py": "code"}'  # Missing other required files
        files = _extract_files_from_response(response)

        assert files == {}

    def test_validate_python_syntax_valid(self):
        """Test validating valid Python syntax."""
        from lsqm.services.generator import _validate_python_syntax

        code = '''
def hello():
    print("Hello, World!")

class MyClass:
    def method(self):
        return 42
'''
        valid, error = _validate_python_syntax(code)

        assert valid is True
        assert error is None

    def test_validate_python_syntax_invalid(self):
        """Test validating invalid Python syntax."""
        from lsqm.services.generator import _validate_python_syntax

        code = '''
def broken(
    # Missing closing parenthesis
'''
        valid, error = _validate_python_syntax(code)

        assert valid is False
        assert error is not None


class TestValidatorHelpers:
    """Tests for validator helper functions."""

    def test_cleanup_stale_containers_mocked(self):
        """Test cleanup function with mocked Docker client."""
        from lsqm.services.validator import cleanup_stale_containers

        with patch("lsqm.services.validator.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client

            mock_container = MagicMock()
            mock_client.containers.list.return_value = [mock_container]

            removed = cleanup_stale_containers()

            assert removed == 1
            mock_container.stop.assert_called_once()
            mock_container.remove.assert_called_once()

    def test_get_container_logs(self):
        """Test getting container logs."""
        from lsqm.services.validator import _get_container_logs

        mock_container = MagicMock()
        mock_container.logs.return_value = b"Container log output"

        logs = _get_container_logs(mock_container)

        assert "Container log output" in logs

    def test_get_container_logs_error(self):
        """Test getting container logs when error occurs."""
        from lsqm.services.validator import _get_container_logs

        mock_container = MagicMock()
        mock_container.logs.side_effect = Exception("Docker error")

        logs = _get_container_logs(mock_container)

        assert logs == ""
