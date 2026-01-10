"""ValidationResult model - represents the outcome of validating one architecture."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


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
    def from_dict(cls, data: dict) -> "TerraformApplyResult":
        """Deserialize from dictionary."""
        return cls(
            success=data.get("success", False),
            resources_created=data.get("resources_created", 0),
            outputs=data.get("outputs", {}),
            logs=data.get("logs", ""),
        )


@dataclass
class PytestResult:
    """Result of pytest execution."""

    total: int
    passed: int
    failed: int
    skipped: int = 0
    output: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PytestResult":
        """Deserialize from dictionary."""
        return cls(
            total=data.get("total", 0),
            passed=data.get("passed", 0),
            failed=data.get("failed", 0),
            skipped=data.get("skipped", 0),
            output=data.get("output", ""),
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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ValidationResult":
        """Deserialize from dictionary."""
        tf_data = data.get("terraform_apply")
        pytest_data = data.get("pytest_results")

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
        )

    @classmethod
    def create_error(
        cls, arch_hash: str, run_id: str, error_message: str, started_at: datetime
    ) -> "ValidationResult":
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
    def create_timeout(cls, arch_hash: str, run_id: str, started_at: datetime) -> "ValidationResult":
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
