"""AST-based test analysis for detecting boto3 operations and quality issues."""

import ast
import re

from lsqm.models.operation_coverage import map_test_to_operations
from lsqm.models.test_quality import (
    Boto3Call,
    CoverageComparison,
    TestFunctionAnalysis,
    TestQualityAnalysis,
)


class Boto3CallVisitor(ast.NodeVisitor):
    """AST visitor to find boto3 client/resource method calls."""

    # Known boto3 client method names that correspond to AWS operations
    BOTO3_METHODS = {
        # S3
        "put_object",
        "get_object",
        "delete_object",
        "list_objects",
        "list_objects_v2",
        "create_bucket",
        "delete_bucket",
        "head_bucket",
        "head_object",
        "copy_object",
        "upload_file",
        "download_file",
        "upload_fileobj",
        "download_fileobj",
        # DynamoDB
        "put_item",
        "get_item",
        "delete_item",
        "update_item",
        "query",
        "scan",
        "create_table",
        "delete_table",
        "describe_table",
        "batch_write_item",
        "batch_get_item",
        "transact_write_items",
        "transact_get_items",
        # Lambda
        "invoke",
        "create_function",
        "delete_function",
        "update_function_code",
        "update_function_configuration",
        "list_functions",
        "get_function",
        # SQS
        "send_message",
        "receive_message",
        "delete_message",
        "create_queue",
        "delete_queue",
        "get_queue_url",
        "purge_queue",
        "send_message_batch",
        # SNS
        "publish",
        "subscribe",
        "unsubscribe",
        "create_topic",
        "delete_topic",
        "list_topics",
        "list_subscriptions",
        # API Gateway
        "create_rest_api",
        "delete_rest_api",
        "create_resource",
        "put_method",
        "create_deployment",
        "get_rest_apis",
        # Step Functions
        "create_state_machine",
        "delete_state_machine",
        "start_execution",
        "describe_execution",
        "stop_execution",
        "list_executions",
        # EventBridge
        "put_events",
        "put_rule",
        "put_targets",
        "create_event_bus",
        "delete_event_bus",
        # Secrets Manager
        "create_secret",
        "get_secret_value",
        "delete_secret",
        "update_secret",
        "rotate_secret",
        # SSM
        "put_parameter",
        "get_parameter",
        "get_parameters",
        "delete_parameter",
        # KMS
        "create_key",
        "encrypt",
        "decrypt",
        "generate_data_key",
        # IAM
        "create_role",
        "delete_role",
        "attach_role_policy",
        "create_user",
        "delete_user",
        "create_policy",
        # CloudWatch
        "put_metric_data",
        "get_metric_data",
        "put_metric_alarm",
        # Kinesis
        "create_stream",
        "delete_stream",
        "put_record",
        "put_records",
        "get_records",
        "get_shard_iterator",
        # EC2/VPC
        "create_vpc",
        "delete_vpc",
        "create_subnet",
        "delete_subnet",
        "create_security_group",
        "delete_security_group",
        "run_instances",
        "terminate_instances",
        "describe_instances",
    }

    # Service detection patterns for variable names
    SERVICE_PATTERNS = {
        "s3": r"s3|bucket",
        "dynamodb": r"dynamo|ddb|table",
        "lambda": r"lambda|function",
        "sqs": r"sqs|queue",
        "sns": r"sns|topic",
        "apigateway": r"api|gateway",
        "stepfunctions": r"sfn|step|state_machine",
        "events": r"events|eventbridge",
        "secretsmanager": r"secret",
        "ssm": r"ssm|parameter",
        "kms": r"kms|key",
        "iam": r"iam|role|policy",
        "cloudwatch": r"cloudwatch|cw|metric|alarm",
        "kinesis": r"kinesis|stream",
        "ec2": r"ec2|vpc|subnet|instance",
    }

    def __init__(self):
        self.client_vars: dict[str, str] = {}  # {var_name: service}
        self.boto3_calls: list[Boto3Call] = []
        self.current_function: str = ""
        self.current_line: int = 0
        self.is_in_test: bool = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track current function context."""
        old_function = self.current_function
        old_is_test = self.is_in_test

        self.current_function = node.name
        self.is_in_test = node.name.startswith("test_")

        self.generic_visit(node)

        self.current_function = old_function
        self.is_in_test = old_is_test

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track current async function context."""
        old_function = self.current_function
        old_is_test = self.is_in_test

        self.current_function = node.name
        self.is_in_test = node.name.startswith("test_")

        self.generic_visit(node)

        self.current_function = old_function
        self.is_in_test = old_is_test

    def visit_Assign(self, node: ast.Assign) -> None:
        """Detect boto3 client/resource assignments."""
        # Pattern: client = boto3.client('s3')
        # Pattern: s3_client = fixture_name
        if isinstance(node.value, ast.Call):
            self._check_boto3_client_call(node)

        self.generic_visit(node)

    def _check_boto3_client_call(self, node: ast.Assign) -> None:
        """Check if assignment is a boto3 client/resource creation."""
        call = node.value
        if not isinstance(call, ast.Call):
            return

        # Check for boto3.client('service') or boto3.resource('service')
        if isinstance(call.func, ast.Attribute):
            if isinstance(call.func.value, ast.Name):
                if call.func.value.id == "boto3" and call.func.attr in ("client", "resource"):
                    # Extract service name from first argument
                    if call.args and isinstance(call.args[0], ast.Constant):
                        service = call.args[0].value
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                self.client_vars[target.id] = service

    def visit_Call(self, node: ast.Call) -> None:
        """Detect boto3 API calls."""
        self.current_line = node.lineno

        # Pattern: client.put_object(...)
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr

            if method_name in self.BOTO3_METHODS:
                # Try to determine the service
                service = self._get_service_for_call(node)

                if service:
                    self.boto3_calls.append(
                        Boto3Call(
                            service=service,
                            operation=method_name,
                            line_number=node.lineno,
                            in_function=self.current_function,
                            is_in_test=self.is_in_test,
                        )
                    )

        self.generic_visit(node)

    def _get_service_for_call(self, node: ast.Call) -> str | None:
        """Determine the AWS service for a method call."""
        if not isinstance(node.func, ast.Attribute):
            return None

        # Check if calling on a known client variable
        if isinstance(node.func.value, ast.Name):
            var_name = node.func.value.id
            if var_name in self.client_vars:
                return self.client_vars[var_name]

            # Try to infer from variable name
            for service, pattern in self.SERVICE_PATTERNS.items():
                if re.search(pattern, var_name, re.IGNORECASE):
                    return service

        # Infer from method name
        method = node.func.attr
        return self._infer_service_from_method(method)

    def _infer_service_from_method(self, method: str) -> str | None:
        """Infer AWS service from method name."""
        method_to_service = {
            # S3
            "put_object": "s3",
            "get_object": "s3",
            "delete_object": "s3",
            "list_objects": "s3",
            "list_objects_v2": "s3",
            "create_bucket": "s3",
            "head_bucket": "s3",
            "upload_file": "s3",
            "download_file": "s3",
            # DynamoDB
            "put_item": "dynamodb",
            "get_item": "dynamodb",
            "delete_item": "dynamodb",
            "update_item": "dynamodb",
            "query": "dynamodb",
            "scan": "dynamodb",
            "batch_write_item": "dynamodb",
            # Lambda
            "invoke": "lambda",
            "create_function": "lambda",
            # SQS
            "send_message": "sqs",
            "receive_message": "sqs",
            "create_queue": "sqs",
            "get_queue_url": "sqs",
            # SNS
            "publish": "sns",
            "subscribe": "sns",
            "create_topic": "sns",
            # Step Functions
            "start_execution": "stepfunctions",
            "describe_execution": "stepfunctions",
            # EventBridge
            "put_events": "events",
            "put_rule": "events",
            # Secrets Manager
            "get_secret_value": "secretsmanager",
            "create_secret": "secretsmanager",
            # SSM
            "put_parameter": "ssm",
            "get_parameter": "ssm",
            # KMS
            "encrypt": "kms",
            "decrypt": "kms",
            # CloudWatch
            "put_metric_data": "cloudwatch",
        }
        return method_to_service.get(method)


class TestFunctionVisitor(ast.NodeVisitor):
    """AST visitor to analyze individual test functions."""

    def __init__(self):
        self.test_functions: list[TestFunctionAnalysis] = []
        self.fixtures_used: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Analyze test functions."""
        if node.name.startswith("test_"):
            analysis = self._analyze_test_function(node)
            self.test_functions.append(analysis)
        elif node.name.startswith("fixture") or self._has_fixture_decorator(node):
            # Track fixture definitions
            pass

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Analyze async test functions."""
        if node.name.startswith("test_"):
            analysis = self._analyze_test_function(node)
            self.test_functions.append(analysis)

        self.generic_visit(node)

    def _has_fixture_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if function has pytest.fixture decorator."""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "fixture":
                return True
            if isinstance(decorator, ast.Attribute) and decorator.attr == "fixture":
                return True
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "fixture":
                    return True
        return False

    def _analyze_test_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> TestFunctionAnalysis:
        """Analyze a single test function."""
        # Get fixture dependencies from function arguments
        fixtures = []
        for arg in node.args.args:
            if arg.arg not in ("self", "cls"):
                fixtures.append(arg.arg)

        # Find boto3 calls within this function
        call_visitor = Boto3CallVisitor()
        call_visitor.current_function = node.name
        call_visitor.is_in_test = True
        call_visitor.visit(node)

        # Check for assertions
        has_assertions = self._has_assertions(node)

        # Find resource references (string literals that look like resource names)
        resource_refs = self._find_resource_references(node)

        return TestFunctionAnalysis(
            name=node.name,
            line_number=node.lineno,
            boto3_calls=call_visitor.boto3_calls,
            has_assertions=has_assertions,
            fixture_dependencies=fixtures,
            resource_references=resource_refs,
        )

    def _has_assertions(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if function contains assertions."""
        for child in ast.walk(node):
            # assert statements
            if isinstance(child, ast.Assert):
                return True
            # pytest assertions (pytest.raises, etc.)
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr in ("raises", "warns", "approx"):
                        return True
                # assertEqual, assertTrue, etc.
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr.startswith("assert"):
                        return True
        return False

    def _find_resource_references(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """Find string literals that look like AWS resource names."""
        refs = []
        patterns = [
            r"^arn:aws:",  # ARN
            r"^[a-z]+-[a-z0-9-]+$",  # bucket-name, queue-name style
            r"^[A-Z][a-zA-Z0-9]+Table$",  # DynamoDB table name
        ]

        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                value = child.value
                for pattern in patterns:
                    if re.match(pattern, value):
                        refs.append(value)
                        break

        return refs


def analyze_test_file(code: str) -> dict:
    """Analyze a test file for boto3 operations and structure.

    Args:
        code: Python source code of the test file

    Returns:
        Dictionary with analysis results
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"error": "Syntax error in test file", "boto3_calls": [], "client_vars": {}}

    # Find all boto3 calls
    call_visitor = Boto3CallVisitor()
    call_visitor.visit(tree)

    # Analyze test functions
    test_visitor = TestFunctionVisitor()
    test_visitor.visit(tree)

    return {
        "client_vars": call_visitor.client_vars,
        "boto3_calls": [c.to_dict() for c in call_visitor.boto3_calls],
        "test_functions": [t.to_dict() for t in test_visitor.test_functions],
    }


def analyze_test_quality(
    test_code: str,
    conftest_code: str | None = None,
    terraform_resources: list[str] | None = None,
) -> TestQualityAnalysis:
    """Full quality analysis of test code.

    Checks:
    1. Each test function makes at least one boto3 call
    2. Client variables are used, not just created
    3. Resource names in tests match Terraform outputs
    4. Tests have assertions

    Args:
        test_code: Python source code of test_app.py
        conftest_code: Optional Python source code of conftest.py
        terraform_resources: Optional list of expected Terraform resource names

    Returns:
        TestQualityAnalysis with quality score and issues
    """
    analysis = TestQualityAnalysis()

    try:
        tree = ast.parse(test_code)
    except SyntaxError as e:
        analysis.add_issue(
            test_name="<module>",
            issue_type="empty_test",
            description=f"Syntax error in test file: {e}",
            severity="error",
        )
        return analysis

    # Analyze boto3 calls
    call_visitor = Boto3CallVisitor()
    call_visitor.visit(tree)

    # Analyze test functions
    test_visitor = TestFunctionVisitor()
    test_visitor.visit(tree)

    # Populate analysis
    analysis.test_analyses = test_visitor.test_functions
    analysis.total_tests = len(test_visitor.test_functions)
    analysis.client_variables = call_visitor.client_vars

    # Count tests with/without boto3 calls
    tests_with_calls = 0
    all_calls = []

    for test in test_visitor.test_functions:
        if test.has_boto3_calls:
            tests_with_calls += 1
            all_calls.extend(test.boto3_calls)
        else:
            # Issue: Test without boto3 calls
            analysis.add_issue(
                test_name=test.name,
                issue_type="no_boto3_call",
                description=f"Test '{test.name}' does not make any boto3 API calls",
                severity="warning",
                line_number=test.line_number,
                suggestion="Add boto3 operations to test actual AWS functionality",
            )

        # Check for assertions
        if not test.has_assertions:
            analysis.add_issue(
                test_name=test.name,
                issue_type="missing_assertion",
                description=f"Test '{test.name}' has no assertions",
                severity="warning",
                line_number=test.line_number,
                suggestion="Add assert statements to verify expected behavior",
            )

    analysis.tests_with_boto3_calls = tests_with_calls
    analysis.tests_without_calls = analysis.total_tests - tests_with_calls
    analysis.total_boto3_calls = len(all_calls)

    # Get unique operations
    analysis.unique_operations = list({call.operation_key for call in all_calls})

    # Check for unused clients
    used_clients = {call.in_function for call in all_calls}
    for var_name, service in call_visitor.client_vars.items():
        # This is a simplistic check - in reality we'd need more sophisticated analysis
        if var_name not in used_clients and service not in str(used_clients):
            analysis.unused_clients.append(var_name)
            analysis.add_issue(
                test_name="<module>",
                issue_type="unused_client",
                description=f"Client variable '{var_name}' ({service}) appears unused",
                severity="warning",
                suggestion=f"Use {var_name} to test {service} operations or remove it",
            )

    # Build coverage comparison
    inferred_ops = []
    for test in test_visitor.test_functions:
        inferred_ops.extend(map_test_to_operations(test.name))

    actual_ops = [call.operation_key for call in all_calls]

    analysis.coverage_comparison = CoverageComparison(
        inferred_operations=list(set(inferred_ops)),
        actual_operations=list(set(actual_ops)),
    )

    # Check for resource name mismatches if terraform resources provided
    if terraform_resources:
        for test in test_visitor.test_functions:
            for ref in test.resource_references:
                if ref not in terraform_resources and not ref.startswith("arn:aws:"):
                    analysis.add_issue(
                        test_name=test.name,
                        issue_type="name_mismatch",
                        description=f"Resource '{ref}' referenced but not in Terraform",
                        severity="warning",
                        suggestion="Verify resource name matches Terraform configuration",
                    )

    # Analyze conftest if provided
    if conftest_code:
        _analyze_conftest(conftest_code, analysis)

    return analysis


def _analyze_conftest(conftest_code: str, analysis: TestQualityAnalysis) -> None:
    """Analyze conftest.py for fixture quality."""
    try:
        tree = ast.parse(conftest_code)
    except SyntaxError:
        analysis.add_issue(
            test_name="conftest.py",
            issue_type="empty_test",
            description="Syntax error in conftest.py",
            severity="error",
        )
        return

    # Find fixture definitions
    fixtures_defined = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                is_fixture = False
                if isinstance(decorator, ast.Name) and decorator.id == "fixture":
                    is_fixture = True
                elif isinstance(decorator, ast.Attribute) and decorator.attr == "fixture":
                    is_fixture = True
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Attribute):
                        if decorator.func.attr == "fixture":
                            is_fixture = True
                    elif isinstance(decorator.func, ast.Name):
                        if decorator.func.id == "fixture":
                            is_fixture = True

                if is_fixture:
                    fixtures_defined.add(node.name)

    # Check if tests use fixtures that aren't defined
    for test in analysis.test_analyses:
        for fixture in test.fixture_dependencies:
            # Skip common pytest fixtures
            if fixture in ("request", "tmp_path", "capsys", "monkeypatch", "caplog"):
                continue
            if fixture not in fixtures_defined:
                analysis.add_issue(
                    test_name=test.name,
                    issue_type="missing_fixture",
                    description=f"Test uses fixture '{fixture}' not defined in conftest.py",
                    severity="warning",
                    suggestion=f"Define '{fixture}' fixture in conftest.py",
                )


def extract_terraform_resource_names(tf_content: str) -> list[str]:
    """Extract resource names from Terraform content.

    Args:
        tf_content: Terraform HCL content

    Returns:
        List of resource identifiers (bucket names, table names, etc.)
    """
    resources = []

    # Pattern for resource blocks with name attributes
    # resource "aws_s3_bucket" "my_bucket" { bucket = "actual-bucket-name" }
    patterns = [
        # Bucket names
        r'bucket\s*=\s*"([^"]+)"',
        # Table names
        r'name\s*=\s*"([^"]+)"',
        # Function names
        r'function_name\s*=\s*"([^"]+)"',
        # Queue names
        r'queue_name\s*=\s*"([^"]+)"',
        # Topic names
        r'topic_name\s*=\s*"([^"]+)"',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, tf_content)
        resources.extend(matches)

    # Also extract resource addresses
    resource_pattern = r'resource\s+"(aws_[^"]+)"\s+"([^"]+)"'
    for match in re.finditer(resource_pattern, tf_content):
        resource_type = match.group(1)
        resource_name = match.group(2)
        resources.append(f"{resource_type}.{resource_name}")

    return list(set(resources))


def filter_tests_for_removed_services(
    test_code: str,
    removed_services: set[str],
) -> tuple[str, list[str]]:
    """Add skip decorators to tests that depend on removed services.

    Args:
        test_code: Original test code
        removed_services: Set of service names that were removed during preprocessing

    Returns:
        Tuple of (modified_code, list_of_skipped_tests)
    """
    if not removed_services:
        return test_code, []

    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return test_code, []

    skipped_tests = []
    lines = test_code.split("\n")
    insertions = []  # (line_number, text_to_insert)

    # Analyze each test function
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test_"):
                continue

            # Check if test references removed services
            test_services = _detect_services_in_function(node)
            affected_services = test_services & removed_services

            if affected_services:
                skipped_tests.append(node.name)
                # Insert skip decorator before the function
                skip_reason = f"Services removed during preprocessing: {', '.join(sorted(affected_services))}"
                decorator = f'@pytest.mark.skip(reason="{skip_reason}")'
                insertions.append((node.lineno - 1, decorator))

    # Apply insertions in reverse order to preserve line numbers
    for line_num, text in sorted(insertions, reverse=True):
        # Find indentation of the function
        indent = len(lines[line_num]) - len(lines[line_num].lstrip())
        lines.insert(line_num, " " * indent + text)

    # Add pytest import if needed and we added skip decorators
    if insertions and "import pytest" not in test_code:
        lines.insert(0, "import pytest")

    return "\n".join(lines), skipped_tests


def _detect_services_in_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Detect which AWS services a test function uses."""
    services = set()

    # Service keywords to detect
    service_keywords = {
        "s3": ["s3", "bucket", "object"],
        "dynamodb": ["dynamodb", "dynamo", "table", "item"],
        "lambda": ["lambda", "function", "invoke"],
        "sqs": ["sqs", "queue", "message"],
        "sns": ["sns", "topic", "publish", "subscribe"],
        "apigateway": ["apigateway", "api", "gateway", "rest_api"],
        "stepfunctions": ["stepfunctions", "sfn", "state_machine", "execution"],
        "events": ["events", "eventbridge", "event_bus", "rule"],
        "secretsmanager": ["secretsmanager", "secret"],
        "ssm": ["ssm", "parameter"],
        "kms": ["kms", "key", "encrypt", "decrypt"],
        "cognito": ["cognito", "user_pool"],
        "rds": ["rds", "database", "db_instance"],
        "elasticache": ["elasticache", "redis", "memcached"],
    }

    # Convert function to string and search for keywords
    func_source = ast.dump(node).lower()

    for service, keywords in service_keywords.items():
        for keyword in keywords:
            if keyword in func_source:
                services.add(service)
                break

    return services
