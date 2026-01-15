"""QA command group - quality assurance tools."""

import json
from pathlib import Path

import click

from lsqm.utils import get_artifacts_dir, get_logger


@click.group("qa")
@click.pass_context
def qa_group(ctx):
    """Quality assurance tools and reports."""
    pass


@qa_group.command("flaky")
@click.option("--arch", "-a", help="Filter by architecture hash")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def flaky_tests(ctx, arch, json_output):
    """Show flaky test detection results."""
    logger = get_logger("lsqm.qa.flaky", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.flaky_detector import FlakyTestDetector

    detector = FlakyTestDetector(artifacts_dir, logger)
    report = detector.get_stability_report(arch)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        click.echo(f"Total tests tracked: {report['total_tests_tracked']}")
        click.echo(f"Flaky tests: {report['flaky_tests_count']}")
        click.echo(f"Stable tests: {report['stable_tests_count']}")
        click.echo(f"Average pass rate: {report['average_pass_rate']:.1%}")

        if report["flaky_tests"]:
            click.echo("\nFlaky Tests:")
            for test in report["flaky_tests"]:
                click.echo(f"  - {test['test_name']} ({test['arch_hash'][:8]})")
                click.echo(f"    Pass rate: {test['pass_rate']:.1%} over {test['total_runs']} runs")


@qa_group.command("errors")
@click.option("--type", "-t", "error_type", help="Filter by error type")
@click.option("--limit", "-l", default=10, help="Max clusters to show")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def error_clusters(ctx, error_type, limit, json_output):
    """Show error clusters and root cause analysis."""
    logger = get_logger("lsqm.qa.errors", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.root_cause import RootCauseAnalyzer

    analyzer = RootCauseAnalyzer(artifacts_dir, logger)
    report = analyzer.get_report()

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        click.echo(f"Total error clusters: {report['total_error_clusters']}")
        click.echo(f"Total occurrences: {report['total_occurrences']}")
        click.echo(f"Architectures affected: {report['unique_architectures_affected']}")

        click.echo("\nErrors by type:")
        for err_type, data in report["errors_by_type"].items():
            click.echo(
                f"  {err_type}: {data['cluster_count']} clusters, {data['total_occurrences']} occurrences"
            )

        if report["actionable_fixes"]:
            click.echo("\nActionable fixes:")
            for fix in report["actionable_fixes"][:limit]:
                click.echo(f"  - [{fix['error_type']}] {fix['pattern'][:40]}...")
                click.echo(f"    Root cause: {fix['root_cause']}")
                click.echo(f"    Fix: {fix['suggested_fix']}")
                click.echo()


@qa_group.command("performance")
@click.option("--arch", "-a", help="Filter by architecture hash")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def performance(ctx, arch, json_output):
    """Show performance baselines and trends."""
    logger = get_logger("lsqm.qa.perf", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.performance import PerformanceTracker, format_duration

    tracker = PerformanceTracker(artifacts_dir, logger)
    report = tracker.get_performance_report()

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        click.echo(f"Total metrics tracked: {report['total_metrics_tracked']}")
        click.echo(f"Unique architectures: {report['unique_architectures']}")

        click.echo("\nMetrics by type:")
        for metric_type, data in report["metrics_by_type"].items():
            avg = format_duration(data["avg_duration_seconds"])
            click.echo(f"  {metric_type}: {data['count']} samples, avg {avg}")

        if report["degrading_operations"]:
            click.echo("\nDegrading operations:")
            for op in report["degrading_operations"][:5]:
                click.echo(
                    f"  - {op['arch_hash'][:8]} {op['metric_type']}: +{op['increase_pct']:.1f}%"
                )

        if report["improving_operations"]:
            click.echo("\nImproving operations:")
            for op in report["improving_operations"][:5]:
                click.echo(
                    f"  - {op['arch_hash'][:8]} {op['metric_type']}: -{op['decrease_pct']:.1f}%"
                )


@qa_group.command("gates")
@click.option("--run-id", "-r", help="Run ID to evaluate")
@click.option("--config", "-c", type=click.Path(exists=True), help="Quality gate config file")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def quality_gates(ctx, run_id, config, json_output):
    """Evaluate quality gates for a run."""
    logger = get_logger("lsqm.qa.gates", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.flaky_detector import FlakyTestDetector
    from lsqm.services.quality_gates import (
        QualityGateEvaluator,
        create_quality_gate_report,
    )

    # Load run summary
    if run_id:
        run_dir = artifacts_dir / "runs" / run_id
    else:
        # Get latest run
        runs_dir = artifacts_dir / "runs"
        if runs_dir.exists():
            runs = sorted(runs_dir.iterdir(), reverse=True)
            if runs:
                run_dir = runs[0]
                run_id = run_dir.name
            else:
                click.echo("No runs found")
                return
        else:
            click.echo("No runs directory found")
            return

    summary_file = run_dir / "summary.json"
    if not summary_file.exists():
        click.echo(f"No summary found for run {run_id}")
        return

    with open(summary_file) as f:
        summary = json.load(f)

    # Get flaky tests
    detector = FlakyTestDetector(artifacts_dir, logger)
    flaky_tests = detector.get_flaky_tests()

    # Create evaluator
    if config:
        evaluator = QualityGateEvaluator.from_config_file(Path(config), logger)
    else:
        evaluator = QualityGateEvaluator(logger=logger)

    # Evaluate
    result = evaluator.evaluate(
        run_summary=summary.get("summary", {}),
        flaky_tests=flaky_tests,
    )

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        report = create_quality_gate_report(result)
        click.echo(report)


@qa_group.command("cache")
@click.option("--clear", is_flag=True, help="Clear all cache entries")
@click.option("--arch", "-a", help="Clear specific architecture")
@click.option("--stats", is_flag=True, help="Show cache statistics")
@click.pass_context
def cache(ctx, clear, arch, stats):
    """Manage incremental validation cache."""
    logger = get_logger("lsqm.qa.cache", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.incremental import IncrementalValidator

    validator = IncrementalValidator(artifacts_dir, logger=logger)

    if clear:
        count = validator.clear_cache(arch)
        click.echo(f"Cleared {count} cache entries")
    elif stats:
        # Load cache file directly for stats
        cache_file = artifacts_dir / "qa" / "validation_cache.json"
        if cache_file.exists():
            with open(cache_file) as f:
                cache_data = json.load(f)

            total = len(cache_data)
            passed = sum(1 for c in cache_data.values() if c.get("last_status") == "PASSED")
            failed = sum(
                1 for c in cache_data.values() if c.get("last_status") in ["FAILED", "ERROR"]
            )

            click.echo(f"Total cached: {total}")
            click.echo(f"Passed: {passed}")
            click.echo(f"Failed: {failed}")
            click.echo(f"Other: {total - passed - failed}")
        else:
            click.echo("No cache file found")
    else:
        click.echo("Use --clear to clear cache or --stats to view statistics")


@qa_group.command("api")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", "-p", default=8080, help="Port to listen on")
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.pass_context
def api_server(ctx, host, port, debug):
    """Start the REST API server."""
    logger = get_logger("lsqm.qa.api", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    try:
        from lsqm.services.api_server import ResultsAPI

        api = ResultsAPI(artifacts_dir, logger)
        click.echo(f"Starting API server on {host}:{port}")
        click.echo("Endpoints:")
        click.echo("  GET /health - Health check")
        click.echo("  GET /api/v1/runs - List runs")
        click.echo("  GET /api/v1/architectures - List architectures")
        click.echo("  GET /api/v1/stats - Overall statistics")
        click.echo("  GET /api/v1/qa/flaky-tests - Flaky test info")
        click.echo("  GET /api/v1/qa/error-clusters - Error clusters")
        api.run(host=host, port=port, debug=debug)

    except ImportError as e:
        click.echo(f"Error: {e}")
        click.echo("Install Flask with: pip install flask")


@qa_group.command("worker")
@click.option("--id", "worker_id", help="Worker ID (auto-generated if not provided)")
@click.pass_context
def start_worker(ctx, worker_id):
    """Start a distributed validation worker."""
    import asyncio

    logger = get_logger("lsqm.qa.worker", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.distributed import DistributedWorker

    # Placeholder validation function
    async def validate_func(arch_hash, arch_data, run_id, version, timeout):
        logger.info(f"Validating {arch_hash[:8]}")
        # This would call the actual validator
        return {"status": "PASSED"}

    worker = DistributedWorker(
        artifacts_dir=artifacts_dir,
        validate_func=validate_func,
        worker_id=worker_id,
        logger=logger,
    )

    click.echo(f"Starting worker {worker.worker_id}")
    asyncio.run(worker.run())


@qa_group.command("versions")
@click.option("--pull", is_flag=True, help="Pull LocalStack images")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def version_matrix(ctx, pull, json_output):
    """Show multi-version test matrix."""
    logger = get_logger("lsqm.qa.versions", ctx.obj.get("verbose", False))
    artifacts_dir = get_artifacts_dir()

    from lsqm.services.multi_version import (
        DEFAULT_VERSIONS,
        MultiVersionTester,
        get_available_versions,
    )

    tester = MultiVersionTester(artifacts_dir=artifacts_dir, logger=logger)

    if pull:
        click.echo("Pulling LocalStack images...")
        available = get_available_versions(DEFAULT_VERSIONS)
        click.echo(f"Available versions: {', '.join(available)}")
    else:
        report = tester.get_summary_report()

        if json_output:
            click.echo(json.dumps(report, indent=2))
        else:
            click.echo(f"Total architectures tested: {report['total_architectures_tested']}")
            click.echo(f"Versions tested: {', '.join(report['versions_tested'])}")

            if report.get("version_compatibility"):
                click.echo("\nVersion compatibility:")
                for version, data in report["version_compatibility"].items():
                    rate = data["compatibility_rate"]
                    click.echo(f"  {version}: {rate:.1%} compatible")

            if report.get("most_compatible_version"):
                click.echo(f"\nMost compatible: {report['most_compatible_version']}")
