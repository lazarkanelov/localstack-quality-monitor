"""GitHub organization discovery - find architectures from AWS GitHub orgs."""

import logging
import time
from datetime import UTC, datetime

from github import Auth, Github, GithubException, RateLimitExceededException

from lsqm.models import Architecture
from lsqm.services.localstack_services import extract_services_from_terraform
from lsqm.utils.hashing import compute_architecture_hash

# AWS GitHub organizations to search (fallback defaults)
AWS_ORGS = ["aws-quickstart", "aws-solutions", "aws-samples"]

# Rate limit handling
MAX_RETRIES = 3
INITIAL_BACKOFF = 30  # seconds (reduced from 60 for search API)
SEARCH_RATE_LIMIT_BACKOFF = 10  # seconds between search requests


def discover_github_orgs(
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    config=None,  # GitHubOrgsSourceConfig
) -> list[Architecture]:
    """Discover architectures from AWS GitHub organizations using Search API.

    Uses GitHub's code search API to efficiently find repositories containing
    Terraform files, rather than iterating through all repos in an org.

    Args:
        github_token: GitHub personal access token
        limit: Maximum architectures to discover (0=unlimited)
        existing_urls: Already-known source URLs
        existing_hashes: Already-known content hashes
        logger: Logger instance
        config: GitHubOrgsSourceConfig with organizations list

    Returns:
        List of discovered Architecture objects
    """
    existing_urls = existing_urls or set()
    existing_hashes = existing_hashes or set()
    discovered: list[Architecture] = []

    g = Github(auth=Auth.Token(github_token))

    # Get config values
    orgs_to_scan = (
        config.organizations
        if config and hasattr(config, "organizations") and config.organizations
        else AWS_ORGS
    )
    max_repos_per_org = getattr(config, "max_files_per_repo", 100) if config else 100
    skip_archived = getattr(config, "skip_archived", True) if config else True
    skip_forks = getattr(config, "skip_forks", True) if config else True

    if logger:
        logger.info(f"Discovering from organizations: {orgs_to_scan}")

    for org_name in orgs_to_scan:
        if limit > 0 and len(discovered) >= limit:
            break

        remaining_limit = limit - len(discovered) if limit > 0 else max_repos_per_org

        if logger:
            logger.info(f"Searching for Terraform repos in {org_name}...")

        # Try search API first (much faster)
        try:
            org_discovered = _discover_via_search(
                g=g,
                org_name=org_name,
                limit=min(remaining_limit, max_repos_per_org),
                existing_urls=existing_urls,
                existing_hashes=existing_hashes,
                skip_archived=skip_archived,
                skip_forks=skip_forks,
                logger=logger,
            )
            discovered.extend(org_discovered)

            # Update tracking sets
            for arch in org_discovered:
                existing_urls = existing_urls | {arch.source_url}
                existing_hashes = existing_hashes | {arch.hash}

            if logger:
                logger.info(f"Found {len(org_discovered)} architectures in {org_name}")

        except Exception as e:
            if logger:
                logger.warning(f"Search API failed for {org_name}: {e}")
                logger.info(f"Falling back to iteration method for {org_name}")

            # Fall back to iteration method
            try:
                org_discovered = _discover_via_iteration(
                    g=g,
                    org_name=org_name,
                    limit=min(remaining_limit, max_repos_per_org),
                    existing_urls=existing_urls,
                    existing_hashes=existing_hashes,
                    skip_archived=skip_archived,
                    skip_forks=skip_forks,
                    logger=logger,
                )
                discovered.extend(org_discovered)

                for arch in org_discovered:
                    existing_urls = existing_urls | {arch.source_url}
                    existing_hashes = existing_hashes | {arch.hash}

            except Exception as fallback_error:
                if logger:
                    logger.error(f"Both methods failed for {org_name}: {fallback_error}")

    return discovered


def _discover_via_search(
    g: Github,
    org_name: str,
    limit: int,
    existing_urls: set[str],
    existing_hashes: set[str],
    skip_archived: bool,
    skip_forks: bool,
    logger: logging.Logger | None,
) -> list[Architecture]:
    """Discover repos using GitHub's code search API.

    This is much faster than iterating - we search for .tf files directly
    and get back only repos that contain them.
    """
    discovered: list[Architecture] = []
    repos_seen: set[str] = set()

    # Search for Terraform files in the organization
    # Using extension:tf finds files with .tf extension
    query = f"extension:tf org:{org_name}"

    if logger:
        logger.info(f"Executing search: {query}")

    retries = 0
    while retries < MAX_RETRIES:
        try:
            search_results = g.search_code(query)

            # Extract unique repositories from search results
            for result in search_results:
                if limit > 0 and len(discovered) >= limit:
                    break

                repo = result.repository
                repo_full_name = repo.full_name

                # Skip if we've already seen this repo in this search
                if repo_full_name in repos_seen:
                    continue
                repos_seen.add(repo_full_name)

                # Skip if already in existing URLs
                if repo.html_url in existing_urls:
                    if logger:
                        logger.debug(f"Skipping {repo.name} (already known)")
                    continue

                # Apply filters
                if skip_archived and repo.archived:
                    if logger:
                        logger.debug(f"Skipping {repo.name} (archived)")
                    continue

                if skip_forks and repo.fork:
                    if logger:
                        logger.debug(f"Skipping {repo.name} (fork)")
                    continue

                # Process the repository
                arch = _process_repository_with_retry(repo, existing_hashes, logger)
                if arch:
                    discovered.append(arch)
                    existing_hashes = existing_hashes | {arch.hash}
                    if logger:
                        logger.info(f"  Found: {repo.name} ({len(arch.services)} services)")

                # Small delay to be nice to GitHub API
                time.sleep(0.5)

            break  # Success, exit retry loop

        except RateLimitExceededException:
            retries += 1
            # Check rate limit reset time
            rate_limit = g.get_rate_limit()
            search_limit = rate_limit.resources.search

            if search_limit.remaining == 0:
                reset_time = search_limit.reset
                # Handle timezone-aware datetime
                if reset_time.tzinfo is not None:
                    now = datetime.now(UTC)
                else:
                    now = datetime.utcnow()
                wait_time = max(
                    (reset_time - now).total_seconds(),
                    SEARCH_RATE_LIMIT_BACKOFF
                )
                wait_time = min(wait_time, 120)  # Cap at 2 minutes
            else:
                wait_time = INITIAL_BACKOFF * (2 ** (retries - 1))

            if logger:
                logger.warning(
                    f"Search rate limit hit, waiting {wait_time:.0f}s "
                    f"(retry {retries}/{MAX_RETRIES})"
                )

            if retries < MAX_RETRIES:
                time.sleep(wait_time)
            else:
                raise

        except GithubException as e:
            if e.status == 422:
                # Validation error - query might be too complex or org doesn't exist
                if logger:
                    logger.warning(f"Search query validation failed for {org_name}: {e}")
                break
            raise

    return discovered


def _discover_via_iteration(
    g: Github,
    org_name: str,
    limit: int,
    existing_urls: set[str],
    existing_hashes: set[str],
    skip_archived: bool,
    skip_forks: bool,
    logger: logging.Logger | None,
) -> list[Architecture]:
    """Fallback: discover repos by iterating through org repos.

    This is slower but works when search API fails.
    """
    discovered: list[Architecture] = []

    retries = 0
    while retries < MAX_RETRIES:
        try:
            org = g.get_organization(org_name)
            repos_checked = 0

            for repo in org.get_repos():
                if limit > 0 and len(discovered) >= limit:
                    break

                repos_checked += 1
                if repos_checked > limit * 10:  # Check up to 10x limit repos
                    if logger:
                        logger.info(f"Checked {repos_checked} repos, stopping iteration")
                    break

                if skip_archived and repo.archived:
                    continue

                if skip_forks and repo.fork:
                    continue

                if repo.html_url in existing_urls:
                    continue

                arch = _process_repository_with_retry(repo, existing_hashes, logger)
                if arch:
                    discovered.append(arch)
                    existing_hashes = existing_hashes | {arch.hash}
                    if logger:
                        logger.info(f"  Found: {repo.name}")

            break  # Success

        except RateLimitExceededException:
            retries += 1
            backoff = INITIAL_BACKOFF * (2 ** (retries - 1))
            if logger:
                logger.warning(
                    f"Rate limit exceeded, waiting {backoff}s (retry {retries}/{MAX_RETRIES})"
                )
            if retries < MAX_RETRIES:
                time.sleep(backoff)
            else:
                raise

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


def _process_repository(
    repo, existing_hashes: set[str], logger: logging.Logger | None
) -> Architecture | None:
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
        resource_count = all_content.count('resource "aws_')

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
