"""Sync command - pull existing artifacts from GitHub repository."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--force", is_flag=True, default=False, help="Force fresh clone")
@pass_context
def sync(ctx, force):
    """Pull existing artifacts from GitHub repository."""
    if ctx.dry_run:
        click.echo("DRY RUN: Would sync artifact repository")
        click.echo(f"  Repository: {ctx.config.artifact_repo}")
        click.echo(f"  Force: {force}")
        return

    result = _sync_impl(ctx, force=force)
    click.echo(f"Sync complete. Architectures loaded: {result.get('architectures_count', 0)}")


def _sync_impl(ctx, force: bool = False) -> dict:
    """Implementation of sync logic."""
    from lsqm.services.git_ops import clone_or_pull_artifacts, load_architecture_index

    config = ctx.config
    logger = ctx.logger

    click.echo("Syncing artifact repository...")
    click.echo(f"Repository: {config.artifact_repo}")

    # Clone or pull the artifact repository
    artifacts_dir = clone_or_pull_artifacts(
        repo=config.artifact_repo,
        token=config.github_token,
        force=force,
        logger=logger,
    )

    # Load architecture index
    index = load_architecture_index(artifacts_dir)
    architectures_count = len(index.get("architectures", {}))

    latest_run = index.get("latest_run")
    if latest_run:
        click.echo(f"Latest run: {latest_run}")

    click.echo(f"Architectures loaded: {architectures_count}")

    return {
        "artifacts_dir": str(artifacts_dir),
        "architectures_count": architectures_count,
        "latest_run": latest_run,
    }
