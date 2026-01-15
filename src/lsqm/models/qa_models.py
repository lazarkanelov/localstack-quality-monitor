"""QA enhancement models for production-grade quality assurance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class QualityGateStatus(str, Enum):
    """Quality gate evaluation result."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"


@dataclass
class NegativeTestCase:
    """A negative test case definition."""

    name: str  # e.g., "test_invalid_bucket_name"
    description: str
    test_type: Literal["invalid_input", "permission_denied", "resource_not_found",
                       "rate_limit", "timeout", "edge_case"]
    service: str  # e.g., "s3"
    operation: str  # e.g., "create_bucket"
    expected_error: str | None = None  # Expected error code/type

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "test_type": self.test_type,
            "service": self.service,
            "operation": self.operation,
            "expected_error": self.expected_error,
        }


@dataclass
class ResourceConfigVerification:
    """Verification result for a specific resource configuration."""

    resource_type: str  # e.g., "aws_s3_bucket"
    resource_name: str  # e.g., "my_bucket"
    config_checks: list[ConfigCheck] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "config_checks": [c.to_dict() for c in self.config_checks],
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResourceConfigVerification:
        return cls(
            resource_type=data["resource_type"],
            resource_name=data["resource_name"],
            config_checks=[ConfigCheck.from_dict(c) for c in data.get("config_checks", [])],
            passed=data.get("passed", True),
        )


@dataclass
class ConfigCheck:
    """Individual configuration check result."""

    attribute: str  # e.g., "versioning.enabled"
    expected_value: str | None
    actual_value: str | None
    passed: bool
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "attribute": self.attribute,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "passed": self.passed,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConfigCheck:
        return cls(
            attribute=data["attribute"],
            expected_value=data.get("expected_value"),
            actual_value=data.get("actual_value"),
            passed=data["passed"],
            message=data.get("message", ""),
        )


@dataclass
class VersionTestResult:
    """Result of testing against a specific LocalStack version."""

    version: str  # e.g., "3.0.0", "latest"
    status: str  # PASSED, FAILED, etc.
    passed_tests: int
    failed_tests: int
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "status": self.status,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VersionTestResult:
        return cls(
            version=data["version"],
            status=data["status"],
            passed_tests=data.get("passed_tests", 0),
            failed_tests=data.get("failed_tests", 0),
            errors=data.get("errors", []),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class MultiVersionMatrix:
    """Results across multiple LocalStack versions."""

    arch_hash: str
    versions_tested: list[str] = field(default_factory=list)
    results: list[VersionTestResult] = field(default_factory=list)
    compatible_versions: list[str] = field(default_factory=list)
    incompatible_versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "arch_hash": self.arch_hash,
            "versions_tested": self.versions_tested,
            "results": [r.to_dict() for r in self.results],
            "compatible_versions": self.compatible_versions,
            "incompatible_versions": self.incompatible_versions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MultiVersionMatrix:
        return cls(
            arch_hash=data["arch_hash"],
            versions_tested=data.get("versions_tested", []),
            results=[VersionTestResult.from_dict(r) for r in data.get("results", [])],
            compatible_versions=data.get("compatible_versions", []),
            incompatible_versions=data.get("incompatible_versions", []),
        )


@dataclass
class TestStabilityRecord:
    """Track test stability over multiple runs for flaky detection."""

    test_name: str
    arch_hash: str
    total_runs: int = 0
    passed_runs: int = 0
    failed_runs: int = 0
    pass_rate: float = 0.0
    is_flaky: bool = False
    last_results: list[str] = field(default_factory=list)  # Last N results: ["passed", "failed", ...]
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "arch_hash": self.arch_hash,
            "total_runs": self.total_runs,
            "passed_runs": self.passed_runs,
            "failed_runs": self.failed_runs,
            "pass_rate": self.pass_rate,
            "is_flaky": self.is_flaky,
            "last_results": self.last_results,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TestStabilityRecord:
        return cls(
            test_name=data["test_name"],
            arch_hash=data["arch_hash"],
            total_runs=data.get("total_runs", 0),
            passed_runs=data.get("passed_runs", 0),
            failed_runs=data.get("failed_runs", 0),
            pass_rate=data.get("pass_rate", 0.0),
            is_flaky=data.get("is_flaky", False),
            last_results=data.get("last_results", []),
            first_seen=datetime.fromisoformat(data["first_seen"]) if data.get("first_seen") else None,
            last_seen=datetime.fromisoformat(data["last_seen"]) if data.get("last_seen") else None,
        )

    def update(self, result: str) -> None:
        """Update stability record with a new test result."""
        self.total_runs += 1
        if result == "passed":
            self.passed_runs += 1
        else:
            self.failed_runs += 1

        self.pass_rate = self.passed_runs / self.total_runs if self.total_runs > 0 else 0.0

        # Keep last 10 results
        self.last_results.append(result)
        if len(self.last_results) > 10:
            self.last_results = self.last_results[-10:]

        # Detect flakiness: if pass rate is between 10% and 90% with at least 3 runs
        self.is_flaky = (
            self.total_runs >= 3 and
            0.1 < self.pass_rate < 0.9
        )

        self.last_seen = datetime.utcnow()
        if self.first_seen is None:
            self.first_seen = self.last_seen


@dataclass
class QualityGateConfig:
    """Configuration for quality gates."""

    min_pass_rate: float = 0.8  # Minimum overall pass rate
    min_test_quality_score: float = 0.7  # Minimum test quality score
    max_flaky_tests: int = 3  # Maximum number of flaky tests allowed
    require_negative_tests: bool = False  # Require negative test cases
    min_resource_verification_rate: float = 0.9  # Minimum resource config verification rate
    block_on_regression: bool = True  # Block if regressions detected

    def to_dict(self) -> dict:
        return {
            "min_pass_rate": self.min_pass_rate,
            "min_test_quality_score": self.min_test_quality_score,
            "max_flaky_tests": self.max_flaky_tests,
            "require_negative_tests": self.require_negative_tests,
            "min_resource_verification_rate": self.min_resource_verification_rate,
            "block_on_regression": self.block_on_regression,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QualityGateConfig:
        return cls(
            min_pass_rate=data.get("min_pass_rate", 0.8),
            min_test_quality_score=data.get("min_test_quality_score", 0.7),
            max_flaky_tests=data.get("max_flaky_tests", 3),
            require_negative_tests=data.get("require_negative_tests", False),
            min_resource_verification_rate=data.get("min_resource_verification_rate", 0.9),
            block_on_regression=data.get("block_on_regression", True),
        )


@dataclass
class QualityGateResult:
    """Result of quality gate evaluation."""

    status: QualityGateStatus
    checks: list[QualityGateCheck] = field(default_factory=list)
    blocking_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "checks": [c.to_dict() for c in self.checks],
            "blocking_failures": self.blocking_failures,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QualityGateResult:
        return cls(
            status=QualityGateStatus(data["status"]),
            checks=[QualityGateCheck.from_dict(c) for c in data.get("checks", [])],
            blocking_failures=data.get("blocking_failures", []),
            warnings=data.get("warnings", []),
        )


@dataclass
class QualityGateCheck:
    """Individual quality gate check."""

    name: str
    passed: bool
    actual_value: float | int | str
    threshold: float | int | str
    message: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual_value": self.actual_value,
            "threshold": self.threshold,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QualityGateCheck:
        return cls(
            name=data["name"],
            passed=data["passed"],
            actual_value=data["actual_value"],
            threshold=data["threshold"],
            message=data.get("message", ""),
        )


@dataclass
class ErrorCluster:
    """Cluster of similar errors for root cause analysis."""

    cluster_id: str
    pattern: str  # Regex or key phrase identifying this cluster
    error_type: str  # e.g., "terraform_config", "localstack_api", "timeout"
    occurrences: int = 0
    affected_architectures: list[str] = field(default_factory=list)
    affected_services: list[str] = field(default_factory=list)
    sample_errors: list[str] = field(default_factory=list)  # Sample error messages
    suggested_fix: str | None = None
    root_cause: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "pattern": self.pattern,
            "error_type": self.error_type,
            "occurrences": self.occurrences,
            "affected_architectures": self.affected_architectures,
            "affected_services": self.affected_services,
            "sample_errors": self.sample_errors,
            "suggested_fix": self.suggested_fix,
            "root_cause": self.root_cause,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ErrorCluster:
        return cls(
            cluster_id=data["cluster_id"],
            pattern=data["pattern"],
            error_type=data["error_type"],
            occurrences=data.get("occurrences", 0),
            affected_architectures=data.get("affected_architectures", []),
            affected_services=data.get("affected_services", []),
            sample_errors=data.get("sample_errors", []),
            suggested_fix=data.get("suggested_fix"),
            root_cause=data.get("root_cause"),
            first_seen=datetime.fromisoformat(data["first_seen"]) if data.get("first_seen") else None,
            last_seen=datetime.fromisoformat(data["last_seen"]) if data.get("last_seen") else None,
        )


@dataclass
class PerformanceBaseline:
    """Performance baseline for an architecture or operation."""

    arch_hash: str
    metric_type: Literal["terraform_init", "terraform_apply", "terraform_destroy",
                         "pytest", "total_validation"]
    baseline_duration: float  # seconds
    std_deviation: float = 0.0
    sample_count: int = 0
    min_duration: float = 0.0
    max_duration: float = 0.0
    last_duration: float = 0.0
    trend: Literal["stable", "improving", "degrading"] = "stable"

    def to_dict(self) -> dict:
        return {
            "arch_hash": self.arch_hash,
            "metric_type": self.metric_type,
            "baseline_duration": self.baseline_duration,
            "std_deviation": self.std_deviation,
            "sample_count": self.sample_count,
            "min_duration": self.min_duration,
            "max_duration": self.max_duration,
            "last_duration": self.last_duration,
            "trend": self.trend,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PerformanceBaseline:
        return cls(
            arch_hash=data["arch_hash"],
            metric_type=data["metric_type"],
            baseline_duration=data["baseline_duration"],
            std_deviation=data.get("std_deviation", 0.0),
            sample_count=data.get("sample_count", 0),
            min_duration=data.get("min_duration", 0.0),
            max_duration=data.get("max_duration", 0.0),
            last_duration=data.get("last_duration", 0.0),
            trend=data.get("trend", "stable"),
        )

    def update(self, duration: float) -> None:
        """Update baseline with new measurement."""
        import math

        self.sample_count += 1
        self.last_duration = duration

        if self.sample_count == 1:
            self.baseline_duration = duration
            self.min_duration = duration
            self.max_duration = duration
        else:
            # Running average
            old_avg = self.baseline_duration
            self.baseline_duration = old_avg + (duration - old_avg) / self.sample_count

            # Update std deviation (Welford's algorithm)
            self.std_deviation = math.sqrt(
                ((self.sample_count - 1) * self.std_deviation**2 +
                 (duration - old_avg) * (duration - self.baseline_duration)) / self.sample_count
            )

            self.min_duration = min(self.min_duration, duration)
            self.max_duration = max(self.max_duration, duration)

        # Determine trend based on last vs baseline
        if self.sample_count >= 3:
            if duration > self.baseline_duration + 2 * self.std_deviation:
                self.trend = "degrading"
            elif duration < self.baseline_duration - self.std_deviation:
                self.trend = "improving"
            else:
                self.trend = "stable"


@dataclass
class ValidationCache:
    """Cache entry for incremental validation."""

    arch_hash: str
    terraform_hash: str  # Hash of terraform files
    app_hash: str  # Hash of test app files
    last_status: str
    last_run_id: str
    last_validated: datetime
    skip_reason: str | None = None  # Why we might skip this

    def to_dict(self) -> dict:
        return {
            "arch_hash": self.arch_hash,
            "terraform_hash": self.terraform_hash,
            "app_hash": self.app_hash,
            "last_status": self.last_status,
            "last_run_id": self.last_run_id,
            "last_validated": self.last_validated.isoformat(),
            "skip_reason": self.skip_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ValidationCache:
        return cls(
            arch_hash=data["arch_hash"],
            terraform_hash=data["terraform_hash"],
            app_hash=data["app_hash"],
            last_status=data["last_status"],
            last_run_id=data["last_run_id"],
            last_validated=datetime.fromisoformat(data["last_validated"]),
            skip_reason=data.get("skip_reason"),
        )


@dataclass
class WorkerTask:
    """Task for distributed worker execution."""

    task_id: str
    arch_hash: str
    arch_data: dict
    run_id: str
    localstack_version: str
    timeout: int
    priority: int = 0  # Higher = more important
    created_at: datetime = field(default_factory=datetime.utcnow)
    assigned_worker: str | None = None
    status: Literal["pending", "assigned", "running", "completed", "failed"] = "pending"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "arch_hash": self.arch_hash,
            "arch_data": self.arch_data,
            "run_id": self.run_id,
            "localstack_version": self.localstack_version,
            "timeout": self.timeout,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "assigned_worker": self.assigned_worker,
            "status": self.status,
        }


@dataclass
class WorkerStatus:
    """Status of a distributed worker."""

    worker_id: str
    hostname: str
    started_at: datetime
    last_heartbeat: datetime
    tasks_completed: int = 0
    tasks_failed: int = 0
    current_task: str | None = None
    status: Literal["idle", "busy", "offline"] = "idle"

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "hostname": self.hostname,
            "started_at": self.started_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "current_task": self.current_task,
            "status": self.status,
        }
