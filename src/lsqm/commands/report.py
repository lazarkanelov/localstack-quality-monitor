"""Report command - generate HTML compatibility dashboard."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--output", type=click.Path(), default="reports/latest", help="Output directory")
@click.option("--run", "run_id", type=str, default="latest", help="Run ID to report on")
@pass_context
def report(ctx, output, run_id):
    """Generate HTML compatibility dashboard."""
    if ctx.dry_run:
        click.echo("DRY RUN: Would generate report")
        click.echo(f"  Output: {output}")
        click.echo(f"  Run: {run_id}")
        return

    result = _report_impl(ctx, output_dir=output, run_id=run_id)
    click.echo(f"Report generated: {result['path']}")
    click.echo(f"  - Summary: {result['total']} architectures, {result['pass_rate']:.0f}% pass rate")
    if result.get("regressions", 0) > 0:
        click.echo(f"  - Regressions: {result['regressions']} detected")


def _report_impl(
    ctx, output_dir: str = "reports/latest", run_id: str = "latest"
) -> dict:
    """Implementation of report logic."""
    from pathlib import Path

    from lsqm.services.git_ops import load_run_results
    from lsqm.services.reporter import generate_html_report
    from lsqm.utils.config import get_artifacts_dir

    logger = ctx.logger

    click.echo("Generating compatibility report...")

    artifacts_dir = get_artifacts_dir()

    # Load run results
    run_data = load_run_results(artifacts_dir, run_id)
    if not run_data:
        click.echo(f"No data available for run: {run_id}")
        return {"path": "", "total": 0, "pass_rate": 0, "regressions": 0}

    click.echo(f"Run: {run_data.get('run_id', run_id)}")
    click.echo(f"Date: {run_data.get('started_at', 'unknown')}")

    # Generate HTML report
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    report_path = generate_html_report(
        run_data=run_data,
        artifacts_dir=artifacts_dir,
        output_dir=output_path,
        logger=logger,
    )

    summary = run_data.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    pass_rate = (passed / total * 100) if total > 0 else 0

    return {
        "path": str(report_path),
        "total": total,
        "pass_rate": pass_rate,
        "regressions": run_data.get("regressions_count", 0),
    }
