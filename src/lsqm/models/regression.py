"""Regression model - records a compatibility regression between runs."""

from dataclasses import dataclass
from datetime import datetime

from lsqm.models.validation_result import ValidationStatus


@dataclass
class Regression:
    """A change in status from passing to failing between two runs."""

    arch_hash: str
    from_run_id: str
    to_run_id: str
    from_status: ValidationStatus
    to_status: ValidationStatus
    detected_at: datetime
    services_affected: list[str]
    architecture_name: str | None = None
    github_issue_url: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "arch_hash": self.arch_hash,
            "architecture_name": self.architecture_name,
            "from_run_id": self.from_run_id,
            "to_run_id": self.to_run_id,
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "detected_at": self.detected_at.isoformat(),
            "services_affected": self.services_affected,
            "github_issue_url": self.github_issue_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Regression":
        """Deserialize from dictionary."""
        return cls(
            arch_hash=data["arch_hash"],
            architecture_name=data.get("architecture_name"),
            from_run_id=data["from_run_id"],
            to_run_id=data["to_run_id"],
            from_status=ValidationStatus(data["from_status"]),
            to_status=ValidationStatus(data["to_status"]),
            detected_at=datetime.fromisoformat(data["detected_at"]),
            services_affected=data["services_affected"],
            github_issue_url=data.get("github_issue_url"),
        )

    @property
    def is_regression(self) -> bool:
        """Check if this represents a regression (was passing, now failing)."""
        passing_states = {ValidationStatus.PASSED, ValidationStatus.PARTIAL}
        failing_states = {ValidationStatus.FAILED, ValidationStatus.TIMEOUT, ValidationStatus.ERROR}
        return self.from_status in passing_states and self.to_status in failing_states

    @property
    def is_fix(self) -> bool:
        """Check if this represents a fix (was failing, now passing)."""
        passing_states = {ValidationStatus.PASSED, ValidationStatus.PARTIAL}
        failing_states = {ValidationStatus.FAILED, ValidationStatus.TIMEOUT, ValidationStatus.ERROR}
        return self.from_status in failing_states and self.to_status in passing_states
