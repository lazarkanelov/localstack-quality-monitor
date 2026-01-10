"""Run model - represents a single pipeline execution."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class RunConfig:
    """Configuration snapshot for a pipeline run."""

    parallel: int = 4
    timeout: int = 300
    token_budget: int = 500_000
    dry_run: bool = False

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "parallel": self.parallel,
            "timeout": self.timeout,
            "token_budget": self.token_budget,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunConfig":
        """Deserialize from dictionary."""
        return cls(
            parallel=data.get("parallel", 4),
            timeout=data.get("timeout", 300),
            token_budget=data.get("token_budget", 500_000),
            dry_run=data.get("dry_run", False),
        )


@dataclass
class RunSummary:
    """Aggregate results from a pipeline run."""

    total: int = 0
    passed: int = 0
    partial: int = 0
    failed: int = 0
    timeout: int = 0
    error: int = 0
    new_architectures: int = 0
    tokens_used: int = 0
    duration_seconds: float = 0.0

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage."""
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "total": self.total,
            "passed": self.passed,
            "partial": self.partial,
            "failed": self.failed,
            "timeout": self.timeout,
            "error": self.error,
            "new_architectures": self.new_architectures,
            "tokens_used": self.tokens_used,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunSummary":
        """Deserialize from dictionary."""
        return cls(
            total=data.get("total", 0),
            passed=data.get("passed", 0),
            partial=data.get("partial", 0),
            failed=data.get("failed", 0),
            timeout=data.get("timeout", 0),
            error=data.get("error", 0),
            new_architectures=data.get("new_architectures", 0),
            tokens_used=data.get("tokens_used", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class Run:
    """A single pipeline execution with configuration and results."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    localstack_version: str = "latest"
    lsqm_version: str = "1.0.0"
    config: RunConfig = field(default_factory=RunConfig)
    summary: RunSummary = field(default_factory=RunSummary)

    @property
    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def complete(self) -> None:
        """Mark run as completed."""
        self.completed_at = datetime.utcnow()
        if self.duration_seconds:
            self.summary.duration_seconds = self.duration_seconds

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "localstack_version": self.localstack_version,
            "lsqm_version": self.lsqm_version,
            "config": self.config.to_dict(),
            "summary": self.summary.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Run":
        """Deserialize from dictionary."""
        return cls(
            run_id=data["run_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            localstack_version=data.get("localstack_version", "latest"),
            lsqm_version=data.get("lsqm_version", "1.0.0"),
            config=RunConfig.from_dict(data.get("config", {})),
            summary=RunSummary.from_dict(data.get("summary", {})),
        )
