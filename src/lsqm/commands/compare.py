"""Compare command - compare two runs and detect regressions."""

import sys

import click

from lsqm.cli import pass_context


@click.command()
@click.argument("run_id", default="previous")
@click.option("--current", type=str, default="latest", help="Current run ID")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@pass_context
def compare(ctx, run_id, current, output_format):
    """Compare two runs and detect regressions."""
    if ctx.dry_run:
        click.echo("DRY RUN: Would compare runs")
        click.echo(f"  Current: {current}")
        click.echo(f"  Previous: {run_id}")
        return

    result = _compare_impl(ctx, current_run=current, previous_run=run_id)

    if output_format == "json":
        import json

        click.echo(json.dumps(result, indent=2))
    else:
        _print_comparison(result)

    # Exit with code 1 if regressions detected
    if result.get("regressions", []):
        sys.exit(1)


def _compare_impl(ctx, current_run: str = "latest", previous_run: str = "previous") -> dict:
    """Implementation of compare logic."""
    from lsqm.services.comparator import compare_runs
    from lsqm.services.git_ops import load_run_results
    from lsqm.utils.config import get_artifacts_dir

    logger = ctx.logger

    click.echo("Comparing runs...")

    artifacts_dir = get_artifacts_dir()

    # Load run results
    current_data = load_run_results(artifacts_dir, current_run)
    previous_data = load_run_results(artifacts_dir, previous_run)

    if not current_data:
        click.echo(f"Current run not found: {current_run}")
        return {"error": "Current run not found"}
    if not previous_data:
        click.echo(f"Previous run not found: {previous_run}")
        return {"error": "Previous run not found"}

    click.echo(
        f"  Current: {current_data.get('run_id', current_run)[:8]} ({current_data.get('started_at', 'unknown')[:10]})"
    )
    click.echo(
        f"  Previous: {previous_data.get('run_id', previous_run)[:8]} ({previous_data.get('started_at', 'unknown')[:10]})"
    )

    # Compare runs
    result = compare_runs(
        current_results=current_data.get("results", {}),
        previous_results=previous_data.get("results", {}),
        current_run_id=current_data.get("run_id", current_run),
        previous_run_id=previous_data.get("run_id", previous_run),
        logger=logger,
    )

    return result


def _print_comparison(result: dict) -> None:
    """Print comparison results in text format."""
    regressions = result.get("regressions", [])
    fixes = result.get("fixes", [])

    click.echo("")
    if regressions:
        click.echo(f"Regressions ({len(regressions)}):")
        for r in regressions:
            click.echo(
                f"  - {r['arch_hash'][:8]} {r.get('name', '')}: {r['from_status']} → {r['to_status']}"
            )

    if fixes:
        click.echo(f"Fixes ({len(fixes)}):")
        for f in fixes:
            click.echo(
                f"  - {f['arch_hash'][:8]} {f.get('name', '')}: {f['from_status']} → {f['to_status']}"
            )

    click.echo("")
    click.echo(f"Summary: {len(regressions)} regressions, {len(fixes)} fixes")
