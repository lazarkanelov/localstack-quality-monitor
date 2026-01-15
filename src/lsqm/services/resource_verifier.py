"""Resource configuration verification - verify deployed resources match expected config."""

import logging
import re
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from lsqm.models.qa_models import ConfigCheck, ResourceConfigVerification


def verify_resource_configurations(
    work_dir: Path,
    endpoint: str,
    logger: logging.Logger | None = None,
) -> list[ResourceConfigVerification]:
    """Verify that deployed resources match their Terraform configuration.

    Args:
        work_dir: Directory containing Terraform files
        endpoint: LocalStack endpoint URL
        logger: Optional logger

    Returns:
        List of ResourceConfigVerification results
    """
    verifications = []

    # Parse expected configurations from Terraform files
    expected_configs = _parse_terraform_configs(work_dir)

    # Create boto3 session pointing to LocalStack
    session = boto3.Session(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )

    for resource_addr, config in expected_configs.items():
        resource_type = config.get("type", "")
        resource_name = config.get("name", "")

        verification = ResourceConfigVerification(
            resource_type=resource_type,
            resource_name=resource_name,
        )

        try:
            # Get the actual resource configuration from AWS/LocalStack
            actual_config = _get_actual_config(session, endpoint, resource_type, config)

            if actual_config:
                # Compare configurations
                checks = _compare_configs(resource_type, config, actual_config)
                verification.config_checks = checks
                verification.passed = all(c.passed for c in checks)
            else:
                verification.config_checks = [
                    ConfigCheck(
                        attribute="existence",
                        expected_value="exists",
                        actual_value="not_found",
                        passed=False,
                        message="Resource not found in LocalStack",
                    )
                ]
                verification.passed = False

        except Exception as e:
            if logger:
                logger.warning(f"Failed to verify {resource_addr}: {e}")
            verification.config_checks = [
                ConfigCheck(
                    attribute="verification",
                    expected_value="success",
                    actual_value="error",
                    passed=False,
                    message=str(e)[:200],
                )
            ]
            verification.passed = False

        verifications.append(verification)

    return verifications


def _parse_terraform_configs(work_dir: Path) -> dict[str, dict]:
    """Parse Terraform files to extract expected resource configurations.

    Args:
        work_dir: Directory containing Terraform files

    Returns:
        Dict mapping resource addresses to their configuration
    """
    configs = {}

    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()

        # Find resource blocks
        # resource "aws_s3_bucket" "my_bucket" { ... }
        resource_pattern = re.compile(
            r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', re.DOTALL
        )

        for match in resource_pattern.finditer(content):
            resource_type = match.group(1)
            resource_name = match.group(2)
            resource_body = match.group(3)

            address = f"{resource_type}.{resource_name}"

            # Parse the resource body to extract configuration
            config = _parse_resource_body(resource_type, resource_body)
            config["type"] = resource_type
            config["name"] = resource_name

            configs[address] = config

    return configs


def _parse_resource_body(resource_type: str, body: str) -> dict:
    """Parse a Terraform resource body to extract configuration values.

    Args:
        resource_type: Type of the resource
        body: The HCL body content

    Returns:
        Dict of configuration attributes
    """
    config = {}

    # Simple attribute extraction: attribute = "value" or attribute = value
    simple_attrs = re.findall(r'^\s*(\w+)\s*=\s*"([^"]*)"', body, re.MULTILINE)
    for attr, value in simple_attrs:
        config[attr] = value

    # Boolean/number attributes: attribute = true/false/123
    bool_num_attrs = re.findall(r"^\s*(\w+)\s*=\s*(true|false|\d+)\s*$", body, re.MULTILINE)
    for attr, value in bool_num_attrs:
        if value == "true":
            config[attr] = True
        elif value == "false":
            config[attr] = False
        else:
            config[attr] = int(value)

    # Handle nested blocks for specific resource types
    if resource_type == "aws_s3_bucket":
        # Check for versioning block
        if "versioning {" in body:
            versioning_match = re.search(r"versioning\s*\{([^}]+)\}", body)
            if versioning_match:
                versioning_body = versioning_match.group(1)
                if "enabled = true" in versioning_body:
                    config["versioning_enabled"] = True

    elif resource_type == "aws_lambda_function":
        # Extract runtime, handler, memory, timeout
        runtime_match = re.search(r'runtime\s*=\s*"([^"]+)"', body)
        if runtime_match:
            config["runtime"] = runtime_match.group(1)

        handler_match = re.search(r'handler\s*=\s*"([^"]+)"', body)
        if handler_match:
            config["handler"] = handler_match.group(1)

        memory_match = re.search(r"memory_size\s*=\s*(\d+)", body)
        if memory_match:
            config["memory_size"] = int(memory_match.group(1))

        timeout_match = re.search(r"timeout\s*=\s*(\d+)", body)
        if timeout_match:
            config["timeout"] = int(timeout_match.group(1))

    elif resource_type == "aws_dynamodb_table":
        # Extract billing mode, hash key
        billing_match = re.search(r'billing_mode\s*=\s*"([^"]+)"', body)
        if billing_match:
            config["billing_mode"] = billing_match.group(1)

        hash_key_match = re.search(r'hash_key\s*=\s*"([^"]+)"', body)
        if hash_key_match:
            config["hash_key"] = hash_key_match.group(1)

    return config


def _get_actual_config(
    session: boto3.Session,
    endpoint: str,
    resource_type: str,
    expected_config: dict,
) -> dict[str, Any] | None:
    """Get the actual configuration of a resource from LocalStack.

    Args:
        session: boto3 Session
        endpoint: LocalStack endpoint
        resource_type: Type of the resource
        expected_config: Expected configuration (used to identify resource)

    Returns:
        Dict of actual configuration or None if not found
    """
    try:
        if resource_type == "aws_s3_bucket":
            return _get_s3_bucket_config(session, endpoint, expected_config)
        elif resource_type == "aws_lambda_function":
            return _get_lambda_config(session, endpoint, expected_config)
        elif resource_type == "aws_dynamodb_table":
            return _get_dynamodb_config(session, endpoint, expected_config)
        elif resource_type == "aws_sqs_queue":
            return _get_sqs_config(session, endpoint, expected_config)
        elif resource_type == "aws_sns_topic":
            return _get_sns_config(session, endpoint, expected_config)
        elif resource_type == "aws_iam_role":
            return _get_iam_role_config(session, endpoint, expected_config)
        else:
            # For unsupported resource types, return empty config
            return {}
    except ClientError:
        return None


def _get_s3_bucket_config(
    session: boto3.Session,
    endpoint: str,
    expected: dict,
) -> dict[str, Any] | None:
    """Get S3 bucket configuration."""
    s3 = session.client("s3", endpoint_url=endpoint)
    bucket_name = expected.get("bucket", expected.get("name", ""))

    if not bucket_name:
        return None

    config = {"bucket": bucket_name}

    try:
        # Check if bucket exists
        s3.head_bucket(Bucket=bucket_name)

        # Get versioning
        try:
            versioning = s3.get_bucket_versioning(Bucket=bucket_name)
            config["versioning_enabled"] = versioning.get("Status") == "Enabled"
        except ClientError:
            config["versioning_enabled"] = False

        # Get encryption
        try:
            encryption = s3.get_bucket_encryption(Bucket=bucket_name)
            config["encryption_enabled"] = True
            rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            if rules:
                sse = rules[0].get("ApplyServerSideEncryptionByDefault", {})
                config["sse_algorithm"] = sse.get("SSEAlgorithm")
        except ClientError:
            config["encryption_enabled"] = False

        # Get ACL
        try:
            acl = s3.get_bucket_acl(Bucket=bucket_name)
            config["acl"] = "private"  # Default
            for grant in acl.get("Grants", []):
                grantee = grant.get("Grantee", {})
                if grantee.get("URI") == "http://acs.amazonaws.com/groups/global/AllUsers":
                    config["acl"] = "public-read"
        except ClientError:
            pass

        return config

    except ClientError:
        return None


def _get_lambda_config(
    session: boto3.Session,
    endpoint: str,
    expected: dict,
) -> dict[str, Any] | None:
    """Get Lambda function configuration."""
    lambda_client = session.client("lambda", endpoint_url=endpoint)
    function_name = expected.get("function_name", expected.get("name", ""))

    if not function_name:
        return None

    try:
        response = lambda_client.get_function(FunctionName=function_name)
        config_data = response.get("Configuration", {})

        return {
            "function_name": config_data.get("FunctionName"),
            "runtime": config_data.get("Runtime"),
            "handler": config_data.get("Handler"),
            "memory_size": config_data.get("MemorySize"),
            "timeout": config_data.get("Timeout"),
            "role": config_data.get("Role"),
        }
    except ClientError:
        return None


def _get_dynamodb_config(
    session: boto3.Session,
    endpoint: str,
    expected: dict,
) -> dict[str, Any] | None:
    """Get DynamoDB table configuration."""
    dynamodb = session.client("dynamodb", endpoint_url=endpoint)
    table_name = expected.get("name", "")

    if not table_name:
        return None

    try:
        response = dynamodb.describe_table(TableName=table_name)
        table = response.get("Table", {})

        config = {
            "name": table.get("TableName"),
            "billing_mode": table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
        }

        # Extract hash key
        for schema in table.get("KeySchema", []):
            if schema.get("KeyType") == "HASH":
                config["hash_key"] = schema.get("AttributeName")
            elif schema.get("KeyType") == "RANGE":
                config["range_key"] = schema.get("AttributeName")

        return config
    except ClientError:
        return None


def _get_sqs_config(
    session: boto3.Session,
    endpoint: str,
    expected: dict,
) -> dict[str, Any] | None:
    """Get SQS queue configuration."""
    sqs = session.client("sqs", endpoint_url=endpoint)
    queue_name = expected.get("name", "")

    if not queue_name:
        return None

    try:
        # Get queue URL
        response = sqs.get_queue_url(QueueName=queue_name)
        queue_url = response.get("QueueUrl")

        # Get queue attributes
        attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["All"]).get(
            "Attributes", {}
        )

        return {
            "name": queue_name,
            "visibility_timeout": int(attrs.get("VisibilityTimeout", 30)),
            "message_retention_seconds": int(attrs.get("MessageRetentionPeriod", 345600)),
            "delay_seconds": int(attrs.get("DelaySeconds", 0)),
            "fifo_queue": attrs.get("FifoQueue") == "true",
        }
    except ClientError:
        return None


def _get_sns_config(
    session: boto3.Session,
    endpoint: str,
    expected: dict,
) -> dict[str, Any] | None:
    """Get SNS topic configuration."""
    sns = session.client("sns", endpoint_url=endpoint)
    topic_name = expected.get("name", "")

    if not topic_name:
        return None

    try:
        # List topics to find the ARN
        paginator = sns.get_paginator("list_topics")
        for page in paginator.paginate():
            for topic in page.get("Topics", []):
                arn = topic.get("TopicArn", "")
                if arn.endswith(f":{topic_name}"):
                    attrs = sns.get_topic_attributes(TopicArn=arn).get("Attributes", {})
                    return {
                        "name": topic_name,
                        "arn": arn,
                        "display_name": attrs.get("DisplayName", ""),
                    }
        return None
    except ClientError:
        return None


def _get_iam_role_config(
    session: boto3.Session,
    endpoint: str,
    expected: dict,
) -> dict[str, Any] | None:
    """Get IAM role configuration."""
    iam = session.client("iam", endpoint_url=endpoint)
    role_name = expected.get("name", "")

    if not role_name:
        return None

    try:
        response = iam.get_role(RoleName=role_name)
        role = response.get("Role", {})

        return {
            "name": role.get("RoleName"),
            "arn": role.get("Arn"),
            "path": role.get("Path"),
            "assume_role_policy": role.get("AssumeRolePolicyDocument"),
        }
    except ClientError:
        return None


def _compare_configs(
    resource_type: str,
    expected: dict,
    actual: dict,
) -> list[ConfigCheck]:
    """Compare expected and actual configurations.

    Args:
        resource_type: Type of the resource
        expected: Expected configuration from Terraform
        actual: Actual configuration from AWS/LocalStack

    Returns:
        List of ConfigCheck results
    """
    checks = []

    # Define which attributes to check for each resource type
    check_attrs = {
        "aws_s3_bucket": ["bucket", "versioning_enabled", "acl"],
        "aws_lambda_function": ["function_name", "runtime", "handler", "memory_size", "timeout"],
        "aws_dynamodb_table": ["name", "billing_mode", "hash_key"],
        "aws_sqs_queue": ["name", "visibility_timeout", "fifo_queue"],
        "aws_sns_topic": ["name"],
        "aws_iam_role": ["name"],
    }

    attrs_to_check = check_attrs.get(resource_type, [])

    for attr in attrs_to_check:
        expected_val = expected.get(attr)
        actual_val = actual.get(attr)

        # Skip if expected value is not set (not configured in Terraform)
        if expected_val is None:
            continue

        passed = expected_val == actual_val

        checks.append(
            ConfigCheck(
                attribute=attr,
                expected_value=str(expected_val),
                actual_value=str(actual_val) if actual_val is not None else "not_set",
                passed=passed,
                message="" if passed else f"Mismatch: expected {expected_val}, got {actual_val}",
            )
        )

    return checks


def generate_config_verification_report(
    verifications: list[ResourceConfigVerification],
) -> dict:
    """Generate a summary report of configuration verifications.

    Args:
        verifications: List of verification results

    Returns:
        Summary dict with statistics
    """
    total = len(verifications)
    passed = sum(1 for v in verifications if v.passed)
    failed = total - passed

    total_checks = sum(len(v.config_checks) for v in verifications)
    passed_checks = sum(sum(1 for c in v.config_checks if c.passed) for v in verifications)

    failed_resources = [
        {
            "resource": f"{v.resource_type}.{v.resource_name}",
            "failed_checks": [c.to_dict() for c in v.config_checks if not c.passed],
        }
        for v in verifications
        if not v.passed
    ]

    return {
        "total_resources": total,
        "passed_resources": passed,
        "failed_resources": failed,
        "verification_rate": passed / total if total > 0 else 0.0,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "check_pass_rate": passed_checks / total_checks if total_checks > 0 else 0.0,
        "failures": failed_resources,
    }
