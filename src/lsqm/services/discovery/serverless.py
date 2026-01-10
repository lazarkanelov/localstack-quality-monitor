"""Serverless Framework examples discovery."""

import logging
from datetime import datetime

from github import Github

from lsqm.models import Architecture
from lsqm.services.normalizer import serverless_to_terraform
from lsqm.utils.hashing import compute_architecture_hash

# Serverless examples repository
SERVERLESS_REPO = "serverless/examples"


def discover_serverless(
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    config=None,  # ServerlessSourceConfig
) -> list[Architecture]:
    """Discover architectures from Serverless Framework examples.

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
        repo = g.get_repo(SERVERLESS_REPO)

        # Find AWS-related examples
        for content in _find_aws_examples(repo, logger):
            if limit > 0 and len(discovered) >= limit:
                break

            source_url = f"{repo.html_url}/tree/main/{content['path']}"
            if source_url in existing_urls:
                continue

            arch = _process_serverless_example(repo, content, existing_hashes, logger)
            if arch:
                discovered.append(arch)
                existing_urls.add(arch.source_url)
                existing_hashes.add(arch.hash)

    except Exception as e:
        if logger:
            logger.error(f"Error discovering serverless examples: {e}")

    return discovered


def _find_aws_examples(repo, logger: logging.Logger | None) -> list[dict]:
    """Find directories with serverless.yml for AWS."""
    examples = []

    try:
        root_contents = repo.get_contents("")

        for content in root_contents:
            if content.type == "dir" and "aws" in content.name.lower():
                # Check for serverless.yml
                try:
                    dir_contents = repo.get_contents(content.path)
                    has_serverless = any(
                        c.name in ("serverless.yml", "serverless.yaml")
                        for c in dir_contents
                    )
                    if has_serverless:
                        examples.append({
                            "path": content.path,
                            "name": content.name,
                        })
                except Exception:
                    pass

    except Exception as e:
        if logger:
            logger.error(f"Error finding AWS examples: {e}")

    return examples


def _process_serverless_example(
    repo,
    example: dict,
    existing_hashes: set[str],
    logger: logging.Logger | None,
) -> Architecture | None:
    """Process a serverless example and convert to Terraform."""
    try:
        # Get serverless.yml content
        yml_path = f"{example['path']}/serverless.yml"
        try:
            yml_content = repo.get_contents(yml_path).decoded_content.decode("utf-8")
        except Exception:
            yml_path = f"{example['path']}/serverless.yaml"
            yml_content = repo.get_contents(yml_path).decoded_content.decode("utf-8")

        # Convert to Terraform
        tf_files, services = serverless_to_terraform(yml_content)
        if not tf_files:
            return None

        # Compute hash
        content_hash = compute_architecture_hash(tf_files)
        if content_hash in existing_hashes:
            return None

        # Count resources
        all_content = "\n".join(tf_files.values())
        resource_count = all_content.count("resource \"aws_")

        return Architecture(
            hash=content_hash,
            source_url=f"{repo.html_url}/tree/main/{example['path']}",
            source_type="serverless",
            discovered_at=datetime.utcnow(),
            services=list(services),
            resource_count=resource_count,
            name=example["name"],
            description=f"Serverless Framework example: {example['name']}",
            version=None,
            terraform_files=tf_files,
        )

    except Exception as e:
        if logger:
            logger.debug(f"Skipping serverless example {example['name']}: {e}")
        return None
