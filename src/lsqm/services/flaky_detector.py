"""Flaky test detection - track test stability over multiple runs."""

import json
import logging
from datetime import datetime
from pathlib import Path

from lsqm.models.qa_models import TestStabilityRecord
from lsqm.models.validation_result import TestResult


class FlakyTestDetector:
    """Detect and track flaky tests across runs."""

    def __init__(self, artifacts_dir: Path, logger: logging.Logger | None = None):
        self.artifacts_dir = artifacts_dir
        self.logger = logger
        self.stability_file = artifacts_dir / "qa" / "test_stability.json"
        self.stability_file.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, TestStabilityRecord] = {}
        self._load()

    def _load(self) -> None:
        """Load stability records from disk."""
        if self.stability_file.exists():
            try:
                with open(self.stability_file) as f:
                    data = json.load(f)
                for key, record_data in data.items():
                    self._records[key] = TestStabilityRecord.from_dict(record_data)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to load stability data: {e}")

    def _save(self) -> None:
        """Save stability records to disk."""
        try:
            data = {key: record.to_dict() for key, record in self._records.items()}
            with open(self.stability_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to save stability data: {e}")

    def _get_key(self, arch_hash: str, test_name: str) -> str:
        """Get unique key for a test."""
        return f"{arch_hash}:{test_name}"

    def record_test_results(
        self,
        arch_hash: str,
        test_results: list[TestResult],
    ) -> list[TestStabilityRecord]:
        """Record test results and update stability tracking.

        Args:
            arch_hash: Architecture hash
            test_results: List of test results from this run

        Returns:
            List of updated stability records
        """
        updated_records = []

        for test in test_results:
            key = self._get_key(arch_hash, test.test_name)

            if key not in self._records:
                self._records[key] = TestStabilityRecord(
                    test_name=test.test_name,
                    arch_hash=arch_hash,
                    first_seen=datetime.utcnow(),
                )

            record = self._records[key]
            record.update(test.status)
            updated_records.append(record)

        self._save()
        return updated_records

    def get_flaky_tests(self, arch_hash: str | None = None) -> list[TestStabilityRecord]:
        """Get all flaky tests, optionally filtered by architecture.

        Args:
            arch_hash: Optional architecture hash to filter by

        Returns:
            List of flaky test records
        """
        flaky = []
        for record in self._records.values():
            if record.is_flaky:
                if arch_hash is None or record.arch_hash == arch_hash:
                    flaky.append(record)
        return flaky

    def get_stability_report(self, arch_hash: str | None = None) -> dict:
        """Get a stability report.

        Args:
            arch_hash: Optional architecture hash to filter by

        Returns:
            Dict with stability statistics
        """
        records = list(self._records.values())
        if arch_hash:
            records = [r for r in records if r.arch_hash == arch_hash]

        total_tests = len(records)
        flaky_tests = [r for r in records if r.is_flaky]
        stable_tests = [r for r in records if not r.is_flaky and r.total_runs >= 3]

        # Calculate average pass rate
        avg_pass_rate = (
            sum(r.pass_rate for r in records) / len(records)
            if records else 0.0
        )

        return {
            "total_tests_tracked": total_tests,
            "flaky_tests_count": len(flaky_tests),
            "stable_tests_count": len(stable_tests),
            "average_pass_rate": avg_pass_rate,
            "flaky_tests": [
                {
                    "test_name": r.test_name,
                    "arch_hash": r.arch_hash,
                    "pass_rate": r.pass_rate,
                    "total_runs": r.total_runs,
                    "last_results": r.last_results[-5:],
                }
                for r in flaky_tests
            ],
            "most_unstable": sorted(
                [r for r in records if r.total_runs >= 3],
                key=lambda r: abs(r.pass_rate - 0.5),
            )[:10],  # Tests closest to 50% pass rate
        }

    def should_rerun_test(self, arch_hash: str, test_name: str) -> bool:
        """Check if a test should be re-run due to flakiness.

        Args:
            arch_hash: Architecture hash
            test_name: Test name

        Returns:
            True if test should be re-run
        """
        key = self._get_key(arch_hash, test_name)
        record = self._records.get(key)

        if record and record.is_flaky:
            return True

        return False

    def get_recommended_reruns(self, arch_hash: str) -> int:
        """Get recommended number of re-runs for an architecture.

        Based on the number of flaky tests, recommend how many times
        to run tests to get stable results.

        Args:
            arch_hash: Architecture hash

        Returns:
            Recommended number of test runs
        """
        flaky_count = len(self.get_flaky_tests(arch_hash))

        if flaky_count == 0:
            return 1  # No reruns needed
        elif flaky_count <= 2:
            return 2  # Run twice
        elif flaky_count <= 5:
            return 3  # Run three times
        else:
            return 5  # Run five times for heavily flaky suites


def run_tests_with_flaky_detection(
    arch_hash: str,
    run_pytest_func,  # Callable that runs pytest and returns PytestResult
    artifacts_dir: Path,
    max_runs: int = 3,
    logger: logging.Logger | None = None,
) -> tuple[list[TestResult], dict]:
    """Run tests multiple times if flakiness is detected.

    Args:
        arch_hash: Architecture hash
        run_pytest_func: Function to run pytest (returns PytestResult)
        artifacts_dir: Artifacts directory
        max_runs: Maximum number of runs
        logger: Optional logger

    Returns:
        Tuple of (consolidated test results, flaky detection info)
    """
    detector = FlakyTestDetector(artifacts_dir, logger)

    # Get recommended reruns based on history
    recommended_runs = detector.get_recommended_reruns(arch_hash)
    num_runs = min(recommended_runs, max_runs)

    all_results: dict[str, list[str]] = {}  # test_name -> list of statuses

    for run_num in range(num_runs):
        if logger:
            logger.info(f"Test run {run_num + 1}/{num_runs} for {arch_hash[:8]}")

        pytest_result = run_pytest_func()

        for test in pytest_result.individual_tests:
            if test.test_name not in all_results:
                all_results[test.test_name] = []
            all_results[test.test_name].append(test.status)

        # Record results for flaky detection
        detector.record_test_results(arch_hash, pytest_result.individual_tests)

        # If all tests passed, no need to rerun
        if pytest_result.failed == 0:
            break

    # Consolidate results - a test passes if it passed in majority of runs
    consolidated: list[TestResult] = []
    for test_name, statuses in all_results.items():
        passed_count = sum(1 for s in statuses if s == "passed")
        failed_count = len(statuses) - passed_count

        # Majority vote
        final_status = "passed" if passed_count > failed_count else "failed"

        # Note: flakiness = 0 < passed_count < len(statuses)
        # This is tracked by the FlakyTestDetector for future runs

        consolidated.append(
            TestResult(
                test_name=test_name,
                status=final_status,
                aws_operations=[],
            )
        )

    flaky_info = {
        "total_runs": num_runs,
        "tests_with_inconsistent_results": sum(
            1 for statuses in all_results.values()
            if len(set(statuses)) > 1
        ),
        "flaky_tests_detected": detector.get_flaky_tests(arch_hash),
    }

    return consolidated, flaky_info
