"""Template normalization - CloudFormation and Serverless to Terraform conversion."""

import logging
import subprocess
import tempfile
from pathlib import Path

import yaml


def cloudformation_to_terraform(
    cf_template: str, logger: logging.Logger | None = None
) -> tuple[dict[str, str], set[str]]:
    """Convert CloudFormation template to Terraform using cf2tf.

    Args:
        cf_template: CloudFormation template content (JSON or YAML)
        logger: Logger instance

    Returns:
        Tuple of (terraform_files dict, services set)
    """
    tf_files: dict[str, str] = {}
    services: set[str] = set()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Write CloudFormation template
            cf_path = tmpdir_path / "template.yaml"
            with open(cf_path, "w") as f:
                f.write(cf_template)

            # Run cf2tf
            output_dir = tmpdir_path / "terraform"
            result = subprocess.run(
                ["cf2tf", str(cf_path), "-o", str(output_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                if logger:
                    logger.warning(f"cf2tf conversion failed: {result.stderr}")
                return {}, set()

            # Read generated Terraform files
            for tf_file in output_dir.glob("*.tf"):
                with open(tf_file) as f:
                    tf_files[tf_file.name] = f.read()

            # Extract services from generated Terraform
            from lsqm.services.localstack_services import extract_services_from_terraform

            for content in tf_files.values():
                services.update(extract_services_from_terraform(content))

    except subprocess.TimeoutExpired:
        if logger:
            logger.error("cf2tf conversion timed out")
    except FileNotFoundError:
        if logger:
            logger.error("cf2tf not installed")
    except Exception as e:
        if logger:
            logger.error(f"CloudFormation conversion error: {e}")

    return tf_files, services


def serverless_to_terraform(
    serverless_yml: str, logger: logging.Logger | None = None
) -> tuple[dict[str, str], set[str]]:
    """Convert Serverless Framework YAML to Terraform.

    Uses templates for common Serverless patterns.

    Args:
        serverless_yml: Serverless.yml content
        logger: Logger instance

    Returns:
        Tuple of (terraform_files dict, services set)
    """
    try:
        config = yaml.safe_load(serverless_yml)
    except yaml.YAMLError as e:
        if logger:
            logger.error(f"Failed to parse serverless.yml: {e}")
        return {}, set()

    tf_files: dict[str, str] = {}
    services: set[str] = set()

    # Extract functions
    functions = config.get("functions", {})
    if not functions:
        return {}, set()

    # Generate main.tf
    main_tf_parts = [
        "terraform {",
        "  required_providers {",
        "    aws = {",
        '      source  = "hashicorp/aws"',
        '      version = "~> 5.0"',
        "    }",
        "  }",
        "}",
        "",
        'provider "aws" {',
        '  region = "us-east-1"',
        "",
        "  endpoints {",
        '    lambda     = "http://localhost:4566"',
        '    iam        = "http://localhost:4566"',
        '    s3         = "http://localhost:4566"',
        '    dynamodb   = "http://localhost:4566"',
        '    sqs        = "http://localhost:4566"',
        '    sns        = "http://localhost:4566"',
        '    apigateway = "http://localhost:4566"',
        "  }",
        "",
        "  skip_credentials_validation = true",
        "  skip_metadata_api_check     = true",
        "  skip_requesting_account_id  = true",
        "}",
        "",
    ]

    # IAM role for Lambda
    main_tf_parts.extend(
        [
            "# IAM Role for Lambda",
            'resource "aws_iam_role" "lambda_role" {',
            '  name = "lambda_execution_role"',
            "",
            "  assume_role_policy = jsonencode({",
            '    Version = "2012-10-17"',
            "    Statement = [{",
            '      Action = "sts:AssumeRole"',
            '      Effect = "Allow"',
            "      Principal = {",
            '        Service = "lambda.amazonaws.com"',
            "      }",
            "    }]",
            "  })",
            "}",
            "",
        ]
    )
    services.add("iam")
    services.add("lambda")

    # Generate Lambda functions
    for func_name, func_config in functions.items():
        handler = func_config.get("handler", f"{func_name}.handler")
        runtime = func_config.get(
            "runtime", config.get("provider", {}).get("runtime", "python3.11")
        )
        timeout = func_config.get("timeout", 30)
        memory = func_config.get("memorySize", 128)

        safe_name = func_name.replace("-", "_")

        main_tf_parts.extend(
            [
                f"# Lambda Function: {func_name}",
                f'resource "aws_lambda_function" "{safe_name}" {{',
                f'  function_name = "{func_name}"',
                "  role          = aws_iam_role.lambda_role.arn",
                f'  handler       = "{handler}"',
                f'  runtime       = "{runtime}"',
                f"  timeout       = {timeout}",
                f"  memory_size   = {memory}",
                "",
                '  filename         = "lambda.zip"',
                '  source_code_hash = filebase64sha256("lambda.zip")',
                "}",
                "",
            ]
        )

        # Process events
        events = func_config.get("events", [])
        for event in events:
            if "http" in event:
                _add_api_gateway_event(main_tf_parts, safe_name, event["http"], services)
            elif "sqs" in event:
                _add_sqs_event(main_tf_parts, safe_name, event["sqs"], services)
            elif "s3" in event:
                _add_s3_event(main_tf_parts, safe_name, event["s3"], services)
            elif "schedule" in event:
                _add_schedule_event(main_tf_parts, safe_name, event["schedule"], services)

    tf_files["main.tf"] = "\n".join(main_tf_parts)
    return tf_files, services


def _add_api_gateway_event(
    parts: list[str], func_name: str, http_config: dict | str, services: set[str]
) -> None:
    """Add API Gateway resources for HTTP event."""
    services.add("apigateway")

    # Parse HTTP config (path/method reserved for future detailed API Gateway generation)
    if isinstance(http_config, str):
        _ = http_config  # path
    else:
        _ = http_config.get("path", "/")
        _ = http_config.get("method", "GET").upper()

    parts.extend(
        [
            f"# API Gateway for {func_name}",
            f'resource "aws_api_gateway_rest_api" "{func_name}_api" {{',
            f'  name = "{func_name}-api"',
            "}",
            "",
        ]
    )


def _add_sqs_event(
    parts: list[str], func_name: str, sqs_config: dict | str, services: set[str]
) -> None:
    """Add SQS event source mapping."""
    services.add("sqs")

    queue_name = sqs_config if isinstance(sqs_config, str) else sqs_config.get("arn", "queue")
    safe_queue = queue_name.split(":")[-1] if ":" in queue_name else queue_name

    parts.extend(
        [
            f"# SQS Event Source for {func_name}",
            f'resource "aws_lambda_event_source_mapping" "{func_name}_sqs" {{',
            f"  event_source_arn = aws_sqs_queue.{func_name}_queue.arn",
            f"  function_name    = aws_lambda_function.{func_name}.arn",
            "}",
            "",
            f'resource "aws_sqs_queue" "{func_name}_queue" {{',
            f'  name = "{safe_queue}"',
            "}",
            "",
        ]
    )


def _add_s3_event(parts: list[str], func_name: str, s3_config: dict, services: set[str]) -> None:
    """Add S3 notification."""
    services.add("s3")

    bucket = s3_config.get("bucket", f"{func_name}-bucket")
    event_type = s3_config.get("event", "s3:ObjectCreated:*")

    parts.extend(
        [
            f"# S3 Event for {func_name}",
            f'resource "aws_s3_bucket" "{func_name}_bucket" {{',
            f'  bucket = "{bucket}"',
            "}",
            "",
            f'resource "aws_s3_bucket_notification" "{func_name}_notification" {{',
            f"  bucket = aws_s3_bucket.{func_name}_bucket.id",
            "",
            "  lambda_function {",
            f"    lambda_function_arn = aws_lambda_function.{func_name}.arn",
            f'    events              = ["{event_type}"]',
            "  }",
            "}",
            "",
        ]
    )


def _add_schedule_event(
    parts: list[str], func_name: str, schedule_config: dict | str, services: set[str]
) -> None:
    """Add CloudWatch Events schedule."""
    services.add("events")

    if isinstance(schedule_config, str):
        schedule_expr = schedule_config
    else:
        rate = schedule_config.get("rate", "rate(1 hour)")
        schedule_expr = rate

    parts.extend(
        [
            f"# Schedule for {func_name}",
            f'resource "aws_cloudwatch_event_rule" "{func_name}_schedule" {{',
            f'  name                = "{func_name}-schedule"',
            f'  schedule_expression = "{schedule_expr}"',
            "}",
            "",
            f'resource "aws_cloudwatch_event_target" "{func_name}_target" {{',
            f"  rule      = aws_cloudwatch_event_rule.{func_name}_schedule.name",
            f'  target_id = "{func_name}"',
            f"  arn       = aws_lambda_function.{func_name}.arn",
            "}",
            "",
        ]
    )
