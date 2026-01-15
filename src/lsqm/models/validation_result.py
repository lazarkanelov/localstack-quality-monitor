"""ValidationResult model - represents the outcome of validating one architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from lsqm.models.preprocessing_delta import PreprocessingDelta
    from lsqm.models.resource_inventory import ResourceInventory
    from lsqm.models.test_quality import TestQualityAnalysis


class ValidationStatus(str, Enum):
    """Possible validation outcomes."""

    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass
class TerraformApplyResult:
    """Result of terraform apply execution."""

    success: bool
    resources_created: int = 0
    outputs: dict = field(default_factory=dict)
    logs: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "resources_created": self.resources_created,
            "outputs": self.outputs,
            "logs": self.logs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TerraformApplyResult:
        """Deserialize from dictionary."""
        return cls(
            success=data.get("success", False),
            resources_created=data.get("resources_created", 0),
            outputs=data.get("outputs", {}),
            logs=data.get("logs", ""),
        )


@dataclass
class TestResult:
    """Individual test result from pytest output."""

    test_name: str  # e.g., "test_put_object"
    status: Literal["passed", "failed", "skipped", "error"]
    duration: float = 0.0
    error_message: str | None = None
    aws_operations: list[str] = field(default_factory=list)  # e.g., ["s3:PutObject"]

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "test_name": self.test_name,
            "status": self.status,
            "duration": self.duration,
            "error_message": self.error_message,
            "aws_operations": self.aws_operations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TestResult:
        """Deserialize from dictionary."""
        return cls(
            test_name=data["test_name"],
            status=data["status"],
            duration=data.get("duration", 0.0),
            error_message=data.get("error_message"),
            aws_operations=data.get("aws_operations", []),
        )


@dataclass
class OperationResult:
    """Result for a specific AWS API operation."""

    operation: str  # e.g., "s3:PutObject"
    service: str  # e.g., "s3"
    succeeded: bool
    test_name: str  # Which test exercised this
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "operation": self.operation,
            "service": self.service,
            "succeeded": self.succeeded,
            "test_name": self.test_name,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OperationResult:
        """Deserialize from dictionary."""
        return cls(
            operation=data["operation"],
            service=data["service"],
            succeeded=data["succeeded"],
            test_name=data["test_name"],
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
        )


@dataclass
class PytestResult:
    """Result of pytest execution."""

    total: int
    passed: int
    failed: int
    skipped: int = 0
    output: str = ""
    individual_tests: list[TestResult] = field(default_factory=list)
    operation_results: list[OperationResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "output": self.output,
            "individual_tests": [t.to_dict() for t in self.individual_tests],
            "operation_results": [o.to_dict() for o in self.operation_results],
        }

    @classmethod
    def from_dict(cls, data: dict) -> PytestResult:
        """Deserialize from dictionary."""
        return cls(
            total=data.get("total", 0),
            passed=data.get("passed", 0),
            failed=data.get("failed", 0),
            skipped=data.get("skipped", 0),
            output=data.get("output", ""),
            individual_tests=[TestResult.from_dict(t) for t in data.get("individual_tests", [])],
            operation_results=[
                OperationResult.from_dict(o) for o in data.get("operation_results", [])
            ],
        )


@dataclass
class ValidationResult:
    """Outcome of validating one architecture in a run."""

    arch_hash: str
    run_id: str
    status: ValidationStatus
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    terraform_apply: TerraformApplyResult | None = None
    pytest_results: PytestResult | None = None
    container_logs: str = ""
    error_message: str | None = None
    # New fields for enhanced tracking
    preprocessing_delta: PreprocessingDelta | None = None
    resource_inventory: ResourceInventory | None = None
    test_quality: TestQualityAnalysis | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "arch_hash": self.arch_hash,
            "run_id": self.run_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "terraform_apply": self.terraform_apply.to_dict() if self.terraform_apply else None,
            "pytest_results": self.pytest_results.to_dict() if self.pytest_results else None,
            "container_logs": self.container_logs,
            "error_message": self.error_message,
            "preprocessing_delta": (
                self.preprocessing_delta.to_dict() if self.preprocessing_delta else None
            ),
            "resource_inventory": (
                self.resource_inventory.to_dict() if self.resource_inventory else None
            ),
            "test_quality": self.test_quality.to_dict() if self.test_quality else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ValidationResult:
        """Deserialize from dictionary."""
        # Import here to avoid circular imports
        from lsqm.models.preprocessing_delta import PreprocessingDelta
        from lsqm.models.resource_inventory import ResourceInventory
        from lsqm.models.test_quality import TestQualityAnalysis

        tf_data = data.get("terraform_apply")
        pytest_data = data.get("pytest_results")
        preprocessing_data = data.get("preprocessing_delta")
        inventory_data = data.get("resource_inventory")
        quality_data = data.get("test_quality")

        return cls(
            arch_hash=data["arch_hash"],
            run_id=data["run_id"],
            status=ValidationStatus(data["status"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]),
            duration_seconds=data["duration_seconds"],
            terraform_apply=TerraformApplyResult.from_dict(tf_data) if tf_data else None,
            pytest_results=PytestResult.from_dict(pytest_data) if pytest_data else None,
            container_logs=data.get("container_logs", ""),
            error_message=data.get("error_message"),
            preprocessing_delta=(
                PreprocessingDelta.from_dict(preprocessing_data) if preprocessing_data else None
            ),
            resource_inventory=(
                ResourceInventory.from_dict(inventory_data) if inventory_data else None
            ),
            test_quality=TestQualityAnalysis.from_dict(quality_data) if quality_data else None,
        )

    @classmethod
    def create_error(
        cls, arch_hash: str, run_id: str, error_message: str, started_at: datetime
    ) -> ValidationResult:
        """Create an ERROR result."""
        now = datetime.utcnow()
        return cls(
            arch_hash=arch_hash,
            run_id=run_id,
            status=ValidationStatus.ERROR,
            started_at=started_at,
            completed_at=now,
            duration_seconds=(now - started_at).total_seconds(),
            error_message=error_message,
        )

    @classmethod
    def create_timeout(
        cls, arch_hash: str, run_id: str, started_at: datetime
    ) -> ValidationResult:
        """Create a TIMEOUT result."""
        now = datetime.utcnow()
        return cls(
            arch_hash=arch_hash,
            run_id=run_id,
            status=ValidationStatus.TIMEOUT,
            started_at=started_at,
            completed_at=now,
            duration_seconds=(now - started_at).total_seconds(),
        )
