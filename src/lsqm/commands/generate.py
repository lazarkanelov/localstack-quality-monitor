"""Generate command - generate Python test applications using Claude API."""

import click

from lsqm.cli import pass_context


@click.command()
@click.option("--budget", type=int, default=500000, help="Token budget")
@click.option("--arch", type=str, default=None, help="Generate for specific architecture hash")
@click.option("--force", is_flag=True, default=False, help="Regenerate existing apps")
@pass_context
def generate(ctx, budget, arch, force):
    """Generate Python test applications using Claude API."""
    if ctx.dry_run:
        click.echo("DRY RUN: Would generate test applications")
        click.echo(f"  Budget: {budget} tokens")
        click.echo(f"  Architecture: {arch or 'all pending'}")
        click.echo(f"  Force: {force}")
        return

    result = _generate_impl(ctx, budget=budget, arch_hash=arch, force=force)
    click.echo(f"Generated: {result['generated_count']} apps")
    click.echo(f"Tokens used: {result['tokens_used']} / {budget}")
    if result.get("remaining", 0) > 0:
        click.echo(f"Remaining: {result['remaining']} architectures")


def _generate_impl(
    ctx, budget: int = 500000, arch_hash: str | None = None, force: bool = False
) -> dict:
    """Implementation of generate logic."""
    from lsqm.services.generator import generate_test_apps
    from lsqm.services.git_ops import load_architecture_index
    from lsqm.utils.config import get_artifacts_dir

    config = ctx.config
    logger = ctx.logger

    click.echo("Generating test applications...")

    # Load architecture index
    artifacts_dir = get_artifacts_dir()
    index = load_architecture_index(artifacts_dir)
    architectures = index.get("architectures", {})

    # Filter architectures to generate for
    to_generate = []
    for hash_id, arch_data in architectures.items():
        if arch_data.get("skipped"):
            continue
        if arch_hash and hash_id != arch_hash:
            continue
        if not force and arch_data.get("has_app"):
            continue
        to_generate.append((hash_id, arch_data))

    if not to_generate:
        click.echo("No architectures to generate apps for")
        return {"generated_count": 0, "tokens_used": 0, "remaining": 0}

    # Generate apps
    result = generate_test_apps(
        architectures=to_generate,
        api_key=config.anthropic_api_key,
        budget=budget,
        artifacts_dir=artifacts_dir,
        logger=logger,
    )

    # Print progress
    for gen_result in result.get("results", []):
        status = "Generated" if gen_result["success"] else "Failed"
        tokens = gen_result.get("tokens", 0)
        click.echo(f"  [{gen_result['hash']}] {gen_result['name']}: {status} ({tokens} tokens)")

    return result
