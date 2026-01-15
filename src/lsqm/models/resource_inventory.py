"""Resource inventory model for tracking Terraform-created resources."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TerraformResource:
    """A resource from terraform state."""

    resource_type: str  # e.g., "aws_s3_bucket"
    resource_name: str  # e.g., "my_bucket"
    resource_id: str  # AWS resource ID
    attributes: dict = field(default_factory=dict)  # Key attributes (bucket name, ARN, etc.)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "resource_id": self.resource_id,
            "attributes": self.attributes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TerraformResource":
        """Deserialize from dictionary."""
        return cls(
            resource_type=data["resource_type"],
            resource_name=data["resource_name"],
            resource_id=data.get("resource_id", ""),
            attributes=data.get("attributes", {}),
        )

    @property
    def address(self) -> str:
        """Return the Terraform resource address."""
        return f"{self.resource_type}.{self.resource_name}"

    @property
    def service(self) -> str:
        """Extract AWS service from resource type."""
        # aws_s3_bucket -> s3
        # aws_lambda_function -> lambda
        # aws_dynamodb_table -> dynamodb
        parts = self.resource_type.split("_")
        if len(parts) >= 2 and parts[0] == "aws":
            return parts[1]
        return self.resource_type


@dataclass
class ResourceInventory:
    """Inventory of resources created by terraform apply."""

    resources: list[TerraformResource] = field(default_factory=list)
    expected_resources: list[str] = field(default_factory=list)  # From test file analysis
    missing_resources: list[str] = field(default_factory=list)  # Expected but not created
    extra_resources: list[str] = field(default_factory=list)  # Created but not expected
    verification_status: Literal["complete", "incomplete", "failed", "skipped"] = "skipped"
    verification_error: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "resources": [r.to_dict() for r in self.resources],
            "expected_resources": self.expected_resources,
            "missing_resources": self.missing_resources,
            "extra_resources": self.extra_resources,
            "verification_status": self.verification_status,
            "verification_error": self.verification_error,
            "resource_count": self.resource_count,
            "is_complete": self.is_complete,
            "completeness_ratio": self.completeness_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceInventory":
        """Deserialize from dictionary."""
        return cls(
            resources=[TerraformResource.from_dict(r) for r in data.get("resources", [])],
            expected_resources=data.get("expected_resources", []),
            missing_resources=data.get("missing_resources", []),
            extra_resources=data.get("extra_resources", []),
            verification_status=data.get("verification_status", "skipped"),
            verification_error=data.get("verification_error"),
        )

    @property
    def resource_count(self) -> int:
        """Total number of created resources."""
        return len(self.resources)

    @property
    def is_complete(self) -> bool:
        """Check if all expected resources were created."""
        return len(self.missing_resources) == 0 and self.verification_status == "complete"

    @property
    def completeness_ratio(self) -> float:
        """Ratio of created to expected resources."""
        if not self.expected_resources:
            return 1.0 if self.resources else 0.0
        created_count = len(self.expected_resources) - len(self.missing_resources)
        return created_count / len(self.expected_resources)

    def get_resources_by_service(self) -> dict[str, list[TerraformResource]]:
        """Group resources by AWS service."""
        by_service: dict[str, list[TerraformResource]] = {}
        for resource in self.resources:
            service = resource.service
            if service not in by_service:
                by_service[service] = []
            by_service[service].append(resource)
        return by_service

    def get_resources_by_type(self) -> dict[str, list[TerraformResource]]:
        """Group resources by Terraform resource type."""
        by_type: dict[str, list[TerraformResource]] = {}
        for resource in self.resources:
            if resource.resource_type not in by_type:
                by_type[resource.resource_type] = []
            by_type[resource.resource_type].append(resource)
        return by_type

    @classmethod
    def create_failed(cls, error: str) -> "ResourceInventory":
        """Create a failed inventory result."""
        return cls(
            verification_status="failed",
            verification_error=error,
        )

    @classmethod
    def create_skipped(cls, reason: str) -> "ResourceInventory":
        """Create a skipped inventory result."""
        return cls(
            verification_status="skipped",
            verification_error=reason,
        )
