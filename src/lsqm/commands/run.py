"""Run command - execute the full pipeline."""

import sys

import click

from lsqm.cli import pass_context
from lsqm.models import Run, RunConfig
from lsqm.utils.logging import stage_context


@click.command()
@pass_context
def run(ctx):
    """Execute the full pipeline: sync -> mine -> generate -> validate -> report -> push -> notify."""
    config = ctx.config
    logger = ctx.logger

    # Validate configuration
    valid, errors = config.validate()
    if not valid:
        for error in errors:
            click.echo(f"Configuration error: {error}", err=True)
        sys.exit(3)

    if ctx.dry_run:
        click.echo("DRY RUN: Would execute full pipeline")
        click.echo("  1. sync - Pull artifact repository")
        click.echo("  2. mine - Discover new architectures")
        click.echo("  3. generate - Generate test applications")
        click.echo("  4. validate - Run validations against LocalStack")
        click.echo("  5. report - Generate HTML dashboard")
        click.echo("  6. push - Push artifacts to repository")
        click.echo("  7. notify - Send Slack notification")
        return

    # Create run record
    pipeline_run = Run(
        localstack_version=config.localstack_version,
        config=RunConfig(
            parallel=config.parallel,
            timeout=config.timeout,
            token_budget=config.token_budget,
            dry_run=config.dry_run,
        ),
    )

    click.echo(f"Starting pipeline run: {pipeline_run.run_id}")
    click.echo(f"LocalStack version: {config.localstack_version}")

    exit_code = 0
    stages_status = {}

    # Execute stages with graceful degradation
    stages = [
        ("sync", _run_sync),
        ("mine", _run_mine),
        ("generate", _run_generate),
        ("validate", _run_validate),
        ("report", _run_report),
        ("push", _run_push),
        ("notify", _run_notify),
    ]

    for stage_name, stage_func in stages:
        try:
            with stage_context(stage_name, logger):
                result = stage_func(ctx, pipeline_run)
                stages_status[stage_name] = {"status": "success", "result": result}
        except Exception as e:
            logger.error(f"Stage {stage_name} failed: {e}")
            stages_status[stage_name] = {"status": "failed", "error": str(e)}
            # Continue with next stage (graceful degradation)
            if stage_name in ("sync", "mine"):
                # Critical stages - cannot continue
                exit_code = 4
                break
            else:
                exit_code = max(exit_code, 2)  # Partial success

    # Complete the run
    pipeline_run.complete()

    # Check for regressions
    if stages_status.get("validate", {}).get("status") == "success":
        if pipeline_run.summary.failed > 0 or pipeline_run.summary.error > 0:
            # Check if there are regressions vs previous run
            # For now, just mark as having failures
            if exit_code == 0:
                exit_code = 1  # Regressions detected

    # Print summary
    click.echo("")
    click.echo("Pipeline Summary")
    click.echo("=" * 40)
    click.echo(f"Run ID: {pipeline_run.run_id}")
    click.echo(f"Duration: {pipeline_run.summary.duration_seconds:.1f}s")
    click.echo(f"Architectures: {pipeline_run.summary.total}")
    click.echo(f"Passed: {pipeline_run.summary.passed}")
    click.echo(f"Failed: {pipeline_run.summary.failed}")
    click.echo(f"Pass rate: {pipeline_run.summary.pass_rate:.1f}%")

    if ctx.verbose:
        import json

        click.echo(json.dumps({
            "run_id": pipeline_run.run_id,
            "stages": stages_status,
            "summary": pipeline_run.summary.to_dict(),
        }, indent=2))

    sys.exit(exit_code)


def _run_sync(ctx, run: Run) -> dict:
    """Execute sync stage."""
    from lsqm.commands.sync import _sync_impl
    return _sync_impl(ctx)


def _run_mine(ctx, run: Run) -> dict:
    """Execute mine stage."""
    from lsqm.commands.mine import _mine_impl
    result = _mine_impl(ctx, limit=0)
    run.summary.new_architectures = result.get("new_count", 0)
    return result


def _run_generate(ctx, run: Run) -> dict:
    """Execute generate stage."""
    from lsqm.commands.generate import _generate_impl
    result = _generate_impl(ctx, budget=ctx.config.token_budget)
    run.summary.tokens_used = result.get("tokens_used", 0)
    return result


def _run_validate(ctx, run: Run) -> dict:
    """Execute validate stage."""
    from lsqm.commands.validate import _validate_impl
    result = _validate_impl(ctx, run_id=run.run_id)
    run.summary.total = result.get("total", 0)
    run.summary.passed = result.get("passed", 0)
    run.summary.partial = result.get("partial", 0)
    run.summary.failed = result.get("failed", 0)
    run.summary.timeout = result.get("timeout", 0)
    run.summary.error = result.get("error", 0)
    return result


def _run_report(ctx, run: Run) -> dict:
    """Execute report stage."""
    from lsqm.commands.report import _report_impl
    return _report_impl(ctx, run_id=run.run_id)


def _run_push(ctx, run: Run) -> dict:
    """Execute push stage."""
    from lsqm.commands.push import _push_impl
    return _push_impl(ctx, run=run)


def _run_notify(ctx, run: Run) -> dict:
    """Execute notify stage."""
    from lsqm.commands.notify import _notify_impl
    return _notify_impl(ctx, run=run)
