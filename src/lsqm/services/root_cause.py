"""Root cause analysis - cluster errors and identify root causes."""

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from lsqm.models.qa_models import ErrorCluster

# Known error patterns with suggested fixes
KNOWN_ERROR_PATTERNS = [
    {
        "pattern": r"missing required variable",
        "error_type": "terraform_config",
        "root_cause": "Terraform module requires input variables that weren't provided",
        "suggested_fix": "Add required variables to terraform.tfvars or use default values",
    },
    {
        "pattern": r"unsupported (provider )?endpoint",
        "error_type": "terraform_config",
        "root_cause": "Terraform AWS provider doesn't recognize the endpoint name",
        "suggested_fix": "Remove unsupported endpoint from provider override file",
    },
    {
        "pattern": r"failed to get shared config profile",
        "error_type": "terraform_config",
        "root_cause": "Terraform is trying to use AWS profile that doesn't exist",
        "suggested_fix": "Remove profile references from provider configuration",
    },
    {
        "pattern": r"invalid.*runtime|expected runtime to be one of",
        "error_type": "terraform_config",
        "root_cause": "Lambda runtime not supported by Terraform provider version",
        "suggested_fix": "Update AWS provider version or use a supported runtime",
    },
    {
        "pattern": r"reference to undeclared resource",
        "error_type": "terraform_config",
        "root_cause": "Terraform references a resource that was removed or doesn't exist",
        "suggested_fix": "Check for removed resources or missing module outputs",
    },
    {
        "pattern": r"ResourceNotFoundException",
        "error_type": "localstack_api",
        "root_cause": "Resource was not created or was deleted before access",
        "suggested_fix": "Check terraform apply logs; resource may have failed to create",
    },
    {
        "pattern": r"AccessDeniedException",
        "error_type": "localstack_api",
        "root_cause": "IAM permissions not properly configured",
        "suggested_fix": "Verify IAM role/policy attachments in LocalStack",
    },
    {
        "pattern": r"ValidationException",
        "error_type": "localstack_api",
        "root_cause": "Invalid parameter or configuration in API request",
        "suggested_fix": "Check API parameters match AWS specifications",
    },
    {
        "pattern": r"not implemented|NotImplementedError",
        "error_type": "localstack_feature_gap",
        "root_cause": "Feature not implemented in LocalStack",
        "suggested_fix": "Check LocalStack coverage docs or use LocalStack Pro",
    },
    {
        "pattern": r"connection refused|ECONNREFUSED",
        "error_type": "infrastructure",
        "root_cause": "LocalStack container not running or not ready",
        "suggested_fix": "Increase health check wait time; check container logs",
    },
    {
        "pattern": r"timed? ?out|deadline exceeded",
        "error_type": "timeout",
        "root_cause": "Operation took too long to complete",
        "suggested_fix": "Increase timeout; check if resource creation is hanging",
    },
    {
        "pattern": r"module.*not found|no available releases",
        "error_type": "terraform_registry",
        "root_cause": "Terraform module not available in registry",
        "suggested_fix": "Check module source URL and version constraints",
    },
    {
        "pattern": r"backend.*initialization|backend configuration",
        "error_type": "terraform_config",
        "root_cause": "Remote backend not available in test environment",
        "suggested_fix": "Remove backend configuration for local testing",
    },
    {
        "pattern": r"archive.*missing|source.*not found",
        "error_type": "missing_files",
        "root_cause": "Source files for Lambda/archive not found",
        "suggested_fix": "Create stub files or provide actual source code",
    },
    {
        "pattern": r"circular dependency|cycle:",
        "error_type": "terraform_config",
        "root_cause": "Circular dependency between Terraform resources",
        "suggested_fix": "Review resource dependencies; may need explicit depends_on",
    },
    {
        "pattern": r"pro.*required|license.*plan",
        "error_type": "localstack_license",
        "root_cause": "Feature requires LocalStack Pro license",
        "suggested_fix": "Use LocalStack Pro or remove Pro-only resources",
    },
]


class RootCauseAnalyzer:
    """Analyze errors and identify root causes through clustering."""

    def __init__(
        self,
        artifacts_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.logger = logger
        self.clusters_file = artifacts_dir / "qa" / "error_clusters.json" if artifacts_dir else None
        if self.clusters_file:
            self.clusters_file.parent.mkdir(parents=True, exist_ok=True)
        self._clusters: dict[str, ErrorCluster] = {}
        self._load()

    def _load(self) -> None:
        """Load existing error clusters."""
        if self.clusters_file and self.clusters_file.exists():
            try:
                with open(self.clusters_file) as f:
                    data = json.load(f)
                for cluster_id, cluster_data in data.items():
                    self._clusters[cluster_id] = ErrorCluster.from_dict(cluster_data)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to load error clusters: {e}")

    def _save(self) -> None:
        """Save error clusters."""
        if not self.clusters_file:
            return
        try:
            data = {cluster_id: cluster.to_dict() for cluster_id, cluster in self._clusters.items()}
            with open(self.clusters_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to save error clusters: {e}")

    def _generate_cluster_id(self, pattern: str) -> str:
        """Generate a unique cluster ID from a pattern."""
        return hashlib.md5(pattern.encode()).hexdigest()[:12]

    def analyze_error(
        self,
        error_message: str,
        arch_hash: str,
        services: list[str] | None = None,
    ) -> ErrorCluster | None:
        """Analyze an error and assign it to a cluster.

        Args:
            error_message: The error message to analyze
            arch_hash: Architecture hash where error occurred
            services: Services involved in the architecture

        Returns:
            ErrorCluster the error was assigned to, or None
        """
        if not error_message:
            return None

        error_lower = error_message.lower()

        # Try to match against known patterns
        for known in KNOWN_ERROR_PATTERNS:
            if re.search(known["pattern"], error_lower, re.IGNORECASE):
                cluster_id = self._generate_cluster_id(known["pattern"])

                if cluster_id not in self._clusters:
                    self._clusters[cluster_id] = ErrorCluster(
                        cluster_id=cluster_id,
                        pattern=known["pattern"],
                        error_type=known["error_type"],
                        root_cause=known["root_cause"],
                        suggested_fix=known["suggested_fix"],
                        first_seen=datetime.utcnow(),
                    )

                cluster = self._clusters[cluster_id]
                cluster.occurrences += 1
                cluster.last_seen = datetime.utcnow()

                if arch_hash not in cluster.affected_architectures:
                    cluster.affected_architectures.append(arch_hash)

                if services:
                    for svc in services:
                        if svc not in cluster.affected_services:
                            cluster.affected_services.append(svc)

                # Keep sample errors (max 5)
                if len(cluster.sample_errors) < 5:
                    truncated = error_message[:500]
                    if truncated not in cluster.sample_errors:
                        cluster.sample_errors.append(truncated)

                self._save()
                return cluster

        # No known pattern matched - create a new cluster for unknown errors
        # Use a hash of the first 100 chars as the pattern
        unknown_pattern = error_lower[:100].strip()
        cluster_id = self._generate_cluster_id(unknown_pattern)

        if cluster_id not in self._clusters:
            self._clusters[cluster_id] = ErrorCluster(
                cluster_id=cluster_id,
                pattern=unknown_pattern,
                error_type="unknown",
                first_seen=datetime.utcnow(),
            )

        cluster = self._clusters[cluster_id]
        cluster.occurrences += 1
        cluster.last_seen = datetime.utcnow()

        if arch_hash not in cluster.affected_architectures:
            cluster.affected_architectures.append(arch_hash)

        if services:
            for svc in services:
                if svc not in cluster.affected_services:
                    cluster.affected_services.append(svc)

        if len(cluster.sample_errors) < 5:
            truncated = error_message[:500]
            if truncated not in cluster.sample_errors:
                cluster.sample_errors.append(truncated)

        self._save()
        return cluster

    def analyze_validation_results(
        self,
        results: list[dict],
    ) -> list[ErrorCluster]:
        """Analyze multiple validation results for root causes.

        Args:
            results: List of validation result dicts

        Returns:
            List of error clusters that were updated
        """
        updated_clusters = []

        for result in results:
            if result.get("status") in ["FAILED", "ERROR", "TIMEOUT"]:
                arch_hash = result.get("arch_hash", "")
                services = result.get("services", [])

                # Get error message from various sources
                error_message = (
                    result.get("error_message")
                    or result.get("failure_analysis", {}).get("error_message")
                    or result.get("terraform_apply", {}).get("logs", "")[-500:]
                )

                if error_message:
                    cluster = self.analyze_error(error_message, arch_hash, services)
                    if cluster and cluster not in updated_clusters:
                        updated_clusters.append(cluster)

        return updated_clusters

    def get_top_errors(self, limit: int = 10) -> list[ErrorCluster]:
        """Get the most frequent error clusters.

        Args:
            limit: Maximum number of clusters to return

        Returns:
            List of ErrorCluster sorted by occurrence count
        """
        sorted_clusters = sorted(
            self._clusters.values(),
            key=lambda c: c.occurrences,
            reverse=True,
        )
        return sorted_clusters[:limit]

    def get_errors_by_type(self, error_type: str) -> list[ErrorCluster]:
        """Get error clusters of a specific type.

        Args:
            error_type: Type of error to filter by

        Returns:
            List of matching ErrorCluster
        """
        return [c for c in self._clusters.values() if c.error_type == error_type]

    def get_errors_by_service(self, service: str) -> list[ErrorCluster]:
        """Get error clusters affecting a specific service.

        Args:
            service: Service name to filter by

        Returns:
            List of matching ErrorCluster
        """
        return [c for c in self._clusters.values() if service in c.affected_services]

    def get_report(self) -> dict:
        """Generate a root cause analysis report.

        Returns:
            Dict with error analysis summary
        """
        clusters = list(self._clusters.values())

        # Group by error type
        by_type = defaultdict(list)
        for cluster in clusters:
            by_type[cluster.error_type].append(cluster)

        # Calculate statistics
        total_occurrences = sum(c.occurrences for c in clusters)
        unique_architectures = set()
        for c in clusters:
            unique_architectures.update(c.affected_architectures)

        return {
            "total_error_clusters": len(clusters),
            "total_occurrences": total_occurrences,
            "unique_architectures_affected": len(unique_architectures),
            "errors_by_type": {
                error_type: {
                    "cluster_count": len(type_clusters),
                    "total_occurrences": sum(c.occurrences for c in type_clusters),
                    "top_clusters": [
                        {
                            "pattern": c.pattern[:50],
                            "occurrences": c.occurrences,
                            "suggested_fix": c.suggested_fix,
                        }
                        for c in sorted(type_clusters, key=lambda x: x.occurrences, reverse=True)[
                            :3
                        ]
                    ],
                }
                for error_type, type_clusters in by_type.items()
            },
            "actionable_fixes": [
                {
                    "error_type": c.error_type,
                    "pattern": c.pattern[:50],
                    "occurrences": c.occurrences,
                    "root_cause": c.root_cause,
                    "suggested_fix": c.suggested_fix,
                }
                for c in sorted(clusters, key=lambda x: x.occurrences, reverse=True)[:10]
                if c.suggested_fix
            ],
        }


def infer_root_cause(error_message: str) -> tuple[str, str | None]:
    """Infer root cause from an error message.

    Args:
        error_message: The error message

    Returns:
        Tuple of (error_type, suggested_fix or None)
    """
    if not error_message:
        return "unknown", None

    error_lower = error_message.lower()

    for known in KNOWN_ERROR_PATTERNS:
        if re.search(known["pattern"], error_lower, re.IGNORECASE):
            return known["error_type"], known["suggested_fix"]

    return "unknown", None
