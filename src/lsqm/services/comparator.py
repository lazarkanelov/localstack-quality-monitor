"""Run comparison and regression detection."""

import logging
from datetime import datetime

from lsqm.models import Regression, ValidationStatus


def compare_runs(
    current_results: dict[str, dict],
    previous_results: dict[str, dict],
    current_run_id: str,
    previous_run_id: str,
    logger: logging.Logger | None = None,
) -> dict:
    """Compare two runs and detect regressions and fixes.

    Args:
        current_results: Current run results by arch_hash
        previous_results: Previous run results by arch_hash
        current_run_id: Current run ID
        previous_run_id: Previous run ID
        logger: Logger instance

    Returns:
        Dictionary with regressions and fixes lists
    """
    regressions: list[dict] = []
    fixes: list[dict] = []

    # Statuses considered "passing"
    passing = {ValidationStatus.PASSED.value, ValidationStatus.PARTIAL.value, "PASSED", "PARTIAL"}
    # Statuses considered "failing"
    failing = {
        ValidationStatus.FAILED.value,
        ValidationStatus.TIMEOUT.value,
        ValidationStatus.ERROR.value,
        "FAILED",
        "TIMEOUT",
        "ERROR",
    }

    # Find all architecture hashes present in both runs
    all_hashes = set(current_results.keys()) & set(previous_results.keys())

    for arch_hash in all_hashes:
        current = current_results[arch_hash]
        previous = previous_results[arch_hash]

        current_status = current.get("status", "UNKNOWN")
        previous_status = previous.get("status", "UNKNOWN")

        # Detect regression: was passing, now failing
        if previous_status in passing and current_status in failing:
            regression = {
                "arch_hash": arch_hash,
                "name": current.get("name", arch_hash[:8]),
                "from_run_id": previous_run_id,
                "to_run_id": current_run_id,
                "from_status": previous_status,
                "to_status": current_status,
                "detected_at": datetime.utcnow().isoformat(),
                "services_affected": current.get("services", []),
            }
            regressions.append(regression)

            if logger:
                logger.warning(
                    f"Regression detected: {arch_hash[:8]} {previous_status} -> {current_status}"
                )

        # Detect fix: was failing, now passing
        elif previous_status in failing and current_status in passing:
            fix = {
                "arch_hash": arch_hash,
                "name": current.get("name", arch_hash[:8]),
                "from_run_id": previous_run_id,
                "to_run_id": current_run_id,
                "from_status": previous_status,
                "to_status": current_status,
                "detected_at": datetime.utcnow().isoformat(),
            }
            fixes.append(fix)

            if logger:
                logger.info(f"Fix detected: {arch_hash[:8]} {previous_status} -> {current_status}")

    return {
        "regressions": regressions,
        "fixes": fixes,
        "regressions_count": len(regressions),
        "fixes_count": len(fixes),
    }


def create_regression_objects(
    comparison_result: dict,
    architecture_index: dict,
) -> list[Regression]:
    """Convert comparison results to Regression model objects.

    Args:
        comparison_result: Result from compare_runs
        architecture_index: Architecture index for service lookup

    Returns:
        List of Regression objects
    """
    regressions = []

    for reg_data in comparison_result.get("regressions", []):
        arch_hash = reg_data["arch_hash"]
        arch_info = architecture_index.get("architectures", {}).get(arch_hash, {})

        regression = Regression(
            arch_hash=arch_hash,
            architecture_name=arch_info.get("name"),
            from_run_id=reg_data["from_run_id"],
            to_run_id=reg_data["to_run_id"],
            from_status=ValidationStatus(reg_data["from_status"]),
            to_status=ValidationStatus(reg_data["to_status"]),
            detected_at=datetime.fromisoformat(reg_data["detected_at"]),
            services_affected=arch_info.get("services", []),
        )
        regressions.append(regression)

    return regressions
