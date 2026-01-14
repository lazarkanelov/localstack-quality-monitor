"""Error message parity analysis for LocalStack vs AWS."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Known AWS error code patterns and their expected message structures
AWS_ERROR_PATTERNS: dict[str, dict] = {
    # S3 errors
    "NoSuchBucket": {
        "message_pattern": r"The specified bucket does not exist",
        "http_status": 404,
    },
    "NoSuchKey": {
        "message_pattern": r"The specified key does not exist",
        "http_status": 404,
    },
    "BucketAlreadyExists": {
        "message_pattern": r"The requested bucket name is not available",
        "http_status": 409,
    },
    "BucketAlreadyOwnedByYou": {
        "message_pattern": r"Your previous request to create the named bucket succeeded",
        "http_status": 409,
    },
    "AccessDenied": {
        "message_pattern": r"Access Denied",
        "http_status": 403,
    },
    # DynamoDB errors
    "ResourceNotFoundException": {
        "message_pattern": r"Requested resource not found|does not exist",
        "http_status": 400,
    },
    "ResourceInUseException": {
        "message_pattern": r"Resource .* is in use",
        "http_status": 400,
    },
    "ConditionalCheckFailedException": {
        "message_pattern": r"The conditional request failed",
        "http_status": 400,
    },
    "ValidationException": {
        "message_pattern": r".*",  # Generic validation
        "http_status": 400,
    },
    # Lambda errors
    "ResourceConflictException": {
        "message_pattern": r"The operation cannot be performed",
        "http_status": 409,
    },
    "InvalidParameterValueException": {
        "message_pattern": r".*",
        "http_status": 400,
    },
    "ServiceException": {
        "message_pattern": r"The service encountered an internal error",
        "http_status": 500,
    },
    # SQS errors
    "QueueDoesNotExist": {
        "message_pattern": r"The specified queue does not exist",
        "http_status": 400,
    },
    "QueueNameExists": {
        "message_pattern": r"A queue with this name already exists",
        "http_status": 400,
    },
    # SNS errors
    "NotFoundException": {
        "message_pattern": r"Topic does not exist|not found",
        "http_status": 404,
    },
    # IAM errors
    "EntityAlreadyExistsException": {
        "message_pattern": r".*already exists",
        "http_status": 409,
    },
    "NoSuchEntityException": {
        "message_pattern": r".*cannot be found|does not exist",
        "http_status": 404,
    },
    # Generic AWS errors
    "ThrottlingException": {
        "message_pattern": r"Rate exceeded|Too many requests",
        "http_status": 429,
    },
    "InternalError": {
        "message_pattern": r"An internal error occurred",
        "http_status": 500,
    },
}


@dataclass
class ParityResult:
    """Result of comparing LocalStack error to AWS expected format."""

    error_code: str
    localstack_message: str
    expected_pattern: str | None = None
    similarity_score: float = 0.0  # 0.0 to 1.0
    has_parity: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "error_code": self.error_code,
            "localstack_message": self.localstack_message,
            "expected_pattern": self.expected_pattern,
            "similarity_score": self.similarity_score,
            "has_parity": self.has_parity,
            "issues": self.issues,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParityResult":
        """Deserialize from dictionary."""
        return cls(
            error_code=data.get("error_code", ""),
            localstack_message=data.get("localstack_message", ""),
            expected_pattern=data.get("expected_pattern"),
            similarity_score=data.get("similarity_score", 0.0),
            has_parity=data.get("has_parity", True),
            issues=data.get("issues", []),
        )


def analyze_error_parity(
    error_code: str,
    localstack_message: str,
    aws_reference: str | None = None,
) -> ParityResult:
    """Analyze if LocalStack error message matches AWS expected format.

    Args:
        error_code: AWS error code (e.g., "NoSuchBucket")
        localstack_message: The error message from LocalStack
        aws_reference: Optional reference AWS error message for direct comparison

    Returns:
        ParityResult with similarity score and issues
    """
    issues: list[str] = []

    # Get expected pattern for this error code
    expected = AWS_ERROR_PATTERNS.get(error_code)
    expected_pattern = expected["message_pattern"] if expected else None

    # Calculate similarity
    if aws_reference:
        # Compare against actual AWS reference
        similarity = SequenceMatcher(
            None,
            localstack_message.lower(),
            aws_reference.lower()
        ).ratio()
    elif expected_pattern:
        # Check if message matches expected pattern
        if re.search(expected_pattern, localstack_message, re.IGNORECASE):
            similarity = 0.9  # High score if pattern matches
        else:
            similarity = 0.3  # Low score if pattern doesn't match
            issues.append(f"Message doesn't match expected pattern for {error_code}")
    else:
        similarity = 0.5  # Unknown pattern

    # Check for common parity issues
    issues.extend(_check_message_structure(error_code, localstack_message))

    has_parity = similarity >= 0.7 and len(issues) == 0

    return ParityResult(
        error_code=error_code,
        localstack_message=localstack_message[:500],  # Truncate for storage
        expected_pattern=expected_pattern,
        similarity_score=round(similarity, 3),
        has_parity=has_parity,
        issues=issues,
    )


def _check_message_structure(error_code: str, message: str) -> list[str]:
    """Check for structural issues in error message format.

    Args:
        error_code: The AWS error code
        message: The error message to check

    Returns:
        List of issues found
    """
    issues = []

    # Check for LocalStack-specific patterns that differ from AWS
    if "localstack" in message.lower():
        issues.append("Message contains 'localstack' - AWS errors should not reference implementation")

    if "not implemented" in message.lower():
        issues.append("Message contains 'not implemented' - indicates missing functionality")

    if "moto" in message.lower():
        issues.append("Message contains 'moto' - internal implementation leak")

    # Check for proper error code format in XML-style errors
    if "<Error>" in message and error_code not in message:
        issues.append(f"Error code '{error_code}' not found in XML error response")

    # Check for request ID (AWS always includes one)
    if "<Error>" in message and "RequestId" not in message:
        issues.append("Missing RequestId in XML error response")

    # Check for common AWS error message patterns
    if "Exception" in error_code and "exception" not in message.lower():
        # Many AWS exceptions include the exception type in the message
        pass  # This is informational, not a hard requirement

    return issues


def extract_error_details(error_output: str) -> dict:
    """Extract error code and message from various error formats.

    Supports:
    - botocore ClientError format
    - XML error format
    - JSON error format

    Args:
        error_output: Raw error output string

    Returns:
        Dictionary with error_code, error_message, operation, http_status
    """
    result: dict = {
        "error_code": None,
        "error_message": None,
        "operation": None,
        "http_status": None,
    }

    # Pattern 1: botocore ClientError format
    # "An error occurred (NoSuchBucket) when calling the GetObject operation: ..."
    client_error = re.search(
        r'An error occurred \((\w+)\) when calling the (\w+) operation: (.+?)(?:\n|$)',
        error_output
    )
    if client_error:
        result["error_code"] = client_error.group(1)
        result["operation"] = client_error.group(2)
        result["error_message"] = client_error.group(3).strip()
        return result

    # Pattern 2: XML error format
    xml_code = re.search(r'<Code>(\w+)</Code>', error_output)
    xml_message = re.search(r'<Message>([^<]+)</Message>', error_output)
    xml_status = re.search(r'<HTTPStatusCode>(\d+)</HTTPStatusCode>', error_output)
    if xml_code:
        result["error_code"] = xml_code.group(1)
    if xml_message:
        result["error_message"] = xml_message.group(1)
    if xml_status:
        result["http_status"] = int(xml_status.group(1))
    if result["error_code"]:
        return result

    # Pattern 3: JSON error format
    json_code = re.search(r'"(?:code|Code|errorCode|__type)"\s*:\s*"([^"]+)"', error_output)
    json_message = re.search(r'"(?:message|Message|errorMessage)"\s*:\s*"([^"]+)"', error_output)
    if json_code:
        # Handle AWS format where __type is "namespace#ErrorCode"
        code = json_code.group(1)
        if "#" in code:
            code = code.split("#")[-1]
        result["error_code"] = code
    if json_message:
        result["error_message"] = json_message.group(1)

    # Pattern 4: Terraform error format
    # "Error: creating Lambda Function: InvalidParameterValueException: The runtime..."
    tf_error = re.search(
        r'Error:\s*([^:]+):\s*(\w+(?:Exception|Error)):\s*(.+?)(?=\n|$)',
        error_output
    )
    if tf_error and not result["error_code"]:
        result["operation"] = tf_error.group(1).strip()
        result["error_code"] = tf_error.group(2)
        result["error_message"] = tf_error.group(3).strip()

    return result


def check_error_parity_from_output(
    terraform_output: str,
    container_logs: str = "",
) -> ParityResult | None:
    """Convenience function to check parity from raw outputs.

    Args:
        terraform_output: Terraform apply/plan output
        container_logs: Optional LocalStack container logs

    Returns:
        ParityResult if an error was found, None otherwise
    """
    combined = f"{terraform_output}\n{container_logs}"
    error_details = extract_error_details(combined)

    if not error_details["error_code"]:
        return None

    return analyze_error_parity(
        error_code=error_details["error_code"],
        localstack_message=error_details["error_message"] or "",
    )
