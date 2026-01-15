"""Data models for LSQM."""

from lsqm.models.architecture import Architecture, SourceType
from lsqm.models.operation_coverage import (
    OperationCoverage,
    ServiceCoverage,
    map_test_to_operations,
)
from lsqm.models.preprocessing_delta import (
    PreprocessingDelta,
    RemovedResource,
    ServiceReconciliation,
    StubInfo,
)
from lsqm.models.regression import Regression
from lsqm.models.resource_inventory import ResourceInventory, TerraformResource
from lsqm.models.run import Run, RunConfig, RunSummary
from lsqm.models.service_trend import ServiceTrend, TrendHistoryEntry
from lsqm.models.test_app import TestApp
from lsqm.models.test_quality import (
    Boto3Call,
    CoverageComparison,
    TestFunctionAnalysis,
    TestQualityAnalysis,
    TestQualityIssue,
)
from lsqm.models.validation_result import (
    OperationResult,
    PytestResult,
    TerraformApplyResult,
    TestResult,
    ValidationResult,
    ValidationStatus,
)

__all__ = [
    # Architecture
    "Architecture",
    "SourceType",
    "TestApp",
    # Run
    "Run",
    "RunConfig",
    "RunSummary",
    # Validation
    "ValidationResult",
    "ValidationStatus",
    "TerraformApplyResult",
    "PytestResult",
    "TestResult",
    "OperationResult",
    # Coverage
    "OperationCoverage",
    "ServiceCoverage",
    "map_test_to_operations",
    # Trends & Regression
    "Regression",
    "ServiceTrend",
    "TrendHistoryEntry",
    # Preprocessing Delta (new)
    "PreprocessingDelta",
    "RemovedResource",
    "ServiceReconciliation",
    "StubInfo",
    # Resource Inventory (new)
    "ResourceInventory",
    "TerraformResource",
    # Test Quality (new)
    "Boto3Call",
    "CoverageComparison",
    "TestFunctionAnalysis",
    "TestQualityAnalysis",
    "TestQualityIssue",
]
