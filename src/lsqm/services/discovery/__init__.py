"""Architecture discovery from public sources."""

import logging
from typing import TYPE_CHECKING

from lsqm.models import Architecture

if TYPE_CHECKING:
    from lsqm.utils.config import SourcesConfig


def discover_architectures(
    sources: list[str],
    github_token: str,
    limit: int = 0,
    existing_urls: set[str] | None = None,
    existing_hashes: set[str] | None = None,
    logger: logging.Logger | None = None,
    sources_config: "SourcesConfig | None" = None,
) -> list[Architecture]:
    """Discover architectures from specified sources.

    Args:
        sources: List of source types to query
        github_token: GitHub personal access token
        limit: Maximum architectures to discover (0=unlimited)
        existing_urls: Set of already-known source URLs
        existing_hashes: Set of already-known content hashes
        logger: Logger instance
        sources_config: Configuration for each source type

    Returns:
        List of discovered Architecture objects
    """
    from lsqm.services.discovery.cdk_examples import discover_cdk_examples
    from lsqm.services.discovery.github_orgs import discover_github_orgs
    from lsqm.services.discovery.github_repos import discover_github_repos
    from lsqm.services.discovery.serverless import discover_serverless
    from lsqm.services.discovery.terraform_registry import discover_terraform_registry

    existing_urls = existing_urls or set()
    existing_hashes = existing_hashes or set()
    discovered: list[Architecture] = []

    source_functions = {
        "github_repos": discover_github_repos,
        "terraform_registry": discover_terraform_registry,
        "github_orgs": discover_github_orgs,
        "github": discover_github_orgs,  # Alias for backward compatibility
        "serverless": discover_serverless,
        "cdk": discover_cdk_examples,
    }

    for source in sources:
        if source not in source_functions:
            if logger:
                logger.warning(f"Unknown source: {source}")
            continue

        if limit > 0 and len(discovered) >= limit:
            break

        try:
            remaining = limit - len(discovered) if limit > 0 else 0

            # Build kwargs based on source type
            kwargs = {
                "github_token": github_token,
                "limit": remaining,
                "existing_urls": existing_urls,
                "existing_hashes": existing_hashes,
                "logger": logger,
            }

            # Pass source-specific config if available
            if sources_config:
                if source == "github_repos":
                    kwargs["config"] = sources_config.github_repos
                elif source == "terraform_registry":
                    kwargs["config"] = sources_config.terraform_registry
                elif source in ("github_orgs", "github"):
                    kwargs["config"] = sources_config.github_orgs
                elif source == "serverless":
                    kwargs["config"] = sources_config.serverless
                elif source == "cdk":
                    kwargs["config"] = sources_config.cdk

            source_results = source_functions[source](**kwargs)

            for arch in source_results:
                if arch.source_url not in existing_urls and arch.hash not in existing_hashes:
                    discovered.append(arch)
                    existing_urls.add(arch.source_url)
                    existing_hashes.add(arch.hash)

                    if limit > 0 and len(discovered) >= limit:
                        break

        except Exception as e:
            if logger:
                logger.error(f"Error discovering from {source}: {e}")

    return discovered
