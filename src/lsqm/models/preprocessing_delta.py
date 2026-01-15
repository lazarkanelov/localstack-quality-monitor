"""Preprocessing delta model for tracking Terraform modifications."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class RemovedResource:
    """A resource removed during preprocessing."""

    resource_type: str  # e.g., "aws_cognito_user_pool"
    resource_name: str  # e.g., "main"
    reason: Literal["pro_only", "unsupported", "dependency", "other"]
    file_path: str = ""  # Which file it was removed from

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "reason": self.reason,
            "file_path": self.file_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RemovedResource":
        """Deserialize from dictionary."""
        return cls(
            resource_type=data["resource_type"],
            resource_name=data["resource_name"],
            reason=data.get("reason", "other"),
            file_path=data.get("file_path", ""),
        )

    @property
    def address(self) -> str:
        """Return the Terraform resource address."""
        return f"{self.resource_type}.{self.resource_name}"

    @property
    def service(self) -> str:
        """Extract AWS service from resource type."""
        parts = self.resource_type.split("_")
        if len(parts) >= 2 and parts[0] == "aws":
            return parts[1]
        return self.resource_type


@dataclass
class StubInfo:
    """Information about stub files created for Lambda functions."""

    files: list[str] = field(default_factory=list)  # Paths of created stub files
    lambdas: list[str] = field(default_factory=list)  # Lambda function names using stubs
    stub_types: dict[str, str] = field(default_factory=dict)  # {filename: "js"|"py"|"ts"}
    directories: list[str] = field(default_factory=list)  # Directories created for stubs

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "files": self.files,
            "lambdas": self.lambdas,
            "stub_types": self.stub_types,
            "directories": self.directories,
            "has_stubs": self.has_stubs,
            "stub_count": self.stub_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StubInfo":
        """Deserialize from dictionary."""
        return cls(
            files=data.get("files", []),
            lambdas=data.get("lambdas", []),
            stub_types=data.get("stub_types", {}),
            directories=data.get("directories", []),
        )

    @property
    def has_stubs(self) -> bool:
        """Check if any stubs were created."""
        return len(self.files) > 0 or len(self.directories) > 0

    @property
    def stub_count(self) -> int:
        """Total number of stub files created."""
        return len(self.files)


@dataclass
class ServiceReconciliation:
    """Service list changes after preprocessing."""

    original_services: set[str] = field(default_factory=set)
    final_services: set[str] = field(default_factory=set)
    removed_services: set[str] = field(default_factory=set)
    added_services: set[str] = field(default_factory=set)  # Companion services added
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "original_services": sorted(self.original_services),
            "final_services": sorted(self.final_services),
            "removed_services": sorted(self.removed_services),
            "added_services": sorted(self.added_services),
            "warnings": self.warnings,
            "significant_change": self.significant_change,
            "change_ratio": self.change_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceReconciliation":
        """Deserialize from dictionary."""
        return cls(
            original_services=set(data.get("original_services", [])),
            final_services=set(data.get("final_services", [])),
            removed_services=set(data.get("removed_services", [])),
            added_services=set(data.get("added_services", [])),
            warnings=data.get("warnings", []),
        )

    @property
    def significant_change(self) -> bool:
        """Check if >30% of services were removed."""
        return self.change_ratio > 0.3

    @property
    def change_ratio(self) -> float:
        """Ratio of removed services to original services."""
        if not self.original_services:
            return 0.0
        return len(self.removed_services) / len(self.original_services)


@dataclass
class PreprocessingDelta:
    """Changes made during Terraform preprocessing."""

    removed_resources: list[RemovedResource] = field(default_factory=list)
    stub_info: StubInfo = field(default_factory=StubInfo)
    service_reconciliation: ServiceReconciliation = field(default_factory=ServiceReconciliation)
    modified_files: list[str] = field(default_factory=list)
    generated_tfvars: dict[str, str] = field(default_factory=dict)  # {var_name: value}
    removed_backends: list[str] = field(default_factory=list)  # Backend types removed
    removed_profiles: list[str] = field(default_factory=list)  # AWS profiles removed
    provider_version_changes: list[dict] = field(default_factory=list)  # Version constraint changes

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "removed_resources": [r.to_dict() for r in self.removed_resources],
            "stub_info": self.stub_info.to_dict(),
            "service_reconciliation": self.service_reconciliation.to_dict(),
            "modified_files": self.modified_files,
            "generated_tfvars": self.generated_tfvars,
            "removed_backends": self.removed_backends,
            "removed_profiles": self.removed_profiles,
            "provider_version_changes": self.provider_version_changes,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PreprocessingDelta":
        """Deserialize from dictionary."""
        stub_data = data.get("stub_info", {})
        recon_data = data.get("service_reconciliation", {})

        return cls(
            removed_resources=[
                RemovedResource.from_dict(r) for r in data.get("removed_resources", [])
            ],
            stub_info=StubInfo.from_dict(stub_data) if stub_data else StubInfo(),
            service_reconciliation=(
                ServiceReconciliation.from_dict(recon_data)
                if recon_data
                else ServiceReconciliation()
            ),
            modified_files=data.get("modified_files", []),
            generated_tfvars=data.get("generated_tfvars", {}),
            removed_backends=data.get("removed_backends", []),
            removed_profiles=data.get("removed_profiles", []),
            provider_version_changes=data.get("provider_version_changes", []),
        )

    @property
    def has_changes(self) -> bool:
        """Check if any preprocessing changes were made."""
        return (
            len(self.removed_resources) > 0
            or self.stub_info.has_stubs
            or len(self.modified_files) > 0
            or len(self.generated_tfvars) > 0
            or len(self.removed_backends) > 0
        )

    @property
    def removed_services(self) -> set[str]:
        """Get set of services that had resources removed."""
        return {r.service for r in self.removed_resources}

    @property
    def summary(self) -> dict:
        """Get a summary of preprocessing changes."""
        return {
            "resources_removed": len(self.removed_resources),
            "stubs_created": self.stub_info.stub_count,
            "files_modified": len(self.modified_files),
            "tfvars_generated": len(self.generated_tfvars),
            "backends_removed": len(self.removed_backends),
            "services_removed": len(self.service_reconciliation.removed_services),
            "has_significant_service_changes": self.service_reconciliation.significant_change,
        }

    @property
    def warnings(self) -> list[str]:
        """Collect all warnings from preprocessing."""
        warnings = []

        if self.removed_resources:
            pro_only = [r for r in self.removed_resources if r.reason == "pro_only"]
            if pro_only:
                warnings.append(
                    f"{len(pro_only)} Pro-only resources removed: "
                    f"{', '.join(r.address for r in pro_only[:3])}"
                    + ("..." if len(pro_only) > 3 else "")
                )

        if self.stub_info.has_stubs:
            warnings.append(
                f"{self.stub_info.stub_count} Lambda stub files created - "
                "tests may not reflect actual functionality"
            )

        warnings.extend(self.service_reconciliation.warnings)

        return warnings
