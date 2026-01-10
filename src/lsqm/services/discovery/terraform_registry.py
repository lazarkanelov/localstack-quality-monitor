"""Terraform Registry discovery - find AWS modules from registry.terraform.io."""

import logging
from datetime import datetime

import aiohttp

from lsqm.models import Architecture
from lsqm.services.localstack_services import extract_services_from_terraform
from lsqm.utils.hashing import compute_architecture_hash

# Base URL for Terraform Registry API
REGISTRY_BASE_URL = "https://registry.terraform.io/v1/modules"

# Common AWS module namespaces to search
AWS_MODULE_SEARCHES = [
    "vpc",
    "lambda",
    "s3",
    "dynamodb",
    "sqs",
    "sns",
    "api-gateway",
    "step-functions",
    "ecs",
    "rds",
]


def discover_terraform_registry(
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    config=None,  # TerraformRegistrySourceConfig
) -> list[Architecture]:
    """Discover architectures from Terraform Registry.

    Args:
        github_token: GitHub token (not used for registry, but consistent interface)
        limit: Maximum modules to discover
        existing_urls: Already-known source URLs
        existing_hashes: Already-known content hashes
        logger: Logger instance

    Returns:
        List of discovered Architecture objects
    """
    import asyncio

    return asyncio.run(
        _discover_async(limit, existing_urls or set(), existing_hashes or set(), logger)
    )


async def _discover_async(
    limit: int,
    existing_urls: set[str],
    existing_hashes: set[str],
    logger: logging.Logger | None,
) -> list[Architecture]:
    """Async implementation of registry discovery."""
    discovered: list[Architecture] = []

    async with aiohttp.ClientSession() as session:
        for search_term in AWS_MODULE_SEARCHES:
            if limit > 0 and len(discovered) >= limit:
                break

            try:
                modules = await _search_modules(session, search_term, logger)

                for module in modules:
                    if limit > 0 and len(discovered) >= limit:
                        break

                    source_url = module.get("source_url", "")
                    if source_url in existing_urls:
                        continue

                    arch = await _fetch_module_details(session, module, logger)
                    if arch and arch.hash not in existing_hashes:
                        discovered.append(arch)

            except Exception as e:
                if logger:
                    logger.error(f"Error searching for {search_term}: {e}")

    return discovered


async def _search_modules(
    session: aiohttp.ClientSession,
    query: str,
    logger: logging.Logger | None,
) -> list[dict]:
    """Search for modules in the registry."""
    url = f"{REGISTRY_BASE_URL}/search"
    params = {"q": query, "provider": "aws", "limit": 20}

    try:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("modules", [])
            elif response.status == 429:
                if logger:
                    logger.warning("Rate limited by Terraform Registry")
                return []
            else:
                if logger:
                    logger.warning(f"Registry search failed: {response.status}")
                return []
    except Exception as e:
        if logger:
            logger.error(f"Registry request failed: {e}")
        return []


async def _fetch_module_details(
    session: aiohttp.ClientSession,
    module: dict,
    logger: logging.Logger | None,
) -> Architecture | None:
    """Fetch module details and download Terraform files."""
    namespace = module.get("namespace", "")
    name = module.get("name", "")
    version = module.get("version", "")

    if not all([namespace, name, version]):
        return None

    source_url = f"https://registry.terraform.io/modules/{namespace}/{name}/aws/{version}"

    # Get download URL
    download_url = f"{REGISTRY_BASE_URL}/{namespace}/{name}/aws/{version}/download"

    try:
        async with session.get(download_url, allow_redirects=False) as response:
            if response.status in (204, 301, 302):
                # Get download location from header
                download_location = response.headers.get("X-Terraform-Get", "")
                if not download_location:
                    return None

                # Download and extract Terraform files
                tf_files = await _download_terraform_files(session, download_location, logger)
                if not tf_files:
                    return None

                # Compute hash
                content_hash = compute_architecture_hash(tf_files)

                # Extract services
                all_content = "\n".join(tf_files.values())
                services = list(extract_services_from_terraform(all_content))

                # Count resources
                resource_count = all_content.count("resource \"aws_")

                return Architecture(
                    hash=content_hash,
                    source_url=source_url,
                    source_type="terraform_registry",
                    discovered_at=datetime.utcnow(),
                    services=services,
                    resource_count=resource_count,
                    name=f"{namespace}/{name}",
                    description=module.get("description", ""),
                    version=version,
                    terraform_files=tf_files,
                )

    except Exception as e:
        if logger:
            logger.error(f"Failed to fetch module {namespace}/{name}: {e}")

    return None


def _parse_terraform_get_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Parse Terraform's special git URL format.

    Format examples:
    - git:///:https://github.com/org/repo?ref=abc123
    - git::https://github.com/org/repo.git?ref=abc123
    - https://github.com/org/repo/archive/v1.0.0.tar.gz

    Returns:
        Tuple of (owner, repo, ref) for GitHub URLs, or (None, None, None) for others.
    """
    import re

    # Handle git:///:https:// format
    if url.startswith("git:///:"):
        url = url[8:]  # Remove "git:///:""
    # Handle git::https:// format
    elif url.startswith("git::"):
        url = url[5:]  # Remove "git::"

    # Parse GitHub URL
    github_pattern = r"https?://github\.com/([^/]+)/([^/?]+?)(?:\.git)?(?:\?ref=(.+))?$"
    match = re.match(github_pattern, url)
    if match:
        owner = match.group(1)
        repo = match.group(2)
        ref = match.group(3) or "main"
        return owner, repo, ref

    return None, None, None


async def _download_terraform_files(
    session: aiohttp.ClientSession,
    url: str,
    logger: logging.Logger | None,
) -> dict[str, str]:
    """Download and extract Terraform files from archive URL or GitHub."""
    import io
    import tarfile
    import zipfile

    tf_files: dict[str, str] = {}

    # Check if this is a GitHub URL that needs special handling
    owner, repo, ref = _parse_terraform_get_url(url)

    if owner and repo:
        # Use GitHub API to download as zip archive
        archive_url = f"https://github.com/{owner}/{repo}/archive/{ref}.zip"
        try:
            async with session.get(archive_url) as response:
                if response.status != 200:
                    if logger:
                        logger.debug(f"GitHub archive download failed: {response.status}")
                    return {}

                content = await response.read()

                # Extract zip archive
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for name in zf.namelist():
                        # Skip hidden/system files
                        if name.startswith("__") or "/__" in name:
                            continue

                        # Capture .tf files
                        if name.endswith(".tf"):
                            try:
                                tf_content = zf.read(name).decode("utf-8")
                                # Remove the top-level directory prefix
                                clean_name = "/".join(name.split("/")[1:])
                                if clean_name:
                                    tf_files[clean_name] = tf_content
                            except Exception:
                                pass

                        # Capture .tfvars files (especially from examples/)
                        elif name.endswith(".tfvars") or name.endswith(".tfvars.json"):
                            try:
                                tfvars_content = zf.read(name).decode("utf-8")
                                clean_name = "/".join(name.split("/")[1:])
                                if clean_name:
                                    tf_files[clean_name] = tfvars_content
                            except Exception:
                                pass

                        # Limit files to prevent memory issues
                        if len(tf_files) >= 50:
                            break

        except Exception as e:
            if logger:
                logger.debug(f"Failed to download from GitHub: {e}")

        return tf_files

    # For direct archive URLs, try to download
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return {}

            content = await response.read()

            # Try tar.gz first
            try:
                with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if member.isfile() and member.name.endswith(".tf"):
                            f = tar.extractfile(member)
                            if f:
                                tf_files[member.name] = f.read().decode("utf-8")
                        if len(tf_files) >= 50:
                            break
            except tarfile.ReadError:
                # Try zip format
                try:
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        for name in zf.namelist():
                            if name.endswith(".tf"):
                                tf_files[name] = zf.read(name).decode("utf-8")
                            if len(tf_files) >= 50:
                                break
                except zipfile.BadZipFile:
                    pass

    except Exception as e:
        if logger:
            logger.debug(f"Failed to download Terraform files: {e}")

    return tf_files
