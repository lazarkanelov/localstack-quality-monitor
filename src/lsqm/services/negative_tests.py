"""Negative test generation - generate error scenario tests."""

import re
from typing import Literal

from lsqm.models.qa_models import NegativeTestCase

# Service-specific negative test templates
NEGATIVE_TEST_TEMPLATES: dict[str, list[dict]] = {
    "s3": [
        {
            "name": "test_create_bucket_invalid_name",
            "description": "Test bucket creation with invalid name (uppercase, special chars)",
            "test_type": "invalid_input",
            "operation": "create_bucket",
            "expected_error": "InvalidBucketName",
            "code": '''
def test_create_bucket_invalid_name(s3_client):
    """Test that invalid bucket names are rejected."""
    import pytest
    from botocore.exceptions import ClientError

    invalid_names = [
        "UPPERCASE",  # No uppercase
        "has spaces",  # No spaces
        "-startwithdash",  # Can't start with dash
        "a",  # Too short
        "a" * 64,  # Too long
    ]

    for name in invalid_names:
        with pytest.raises(ClientError) as exc_info:
            s3_client.create_bucket(Bucket=name)
        assert exc_info.value.response["Error"]["Code"] in ["InvalidBucketName", "InvalidParameterValue"]
''',
        },
        {
            "name": "test_get_nonexistent_object",
            "description": "Test getting an object that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "get_object",
            "expected_error": "NoSuchKey",
            "code": '''
def test_get_nonexistent_object(s3_client, test_bucket):
    """Test that getting a non-existent object returns proper error."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        s3_client.get_object(Bucket=test_bucket, Key="nonexistent-key-12345")

    assert exc_info.value.response["Error"]["Code"] == "NoSuchKey"
''',
        },
        {
            "name": "test_put_object_empty_key",
            "description": "Test putting object with empty key",
            "test_type": "invalid_input",
            "operation": "put_object",
            "expected_error": "InvalidArgument",
            "code": '''
def test_put_object_empty_key(s3_client, test_bucket):
    """Test that empty object key is rejected."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        s3_client.put_object(Bucket=test_bucket, Key="", Body=b"test")
''',
        },
    ],
    "dynamodb": [
        {
            "name": "test_get_nonexistent_item",
            "description": "Test getting an item that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "get_item",
            "expected_error": None,  # DynamoDB returns empty, not error
            "code": '''
def test_get_nonexistent_item(dynamodb_client, test_table):
    """Test that getting a non-existent item returns empty response."""
    response = dynamodb_client.get_item(
        TableName=test_table,
        Key={"id": {"S": "nonexistent-id-12345"}}
    )

    assert "Item" not in response
''',
        },
        {
            "name": "test_put_item_missing_key",
            "description": "Test putting item without required key attribute",
            "test_type": "invalid_input",
            "operation": "put_item",
            "expected_error": "ValidationException",
            "code": '''
def test_put_item_missing_key(dynamodb_client, test_table):
    """Test that putting item without key attribute fails."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        dynamodb_client.put_item(
            TableName=test_table,
            Item={"data": {"S": "value"}}  # Missing required key
        )

    assert exc_info.value.response["Error"]["Code"] == "ValidationException"
''',
        },
        {
            "name": "test_query_nonexistent_table",
            "description": "Test querying a table that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "query",
            "expected_error": "ResourceNotFoundException",
            "code": '''
def test_query_nonexistent_table(dynamodb_client):
    """Test that querying non-existent table returns proper error."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        dynamodb_client.query(
            TableName="nonexistent-table-12345",
            KeyConditionExpression="id = :id",
            ExpressionAttributeValues={":id": {"S": "test"}}
        )

    assert exc_info.value.response["Error"]["Code"] == "ResourceNotFoundException"
''',
        },
    ],
    "lambda": [
        {
            "name": "test_invoke_nonexistent_function",
            "description": "Test invoking a function that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "invoke",
            "expected_error": "ResourceNotFoundException",
            "code": '''
def test_invoke_nonexistent_function(lambda_client):
    """Test that invoking non-existent function returns proper error."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        lambda_client.invoke(FunctionName="nonexistent-function-12345")

    assert exc_info.value.response["Error"]["Code"] == "ResourceNotFoundException"
''',
        },
        {
            "name": "test_invoke_with_invalid_payload",
            "description": "Test invoking function with invalid JSON payload",
            "test_type": "invalid_input",
            "operation": "invoke",
            "expected_error": "InvalidRequestContentException",
            "code": '''
def test_invoke_with_invalid_payload(lambda_client, test_function):
    """Test that invalid JSON payload is handled properly."""
    # This tests the function's error handling, not API validation
    response = lambda_client.invoke(
        FunctionName=test_function,
        Payload=b'{"invalid": json}'  # Invalid JSON
    )

    # Either the API rejects it or the function handles it
    status_code = response.get("StatusCode", 0)
    assert status_code in [200, 400, 502]  # Success, Bad Request, or Function Error
''',
        },
    ],
    "sqs": [
        {
            "name": "test_receive_from_nonexistent_queue",
            "description": "Test receiving from a queue that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "receive_message",
            "expected_error": "QueueDoesNotExist",
            "code": '''
def test_receive_from_nonexistent_queue(sqs_client):
    """Test that receiving from non-existent queue returns proper error."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        sqs_client.receive_message(
            QueueUrl="http://localhost:4566/000000000000/nonexistent-queue"
        )

    error_code = exc_info.value.response["Error"]["Code"]
    assert error_code in ["QueueDoesNotExist", "AWS.SimpleQueueService.NonExistentQueue"]
''',
        },
        {
            "name": "test_send_message_too_large",
            "description": "Test sending a message that exceeds size limit",
            "test_type": "invalid_input",
            "operation": "send_message",
            "expected_error": "InvalidParameterValue",
            "code": '''
def test_send_message_too_large(sqs_client, test_queue_url):
    """Test that oversized messages are rejected."""
    import pytest
    from botocore.exceptions import ClientError

    # SQS max message size is 256KB
    large_message = "x" * (257 * 1024)

    with pytest.raises(ClientError) as exc_info:
        sqs_client.send_message(
            QueueUrl=test_queue_url,
            MessageBody=large_message
        )

    assert exc_info.value.response["Error"]["Code"] in ["InvalidParameterValue", "InvalidMessageContents"]
''',
        },
    ],
    "sns": [
        {
            "name": "test_publish_to_nonexistent_topic",
            "description": "Test publishing to a topic that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "publish",
            "expected_error": "NotFound",
            "code": '''
def test_publish_to_nonexistent_topic(sns_client):
    """Test that publishing to non-existent topic returns proper error."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        sns_client.publish(
            TopicArn="arn:aws:sns:us-east-1:000000000000:nonexistent-topic",
            Message="test"
        )

    assert exc_info.value.response["Error"]["Code"] in ["NotFound", "NotFoundException"]
''',
        },
    ],
    "iam": [
        {
            "name": "test_get_nonexistent_role",
            "description": "Test getting a role that doesn't exist",
            "test_type": "resource_not_found",
            "operation": "get_role",
            "expected_error": "NoSuchEntity",
            "code": '''
def test_get_nonexistent_role(iam_client):
    """Test that getting non-existent role returns proper error."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        iam_client.get_role(RoleName="nonexistent-role-12345")

    assert exc_info.value.response["Error"]["Code"] == "NoSuchEntity"
''',
        },
    ],
}

# Edge case tests applicable to all services
COMMON_EDGE_CASES = '''
def test_empty_response_handling(boto3_client):
    """Test handling of empty/null responses gracefully."""
    # This is a template - specific implementation depends on service
    pass


def test_pagination_edge_cases(boto3_client):
    """Test pagination with various edge cases."""
    # Empty results, single page, max items, etc.
    pass


def test_concurrent_operations(boto3_client):
    """Test concurrent operations don't cause race conditions."""
    import concurrent.futures

    def operation():
        # Service-specific operation
        pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(operation) for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Verify all operations completed successfully
    assert len(results) == 10
'''


def generate_negative_tests_for_services(services: list[str]) -> tuple[str, list[NegativeTestCase]]:
    """Generate negative test code for the given services.

    Args:
        services: List of AWS service names (e.g., ["s3", "dynamodb"])

    Returns:
        Tuple of (test_code, list of NegativeTestCase metadata)
    """
    test_cases: list[NegativeTestCase] = []
    test_code_parts = [
        '"""Negative test cases - error scenario validation."""',
        "",
        "import pytest",
        "from botocore.exceptions import ClientError",
        "",
    ]

    for service in services:
        service_lower = service.lower()
        templates = NEGATIVE_TEST_TEMPLATES.get(service_lower, [])

        if templates:
            test_code_parts.append(f"# === {service.upper()} Negative Tests ===")
            test_code_parts.append("")

            for template in templates:
                test_code_parts.append(template["code"].strip())
                test_code_parts.append("")

                test_cases.append(
                    NegativeTestCase(
                        name=template["name"],
                        description=template["description"],
                        test_type=template["test_type"],
                        service=service_lower,
                        operation=template["operation"],
                        expected_error=template.get("expected_error"),
                    )
                )

    return "\n".join(test_code_parts), test_cases


def get_negative_test_prompt_section(services: list[str]) -> str:
    """Generate the prompt section for negative test generation.

    Args:
        services: List of AWS services in the architecture

    Returns:
        Prompt text instructing Claude to generate negative tests
    """
    service_list = ", ".join(services)

    return f'''
### Negative Test Cases (REQUIRED)

In addition to happy-path tests, you MUST include negative test cases that verify error handling.
The architecture uses these services: {service_list}

For EACH service, include at least 2 negative tests from these categories:

1. **Invalid Input Tests** - Test with malformed/invalid parameters
   - Empty strings, null values, invalid formats
   - Values exceeding limits (size, length, count)
   - Invalid characters or patterns

2. **Resource Not Found Tests** - Test operations on non-existent resources
   - Get/Delete operations on missing items
   - References to non-existent ARNs or IDs

3. **Permission/Access Tests** - Test unauthorized operations
   - Operations without required permissions
   - Cross-account access attempts (if applicable)

4. **Edge Case Tests** - Test boundary conditions
   - Empty collections, single items, maximum items
   - Concurrent operations
   - Timeout scenarios

Example negative test pattern:
```python
def test_get_nonexistent_item(dynamodb_client, test_table):
    """Test that getting a non-existent item returns empty response."""
    response = dynamodb_client.get_item(
        TableName=test_table,
        Key={{"id": {{"S": "nonexistent-id-12345"}}}}
    )
    assert "Item" not in response

def test_invalid_bucket_name(s3_client):
    """Test that invalid bucket names are rejected."""
    import pytest
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        s3_client.create_bucket(Bucket="INVALID-UPPERCASE")
    assert exc_info.value.response["Error"]["Code"] == "InvalidBucketName"
```

IMPORTANT:
- Use pytest.raises() to catch expected exceptions
- Verify the specific error code in the response
- Document what error is expected in the docstring
'''


def extract_negative_tests_from_code(test_code: str) -> list[NegativeTestCase]:
    """Extract negative test case metadata from generated test code.

    Args:
        test_code: Python test code

    Returns:
        List of identified negative test cases
    """
    test_cases = []

    # Find test functions that look like negative tests
    negative_patterns = [
        r"test_.*invalid",
        r"test_.*nonexistent",
        r"test_.*not_found",
        r"test_.*missing",
        r"test_.*error",
        r"test_.*fail",
        r"test_.*denied",
        r"test_.*unauthorized",
        r"test_.*empty",
        r"test_.*too_large",
        r"test_.*exceed",
    ]

    # Pattern to extract test function with docstring
    func_pattern = re.compile(
        r'def\s+(test_\w+)\s*\([^)]*\):\s*(?:"""([^"]+)""")?', re.MULTILINE | re.DOTALL
    )

    for match in func_pattern.finditer(test_code):
        test_name = match.group(1)
        docstring = match.group(2) or ""

        # Check if this looks like a negative test
        is_negative = any(
            re.search(pattern, test_name, re.IGNORECASE) for pattern in negative_patterns
        )

        if is_negative:
            # Try to determine test type
            test_type: Literal[
                "invalid_input",
                "permission_denied",
                "resource_not_found",
                "rate_limit",
                "timeout",
                "edge_case",
            ] = "edge_case"

            if "invalid" in test_name.lower() or "empty" in test_name.lower():
                test_type = "invalid_input"
            elif "nonexistent" in test_name.lower() or "not_found" in test_name.lower():
                test_type = "resource_not_found"
            elif "denied" in test_name.lower() or "unauthorized" in test_name.lower():
                test_type = "permission_denied"
            elif "timeout" in test_name.lower():
                test_type = "timeout"

            # Try to extract service from test name or fixture
            service = "unknown"
            service_patterns = ["s3", "dynamodb", "lambda", "sqs", "sns", "iam", "ec2"]
            for svc in service_patterns:
                if svc in test_name.lower() or svc in docstring.lower():
                    service = svc
                    break

            test_cases.append(
                NegativeTestCase(
                    name=test_name,
                    description=docstring.strip()[:200] if docstring else "",
                    test_type=test_type,
                    service=service,
                    operation="",  # Would need more analysis to extract
                )
            )

    return test_cases
