"""AWS CDK examples discovery."""

import logging
from datetime import datetime

from github import Github

from lsqm.models import Architecture
from lsqm.utils.hashing import compute_content_hash

# CDK examples repository
CDK_REPO = "aws-samples/aws-cdk-examples"


def discover_cdk_examples(
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    config=None,  # CDKSourceConfig
) -> list[Architecture]:
    """Discover architectures from AWS CDK examples.

    Note: CDK examples are stored as-is without Terraform conversion.
    They will be synthesized to CloudFormation during test generation.

    Args:
        github_token: GitHub personal access token
        limit: Maximum architectures to discover
        existing_urls: Already-known source URLs
        existing_hashes: Already-known content hashes
        logger: Logger instance

    Returns:
        List of discovered Architecture objects
    """
    existing_urls = existing_urls or set()
    existing_hashes = existing_hashes or set()
    discovered: list[Architecture] = []

    g = Github(github_token)

    try:
        repo = g.get_repo(CDK_REPO)

        # Find TypeScript and Python examples
        for example in _find_cdk_examples(repo, logger):
            if limit > 0 and len(discovered) >= limit:
                break

            source_url = f"{repo.html_url}/tree/main/{example['path']}"
            if source_url in existing_urls:
                continue

            arch = _process_cdk_example(repo, example, existing_hashes, logger)
            if arch:
                discovered.append(arch)
                # Track locally to avoid duplicates within this discovery run
                # Don't mutate the original sets - let caller handle deduplication
                existing_urls = existing_urls | {arch.source_url}
                existing_hashes = existing_hashes | {arch.hash}

    except Exception as e:
        if logger:
            logger.error(f"Error discovering CDK examples: {e}")

    return discovered


def _find_cdk_examples(repo, logger: logging.Logger | None) -> list[dict]:
    """Find CDK example directories."""
    examples = []

    try:
        # Look in typescript and python directories
        for lang_dir in ["typescript", "python"]:
            try:
                lang_contents = repo.get_contents(lang_dir)
                for content in lang_contents:
                    if content.type == "dir":
                        examples.append({
                            "path": content.path,
                            "name": content.name,
                            "language": lang_dir,
                        })
            except Exception:
                pass

    except Exception as e:
        if logger:
            logger.error(f"Error finding CDK examples: {e}")

    return examples


def _process_cdk_example(
    repo,
    example: dict,
    existing_hashes: set[str],
    logger: logging.Logger | None,
) -> Architecture | None:
    """Process a CDK example."""
    try:
        # Get the main CDK file
        main_file = _find_main_cdk_file(repo, example, logger)
        if not main_file:
            return None

        # Extract services from CDK constructs
        services = _extract_services_from_cdk(main_file)
        if not services:
            return None

        # Compute hash from main file content
        content_hash = compute_content_hash(main_file)
        if content_hash in existing_hashes:
            return None

        # For CDK, we store the source but don't have terraform_files
        # The generator will synthesize to CloudFormation and convert
        return Architecture(
            hash=content_hash,
            source_url=f"{repo.html_url}/tree/main/{example['path']}",
            source_type="cdk",
            discovered_at=datetime.utcnow(),
            services=list(services),
            resource_count=len(services),  # Estimate
            name=example["name"],
            description=f"CDK example ({example['language']}): {example['name']}",
            version=None,
            terraform_files={},  # CDK will be converted during generation
        )

    except Exception as e:
        if logger:
            logger.debug(f"Skipping CDK example {example['name']}: {e}")
        return None


def _find_main_cdk_file(repo, example: dict, logger: logging.Logger | None) -> str | None:
    """Find and read the main CDK stack file."""
    lang = example["language"]
    path = example["path"]

    # Common patterns for CDK main files
    patterns = []
    if lang == "typescript":
        patterns = [
            f"{path}/lib/{example['name']}-stack.ts",
            f"{path}/lib/main-stack.ts",
            f"{path}/lib/cdk-stack.ts",
        ]
    elif lang == "python":
        patterns = [
            f"{path}/{example['name'].replace('-', '_')}/stack.py",
            f"{path}/app.py",
            f"{path}/cdk_stack.py",
        ]

    for pattern in patterns:
        try:
            content = repo.get_contents(pattern)
            return content.decoded_content.decode("utf-8")
        except Exception:
            pass

    return None


def _extract_services_from_cdk(content: str) -> set[str]:
    """Extract AWS services from CDK code."""
    import re

    services = set()

    # CDK import patterns
    # TypeScript: import * as s3 from 'aws-cdk-lib/aws-s3'
    # Python: from aws_cdk import aws_s3 as s3
    ts_pattern = r"aws-cdk-lib/aws-(\w+)"
    py_pattern = r"aws_cdk\.aws_(\w+)|from aws_cdk import aws_(\w+)"

    for match in re.finditer(ts_pattern, content):
        service = match.group(1).replace("_", "").lower()
        services.add(_normalize_cdk_service(service))

    for match in re.finditer(py_pattern, content):
        service = (match.group(1) or match.group(2)).replace("_", "").lower()
        services.add(_normalize_cdk_service(service))

    return services


def _normalize_cdk_service(cdk_name: str) -> str:
    """Normalize CDK service name to standard AWS service name."""
    mapping = {
        "s3": "s3",
        "lambda": "lambda",
        "dynamodb": "dynamodb",
        "sqs": "sqs",
        "sns": "sns",
        "apigateway": "apigateway",
        "stepfunctions": "stepfunctions",
        "events": "events",
        "iam": "iam",
        "ec2": "ec2",
        "rds": "rds",
        "ecs": "ecs",
        "ecr": "ecr",
        "kms": "kms",
        "secretsmanager": "secretsmanager",
        "logs": "logs",
        "cloudwatch": "cloudwatch",
    }
    return mapping.get(cdk_name, cdk_name)
