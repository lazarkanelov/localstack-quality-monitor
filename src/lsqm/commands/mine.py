"""Mine command - discover new infrastructure templates."""

import click

from lsqm.cli import pass_context


def _get_enabled_sources(config) -> list[str]:
    """Get list of enabled sources from config."""
    sources = []
    if config.sources.terraform_registry.enabled:
        sources.append("terraform_registry")
    if config.sources.github_orgs.enabled:
        sources.append("github_orgs")
    if config.sources.serverless.enabled:
        sources.append("serverless")
    if config.sources.cdk.enabled:
        sources.append("cdk")
    if config.sources.custom.enabled:
        sources.append("custom")
    return sources


@click.command()
@click.option(
    "--source",
    multiple=True,
    type=click.Choice(["terraform_registry", "github_orgs", "serverless", "cdk", "custom"]),
    help="Sources to mine (default: all enabled in config)",
)
@click.option("--limit", type=int, default=0, help="Max architectures to discover (0=unlimited)")
@pass_context
def mine(ctx, source, limit):
    """Discover new infrastructure templates from public sources."""
    config = ctx.config

    # Get enabled sources from config, or use command-line override
    if source:
        active_sources = list(source)
    else:
        active_sources = _get_enabled_sources(config)

    if not active_sources:
        click.echo("No sources enabled. Enable sources in config.yaml or use --source flag.")
        return

    if ctx.dry_run:
        click.echo("DRY RUN: Would mine architectures from:")
        for s in active_sources:
            click.echo(f"  - {s}")
        click.echo(f"  Limit: {limit if limit > 0 else 'unlimited'}")
        return

    result = _mine_impl(ctx, sources=tuple(active_sources), limit=limit)
    click.echo(f"Total: {result['new_count']} new standalone architectures discovered")
    if result.get("skipped_non_standalone", 0) > 0:
        click.echo(f"Skipped: {result['skipped_non_standalone']} (non-standalone)")
    if result.get("skipped_count", 0) > 0:
        click.echo(f"Skipped: {result['skipped_count']} (unsupported services)")


def _mine_impl(ctx, sources: tuple = (), limit: int = 0) -> dict:
    """Implementation of mine logic."""
    from lsqm.services.discovery import discover_architectures
    from lsqm.services.git_ops import (
        load_architecture_index,
        save_architecture,
        update_architecture_index,
    )
    from lsqm.services.localstack_services import (
        LOCALSTACK_COMMUNITY_SERVICES,
        is_standalone_architecture,
    )
    from lsqm.utils.config import get_artifacts_dir

    config = ctx.config
    logger = ctx.logger

    click.echo("Mining new architectures (standalone only)...")

    # Load existing index for deduplication
    artifacts_dir = get_artifacts_dir()
    index = load_architecture_index(artifacts_dir)
    existing_urls = {a.get("source_url") for a in index.get("architectures", {}).values()}
    existing_hashes = set(index.get("architectures", {}).keys())

    # Use provided sources or get enabled from config
    active_sources = list(sources) if sources else _get_enabled_sources(config)

    # Discover new architectures
    results = {
        "new_count": 0,
        "skipped_count": 0,
        "skipped_non_standalone": 0,
        "saved_count": 0,
        "by_source": {},
    }

    new_architectures = []

    discovered = discover_architectures(
        sources=active_sources,
        sources_config=config.sources,
        github_token=config.github_token,
        limit=limit,
        existing_urls=existing_urls,
        existing_hashes=existing_hashes,
        logger=logger,
    )

    for arch in discovered:
        # First check if standalone (self-contained, deployable)
        all_tf_content = "\n".join(arch.terraform_files.values())
        is_standalone, standalone_reason = is_standalone_architecture(all_tf_content)

        if not is_standalone:
            arch.skipped = True
            arch.skip_reason = f"Not standalone: {standalone_reason}"
            results["skipped_non_standalone"] += 1
            click.echo(f"  SKIP (non-standalone): {arch.name or arch.hash[:8]} - {standalone_reason}")
            continue  # Don't save non-standalone architectures

        # Check for unsupported services
        has_unsupported, unsupported = arch.has_unsupported_services(LOCALSTACK_COMMUNITY_SERVICES)
        if has_unsupported:
            arch.skipped = True
            arch.skip_reason = f"Unsupported services: {', '.join(unsupported)}"
            results["skipped_count"] += 1
        else:
            results["new_count"] += 1

        # Save architecture to artifacts directory (including terraform files)
        if save_architecture(arch, artifacts_dir, logger=logger):
            results["saved_count"] += 1
            new_architectures.append(arch)

        # Track by source
        source_type = arch.source_type
        if source_type not in results["by_source"]:
            results["by_source"][source_type] = 0
        results["by_source"][source_type] += 1

        click.echo(f"  {source_type}: {arch.name or arch.hash[:8]}")

    # Update the architecture index
    if new_architectures:
        update_architecture_index(artifacts_dir, architectures=new_architectures, logger=logger)
        click.echo(f"  Saved {results['saved_count']} architectures to artifacts")

    # Print summary by source
    for source_type, count in results["by_source"].items():
        click.echo(f"  {source_type}: {count} new")

    return results
