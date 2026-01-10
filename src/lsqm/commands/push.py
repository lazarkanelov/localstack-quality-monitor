"""Push command - push artifacts to GitHub repository."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--skip-issues", is_flag=True, default=False, help="Don't create GitHub issues")
@click.option("--message", type=str, default=None, help="Custom commit message")
@pass_context
def push(ctx, skip_issues, message):
    """Push artifacts to GitHub repository."""
    if ctx.dry_run:
        click.echo("DRY RUN: Would push artifacts")
        click.echo(f"  Skip issues: {skip_issues}")
        click.echo(f"  Message: {message or 'auto-generated'}")
        return

    result = _push_impl(ctx, skip_issues=skip_issues, message=message)
    click.echo(f"Commit: {result.get('commit_sha', 'none')[:7]} \"{result.get('commit_message', '')}\"")
    if result.get("issues_created", 0) > 0:
        click.echo(f"Created {result['issues_created']} GitHub issues for regressions")
    click.echo("Push complete.")


def _push_impl(
    ctx,
    run=None,
    skip_issues: bool = False,
    message: str | None = None,
) -> dict:
    """Implementation of push logic."""
    from lsqm.services.git_ops import (
        create_regression_issues,
        delete_old_runs,
        push_artifacts,
        update_architecture_index,
        update_trends,
    )
    from lsqm.utils.config import get_artifacts_dir

    config = ctx.config
    logger = ctx.logger

    click.echo("Pushing artifacts...")

    artifacts_dir = get_artifacts_dir()

    # Check if artifacts directory is a valid git repo
    if not artifacts_dir.exists() or not (artifacts_dir / ".git").exists():
        click.echo("No artifacts repository found. Run 'lsqm sync' first.")
        return {
            "commit_sha": "",
            "commit_message": "",
            "new_architectures": 0,
            "issues_created": 0,
        }

    # Update architecture index
    new_archs = update_architecture_index(artifacts_dir, logger=logger)
    click.echo(f"  New architectures: {new_archs}")

    # Update trends
    update_trends(artifacts_dir, logger=logger)

    # Delete old runs (keep last 52)
    deleted = delete_old_runs(artifacts_dir, keep=52, logger=logger)
    if deleted > 0:
        click.echo(f"  Deleted old runs: {deleted}")

    # Generate commit message
    if message is None and run:
        summary = run.summary
        message = (
            f"Run {run.started_at.strftime('%Y-%m-%d')}: "
            f"{summary.total} archs, {summary.pass_rate:.0f}% pass"
        )
        if summary.failed > 0:
            message += f", {summary.failed} failed"

    # Create issues for regressions
    issues_created = 0
    if not skip_issues:
        issues = create_regression_issues(
            artifacts_dir=artifacts_dir,
            repo=config.issue_repo,
            token=config.github_token,
            logger=logger,
        )
        issues_created = len(issues)
        for issue_url in issues:
            click.echo(f"  Issue: {issue_url}")

    # Push to remote
    result = push_artifacts(
        artifacts_dir=artifacts_dir,
        message=message or "LSQM run update",
        token=config.github_token,
        logger=logger,
    )

    return {
        "commit_sha": result.get("commit_sha", ""),
        "commit_message": message,
        "new_architectures": new_archs,
        "issues_created": issues_created,
    }
