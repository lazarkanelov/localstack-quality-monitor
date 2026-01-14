"""LocalStack supported services list for filtering unsupported architectures."""

# LocalStack Community Edition supported services
# Updated: 2026-01
LOCALSTACK_COMMUNITY_SERVICES: set[str] = {
    "acm",
    "apigateway",
    "cloudformation",
    "cloudwatch",
    "config",
    "dynamodb",
    "dynamodbstreams",
    "ec2",
    "ecr",
    "ecs",
    "events",
    "firehose",
    "iam",
    "kinesis",
    "kms",
    "lambda",
    "logs",
    "opensearch",
    "rds",
    "redshift",
    "resource-groups",
    "resourcegroupstaggingapi",
    "route53",
    "s3",
    "s3control",
    "secretsmanager",
    "ses",
    "sns",
    "sqs",
    "ssm",
    "stepfunctions",
    "sts",
    "transcribe",
}

# Mapping of Terraform resource type prefixes to AWS service names
TERRAFORM_RESOURCE_TO_SERVICE: dict[str, str] = {
    "aws_acm_": "acm",
    "aws_api_gateway_": "apigateway",
    "aws_apigateway": "apigateway",
    "aws_cloudformation_": "cloudformation",
    "aws_cloudwatch_": "cloudwatch",
    "aws_config_": "config",
    "aws_dynamodb_": "dynamodb",
    "aws_ec2_": "ec2",
    "aws_instance": "ec2",
    "aws_vpc": "ec2",
    "aws_subnet": "ec2",
    "aws_security_group": "ec2",
    "aws_network_": "ec2",
    "aws_eip": "ec2",
    "aws_nat_gateway": "ec2",
    "aws_internet_gateway": "ec2",
    "aws_route": "ec2",
    "aws_ecr_": "ecr",
    "aws_ecs_": "ecs",
    "aws_cloudwatch_event_": "events",
    "aws_kinesis_firehose_": "firehose",
    "aws_iam_": "iam",
    "aws_kinesis_stream": "kinesis",
    "aws_kms_": "kms",
    "aws_lambda_": "lambda",
    "aws_cloudwatch_log_": "logs",
    "aws_opensearch_": "opensearch",
    "aws_elasticsearch_": "opensearch",
    "aws_db_": "rds",
    "aws_rds_": "rds",
    "aws_redshift_": "redshift",
    "aws_resourcegroups_": "resource-groups",
    "aws_route53_": "route53",
    "aws_s3_": "s3",
    "aws_s3_bucket": "s3",
    "aws_secretsmanager_": "secretsmanager",
    "aws_ses_": "ses",
    "aws_sns_": "sns",
    "aws_sqs_": "sqs",
    "aws_ssm_": "ssm",
    "aws_sfn_": "stepfunctions",
    "aws_transcribe_": "transcribe",
}


def extract_services_from_terraform(tf_content: str) -> set[str]:
    """Extract AWS services used in Terraform content.

    Args:
        tf_content: Terraform file content

    Returns:
        Set of AWS service names
    """
    import re

    services = set()

    # Find all resource declarations
    resource_pattern = r'resource\s+"(aws_[^"]+)"'
    for match in re.finditer(resource_pattern, tf_content):
        resource_type = match.group(1)

        # Map resource type to service
        for prefix, service in TERRAFORM_RESOURCE_TO_SERVICE.items():
            if resource_type.startswith(prefix):
                services.add(service)
                break
        else:
            # Try to extract service from resource type
            parts = resource_type.split("_")
            if len(parts) >= 2:
                potential_service = parts[1]
                if potential_service in LOCALSTACK_COMMUNITY_SERVICES:
                    services.add(potential_service)

    return services


def is_service_supported(service: str) -> bool:
    """Check if a service is supported by LocalStack Community."""
    return service.lower() in LOCALSTACK_COMMUNITY_SERVICES


def is_standalone_architecture(tf_content: str) -> tuple[bool, str]:
    """Check if Terraform content represents a standalone architecture.

    A standalone architecture:
    - Has at least one resource block (not just module calls)
    - Has no required variables without defaults
    - Does not reference parent/local modules (source = "../")
    - Is not a module meant to be composed (requires inputs)

    Args:
        tf_content: Combined Terraform file content

    Returns:
        Tuple of (is_standalone, reason_if_not)
    """
    import re

    # Check for resource blocks
    resource_pattern = r'resource\s+"[^"]+"\s+"[^"]+"'
    has_resources = bool(re.search(resource_pattern, tf_content))

    if not has_resources:
        # Check if it's only module blocks (composition)
        module_pattern = r'module\s+"[^"]+"'
        has_modules = bool(re.search(module_pattern, tf_content))
        if has_modules:
            return False, "Only module composition (no direct resources)"
        return False, "No resources defined"

    # Check for local/parent module references (common in module examples)
    local_module_pattern = r'source\s*=\s*"(\.\.?/[^"]*)"'
    local_modules = re.findall(local_module_pattern, tf_content)
    if local_modules:
        return False, f"References local/parent module: {local_modules[0]}"

    # Check for required variables without defaults
    # Pattern: variable "name" { ... } without default = ...
    variable_blocks = re.findall(
        r'variable\s+"([^"]+)"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', tf_content, re.DOTALL
    )

    required_vars = []
    for var_name, var_body in variable_blocks:
        # Skip if it has a default
        if re.search(r"\bdefault\s*=", var_body):
            continue
        # Skip if it's nullable or optional
        if re.search(r"\bnullable\s*=\s*true", var_body):
            continue
        if re.search(r"\boptional\s*\(", var_body):
            continue
        required_vars.append(var_name)

    if required_vars:
        return False, f"Required variables without defaults: {', '.join(required_vars[:5])}"

    # Check for data sources that require external resources
    data_pattern = r'data\s+"([^"]+)"\s+"[^"]+"'
    data_sources = re.findall(data_pattern, tf_content)

    # Only terraform_remote_state requires external resources
    # (aws_caller_identity, aws_region, aws_availability_zones are OK)
    problematic_data = [ds for ds in data_sources if ds == "terraform_remote_state"]

    if problematic_data:
        return False, f"Requires external state: {', '.join(problematic_data)}"

    # Check for context variable pattern (Cloud Posse null-label modules)
    # These modules expect a context object passed from parent module
    if re.search(r"\bvar\.context\.\w+", tf_content):
        return False, "Requires external context object (null-label pattern)"

    return True, ""
