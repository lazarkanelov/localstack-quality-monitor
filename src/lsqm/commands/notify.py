"""Notify command - send Slack notification."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--run", "run_id", type=str, default="latest", help="Run ID to notify about")
@click.option("--webhook", type=str, default=None, help="Override webhook URL")
@pass_context
def notify(ctx, run_id, webhook):
    """Send Slack notification with results summary."""
    config = ctx.config
    webhook_url = webhook or config.slack_webhook_url

    if not webhook_url:
        click.echo("Slack webhook not configured. Skipping notification.")
        return

    if ctx.dry_run:
        click.echo("DRY RUN: Would send Slack notification")
        click.echo(f"  Run: {run_id}")
        click.echo(f"  Webhook: {webhook_url[:30]}...")
        return

    result = _notify_impl(ctx, run_id=run_id, webhook_url=webhook_url)
    if result.get("success"):
        click.echo("Notification sent.")
    else:
        click.echo(f"Notification failed: {result.get('error', 'unknown')}")


def _notify_impl(
    ctx, run=None, run_id: str = "latest", webhook_url: str | None = None
) -> dict:
    """Implementation of notify logic."""
    from lsqm.services.git_ops import load_run_results
    from lsqm.services.notifier import send_slack_notification
    from lsqm.utils.config import get_artifacts_dir

    config = ctx.config
    logger = ctx.logger

    webhook = webhook_url or config.slack_webhook_url
    if not webhook:
        return {"success": False, "error": "Webhook not configured"}

    click.echo("Sending Slack notification...")

    # Load run data
    if run:
        run_data = run.to_dict()
    else:
        artifacts_dir = get_artifacts_dir()
        run_data = load_run_results(artifacts_dir, run_id)
        if not run_data:
            return {"success": False, "error": f"Run not found: {run_id}"}

    # Send notification
    result = send_slack_notification(
        webhook_url=webhook,
        run_data=run_data,
        artifact_repo=config.artifact_repo,
        logger=logger,
    )

    summary = run_data.get("summary", {})
    click.echo(f"  Run: {run_data.get('run_id', run_id)[:8]}")
    click.echo(f"  Pass rate: {summary.get('passed', 0)}/{summary.get('total', 0)}")

    return result
