"""Performance baselines - track and analyze performance metrics."""

import json
import logging
from pathlib import Path
from typing import Literal

from lsqm.models.qa_models import PerformanceBaseline


class PerformanceTracker:
    """Track performance baselines for validation operations."""

    def __init__(
        self,
        artifacts_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.logger = logger
        self.baselines_file = (
            artifacts_dir / "qa" / "performance_baselines.json" if artifacts_dir else None
        )
        if self.baselines_file:
            self.baselines_file.parent.mkdir(parents=True, exist_ok=True)
        self._baselines: dict[str, PerformanceBaseline] = {}
        self._load()

    def _load(self) -> None:
        """Load existing performance baselines."""
        if self.baselines_file and self.baselines_file.exists():
            try:
                with open(self.baselines_file) as f:
                    data = json.load(f)
                for key, baseline_data in data.items():
                    self._baselines[key] = PerformanceBaseline.from_dict(baseline_data)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to load performance baselines: {e}")

    def _save(self) -> None:
        """Save performance baselines."""
        if not self.baselines_file:
            return
        try:
            data = {key: baseline.to_dict() for key, baseline in self._baselines.items()}
            with open(self.baselines_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to save performance baselines: {e}")

    def _get_key(
        self,
        arch_hash: str,
        metric_type: Literal["terraform_init", "terraform_apply", "terraform_destroy",
                            "pytest", "total_validation"],
    ) -> str:
        """Get unique key for a baseline."""
        return f"{arch_hash}:{metric_type}"

    def record_metric(
        self,
        arch_hash: str,
        metric_type: Literal["terraform_init", "terraform_apply", "terraform_destroy",
                            "pytest", "total_validation"],
        duration: float,
    ) -> PerformanceBaseline:
        """Record a performance metric.

        Args:
            arch_hash: Architecture hash
            metric_type: Type of metric
            duration: Duration in seconds

        Returns:
            Updated PerformanceBaseline
        """
        key = self._get_key(arch_hash, metric_type)

        if key not in self._baselines:
            self._baselines[key] = PerformanceBaseline(
                arch_hash=arch_hash,
                metric_type=metric_type,
                baseline_duration=duration,
            )

        baseline = self._baselines[key]
        baseline.update(duration)

        self._save()
        return baseline

    def record_validation_metrics(
        self,
        arch_hash: str,
        terraform_init_duration: float | None = None,
        terraform_apply_duration: float | None = None,
        terraform_destroy_duration: float | None = None,
        pytest_duration: float | None = None,
        total_duration: float | None = None,
    ) -> list[PerformanceBaseline]:
        """Record all metrics from a validation run.

        Args:
            arch_hash: Architecture hash
            terraform_init_duration: Duration of terraform init
            terraform_apply_duration: Duration of terraform apply
            terraform_destroy_duration: Duration of terraform destroy
            pytest_duration: Duration of pytest
            total_duration: Total validation duration

        Returns:
            List of updated PerformanceBaseline
        """
        updated = []

        if terraform_init_duration is not None:
            updated.append(self.record_metric(arch_hash, "terraform_init", terraform_init_duration))

        if terraform_apply_duration is not None:
            updated.append(self.record_metric(arch_hash, "terraform_apply", terraform_apply_duration))

        if terraform_destroy_duration is not None:
            updated.append(self.record_metric(arch_hash, "terraform_destroy", terraform_destroy_duration))

        if pytest_duration is not None:
            updated.append(self.record_metric(arch_hash, "pytest", pytest_duration))

        if total_duration is not None:
            updated.append(self.record_metric(arch_hash, "total_validation", total_duration))

        return updated

    def get_baseline(
        self,
        arch_hash: str,
        metric_type: Literal["terraform_init", "terraform_apply", "terraform_destroy",
                            "pytest", "total_validation"],
    ) -> PerformanceBaseline | None:
        """Get baseline for a specific metric.

        Args:
            arch_hash: Architecture hash
            metric_type: Type of metric

        Returns:
            PerformanceBaseline or None
        """
        key = self._get_key(arch_hash, metric_type)
        return self._baselines.get(key)

    def is_regression(
        self,
        arch_hash: str,
        metric_type: Literal["terraform_init", "terraform_apply", "terraform_destroy",
                            "pytest", "total_validation"],
        current_duration: float,
        threshold_multiplier: float = 2.0,
    ) -> bool:
        """Check if current duration is a performance regression.

        Args:
            arch_hash: Architecture hash
            metric_type: Type of metric
            current_duration: Current duration in seconds
            threshold_multiplier: Multiplier for std deviation threshold

        Returns:
            True if this is a regression
        """
        baseline = self.get_baseline(arch_hash, metric_type)
        if not baseline or baseline.sample_count < 3:
            return False

        threshold = baseline.baseline_duration + (threshold_multiplier * baseline.std_deviation)
        return current_duration > threshold

    def get_slow_operations(
        self,
        threshold_percentile: float = 0.9,
    ) -> list[dict]:
        """Get operations that are slower than the threshold percentile.

        Args:
            threshold_percentile: Percentile threshold (e.g., 0.9 for 90th percentile)

        Returns:
            List of slow operations with details
        """
        slow_ops = []

        for baseline in self._baselines.values():
            if baseline.sample_count < 3:
                continue

            # Check if last duration is in the slow tail
            if baseline.last_duration > baseline.baseline_duration + baseline.std_deviation:
                slow_ops.append({
                    "arch_hash": baseline.arch_hash,
                    "metric_type": baseline.metric_type,
                    "last_duration": baseline.last_duration,
                    "baseline_duration": baseline.baseline_duration,
                    "deviation": baseline.last_duration - baseline.baseline_duration,
                    "trend": baseline.trend,
                })

        return sorted(slow_ops, key=lambda x: x["deviation"], reverse=True)

    def get_performance_report(self) -> dict:
        """Generate a performance report.

        Returns:
            Dict with performance statistics
        """
        by_metric: dict[str, list[PerformanceBaseline]] = {}
        for baseline in self._baselines.values():
            if baseline.metric_type not in by_metric:
                by_metric[baseline.metric_type] = []
            by_metric[baseline.metric_type].append(baseline)

        report = {
            "total_metrics_tracked": len(self._baselines),
            "unique_architectures": len(set(b.arch_hash for b in self._baselines.values())),
            "metrics_by_type": {},
            "degrading_operations": [],
            "improving_operations": [],
        }

        for metric_type, baselines in by_metric.items():
            valid_baselines = [b for b in baselines if b.sample_count >= 3]

            if valid_baselines:
                avg_duration = sum(b.baseline_duration for b in valid_baselines) / len(valid_baselines)
                min_duration = min(b.min_duration for b in valid_baselines)
                max_duration = max(b.max_duration for b in valid_baselines)

                report["metrics_by_type"][metric_type] = {
                    "count": len(valid_baselines),
                    "avg_duration_seconds": avg_duration,
                    "min_duration_seconds": min_duration,
                    "max_duration_seconds": max_duration,
                }

                # Find degrading/improving
                for b in valid_baselines:
                    if b.trend == "degrading":
                        report["degrading_operations"].append({
                            "arch_hash": b.arch_hash,
                            "metric_type": b.metric_type,
                            "baseline": b.baseline_duration,
                            "last": b.last_duration,
                            "increase_pct": ((b.last_duration - b.baseline_duration) / b.baseline_duration * 100)
                            if b.baseline_duration > 0 else 0,
                        })
                    elif b.trend == "improving":
                        report["improving_operations"].append({
                            "arch_hash": b.arch_hash,
                            "metric_type": b.metric_type,
                            "baseline": b.baseline_duration,
                            "last": b.last_duration,
                            "decrease_pct": ((b.baseline_duration - b.last_duration) / b.baseline_duration * 100)
                            if b.baseline_duration > 0 else 0,
                        })

        return report

    def get_estimated_duration(self, arch_hash: str) -> float | None:
        """Get estimated total validation duration based on history.

        Args:
            arch_hash: Architecture hash

        Returns:
            Estimated duration in seconds, or None if no data
        """
        baseline = self.get_baseline(arch_hash, "total_validation")
        if baseline and baseline.sample_count >= 2:
            return baseline.baseline_duration
        return None


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2m 30s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
