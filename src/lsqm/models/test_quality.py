"""Test quality analysis models."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Boto3Call:
    """A detected boto3 API call in test code."""

    service: str  # e.g., "s3"
    operation: str  # e.g., "put_object"
    line_number: int
    in_function: str  # Name of function containing this call
    is_in_test: bool = True  # True if in test function, False if in fixture/helper

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "service": self.service,
            "operation": self.operation,
            "line_number": self.line_number,
            "in_function": self.in_function,
            "is_in_test": self.is_in_test,
            "operation_key": self.operation_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Boto3Call":
        """Deserialize from dictionary."""
        return cls(
            service=data["service"],
            operation=data["operation"],
            line_number=data.get("line_number", 0),
            in_function=data.get("in_function", ""),
            is_in_test=data.get("is_in_test", True),
        )

    @property
    def operation_key(self) -> str:
        """Return operation in service:Operation format."""
        # Convert snake_case to PascalCase for operation
        parts = self.operation.split("_")
        pascal_op = "".join(word.capitalize() for word in parts)
        return f"{self.service}:{pascal_op}"


@dataclass
class TestQualityIssue:
    """A quality issue found in test code."""

    test_name: str
    issue_type: Literal[
        "no_boto3_call",
        "unused_client",
        "name_mismatch",
        "empty_test",
        "missing_assertion",
        "hardcoded_resource",
        "missing_fixture",
    ]
    description: str
    severity: Literal["warning", "error"]
    line_number: int | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "test_name": self.test_name,
            "issue_type": self.issue_type,
            "description": self.description,
            "severity": self.severity,
            "line_number": self.line_number,
            "suggestion": self.suggestion,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestQualityIssue":
        """Deserialize from dictionary."""
        return cls(
            test_name=data["test_name"],
            issue_type=data["issue_type"],
            description=data["description"],
            severity=data.get("severity", "warning"),
            line_number=data.get("line_number"),
            suggestion=data.get("suggestion"),
        )


@dataclass
class CoverageComparison:
    """Comparison of inferred vs actual operation coverage."""

    inferred_operations: list[str] = field(default_factory=list)  # From test name heuristics
    actual_operations: list[str] = field(default_factory=list)  # From boto3 call tracking/analysis

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "inferred_operations": self.inferred_operations,
            "actual_operations": self.actual_operations,
            "matched": self.matched,
            "inferred_only": self.inferred_only,
            "actual_only": self.actual_only,
            "accuracy": self.accuracy,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoverageComparison":
        """Deserialize from dictionary."""
        return cls(
            inferred_operations=data.get("inferred_operations", []),
            actual_operations=data.get("actual_operations", []),
        )

    @property
    def matched(self) -> list[str]:
        """Operations in both inferred and actual."""
        inferred_set = set(self.inferred_operations)
        actual_set = set(self.actual_operations)
        return sorted(inferred_set & actual_set)

    @property
    def inferred_only(self) -> list[str]:
        """Operations inferred but not actually called."""
        inferred_set = set(self.inferred_operations)
        actual_set = set(self.actual_operations)
        return sorted(inferred_set - actual_set)

    @property
    def actual_only(self) -> list[str]:
        """Operations actually called but not inferred from name."""
        inferred_set = set(self.inferred_operations)
        actual_set = set(self.actual_operations)
        return sorted(actual_set - inferred_set)

    @property
    def accuracy(self) -> float:
        """Accuracy of inference: matched / total unique operations."""
        all_ops = set(self.inferred_operations) | set(self.actual_operations)
        if not all_ops:
            return 1.0
        return len(self.matched) / len(all_ops)


@dataclass
class TestFunctionAnalysis:
    """Analysis of a single test function."""

    name: str
    line_number: int
    boto3_calls: list[Boto3Call] = field(default_factory=list)
    has_assertions: bool = False
    fixture_dependencies: list[str] = field(default_factory=list)
    resource_references: list[str] = field(default_factory=list)  # Referenced resource names

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "line_number": self.line_number,
            "boto3_calls": [c.to_dict() for c in self.boto3_calls],
            "has_assertions": self.has_assertions,
            "fixture_dependencies": self.fixture_dependencies,
            "resource_references": self.resource_references,
            "call_count": len(self.boto3_calls),
            "operations": self.operations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestFunctionAnalysis":
        """Deserialize from dictionary."""
        return cls(
            name=data["name"],
            line_number=data.get("line_number", 0),
            boto3_calls=[Boto3Call.from_dict(c) for c in data.get("boto3_calls", [])],
            has_assertions=data.get("has_assertions", False),
            fixture_dependencies=data.get("fixture_dependencies", []),
            resource_references=data.get("resource_references", []),
        )

    @property
    def operations(self) -> list[str]:
        """List of unique operations called in this test."""
        return list({call.operation_key for call in self.boto3_calls})

    @property
    def has_boto3_calls(self) -> bool:
        """Check if test makes any boto3 calls."""
        return len(self.boto3_calls) > 0


@dataclass
class TestQualityAnalysis:
    """Quality analysis results for generated tests."""

    total_tests: int = 0
    tests_with_boto3_calls: int = 0
    tests_without_calls: int = 0
    total_boto3_calls: int = 0
    unique_operations: list[str] = field(default_factory=list)
    test_analyses: list[TestFunctionAnalysis] = field(default_factory=list)
    issues: list[TestQualityIssue] = field(default_factory=list)
    coverage_comparison: CoverageComparison = field(default_factory=CoverageComparison)
    client_variables: dict[str, str] = field(default_factory=dict)  # {var_name: service}
    unused_clients: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "total_tests": self.total_tests,
            "tests_with_boto3_calls": self.tests_with_boto3_calls,
            "tests_without_calls": self.tests_without_calls,
            "total_boto3_calls": self.total_boto3_calls,
            "unique_operations": self.unique_operations,
            "test_analyses": [t.to_dict() for t in self.test_analyses],
            "issues": [i.to_dict() for i in self.issues],
            "coverage_comparison": self.coverage_comparison.to_dict(),
            "client_variables": self.client_variables,
            "unused_clients": self.unused_clients,
            "quality_score": self.quality_score,
            "is_high_quality": self.is_high_quality,
            "issue_count_by_severity": self.issue_count_by_severity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestQualityAnalysis":
        """Deserialize from dictionary."""
        coverage_data = data.get("coverage_comparison", {})
        return cls(
            total_tests=data.get("total_tests", 0),
            tests_with_boto3_calls=data.get("tests_with_boto3_calls", 0),
            tests_without_calls=data.get("tests_without_calls", 0),
            total_boto3_calls=data.get("total_boto3_calls", 0),
            unique_operations=data.get("unique_operations", []),
            test_analyses=[
                TestFunctionAnalysis.from_dict(t) for t in data.get("test_analyses", [])
            ],
            issues=[TestQualityIssue.from_dict(i) for i in data.get("issues", [])],
            coverage_comparison=CoverageComparison.from_dict(coverage_data),
            client_variables=data.get("client_variables", {}),
            unused_clients=data.get("unused_clients", []),
        )

    @property
    def quality_score(self) -> float:
        """Calculate overall quality score from 0.0 to 1.0."""
        if self.total_tests == 0:
            return 0.0

        # Factors:
        # 1. Ratio of tests with boto3 calls (40%)
        # 2. No critical issues (30%)
        # 3. Coverage accuracy (20%)
        # 4. All clients used (10%)

        # Factor 1: Tests with calls
        call_ratio = self.tests_with_boto3_calls / self.total_tests
        call_score = call_ratio * 0.4

        # Factor 2: No critical issues
        error_count = sum(1 for i in self.issues if i.severity == "error")
        if error_count == 0:
            issue_score = 0.3
        elif error_count <= 2:
            issue_score = 0.15
        else:
            issue_score = 0.0

        # Factor 3: Coverage accuracy
        coverage_score = self.coverage_comparison.accuracy * 0.2

        # Factor 4: Client usage
        if not self.client_variables:
            usage_score = 0.1  # No clients to check
        elif not self.unused_clients:
            usage_score = 0.1
        else:
            unused_ratio = len(self.unused_clients) / len(self.client_variables)
            usage_score = (1 - unused_ratio) * 0.1

        return round(call_score + issue_score + coverage_score + usage_score, 3)

    @property
    def is_high_quality(self) -> bool:
        """Check if tests meet high quality threshold."""
        return self.quality_score >= 0.7

    @property
    def issue_count_by_severity(self) -> dict[str, int]:
        """Count issues by severity level."""
        counts = {"error": 0, "warning": 0}
        for issue in self.issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts

    def get_tests_without_calls(self) -> list[str]:
        """Get names of tests that don't make boto3 calls."""
        return [t.name for t in self.test_analyses if not t.has_boto3_calls]

    def add_issue(
        self,
        test_name: str,
        issue_type: str,
        description: str,
        severity: str = "warning",
        line_number: int | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Add a quality issue."""
        self.issues.append(
            TestQualityIssue(
                test_name=test_name,
                issue_type=issue_type,
                description=description,
                severity=severity,
                line_number=line_number,
                suggestion=suggestion,
            )
        )
