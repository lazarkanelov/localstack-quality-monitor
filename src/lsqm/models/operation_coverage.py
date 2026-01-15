"""Operation-level coverage tracking models."""

import re
from dataclasses import dataclass, field

# Test name to AWS operation mapping patterns
# Maps regex patterns for test names to AWS service:operation format
TEST_TO_OPERATION_PATTERNS: dict[str, str] = {
    # S3 operations
    r"test.*create.*bucket": "s3:CreateBucket",
    r"test.*delete.*bucket": "s3:DeleteBucket",
    r"test.*head.*bucket": "s3:HeadBucket",
    r"test.*list.*bucket": "s3:ListBuckets",
    r"test.*put.*object": "s3:PutObject",
    r"test.*get.*object": "s3:GetObject",
    r"test.*delete.*object": "s3:DeleteObject",
    r"test.*list.*objects?": "s3:ListObjects",
    r"test.*copy.*object": "s3:CopyObject",
    r"test.*upload": "s3:PutObject",
    r"test.*download": "s3:GetObject",
    # DynamoDB operations
    r"test.*create.*table": "dynamodb:CreateTable",
    r"test.*delete.*table": "dynamodb:DeleteTable",
    r"test.*describe.*table": "dynamodb:DescribeTable",
    r"test.*put.*item": "dynamodb:PutItem",
    r"test.*get.*item": "dynamodb:GetItem",
    r"test.*delete.*item": "dynamodb:DeleteItem",
    r"test.*update.*item": "dynamodb:UpdateItem",
    r"test.*query": "dynamodb:Query",
    r"test.*scan": "dynamodb:Scan",
    r"test.*batch.*write": "dynamodb:BatchWriteItem",
    r"test.*batch.*get": "dynamodb:BatchGetItem",
    # Lambda operations
    r"test.*invoke.*function|test.*lambda.*invoke|test.*invoke.*lambda": "lambda:Invoke",
    r"test.*create.*function": "lambda:CreateFunction",
    r"test.*delete.*function": "lambda:DeleteFunction",
    r"test.*update.*function": "lambda:UpdateFunctionCode",
    r"test.*list.*function": "lambda:ListFunctions",
    # SQS operations
    r"test.*create.*queue": "sqs:CreateQueue",
    r"test.*delete.*queue": "sqs:DeleteQueue",
    r"test.*send.*message": "sqs:SendMessage",
    r"test.*receive.*message": "sqs:ReceiveMessage",
    r"test.*delete.*message": "sqs:DeleteMessage",
    r"test.*get.*queue.*url": "sqs:GetQueueUrl",
    r"test.*purge.*queue": "sqs:PurgeQueue",
    # SNS operations
    r"test.*create.*topic": "sns:CreateTopic",
    r"test.*delete.*topic": "sns:DeleteTopic",
    r"test.*publish": "sns:Publish",
    r"test.*subscribe": "sns:Subscribe",
    r"test.*unsubscribe": "sns:Unsubscribe",
    r"test.*list.*topic": "sns:ListTopics",
    # API Gateway operations
    r"test.*create.*api": "apigateway:CreateRestApi",
    r"test.*delete.*api": "apigateway:DeleteRestApi",
    r"test.*create.*resource": "apigateway:CreateResource",
    r"test.*create.*method": "apigateway:PutMethod",
    r"test.*deploy.*api": "apigateway:CreateDeployment",
    # Step Functions operations
    r"test.*create.*state.*machine": "stepfunctions:CreateStateMachine",
    r"test.*delete.*state.*machine": "stepfunctions:DeleteStateMachine",
    r"test.*start.*execution": "stepfunctions:StartExecution",
    r"test.*describe.*execution": "stepfunctions:DescribeExecution",
    r"test.*stop.*execution": "stepfunctions:StopExecution",
    # EventBridge operations
    r"test.*put.*event": "events:PutEvents",
    r"test.*create.*event.*bus": "events:CreateEventBus",
    r"test.*put.*rule": "events:PutRule",
    r"test.*put.*target": "events:PutTargets",
    # Secrets Manager operations
    r"test.*create.*secret": "secretsmanager:CreateSecret",
    r"test.*get.*secret": "secretsmanager:GetSecretValue",
    r"test.*delete.*secret": "secretsmanager:DeleteSecret",
    r"test.*update.*secret": "secretsmanager:UpdateSecret",
    r"test.*rotate.*secret": "secretsmanager:RotateSecret",
    # SSM Parameter Store operations
    r"test.*put.*parameter": "ssm:PutParameter",
    r"test.*get.*parameter": "ssm:GetParameter",
    r"test.*delete.*parameter": "ssm:DeleteParameter",
    # KMS operations
    r"test.*create.*key": "kms:CreateKey",
    r"test.*encrypt": "kms:Encrypt",
    r"test.*decrypt": "kms:Decrypt",
    r"test.*generate.*data.*key": "kms:GenerateDataKey",
    # IAM operations
    r"test.*create.*role": "iam:CreateRole",
    r"test.*delete.*role": "iam:DeleteRole",
    r"test.*attach.*policy": "iam:AttachRolePolicy",
    r"test.*create.*user": "iam:CreateUser",
    # CloudWatch operations
    r"test.*put.*metric": "cloudwatch:PutMetricData",
    r"test.*get.*metric": "cloudwatch:GetMetricData",
    r"test.*create.*alarm": "cloudwatch:PutMetricAlarm",
    # Kinesis operations
    r"test.*create.*stream": "kinesis:CreateStream",
    r"test.*put.*record": "kinesis:PutRecord",
    r"test.*get.*record": "kinesis:GetRecords",
    # EC2/VPC operations
    r"test.*create.*vpc": "ec2:CreateVpc",
    r"test.*create.*subnet": "ec2:CreateSubnet",
    r"test.*create.*security.*group": "ec2:CreateSecurityGroup",
    r"test.*run.*instance": "ec2:RunInstances",
}


def map_test_to_operations(test_name: str) -> list[str]:
    """Map a test function name to AWS operations it likely exercises.

    Args:
        test_name: Name of the test function (e.g., "test_put_object_to_bucket")

    Returns:
        List of AWS operations in service:Operation format (e.g., ["s3:PutObject"])
    """
    operations = []
    test_lower = test_name.lower()

    for pattern, operation in TEST_TO_OPERATION_PATTERNS.items():
        if re.search(pattern, test_lower):
            if operation not in operations:
                operations.append(operation)

    return operations


def extract_service_from_operation(operation: str) -> str:
    """Extract service name from operation string.

    Args:
        operation: Operation in service:Operation format (e.g., "s3:PutObject")

    Returns:
        Service name (e.g., "s3")
    """
    if ":" in operation:
        return operation.split(":")[0]
    return operation


@dataclass
class OperationCoverage:
    """Aggregated coverage for an AWS operation across runs."""

    operation: str  # e.g., "s3:PutObject"
    service: str
    total_tested: int = 0
    passed: int = 0
    failed: int = 0
    last_tested_run: str | None = None
    failure_patterns: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage."""
        if self.total_tested == 0:
            return 0.0
        return (self.passed / self.total_tested) * 100

    def record_result(self, succeeded: bool, run_id: str, error_message: str | None = None) -> None:
        """Record a test result for this operation."""
        self.total_tested += 1
        if succeeded:
            self.passed += 1
        else:
            self.failed += 1
            if error_message and error_message not in self.failure_patterns:
                # Keep last 5 unique failure patterns
                self.failure_patterns.append(error_message[:200])
                if len(self.failure_patterns) > 5:
                    self.failure_patterns = self.failure_patterns[-5:]
        self.last_tested_run = run_id

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "operation": self.operation,
            "service": self.service,
            "total_tested": self.total_tested,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "last_tested_run": self.last_tested_run,
            "failure_patterns": self.failure_patterns,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OperationCoverage":
        """Deserialize from dictionary."""
        return cls(
            operation=data["operation"],
            service=data["service"],
            total_tested=data.get("total_tested", 0),
            passed=data.get("passed", 0),
            failed=data.get("failed", 0),
            last_tested_run=data.get("last_tested_run"),
            failure_patterns=data.get("failure_patterns", []),
        )


@dataclass
class ServiceCoverage:
    """Aggregated coverage for all operations of an AWS service."""

    service: str
    operations: dict[str, OperationCoverage] = field(default_factory=dict)

    @property
    def total_operations(self) -> int:
        """Total unique operations tested."""
        return len(self.operations)

    @property
    def pass_rate(self) -> float:
        """Overall pass rate for the service."""
        total = sum(op.total_tested for op in self.operations.values())
        passed = sum(op.passed for op in self.operations.values())
        if total == 0:
            return 0.0
        return (passed / total) * 100

    def get_or_create_operation(self, operation: str) -> OperationCoverage:
        """Get or create an OperationCoverage for the given operation."""
        if operation not in self.operations:
            self.operations[operation] = OperationCoverage(
                operation=operation,
                service=self.service,
            )
        return self.operations[operation]

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "service": self.service,
            "total_operations": self.total_operations,
            "pass_rate": self.pass_rate,
            "operations": {k: v.to_dict() for k, v in self.operations.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceCoverage":
        """Deserialize from dictionary."""
        ops = {k: OperationCoverage.from_dict(v) for k, v in data.get("operations", {}).items()}
        return cls(
            service=data["service"],
            operations=ops,
        )
