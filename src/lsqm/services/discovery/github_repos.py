"""GitHub repository discovery - fetch architectures from specific repositories."""

import logging
from datetime import datetime

from github import Github

from lsqm.models import Architecture
from lsqm.services.localstack_services import extract_services_from_terraform
from lsqm.utils.hashing import compute_architecture_hash


def discover_github_repos(
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    config=None,  # GitHubReposSourceConfig
) -> list[Architecture]:
    """Discover architectures from specific GitHub repositories.

    Args:
        github_token: GitHub personal access token
        limit: Maximum architectures to discover (0=unlimited)
        existing_urls: Already-known source URLs
        existing_hashes: Already-known content hashes
        logger: Logger instance
        config: GitHubReposSourceConfig with repository list

    Returns:
        List of discovered Architecture objects
    """
    existing_urls = existing_urls or set()
    existing_hashes = existing_hashes or set()
    discovered: list[Architecture] = []

    if not config or not config.repositories:
        return discovered

    g = Github(github_token)

    for repo_config in config.repositories:
        if limit > 0 and len(discovered) >= limit:
            break

        try:
            # Parse repository URL
            url = repo_config.url
            if not url:
                continue

            # Extract owner/repo from URL
            parts = url.rstrip("/").split("/")
            if len(parts) < 2:
                continue
            owner = parts[-2]
            repo_name = parts[-1].replace(".git", "")

            if logger:
                logger.info(f"Scanning repository: {owner}/{repo_name}")

            repo = g.get_repo(f"{owner}/{repo_name}")

            # Determine branch
            branch = repo_config.branch
            if not branch:
                branch = repo.default_branch

            # Scan specified paths for Terraform files
            for scan_path in repo_config.paths:
                if limit > 0 and len(discovered) >= limit:
                    break

                try:
                    arch = _scan_path_for_terraform(
                        repo=repo,
                        path=scan_path.strip("/"),
                        branch=branch,
                        existing_urls=existing_urls,
                        existing_hashes=existing_hashes,
                        logger=logger,
                    )
                    if arch:
                        discovered.append(arch)
                        # Track locally to avoid duplicates within this discovery run
                        # Don't mutate the original sets - let caller handle deduplication
                        existing_urls = existing_urls | {arch.source_url}
                        existing_hashes = existing_hashes | {arch.hash}

                except Exception as e:
                    if logger:
                        logger.debug(f"Error scanning path {scan_path}: {e}")

        except Exception as e:
            if logger:
                logger.warning(f"Error accessing repository {repo_config.url}: {e}")

    return discovered


def _scan_path_for_terraform(
    repo,
    path: str,
    branch: str,
    existing_urls: set[str],
    existing_hashes: set[str],
    logger: logging.Logger | None = None,
) -> Architecture | None:
    """Scan a specific path in a repository for Terraform files.

    Args:
        repo: PyGithub Repository object
        path: Path within the repository to scan
        branch: Branch to scan
        existing_urls: Already-known source URLs
        existing_hashes: Already-known content hashes
        logger: Logger instance

    Returns:
        Architecture object if Terraform files found, None otherwise
    """
    tf_files: dict[str, str] = {}

    try:
        # Get contents at path
        if path == "." or path == "":
            contents = repo.get_contents("", ref=branch)
        else:
            contents = repo.get_contents(path, ref=branch)

        # Handle single file vs directory
        if not isinstance(contents, list):
            contents = [contents]

        # Collect .tf and .tfvars files
        files_to_process = list(contents)
        processed_dirs = set()

        while files_to_process:
            item = files_to_process.pop(0)

            if item.type == "dir":
                # Recurse into subdirectories (but avoid infinite loops)
                if item.path not in processed_dirs:
                    processed_dirs.add(item.path)
                    try:
                        subcontents = repo.get_contents(item.path, ref=branch)
                        if isinstance(subcontents, list):
                            files_to_process.extend(subcontents)
                        else:
                            files_to_process.append(subcontents)
                    except Exception:
                        pass

            elif item.type == "file":
                # Collect Terraform files
                if item.name.endswith(".tf") or item.name.endswith(".tfvars"):
                    try:
                        content = item.decoded_content.decode("utf-8")
                        # Use relative path from scan root
                        rel_path = item.path
                        if path and path != ".":
                            rel_path = item.path[len(path):].lstrip("/")
                        tf_files[rel_path or item.name] = content
                    except Exception:
                        pass

            # Limit files to prevent memory issues
            if len(tf_files) >= 50:
                break

        if not tf_files:
            return None

        # Filter to only .tf files for content hash
        tf_only = {k: v for k, v in tf_files.items() if k.endswith(".tf")}
        if not tf_only:
            return None

        # Compute hash
        content_hash = compute_architecture_hash(tf_only)

        # Build source URL
        source_url = f"https://github.com/{repo.full_name}"
        if path and path != ".":
            source_url = f"{source_url}/tree/{branch}/{path}"

        # Check if already known
        if source_url in existing_urls or content_hash in existing_hashes:
            return None

        # Extract services
        all_content = "\n".join(tf_only.values())
        services = list(extract_services_from_terraform(all_content))

        # Count resources
        resource_count = all_content.count("resource \"aws_")

        if resource_count == 0:
            return None

        return Architecture(
            hash=content_hash,
            source_url=source_url,
            source_type="github_repos",
            discovered_at=datetime.utcnow(),
            services=services,
            resource_count=resource_count,
            name=f"{repo.full_name}" + (f"/{path}" if path and path != "." else ""),
            description=repo.description or "",
            version=branch,
            terraform_files=tf_files,  # Include tfvars files
        )

    except Exception as e:
        if logger:
            logger.debug(f"Error scanning {repo.full_name}/{path}: {e}")
        return None
