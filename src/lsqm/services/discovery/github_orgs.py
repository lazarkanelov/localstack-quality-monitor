"""GitHub organization discovery - find architectures from AWS GitHub orgs."""

import logging
import time
from datetime import datetime

from github import Github, RateLimitExceededException

from lsqm.models import Architecture
from lsqm.services.localstack_services import extract_services_from_terraform
from lsqm.utils.hashing import compute_architecture_hash

# AWS GitHub organizations to search
AWS_ORGS = ["aws-quickstart", "aws-solutions", "aws-samples"]

# File patterns to look for
TERRAFORM_PATTERNS = ["*.tf", "**/*.tf"]

# Rate limit handling
MAX_RETRIES = 3
INITIAL_BACKOFF = 60  # seconds


def discover_github_orgs(
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    config=None,  # GitHubOrgsSourceConfig
) -> list[Architecture]:
    """Discover architectures from AWS GitHub organizations.

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

    for org_name in AWS_ORGS:
        if limit > 0 and len(discovered) >= limit:
            break

        retries = 0
        while retries < MAX_RETRIES:
            try:
                org = g.get_organization(org_name)

                for repo in org.get_repos():
                    if limit > 0 and len(discovered) >= limit:
                        break

                    if repo.html_url in existing_urls:
                        continue

                    # Check for Terraform files with rate limit handling
                    arch = _process_repository_with_retry(repo, existing_hashes, logger)
                    if arch:
                        discovered.append(arch)
                        existing_urls.add(arch.source_url)
                        existing_hashes.add(arch.hash)

                break  # Success, exit retry loop

            except RateLimitExceededException:
                retries += 1
                backoff = INITIAL_BACKOFF * (2 ** (retries - 1))
                if logger:
                    logger.warning(f"GitHub rate limit exceeded, waiting {backoff}s (retry {retries}/{MAX_RETRIES})")
                if retries < MAX_RETRIES:
                    time.sleep(backoff)
                else:
                    if logger:
                        logger.error(f"GitHub rate limit: max retries exceeded for {org_name}")
            except Exception as e:
                if logger:
                    logger.error(f"Error processing org {org_name}: {e}")
                break

    return discovered


def _process_repository_with_retry(
    repo, existing_hashes: set[str], logger: logging.Logger | None
) -> Architecture | None:
    """Process repository with rate limit retry handling."""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            return _process_repository(repo, existing_hashes, logger)
        except RateLimitExceededException:
            retries += 1
            backoff = INITIAL_BACKOFF * (2 ** (retries - 1))
            if logger:
                logger.warning(f"Rate limit hit on {repo.name}, waiting {backoff}s")
            if retries < MAX_RETRIES:
                time.sleep(backoff)
            else:
                raise
    return None


def _process_repository(repo, existing_hashes: set[str], logger: logging.Logger | None) -> Architecture | None:
    """Process a single repository for Terraform files."""
    try:
        # Check if repo has Terraform files
        tf_files = _find_terraform_files(repo)
        if not tf_files:
            return None

        # Compute hash
        content_hash = compute_architecture_hash(tf_files)
        if content_hash in existing_hashes:
            return None

        # Extract services
        all_content = "\n".join(tf_files.values())
        services = list(extract_services_from_terraform(all_content))
        if not services:
            return None

        # Count resources
        resource_count = all_content.count("resource \"aws_")

        return Architecture(
            hash=content_hash,
            source_url=repo.html_url,
            source_type="github",
            discovered_at=datetime.utcnow(),
            services=services,
            resource_count=resource_count,
            name=repo.name,
            description=repo.description or "",
            version=None,
            terraform_files=tf_files,
        )

    except Exception as e:
        if logger:
            logger.debug(f"Skipping {repo.name}: {e}")
        return None


def _find_terraform_files(repo) -> dict[str, str]:
    """Find and download Terraform files from repository."""
    tf_files: dict[str, str] = {}

    try:
        contents = repo.get_contents("")

        # BFS to find .tf files
        while contents:
            content = contents.pop(0)

            if content.type == "dir":
                try:
                    contents.extend(repo.get_contents(content.path))
                except Exception:
                    pass
            elif content.name.endswith(".tf"):
                try:
                    file_content = content.decoded_content.decode("utf-8")
                    tf_files[content.path] = file_content
                except Exception:
                    pass

            # Limit files to prevent memory issues
            if len(tf_files) >= 50:
                break

    except Exception:
        pass

    return tf_files
