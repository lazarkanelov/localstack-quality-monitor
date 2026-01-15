"""Response schema validation using botocore service models."""

import logging
from dataclasses import dataclass, field
from typing import Any

try:
    import botocore.session

    BOTOCORE_AVAILABLE = True
except ImportError:
    BOTOCORE_AVAILABLE = False


logger = logging.getLogger(__name__)


@dataclass
class SchemaViolation:
    """Single schema violation in an AWS response."""

    operation: str
    service: str
    violation_type: str  # "missing_field", "wrong_type", "extra_field", "invalid_enum"
    field_path: str  # e.g., "Bucket.Name" or "Items[0].Id"
    expected: str | None = None
    actual: str | None = None
    message: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "operation": self.operation,
            "service": self.service,
            "violation_type": self.violation_type,
            "field_path": self.field_path,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaViolation":
        """Deserialize from dictionary."""
        return cls(
            operation=data.get("operation", ""),
            service=data.get("service", ""),
            violation_type=data.get("violation_type", ""),
            field_path=data.get("field_path", ""),
            expected=data.get("expected"),
            actual=data.get("actual"),
            message=data.get("message", ""),
        )


@dataclass
class SchemaValidationResult:
    """Result of validating a response against AWS schema."""

    service: str
    operation: str
    is_valid: bool = True
    violations: list[SchemaViolation] = field(default_factory=list)
    checked_fields: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "service": self.service,
            "operation": self.operation,
            "is_valid": self.is_valid,
            "violations": [v.to_dict() for v in self.violations],
            "checked_fields": self.checked_fields,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaValidationResult":
        """Deserialize from dictionary."""
        return cls(
            service=data.get("service", ""),
            operation=data.get("operation", ""),
            is_valid=data.get("is_valid", True),
            violations=[SchemaViolation.from_dict(v) for v in data.get("violations", [])],
            checked_fields=data.get("checked_fields", 0),
            error=data.get("error"),
        )


class BotocoreSchemaValidator:
    """Validates AWS responses against botocore service model schemas."""

    def __init__(self) -> None:
        """Initialize the validator with botocore session."""
        if not BOTOCORE_AVAILABLE:
            raise ImportError("botocore is required for schema validation")
        self._session = botocore.session.get_session()
        self._service_models: dict[str, Any] = {}

    def _get_service_model(self, service_name: str) -> Any | None:
        """Load and cache botocore service model.

        Args:
            service_name: AWS service name (e.g., "s3", "dynamodb")

        Returns:
            ServiceModel object or None if not found
        """
        if service_name in self._service_models:
            return self._service_models[service_name]

        try:
            # Normalize service name
            normalized = service_name.lower().replace("-", "")

            # Load service model via session
            model = self._session.get_service_model(normalized)
            self._service_models[service_name] = model
            return model
        except Exception as e:
            logger.warning(f"Could not load service model for {service_name}: {e}")
            return None

    def validate_response(
        self,
        service: str,
        operation: str,
        response: dict,
    ) -> SchemaValidationResult:
        """Validate an AWS response against the expected schema.

        Args:
            service: AWS service name (e.g., "s3", "lambda")
            operation: Operation name (e.g., "GetObject", "CreateFunction")
            response: The response dict to validate

        Returns:
            SchemaValidationResult with violations if any
        """
        result = SchemaValidationResult(service=service, operation=operation)

        # Load service model
        service_model = self._get_service_model(service)
        if not service_model:
            result.error = f"Could not load service model for {service}"
            return result

        # Get operation model
        try:
            op_model = service_model.operation_model(operation)
        except Exception as e:
            result.error = f"Could not find operation {operation}: {e}"
            return result

        # Get output shape
        output_shape = op_model.output_shape
        if not output_shape:
            # Operation has no output (void)
            return result

        # Validate response against shape
        violations = self._validate_shape(
            value=response,
            shape=output_shape,
            path="",
            service=service,
            operation=operation,
        )

        result.violations = violations
        result.is_valid = len(violations) == 0
        result.checked_fields = self._count_shape_members(output_shape)

        return result

    def _validate_shape(
        self,
        value: Any,
        shape: Any,
        path: str,
        service: str,
        operation: str,
    ) -> list[SchemaViolation]:
        """Recursively validate a value against its shape.

        Args:
            value: The value to validate
            shape: The botocore Shape object
            path: Current field path for error messages
            service: Service name for violations
            operation: Operation name for violations

        Returns:
            List of schema violations found
        """
        violations: list[SchemaViolation] = []

        # Handle None values
        if value is None:
            return violations

        shape_type = shape.type_name

        # Type-specific validation
        if shape_type == "structure":
            violations.extend(self._validate_structure(value, shape, path, service, operation))
        elif shape_type == "list":
            violations.extend(self._validate_list(value, shape, path, service, operation))
        elif shape_type == "map":
            violations.extend(self._validate_map(value, shape, path, service, operation))
        elif shape_type == "string":
            if not isinstance(value, str):
                violations.append(
                    SchemaViolation(
                        operation=operation,
                        service=service,
                        violation_type="wrong_type",
                        field_path=path or "(root)",
                        expected="string",
                        actual=type(value).__name__,
                        message=f"Expected string, got {type(value).__name__}",
                    )
                )
            # Check enum values if present
            elif hasattr(shape, "enum") and shape.enum and value not in shape.enum:
                violations.append(
                    SchemaViolation(
                        operation=operation,
                        service=service,
                        violation_type="invalid_enum",
                        field_path=path or "(root)",
                        expected=str(shape.enum),
                        actual=value,
                        message=f"Value '{value}' not in allowed enum values",
                    )
                )
        elif shape_type in ("integer", "long"):
            if not isinstance(value, int) or isinstance(value, bool):
                violations.append(
                    SchemaViolation(
                        operation=operation,
                        service=service,
                        violation_type="wrong_type",
                        field_path=path or "(root)",
                        expected="integer",
                        actual=type(value).__name__,
                        message=f"Expected integer, got {type(value).__name__}",
                    )
                )
        elif shape_type in ("double", "float"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                violations.append(
                    SchemaViolation(
                        operation=operation,
                        service=service,
                        violation_type="wrong_type",
                        field_path=path or "(root)",
                        expected="number",
                        actual=type(value).__name__,
                        message=f"Expected number, got {type(value).__name__}",
                    )
                )
        elif shape_type == "boolean":
            if not isinstance(value, bool):
                violations.append(
                    SchemaViolation(
                        operation=operation,
                        service=service,
                        violation_type="wrong_type",
                        field_path=path or "(root)",
                        expected="boolean",
                        actual=type(value).__name__,
                        message=f"Expected boolean, got {type(value).__name__}",
                    )
                )
        # timestamp, blob types are flexible - skip validation

        return violations

    def _validate_structure(
        self,
        value: Any,
        shape: Any,
        path: str,
        service: str,
        operation: str,
    ) -> list[SchemaViolation]:
        """Validate a structure (object) value."""
        violations: list[SchemaViolation] = []

        if not isinstance(value, dict):
            violations.append(
                SchemaViolation(
                    operation=operation,
                    service=service,
                    violation_type="wrong_type",
                    field_path=path or "(root)",
                    expected="object",
                    actual=type(value).__name__,
                    message=f"Expected object, got {type(value).__name__}",
                )
            )
            return violations

        members = shape.members if hasattr(shape, "members") else {}
        required = shape.required_members if hasattr(shape, "required_members") else []

        # Check required fields
        for req_field in required:
            if req_field not in value:
                field_path = f"{path}.{req_field}" if path else req_field
                violations.append(
                    SchemaViolation(
                        operation=operation,
                        service=service,
                        violation_type="missing_field",
                        field_path=field_path,
                        expected="required field",
                        actual="missing",
                        message=f"Required field '{req_field}' is missing",
                    )
                )

        # Validate each field
        for field_name, field_value in value.items():
            field_path = f"{path}.{field_name}" if path else field_name

            if field_name in members:
                member_shape = members[field_name]
                violations.extend(
                    self._validate_shape(field_value, member_shape, field_path, service, operation)
                )
            # Note: We don't flag extra fields as violations since AWS may add new fields

        return violations

    def _validate_list(
        self,
        value: Any,
        shape: Any,
        path: str,
        service: str,
        operation: str,
    ) -> list[SchemaViolation]:
        """Validate a list value."""
        violations: list[SchemaViolation] = []

        if not isinstance(value, list):
            violations.append(
                SchemaViolation(
                    operation=operation,
                    service=service,
                    violation_type="wrong_type",
                    field_path=path or "(root)",
                    expected="list",
                    actual=type(value).__name__,
                    message=f"Expected list, got {type(value).__name__}",
                )
            )
            return violations

        # Get member shape
        member_shape = shape.member if hasattr(shape, "member") else None
        if not member_shape:
            return violations

        # Validate first few items (avoid excessive validation)
        for i, item in enumerate(value[:10]):
            item_path = f"{path}[{i}]"
            violations.extend(
                self._validate_shape(item, member_shape, item_path, service, operation)
            )

        return violations

    def _validate_map(
        self,
        value: Any,
        shape: Any,
        path: str,
        service: str,
        operation: str,
    ) -> list[SchemaViolation]:
        """Validate a map value."""
        violations: list[SchemaViolation] = []

        if not isinstance(value, dict):
            violations.append(
                SchemaViolation(
                    operation=operation,
                    service=service,
                    violation_type="wrong_type",
                    field_path=path or "(root)",
                    expected="map",
                    actual=type(value).__name__,
                    message=f"Expected map (dict), got {type(value).__name__}",
                )
            )
            return violations

        # Get value shape
        value_shape = shape.value if hasattr(shape, "value") else None
        if not value_shape:
            return violations

        # Validate first few values
        for k, v in list(value.items())[:10]:
            item_path = f"{path}['{k}']"
            violations.extend(self._validate_shape(v, value_shape, item_path, service, operation))

        return violations

    def _count_shape_members(self, shape: Any, visited: set | None = None) -> int:
        """Count total members in a shape for statistics."""
        if visited is None:
            visited = set()

        shape_name = shape.name if hasattr(shape, "name") else id(shape)
        if shape_name in visited:
            return 0
        visited.add(shape_name)

        count = 0
        shape_type = shape.type_name if hasattr(shape, "type_name") else None

        if shape_type == "structure" and hasattr(shape, "members"):
            for _member_name, member_shape in shape.members.items():
                count += 1
                count += self._count_shape_members(member_shape, visited)
        elif shape_type == "list" and hasattr(shape, "member"):
            count += self._count_shape_members(shape.member, visited)

        return count


def validate_response_quick(
    service: str,
    operation: str,
    response: dict,
) -> SchemaValidationResult:
    """Quick validation function without needing to instantiate validator.

    Args:
        service: AWS service name
        operation: Operation name
        response: Response to validate

    Returns:
        SchemaValidationResult
    """
    if not BOTOCORE_AVAILABLE:
        return SchemaValidationResult(
            service=service,
            operation=operation,
            error="botocore not available for schema validation",
        )

    try:
        validator = BotocoreSchemaValidator()
        return validator.validate_response(service, operation, response)
    except Exception as e:
        return SchemaValidationResult(
            service=service,
            operation=operation,
            error=str(e),
        )


def validate_error_response(
    service: str,
    error_code: str,
    error_response: dict,
) -> list[SchemaViolation]:
    """Validate an error response has expected structure.

    AWS error responses typically have:
    - Error.Code or __type
    - Error.Message or message
    - RequestId

    Args:
        service: AWS service name
        error_code: The error code
        error_response: The error response dict

    Returns:
        List of violations
    """
    violations: list[SchemaViolation] = []

    # Check for error code
    has_code = (
        error_response.get("Error", {}).get("Code")
        or error_response.get("__type")
        or error_response.get("code")
        or error_response.get("errorCode")
    )
    if not has_code:
        violations.append(
            SchemaViolation(
                operation="error",
                service=service,
                violation_type="missing_field",
                field_path="Error.Code",
                expected="error code",
                actual="missing",
                message="Error response missing error code field",
            )
        )

    # Check for error message
    has_message = (
        error_response.get("Error", {}).get("Message")
        or error_response.get("message")
        or error_response.get("Message")
        or error_response.get("errorMessage")
    )
    if not has_message:
        violations.append(
            SchemaViolation(
                operation="error",
                service=service,
                violation_type="missing_field",
                field_path="Error.Message",
                expected="error message",
                actual="missing",
                message="Error response missing error message field",
            )
        )

    # Check for RequestId (most AWS services include this)
    has_request_id = (
        error_response.get("RequestId")
        or error_response.get("requestId")
        or error_response.get("ResponseMetadata", {}).get("RequestId")
    )
    if not has_request_id:
        violations.append(
            SchemaViolation(
                operation="error",
                service=service,
                violation_type="missing_field",
                field_path="RequestId",
                expected="request ID",
                actual="missing",
                message="Error response missing RequestId",
            )
        )

    return violations
