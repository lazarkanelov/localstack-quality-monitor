"""Incremental validation - cache results and skip unchanged architectures."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from lsqm.models.qa_models import ValidationCache


class IncrementalValidator:
    """Cache validation results and enable incremental validation."""

    def __init__(
        self,
        artifacts_dir: Path,
        cache_ttl_hours: int = 24,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.logger = logger
        self.cache_file = artifacts_dir / "qa" / "validation_cache.json"
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, ValidationCache] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    data = json.load(f)
                for arch_hash, cache_data in data.items():
                    self._cache[arch_hash] = ValidationCache.from_dict(cache_data)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to load validation cache: {e}")

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            data = {arch_hash: cache.to_dict() for arch_hash, cache in self._cache.items()}
            with open(self.cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to save validation cache: {e}")

    def _compute_terraform_hash(self, arch_dir: Path) -> str:
        """Compute hash of Terraform files.

        Args:
            arch_dir: Directory containing Terraform files

        Returns:
            Hash string
        """
        hasher = hashlib.sha256()

        tf_files = sorted(arch_dir.glob("*.tf"))
        for tf_file in tf_files:
            content = tf_file.read_text()
            hasher.update(tf_file.name.encode())
            hasher.update(content.encode())

        tfvars_files = sorted(arch_dir.glob("*.tfvars"))
        for tfvars_file in tfvars_files:
            content = tfvars_file.read_text()
            hasher.update(tfvars_file.name.encode())
            hasher.update(content.encode())

        return hasher.hexdigest()[:16]

    def _compute_app_hash(self, app_dir: Path) -> str:
        """Compute hash of test app files.

        Args:
            app_dir: Directory containing test app files

        Returns:
            Hash string
        """
        hasher = hashlib.sha256()

        if not app_dir.exists():
            return "no_app"

        py_files = sorted(app_dir.glob("*.py"))
        for py_file in py_files:
            content = py_file.read_text()
            hasher.update(py_file.name.encode())
            hasher.update(content.encode())

        return hasher.hexdigest()[:16]

    def should_validate(
        self,
        arch_hash: str,
        force: bool = False,
        skip_passed: bool = True,
        skip_config_errors: bool = True,
    ) -> tuple[bool, str | None]:
        """Determine if an architecture should be validated.

        Args:
            arch_hash: Architecture hash
            force: Force validation regardless of cache
            skip_passed: Skip architectures that passed previously
            skip_config_errors: Skip architectures with known config errors

        Returns:
            Tuple of (should_validate, skip_reason or None)
        """
        if force:
            return True, None

        cache = self._cache.get(arch_hash)
        if not cache:
            return True, None  # No cache entry, must validate

        # Check if cache is expired
        age = datetime.utcnow() - cache.last_validated
        if age > self.cache_ttl:
            return True, None  # Cache expired

        # Check if files changed
        arch_dir = self.artifacts_dir / "architectures" / arch_hash
        app_dir = self.artifacts_dir / "apps" / arch_hash

        if arch_dir.exists():
            current_tf_hash = self._compute_terraform_hash(arch_dir)
            if current_tf_hash != cache.terraform_hash:
                return True, None  # Terraform files changed

        if app_dir.exists():
            current_app_hash = self._compute_app_hash(app_dir)
            if current_app_hash != cache.app_hash:
                return True, None  # Test app files changed

        # Check skip conditions
        if skip_passed and cache.last_status == "PASSED":
            return False, "Previously passed, unchanged"

        if skip_config_errors and cache.skip_reason:
            if "config" in cache.skip_reason.lower():
                return False, cache.skip_reason

        return True, None

    def update_cache(
        self,
        arch_hash: str,
        status: str,
        run_id: str,
        skip_reason: str | None = None,
    ) -> ValidationCache:
        """Update cache after validation.

        Args:
            arch_hash: Architecture hash
            status: Validation status
            run_id: Run ID
            skip_reason: Optional reason to skip future validations

        Returns:
            Updated ValidationCache
        """
        arch_dir = self.artifacts_dir / "architectures" / arch_hash
        app_dir = self.artifacts_dir / "apps" / arch_hash

        tf_hash = self._compute_terraform_hash(arch_dir) if arch_dir.exists() else ""
        app_hash = self._compute_app_hash(app_dir) if app_dir.exists() else ""

        cache = ValidationCache(
            arch_hash=arch_hash,
            terraform_hash=tf_hash,
            app_hash=app_hash,
            last_status=status,
            last_run_id=run_id,
            last_validated=datetime.utcnow(),
            skip_reason=skip_reason,
        )

        self._cache[arch_hash] = cache
        self._save()

        return cache

    def mark_as_config_error(self, arch_hash: str, error_message: str) -> None:
        """Mark an architecture as having a config error.

        Args:
            arch_hash: Architecture hash
            error_message: The error message
        """
        if arch_hash in self._cache:
            self._cache[arch_hash].skip_reason = f"Config error: {error_message[:100]}"
            self._save()

    def clear_cache(self, arch_hash: str | None = None) -> int:
        """Clear cache entries.

        Args:
            arch_hash: Specific architecture to clear, or None for all

        Returns:
            Number of entries cleared
        """
        if arch_hash:
            if arch_hash in self._cache:
                del self._cache[arch_hash]
                self._save()
                return 1
            return 0
        else:
            count = len(self._cache)
            self._cache.clear()
            self._save()
            return count

    def get_skip_summary(
        self,
        architectures: list[tuple[str, dict]],
    ) -> dict:
        """Get summary of what would be skipped.

        Args:
            architectures: List of (hash, data) tuples

        Returns:
            Dict with skip summary
        """
        will_validate = []
        will_skip = []
        skip_reasons = {}

        for arch_hash, _ in architectures:
            should_run, reason = self.should_validate(arch_hash)
            if should_run:
                will_validate.append(arch_hash)
            else:
                will_skip.append(arch_hash)
                skip_reasons[arch_hash] = reason

        return {
            "total": len(architectures),
            "will_validate": len(will_validate),
            "will_skip": len(will_skip),
            "skip_breakdown": {
                "unchanged_passed": sum(
                    1 for r in skip_reasons.values()
                    if r and "passed" in r.lower()
                ),
                "config_errors": sum(
                    1 for r in skip_reasons.values()
                    if r and "config" in r.lower()
                ),
                "other": sum(
                    1 for r in skip_reasons.values()
                    if r and "passed" not in r.lower() and "config" not in r.lower()
                ),
            },
            "architectures_to_validate": will_validate[:20],  # First 20
            "architectures_to_skip": will_skip[:20],  # First 20
        }

    def get_cached_result(self, arch_hash: str) -> dict | None:
        """Get cached validation result.

        Args:
            arch_hash: Architecture hash

        Returns:
            Cached result dict or None
        """
        cache = self._cache.get(arch_hash)
        if cache:
            return {
                "arch_hash": arch_hash,
                "status": cache.last_status,
                "run_id": cache.last_run_id,
                "validated_at": cache.last_validated.isoformat(),
                "cached": True,
            }
        return None


def filter_for_incremental_validation(
    architectures: list[tuple[str, dict]],
    artifacts_dir: Path,
    force: bool = False,
    logger: logging.Logger | None = None,
) -> tuple[list[tuple[str, dict]], list[dict]]:
    """Filter architectures for incremental validation.

    Args:
        architectures: List of (hash, data) tuples
        artifacts_dir: Artifacts directory
        force: Force full validation
        logger: Optional logger

    Returns:
        Tuple of (architectures to validate, cached results)
    """
    if force:
        return architectures, []

    validator = IncrementalValidator(artifacts_dir, logger=logger)

    to_validate = []
    cached_results = []

    for arch_hash, arch_data in architectures:
        should_run, reason = validator.should_validate(arch_hash)

        if should_run:
            to_validate.append((arch_hash, arch_data))
        else:
            cached = validator.get_cached_result(arch_hash)
            if cached:
                cached["skip_reason"] = reason
                cached_results.append(cached)
            if logger:
                logger.info(f"Skipping {arch_hash[:8]}: {reason}")

    if logger:
        logger.info(
            f"Incremental validation: {len(to_validate)} to run, "
            f"{len(cached_results)} cached"
        )

    return to_validate, cached_results
