"""Multi-version testing - test architectures against multiple LocalStack versions."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import docker

from lsqm.models.qa_models import MultiVersionMatrix, VersionTestResult

# Default LocalStack versions to test against
DEFAULT_VERSIONS = [
    "latest",
    "3.0",  # Latest stable major
    "2.3",  # Previous stable
]

# Version compatibility matrix - which features are supported in which versions
VERSION_FEATURES = {
    "3.0": {
        "lambda_docker": True,
        "s3_notifications": True,
        "dynamodb_streams": True,
        "api_gateway_v2": True,
        "step_functions": True,
    },
    "2.3": {
        "lambda_docker": True,
        "s3_notifications": True,
        "dynamodb_streams": True,
        "api_gateway_v2": False,  # Limited support
        "step_functions": True,
    },
    "2.0": {
        "lambda_docker": True,
        "s3_notifications": True,
        "dynamodb_streams": False,
        "api_gateway_v2": False,
        "step_functions": False,
    },
}


class MultiVersionTester:
    """Test architectures against multiple LocalStack versions."""

    def __init__(
        self,
        versions: list[str] | None = None,
        artifacts_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ):
        self.versions = versions or DEFAULT_VERSIONS
        self.artifacts_dir = artifacts_dir
        self.logger = logger
        self.results_file = (
            artifacts_dir / "qa" / "version_matrix.json" if artifacts_dir else None
        )
        if self.results_file:
            self.results_file.parent.mkdir(parents=True, exist_ok=True)
        self._matrices: dict[str, MultiVersionMatrix] = {}
        self._load()

    def _load(self) -> None:
        """Load existing version matrix data."""
        if self.results_file and self.results_file.exists():
            try:
                with open(self.results_file) as f:
                    data = json.load(f)
                for arch_hash, matrix_data in data.items():
                    self._matrices[arch_hash] = MultiVersionMatrix.from_dict(matrix_data)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to load version matrix: {e}")

    def _save(self) -> None:
        """Save version matrix data."""
        if not self.results_file:
            return
        try:
            data = {
                arch_hash: matrix.to_dict()
                for arch_hash, matrix in self._matrices.items()
            }
            with open(self.results_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to save version matrix: {e}")

    async def test_architecture_versions(
        self,
        arch_hash: str,
        arch_data: dict,
        run_validation_func,  # Async function that validates an architecture
        timeout: int = 300,
    ) -> MultiVersionMatrix:
        """Test an architecture against multiple LocalStack versions.

        Args:
            arch_hash: Architecture hash
            arch_data: Architecture data
            run_validation_func: Async function(arch_hash, arch_data, version, timeout) -> ValidationResult
            timeout: Timeout per version test

        Returns:
            MultiVersionMatrix with results
        """
        matrix = MultiVersionMatrix(
            arch_hash=arch_hash,
            versions_tested=self.versions,
        )

        for version in self.versions:
            if self.logger:
                self.logger.info(f"Testing {arch_hash[:8]} against LocalStack {version}")

            start_time = datetime.utcnow()
            try:
                result = await run_validation_func(
                    arch_hash, arch_data, version, timeout
                )

                version_result = VersionTestResult(
                    version=version,
                    status=result.status.value,
                    passed_tests=result.pytest_results.passed if result.pytest_results else 0,
                    failed_tests=result.pytest_results.failed if result.pytest_results else 0,
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                )

                if result.status.value in ["PASSED", "PARTIAL"]:
                    matrix.compatible_versions.append(version)
                else:
                    matrix.incompatible_versions.append(version)
                    if result.error_message:
                        version_result.errors.append(result.error_message)

            except Exception as e:
                version_result = VersionTestResult(
                    version=version,
                    status="ERROR",
                    passed_tests=0,
                    failed_tests=0,
                    errors=[str(e)],
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                )
                matrix.incompatible_versions.append(version)

            matrix.results.append(version_result)

        self._matrices[arch_hash] = matrix
        self._save()

        return matrix

    def get_compatible_versions(self, arch_hash: str) -> list[str]:
        """Get list of compatible versions for an architecture.

        Args:
            arch_hash: Architecture hash

        Returns:
            List of compatible version strings
        """
        matrix = self._matrices.get(arch_hash)
        if matrix:
            return matrix.compatible_versions
        return []

    def get_version_matrix(self, arch_hash: str) -> MultiVersionMatrix | None:
        """Get the full version matrix for an architecture.

        Args:
            arch_hash: Architecture hash

        Returns:
            MultiVersionMatrix or None
        """
        return self._matrices.get(arch_hash)

    def get_summary_report(self) -> dict:
        """Get a summary report of version compatibility across all architectures.

        Returns:
            Dict with version compatibility statistics
        """
        version_stats: dict[str, dict] = {
            v: {"compatible": 0, "incompatible": 0} for v in self.versions
        }

        for matrix in self._matrices.values():
            for result in matrix.results:
                if result.version in version_stats:
                    if result.status in ["PASSED", "PARTIAL"]:
                        version_stats[result.version]["compatible"] += 1
                    else:
                        version_stats[result.version]["incompatible"] += 1

        total_archs = len(self._matrices)

        return {
            "total_architectures_tested": total_archs,
            "versions_tested": self.versions,
            "version_compatibility": {
                version: {
                    "compatible_count": stats["compatible"],
                    "incompatible_count": stats["incompatible"],
                    "compatibility_rate": (
                        stats["compatible"] / total_archs if total_archs > 0 else 0
                    ),
                }
                for version, stats in version_stats.items()
            },
            "most_compatible_version": max(
                self.versions,
                key=lambda v: version_stats[v]["compatible"],
            ) if total_archs > 0 else None,
        }


def check_version_available(version: str) -> bool:
    """Check if a LocalStack version is available.

    Args:
        version: Version string (e.g., "latest", "3.0.0")

    Returns:
        True if the image is available
    """
    try:
        client = docker.from_env()
        image_name = f"localstack/localstack:{version}"

        # Try to pull the image
        client.images.pull(image_name)
        return True
    except docker.errors.ImageNotFound:
        return False
    except Exception:
        return False


def get_available_versions(versions: list[str]) -> list[str]:
    """Filter list of versions to only those available.

    Args:
        versions: List of version strings to check

    Returns:
        List of available versions
    """
    available = []
    for version in versions:
        if check_version_available(version):
            available.append(version)
    return available


async def pull_versions_parallel(versions: list[str]) -> dict[str, bool]:
    """Pull multiple LocalStack versions in parallel.

    Args:
        versions: List of versions to pull

    Returns:
        Dict mapping version to success status
    """
    async def pull_one(version: str) -> tuple[str, bool]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, check_version_available, version)
        return version, result

    tasks = [pull_one(v) for v in versions]
    results = await asyncio.gather(*tasks)

    return dict(results)
