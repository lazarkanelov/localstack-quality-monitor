"""Validate command - run validations against LocalStack."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--arch", type=str, default=None, help="Validate specific architecture")
@click.option("--timeout", type=int, default=300, help="Timeout per validation (seconds)")
@click.option("--parallel", type=int, default=None, help="Number of parallel validations")
@click.option("--keep-containers", is_flag=True, default=False, help="Don't cleanup containers")
@pass_context
def validate(ctx, arch, timeout, parallel, keep_containers):
    """Run validations against LocalStack."""
    # Use CLI option if provided, otherwise use config
    if parallel is not None:
        ctx.config.parallel = parallel

    if ctx.dry_run:
        click.echo("DRY RUN: Would validate architectures")
        click.echo(f"  Architecture: {arch or 'all with apps'}")
        click.echo(f"  Timeout: {timeout}s")
        click.echo(f"  Parallel: {ctx.config.parallel}")
        click.echo(f"  Keep containers: {keep_containers}")
        return

    result = _validate_impl(
        ctx,
        arch_hash=arch,
        timeout=timeout,
        keep_containers=keep_containers,
    )

    click.echo("")
    click.echo("Summary:")
    click.echo(f"  Passed: {result['passed']}")
    click.echo(f"  Partial: {result['partial']}")
    click.echo(f"  Failed: {result['failed']}")
    click.echo(f"  Timeout: {result['timeout']}")
    click.echo(f"  Error: {result['error']}")


def _validate_impl(
    ctx,
    run_id: str | None = None,
    arch_hash: str | None = None,
    timeout: int = 300,
    keep_containers: bool = False,
) -> dict:
    """Implementation of validate logic."""
    from uuid import uuid4

    from lsqm.services.git_ops import load_architecture_index
    from lsqm.services.validator import validate_architectures
    from lsqm.utils.config import get_artifacts_dir

    config = ctx.config
    logger = ctx.logger

    if run_id is None:
        run_id = str(uuid4())

    click.echo(f"Validating architectures (parallel: {config.parallel})...")

    # Load architecture index
    artifacts_dir = get_artifacts_dir()
    index = load_architecture_index(artifacts_dir)
    architectures = index.get("architectures", {})

    # Filter architectures to validate
    to_validate = []
    for hash_id, arch_data in architectures.items():
        if arch_data.get("skipped"):
            continue
        if not arch_data.get("has_app"):
            continue
        if arch_hash and hash_id != arch_hash:
            continue
        to_validate.append((hash_id, arch_data))

    if not to_validate:
        click.echo("No architectures to validate")
        return {
            "total": 0,
            "passed": 0,
            "partial": 0,
            "failed": 0,
            "timeout": 0,
            "error": 0,
        }

    # Run validations
    results = validate_architectures(
        architectures=to_validate,
        run_id=run_id,
        localstack_version=config.localstack_version,
        parallel=config.parallel,
        timeout=timeout,
        keep_containers=keep_containers,
        artifacts_dir=artifacts_dir,
        logger=logger,
    )

    # Print progress
    for i, vr in enumerate(results.get("validation_results", []), 1):
        status = vr.status.value
        duration = vr.duration_seconds
        name = architectures.get(vr.arch_hash, {}).get("name", vr.arch_hash[:8])
        click.echo(f"  [{i}/{len(to_validate)}] {vr.arch_hash[:8]} {name}: {status} ({duration:.0f}s)")
        if vr.pytest_results and vr.pytest_results.failed > 0:
            click.echo(f"    └─ {vr.pytest_results.failed}/{vr.pytest_results.total} tests failed")

    return results
