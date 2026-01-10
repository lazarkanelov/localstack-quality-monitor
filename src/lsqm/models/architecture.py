"""Architecture model - represents a discovered AWS infrastructure pattern."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SourceType = Literal["terraform_registry", "github", "serverless", "cdk"]


@dataclass
class Architecture:
    """A discovered AWS infrastructure pattern with content hash and metadata."""

    hash: str
    source_url: str
    source_type: SourceType
    discovered_at: datetime
    services: list[str]
    resource_count: int
    name: str | None = None
    description: str | None = None
    version: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    terraform_files: dict[str, str] = field(default_factory=dict)
    tf_files: dict[str, str] = field(default_factory=dict)  # Alias for terraform_files
    original_format: str | None = None  # e.g., "serverless", "cdk", "terraform"

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        # Merge tf_files into terraform_files for storage
        all_tf_files = {**self.terraform_files, **self.tf_files}
        return {
            "hash": self.hash,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "discovered_at": self.discovered_at.isoformat(),
            "services": self.services,
            "resource_count": self.resource_count,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "original_format": self.original_format,
            "terraform_files": all_tf_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Architecture":
        """Deserialize from dictionary."""
        tf_files = data.get("terraform_files", {}) or data.get("tf_files", {})
        return cls(
            hash=data["hash"],
            source_url=data["source_url"],
            source_type=data["source_type"],
            discovered_at=datetime.fromisoformat(data["discovered_at"]),
            services=data["services"],
            resource_count=data["resource_count"],
            name=data.get("name"),
            description=data.get("description"),
            version=data.get("version"),
            skipped=data.get("skipped", False),
            skip_reason=data.get("skip_reason"),
            terraform_files=tf_files,
            tf_files=tf_files,
            original_format=data.get("original_format"),
        )

    def has_unsupported_services(self, supported: set[str]) -> tuple[bool, list[str]]:
        """Check if architecture uses services not in the supported set."""
        unsupported = [s for s in self.services if s not in supported]
        return len(unsupported) > 0, unsupported
