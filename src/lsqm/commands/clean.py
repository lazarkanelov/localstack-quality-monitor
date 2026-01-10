"""Clean command - remove local cache and stale containers."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--containers/--no-containers", default=True, help="Remove stale LocalStack containers")
@click.option("--cache/--no-cache", default=True, help="Remove local cache")
@click.option("--all", "remove_all", is_flag=True, default=False, help="Remove everything including repo clone")
@pass_context
def clean(ctx, containers, cache, remove_all):
    """Remove local cache and stale containers."""
    if ctx.dry_run:
        click.echo("DRY RUN: Would clean up")
        click.echo(f"  Containers: {containers}")
        click.echo(f"  Cache: {cache}")
        click.echo(f"  All: {remove_all}")
        return

    result = _clean_impl(ctx, containers=containers, cache=cache, remove_all=remove_all)
    click.echo("")
    click.echo("Clean complete.")
    if result.get("containers_removed", 0) > 0:
        click.echo(f"  Removed {result['containers_removed']} stale containers")
    if result.get("cache_cleared"):
        click.echo(f"  Cleared cache: {result.get('cache_size_mb', 0):.1f}MB freed")


def _clean_impl(
    ctx, containers: bool = True, cache: bool = True, remove_all: bool = False
) -> dict:
    """Implementation of clean logic."""
    import shutil

    from lsqm.services.validator import cleanup_stale_containers
    from lsqm.utils.config import get_artifacts_dir, get_cache_dir

    logger = ctx.logger
    result = {"containers_removed": 0, "cache_cleared": False, "cache_size_mb": 0}

    click.echo("Cleaning up...")

    # Remove stale containers
    if containers:
        removed = cleanup_stale_containers(logger=logger)
        result["containers_removed"] = removed
        if removed > 0:
            click.echo(f"  Removed {removed} stale containers")

    # Clear cache
    if cache or remove_all:
        cache_dir = get_cache_dir()
        if cache_dir.exists():
            # Calculate size before clearing
            total_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
            result["cache_size_mb"] = total_size / (1024 * 1024)

            if remove_all:
                shutil.rmtree(cache_dir)
                click.echo(f"  Cleared all cache: {result['cache_size_mb']:.1f}MB freed")
            else:
                # Keep artifacts, clear temp files
                for item in cache_dir.iterdir():
                    if item.name != "artifacts":
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                click.echo("  Cleared temp cache")

            result["cache_cleared"] = True

    # Remove cloned repository if --all
    if remove_all:
        artifacts_dir = get_artifacts_dir()
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)
            click.echo("  Removed cloned artifact repository")

    return result
