"""ServiceTrend model - aggregated compatibility statistics per AWS service."""

from dataclasses import dataclass, field
from typing import Literal

TrendDirection = Literal["improving", "stable", "declining"]


@dataclass
class TrendHistoryEntry:
    """A single data point in service trend history."""

    run_id: str
    run_date: str
    total: int
    passed: int

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate for this entry."""
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "run_id": self.run_id,
            "run_date": self.run_date,
            "total": self.total,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrendHistoryEntry":
        """Deserialize from dictionary."""
        return cls(
            run_id=data["run_id"],
            run_date=data["run_date"],
            total=data["total"],
            passed=data["passed"],
        )


@dataclass
class ServiceTrend:
    """Aggregated compatibility statistics per AWS service over time."""

    service_name: str
    current_pass_rate: float
    previous_pass_rate: float | None = None
    architecture_count: int = 0
    history: list[TrendHistoryEntry] = field(default_factory=list)

    @property
    def trend(self) -> TrendDirection:
        """Calculate trend direction based on pass rate change."""
        if self.previous_pass_rate is None:
            return "stable"

        delta = self.current_pass_rate - self.previous_pass_rate
        if delta > 0.02:
            return "improving"
        elif delta < -0.02:
            return "declining"
        return "stable"

    def add_entry(self, entry: TrendHistoryEntry) -> None:
        """Add a new history entry, maintaining max 12 entries."""
        self.history.insert(0, entry)
        if len(self.history) > 12:
            self.history = self.history[:12]

        # Update rates
        if len(self.history) >= 2:
            self.previous_pass_rate = self.history[1].pass_rate
        self.current_pass_rate = entry.pass_rate

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "service_name": self.service_name,
            "current_pass_rate": self.current_pass_rate,
            "previous_pass_rate": self.previous_pass_rate,
            "trend": self.trend,
            "architecture_count": self.architecture_count,
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceTrend":
        """Deserialize from dictionary."""
        return cls(
            service_name=data["service_name"],
            current_pass_rate=data["current_pass_rate"],
            previous_pass_rate=data.get("previous_pass_rate"),
            architecture_count=data.get("architecture_count", 0),
            history=[TrendHistoryEntry.from_dict(h) for h in data.get("history", [])],
        )
