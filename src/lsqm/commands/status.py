"""Status command - show current statistics."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@pass_context
def status(ctx, output_format):
    """Show current statistics."""
    result = _status_impl(ctx)

    if output_format == "json":
        import json
        click.echo(json.dumps(result, indent=2))
    else:
        _print_status(result)


def _status_impl(ctx) -> dict:
    """Implementation of status logic."""
    from lsqm.services.git_ops import (
        load_architecture_index,
        load_run_results,
        load_service_trends,
    )
    from lsqm.utils.config import get_artifacts_dir

    artifacts_dir = get_artifacts_dir()

    # Load architecture index
    index = load_architecture_index(artifacts_dir)
    architectures = index.get("architectures", {})

    total_archs = len(architectures)
    with_apps = sum(1 for a in architectures.values() if a.get("has_app"))
    pending = sum(1 for a in architectures.values() if not a.get("has_app") and not a.get("skipped"))
    skipped = sum(1 for a in architectures.values() if a.get("skipped"))

    # Load latest run
    latest_run = load_run_results(artifacts_dir, "latest")
    run_info = {}
    if latest_run:
        summary = latest_run.get("summary", {})
        run_info = {
            "run_id": latest_run.get("run_id", ""),
            "date": latest_run.get("started_at", "")[:10],
            "pass_rate": (summary.get("passed", 0) / summary.get("total", 1) * 100)
            if summary.get("total", 0) > 0 else 0,
        }

    # Load service trends
    trends = load_service_trends(artifacts_dir)
    service_stats = []
    for service, data in sorted(trends.items(), key=lambda x: x[1].get("current_pass_rate", 0), reverse=True):
        service_stats.append({
            "name": service,
            "pass_rate": data.get("current_pass_rate", 0) * 100,
            "trend": data.get("trend", "stable"),
        })

    return {
        "architectures": {
            "total": total_archs,
            "with_apps": with_apps,
            "pending": pending,
            "skipped": skipped,
        },
        "latest_run": run_info,
        "services": service_stats[:10],  # Top 10 services
    }


def _print_status(result: dict) -> None:
    """Print status in text format."""
    click.echo("LocalStack Quality Monitor Status")
    click.echo("=" * 35)
    click.echo("")

    archs = result.get("architectures", {})
    click.echo("Architectures:")
    click.echo(f"  Total: {archs.get('total', 0)}")
    click.echo(f"  With apps: {archs.get('with_apps', 0)}")
    click.echo(f"  Pending generation: {archs.get('pending', 0)}")
    click.echo(f"  Skipped: {archs.get('skipped', 0)}")
    click.echo("")

    run_info = result.get("latest_run", {})
    if run_info:
        click.echo("Latest Run:")
        click.echo(f"  Date: {run_info.get('date', 'unknown')} ({run_info.get('run_id', '')[:8]})")
        click.echo(f"  Pass rate: {run_info.get('pass_rate', 0):.0f}%")
        click.echo("")

    services = result.get("services", [])
    if services:
        click.echo("Top Services:")
        for svc in services[:5]:
            trend_icon = {"improving": "↑", "declining": "↓", "stable": "→"}.get(svc.get("trend", "stable"), "→")
            click.echo(f"  {svc['name']}: {svc['pass_rate']:.0f}% {trend_icon}")
