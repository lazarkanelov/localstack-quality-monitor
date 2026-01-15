"""Quality gates - enforce quality thresholds before deployment/release."""

import json
import logging
from pathlib import Path

from lsqm.models.qa_models import (
    QualityGateCheck,
    QualityGateConfig,
    QualityGateResult,
    QualityGateStatus,
)


class QualityGateEvaluator:
    """Evaluate quality gates based on validation results."""

    def __init__(
        self,
        config: QualityGateConfig | None = None,
        logger: logging.Logger | None = None,
    ):
        self.config = config or QualityGateConfig()
        self.logger = logger

    def evaluate(
        self,
        run_summary: dict,
        flaky_tests: list = None,
        regressions: list = None,
        test_quality_scores: dict[str, float] = None,
        resource_verification_rate: float = None,
        has_negative_tests: bool = False,
    ) -> QualityGateResult:
        """Evaluate all quality gates.

        Args:
            run_summary: Summary from validation run (total, passed, failed, etc.)
            flaky_tests: List of flaky test records
            regressions: List of regression records
            test_quality_scores: Dict of arch_hash -> quality score
            resource_verification_rate: Resource config verification pass rate
            has_negative_tests: Whether negative tests were included

        Returns:
            QualityGateResult with evaluation results
        """
        checks = []
        blocking_failures = []
        warnings = []

        # 1. Pass Rate Check
        total = run_summary.get("total", 0)
        passed = run_summary.get("passed", 0)
        pass_rate = passed / total if total > 0 else 0.0

        pass_rate_check = QualityGateCheck(
            name="Pass Rate",
            passed=pass_rate >= self.config.min_pass_rate,
            actual_value=f"{pass_rate:.1%}",
            threshold=f"{self.config.min_pass_rate:.1%}",
            message=f"Pass rate is {pass_rate:.1%} (minimum: {self.config.min_pass_rate:.1%})",
        )
        checks.append(pass_rate_check)

        if not pass_rate_check.passed:
            blocking_failures.append(pass_rate_check.message)

        # 2. Test Quality Score Check
        if test_quality_scores:
            avg_quality = sum(test_quality_scores.values()) / len(test_quality_scores)
            low_quality_count = sum(
                1 for score in test_quality_scores.values()
                if score < self.config.min_test_quality_score
            )

            quality_check = QualityGateCheck(
                name="Test Quality",
                passed=avg_quality >= self.config.min_test_quality_score,
                actual_value=f"{avg_quality:.2f}",
                threshold=f"{self.config.min_test_quality_score:.2f}",
                message=f"Average test quality: {avg_quality:.2f}, {low_quality_count} below threshold",
            )
            checks.append(quality_check)

            if not quality_check.passed:
                warnings.append(quality_check.message)

        # 3. Flaky Tests Check
        flaky_count = len(flaky_tests) if flaky_tests else 0

        flaky_check = QualityGateCheck(
            name="Flaky Tests",
            passed=flaky_count <= self.config.max_flaky_tests,
            actual_value=str(flaky_count),
            threshold=str(self.config.max_flaky_tests),
            message=f"{flaky_count} flaky tests detected (maximum: {self.config.max_flaky_tests})",
        )
        checks.append(flaky_check)

        if not flaky_check.passed:
            warnings.append(flaky_check.message)

        # 4. Regression Check
        if self.config.block_on_regression and regressions:
            regression_count = len(regressions)

            regression_check = QualityGateCheck(
                name="Regressions",
                passed=regression_count == 0,
                actual_value=str(regression_count),
                threshold="0",
                message=f"{regression_count} regressions detected",
            )
            checks.append(regression_check)

            if not regression_check.passed:
                blocking_failures.append(
                    f"Regressions detected: {[r.get('arch_hash', '')[:8] for r in regressions[:5]]}"
                )

        # 5. Resource Verification Check
        if resource_verification_rate is not None:
            verification_check = QualityGateCheck(
                name="Resource Verification",
                passed=resource_verification_rate >= self.config.min_resource_verification_rate,
                actual_value=f"{resource_verification_rate:.1%}",
                threshold=f"{self.config.min_resource_verification_rate:.1%}",
                message=f"Resource verification rate: {resource_verification_rate:.1%}",
            )
            checks.append(verification_check)

            if not verification_check.passed:
                warnings.append(verification_check.message)

        # 6. Negative Tests Check
        if self.config.require_negative_tests:
            negative_check = QualityGateCheck(
                name="Negative Tests",
                passed=has_negative_tests,
                actual_value="Yes" if has_negative_tests else "No",
                threshold="Required",
                message="Negative test cases " + ("included" if has_negative_tests else "missing"),
            )
            checks.append(negative_check)

            if not negative_check.passed:
                warnings.append("Negative test cases are required but not included")

        # Determine overall status
        if blocking_failures:
            status = QualityGateStatus.FAILED
        elif warnings:
            status = QualityGateStatus.WARNING
        else:
            status = QualityGateStatus.PASSED

        return QualityGateResult(
            status=status,
            checks=checks,
            blocking_failures=blocking_failures,
            warnings=warnings,
        )

    @classmethod
    def from_config_file(cls, config_path: Path, logger: logging.Logger | None = None):
        """Create evaluator from a config file.

        Args:
            config_path: Path to JSON config file
            logger: Optional logger

        Returns:
            QualityGateEvaluator instance
        """
        config = QualityGateConfig()

        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = json.load(f)
                config = QualityGateConfig.from_dict(data.get("quality_gates", {}))
            except Exception as e:
                if logger:
                    logger.warning(f"Failed to load quality gate config: {e}")

        return cls(config=config, logger=logger)


def create_quality_gate_report(result: QualityGateResult) -> str:
    """Create a human-readable quality gate report.

    Args:
        result: QualityGateResult to format

    Returns:
        Formatted report string
    """
    lines = []
    lines.append("=" * 60)
    lines.append(f"Quality Gate Status: {result.status.value}")
    lines.append("=" * 60)
    lines.append("")

    # Checks summary
    lines.append("Checks:")
    for check in result.checks:
        icon = "✓" if check.passed else "✗"
        lines.append(f"  {icon} {check.name}: {check.actual_value} (threshold: {check.threshold})")

    if result.blocking_failures:
        lines.append("")
        lines.append("BLOCKING FAILURES:")
        for failure in result.blocking_failures:
            lines.append(f"  ✗ {failure}")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  ⚠ {warning}")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def should_block_deployment(result: QualityGateResult) -> bool:
    """Check if deployment should be blocked based on quality gates.

    Args:
        result: QualityGateResult

    Returns:
        True if deployment should be blocked
    """
    return result.status == QualityGateStatus.FAILED
