"""Click CLI entry point for LSQM."""

import click

from lsqm import __version__
from lsqm.utils.config import load_config
from lsqm.utils.logging import get_logger


class Context:
    """Shared context for all CLI commands."""

    def __init__(self):
        self.config = None
        self.logger = None
        self.verbose = False
        self.dry_run = False


pass_context = click.make_pass_decorator(Context, ensure=True)


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True),
    help="Configuration file path",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable verbose output with structured JSON logging",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show actions without executing",
)
@click.option(
    "-p",
    "--parallel",
    type=int,
    default=None,
    help="Concurrency level (default: 4)",
)
@click.option(
    "--localstack-version",
    type=str,
    default=None,
    help="LocalStack image version (default: latest)",
)
@click.version_option(version=__version__, prog_name="lsqm")
@pass_context
def main(ctx, config_path, verbose, dry_run, parallel, localstack_version):
    """LocalStack Quality Monitor - Automated AWS infrastructure pattern discovery and validation."""
    from pathlib import Path

    # Load configuration
    config = load_config(Path(config_path) if config_path else None)

    # Apply CLI overrides
    config.verbose = verbose
    config.dry_run = dry_run
    if parallel is not None:
        config.parallel = parallel
    if localstack_version is not None:
        config.localstack_version = localstack_version

    # Set up context
    ctx.config = config
    ctx.verbose = verbose
    ctx.dry_run = dry_run
    ctx.logger = get_logger("lsqm", verbose=verbose)


# Import and register commands (must be after main to avoid circular imports)
from lsqm.commands import (  # noqa: E402
    clean,
    compare,
    generate,
    mine,
    notify,
    push,
    report,
    run,
    status,
    sync,
    validate,
)

main.add_command(run.run)
main.add_command(sync.sync)
main.add_command(mine.mine)
main.add_command(generate.generate)
main.add_command(validate.validate)
main.add_command(report.report)
main.add_command(push.push)
main.add_command(notify.notify)
main.add_command(compare.compare)
main.add_command(status.status)
main.add_command(clean.clean)


if __name__ == "__main__":
    main()
