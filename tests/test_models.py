"""Tests for LSQM data models."""

from datetime import datetime

from lsqm.models import (
    Architecture,
    PytestResult,
    Regression,
    Run,
    ServiceTrend,
    TerraformApplyResult,
    TestApp,
    ValidationResult,
    ValidationStatus,
)


class TestArchitecture:
    """Tests for the Architecture model."""

    def test_create_architecture(self):
        """Test creating an Architecture instance."""
        arch = Architecture(
            hash="a1b2c3d4e5f67890",
            source_url="https://example.com/module",
            source_type="terraform_registry",
            discovered_at=datetime(2026, 1, 10),
            services=["ec2", "vpc"],
            resource_count=10,
        )

        assert arch.hash == "a1b2c3d4e5f67890"
        assert arch.source_type == "terraform_registry"
        assert "ec2" in arch.services
        assert arch.resource_count == 10
        assert arch.skipped is False

    def test_architecture_to_dict(self):
        """Test Architecture serialization to dict."""
        arch = Architecture(
            hash="abc123",
            source_url="https://example.com",
            source_type="github",
            discovered_at=datetime(2026, 1, 10, 12, 0, 0),
            services=["lambda", "s3"],
            resource_count=5,
            name="test-arch",
            description="Test description",
            version="1.0.0",
        )

        data = arch.to_dict()

        assert data["hash"] == "abc123"
        assert data["source_type"] == "github"
        assert data["services"] == ["lambda", "s3"]
        assert data["name"] == "test-arch"
        assert "discovered_at" in data

    def test_architecture_from_dict(self):
        """Test Architecture deserialization from dict."""
        data = {
            "hash": "def456",
            "source_url": "https://github.com/example",
            "source_type": "github",
            "discovered_at": "2026-01-10T00:00:00",
            "services": ["dynamodb"],
            "resource_count": 3,
            "name": "example-arch",
            "skipped": True,
        }

        arch = Architecture.from_dict(data)

        assert arch.hash == "def456"
        assert arch.source_type == "github"
        assert arch.skipped is True
        assert "dynamodb" in arch.services

    def test_architecture_roundtrip(self):
        """Test Architecture to_dict/from_dict roundtrip."""
        original = Architecture(
            hash="roundtrip123",
            source_url="https://test.com",
            source_type="serverless",
            discovered_at=datetime(2026, 1, 15),
            services=["apigateway", "lambda"],
            resource_count=8,
            name="roundtrip-test",
        )

        data = original.to_dict()
        restored = Architecture.from_dict(data)

        assert restored.hash == original.hash
        assert restored.source_type == original.source_type
        assert restored.services == original.services


class TestValidationResult:
    """Tests for the ValidationResult model."""

    def test_create_validation_result(self):
        """Test creating a ValidationResult instance."""
        result = ValidationResult(
            arch_hash="test123",
            run_id="run-001",
            status=ValidationStatus.PASSED,
            started_at=datetime(2026, 1, 10, 12, 0, 0),
            completed_at=datetime(2026, 1, 10, 12, 1, 0),
            duration_seconds=60.0,
        )

        assert result.arch_hash == "test123"
        assert result.status == ValidationStatus.PASSED
        assert result.duration_seconds == 60.0

    def test_validation_status_values(self):
        """Test ValidationStatus enum values."""
        assert ValidationStatus.PASSED.value == "PASSED"
        assert ValidationStatus.PARTIAL.value == "PARTIAL"
        assert ValidationStatus.FAILED.value == "FAILED"
        assert ValidationStatus.TIMEOUT.value == "TIMEOUT"
        assert ValidationStatus.ERROR.value == "ERROR"

    def test_create_error(self):
        """Test ValidationResult.create_error factory method."""
        started = datetime(2026, 1, 10, 12, 0, 0)
        result = ValidationResult.create_error(
            arch_hash="error123",
            run_id="run-002",
            error_message="Something went wrong",
            started_at=started,
        )

        assert result.arch_hash == "error123"
        assert result.status == ValidationStatus.ERROR
        assert result.error_message == "Something went wrong"

    def test_create_timeout(self):
        """Test ValidationResult.create_timeout factory method."""
        started = datetime(2026, 1, 10, 12, 0, 0)
        result = ValidationResult.create_timeout(
            arch_hash="timeout123",
            run_id="run-003",
            started_at=started,
        )

        assert result.arch_hash == "timeout123"
        assert result.status == ValidationStatus.TIMEOUT

    def test_validation_result_to_dict(self):
        """Test ValidationResult serialization."""
        result = ValidationResult(
            arch_hash="ser123",
            run_id="run-004",
            status=ValidationStatus.PARTIAL,
            started_at=datetime(2026, 1, 10, 12, 0, 0),
            completed_at=datetime(2026, 1, 10, 12, 0, 30),
            duration_seconds=30.0,
            terraform_apply=TerraformApplyResult(
                success=True,
                resources_created=3,
            ),
            pytest_results=PytestResult(
                total=5,
                passed=4,
                failed=1,
            ),
        )

        data = result.to_dict()

        assert data["arch_hash"] == "ser123"
        assert data["status"] == "PARTIAL"
        assert data["terraform_apply"]["success"] is True
        assert data["pytest_results"]["passed"] == 4


class TestTerraformApplyResult:
    """Tests for TerraformApplyResult model."""

    def test_create_terraform_result(self):
        """Test creating TerraformApplyResult."""
        result = TerraformApplyResult(
            success=True,
            resources_created=5,
            outputs={"vpc_id": "vpc-123"},
            logs="Apply complete!",
        )

        assert result.success is True
        assert result.resources_created == 5
        assert result.outputs["vpc_id"] == "vpc-123"

    def test_terraform_result_to_dict(self):
        """Test TerraformApplyResult serialization."""
        result = TerraformApplyResult(
            success=False,
            logs="Error: resource not found",
        )

        data = result.to_dict()

        assert data["success"] is False
        assert "Error" in data["logs"]


class TestPytestResult:
    """Tests for PytestResult model."""

    def test_create_pytest_result(self):
        """Test creating PytestResult."""
        result = PytestResult(
            total=10,
            passed=8,
            failed=1,
            skipped=1,
            output="10 tests collected",
        )

        assert result.total == 10
        assert result.passed == 8
        assert result.failed == 1
        assert result.skipped == 1

    def test_pytest_result_minimal(self):
        """Test PytestResult with required values only."""
        result = PytestResult(total=5, passed=3, failed=2)

        assert result.total == 5
        assert result.passed == 3
        assert result.failed == 2
        assert result.skipped == 0  # Default


class TestTestApp:
    """Tests for TestApp model."""

    def test_create_test_app(self):
        """Test creating TestApp."""
        app = TestApp(
            arch_hash="app123",
            generated_at=datetime(2026, 1, 10),
            generator_version="1.0.0",
            model_used="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=2000,
            files={"app.py": "print('hello')", "test_app.py": "def test_hello(): pass"},
        )

        assert app.arch_hash == "app123"
        assert app.input_tokens == 1000
        assert len(app.files) == 2

    def test_test_app_to_dict(self):
        """Test TestApp serialization."""
        app = TestApp(
            arch_hash="ser456",
            generated_at=datetime(2026, 1, 10),
            generator_version="1.0.0",
            model_used="claude-sonnet-4-20250514",
            input_tokens=500,
            output_tokens=1500,
        )

        data = app.to_dict()

        assert data["arch_hash"] == "ser456"
        assert data["generator_version"] == "1.0.0"


class TestRun:
    """Tests for Run model."""

    def test_create_run(self):
        """Test creating Run."""
        from lsqm.models.run import RunSummary

        run = Run(
            run_id="run-123",
            started_at=datetime(2026, 1, 10, 0, 0, 0),
            completed_at=datetime(2026, 1, 10, 1, 0, 0),
            localstack_version="3.0.0",
            summary=RunSummary(total=10, passed=8),
        )

        assert run.run_id == "run-123"
        assert run.localstack_version == "3.0.0"
        assert run.summary.total == 10

    def test_run_to_dict(self):
        """Test Run serialization."""
        from lsqm.models.run import RunSummary

        run = Run(
            run_id="run-456",
            started_at=datetime(2026, 1, 10),
            localstack_version="latest",
            summary=RunSummary(total=5, passed=4, failed=1),
        )

        data = run.to_dict()

        assert data["run_id"] == "run-456"
        assert data["summary"]["passed"] == 4


class TestRegression:
    """Tests for Regression model."""

    def test_create_regression(self):
        """Test creating Regression."""
        regression = Regression(
            arch_hash="reg123",
            from_run_id="run-001",
            to_run_id="run-002",
            from_status=ValidationStatus.PASSED,
            to_status=ValidationStatus.FAILED,
            detected_at=datetime(2026, 1, 10),
            services_affected=["lambda", "s3"],
        )

        assert regression.arch_hash == "reg123"
        assert regression.from_status == ValidationStatus.PASSED
        assert regression.to_status == ValidationStatus.FAILED
        assert "lambda" in regression.services_affected

    def test_regression_to_dict(self):
        """Test Regression serialization."""
        regression = Regression(
            arch_hash="reg456",
            from_run_id="run-003",
            to_run_id="run-004",
            from_status=ValidationStatus.PARTIAL,
            to_status=ValidationStatus.TIMEOUT,
            detected_at=datetime(2026, 1, 10),
            services_affected=["lambda"],
        )

        data = regression.to_dict()

        assert data["arch_hash"] == "reg456"
        assert data["from_status"] == "PARTIAL"
        assert data["to_status"] == "TIMEOUT"


class TestServiceTrend:
    """Tests for ServiceTrend model."""

    def test_create_service_trend(self):
        """Test creating ServiceTrend."""
        trend = ServiceTrend(
            service_name="lambda",
            current_pass_rate=0.855,
            architecture_count=50,
        )

        assert trend.service_name == "lambda"
        assert trend.architecture_count == 50
        assert trend.current_pass_rate == 0.855
        assert trend.trend == "stable"  # No previous rate, so stable

    def test_service_trend_improving(self):
        """Test ServiceTrend with improving trend."""
        trend = ServiceTrend(
            service_name="s3",
            current_pass_rate=0.92,
            previous_pass_rate=0.85,
            architecture_count=100,
        )

        assert trend.service_name == "s3"
        assert trend.trend == "improving"

    def test_service_trend_to_dict(self):
        """Test ServiceTrend serialization."""
        trend = ServiceTrend(
            service_name="s3",
            current_pass_rate=0.92,
            architecture_count=100,
        )

        data = trend.to_dict()

        assert data["service_name"] == "s3"
        assert data["current_pass_rate"] == 0.92
        assert data["trend"] == "stable"
