"""REST API server for accessing validation results."""

import json
import logging
from datetime import datetime
from pathlib import Path

try:
    from flask import Flask, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


class ResultsAPI:
    """Simple REST API for accessing validation results."""

    def __init__(
        self,
        artifacts_dir: Path,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.logger = logger

        if not FLASK_AVAILABLE:
            raise ImportError("Flask is required for the API server. Install with: pip install flask")

        self.app = Flask("lsqm-api")
        self._register_routes()

    def _register_routes(self) -> None:
        """Register API routes."""

        @self.app.route("/health")
        def health():
            return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

        @self.app.route("/api/v1/runs")
        def list_runs():
            """List all validation runs."""
            runs_dir = self.artifacts_dir / "runs"
            runs = []

            if runs_dir.exists():
                for run_dir in sorted(runs_dir.iterdir(), reverse=True):
                    if run_dir.is_dir():
                        summary_file = run_dir / "summary.json"
                        if summary_file.exists():
                            with open(summary_file) as f:
                                summary = json.load(f)
                            runs.append({
                                "run_id": run_dir.name,
                                "started_at": summary.get("started_at"),
                                "summary": summary.get("summary", {}),
                            })

            limit = request.args.get("limit", 20, type=int)
            return jsonify({"runs": runs[:limit], "total": len(runs)})

        @self.app.route("/api/v1/runs/<run_id>")
        def get_run(run_id: str):
            """Get details of a specific run."""
            run_dir = self.artifacts_dir / "runs" / run_id

            if not run_dir.exists():
                return jsonify({"error": "Run not found"}), 404

            # Load summary
            summary_file = run_dir / "summary.json"
            if summary_file.exists():
                with open(summary_file) as f:
                    summary = json.load(f)
            else:
                summary = {}

            # Load individual results
            results_dir = run_dir / "results"
            results = []

            if results_dir.exists():
                for result_file in results_dir.glob("*.json"):
                    with open(result_file) as f:
                        results.append(json.load(f))

            return jsonify({
                "run_id": run_id,
                "summary": summary,
                "results": results,
            })

        @self.app.route("/api/v1/runs/<run_id>/results/<arch_hash>")
        def get_result(run_id: str, arch_hash: str):
            """Get result for a specific architecture in a run."""
            result_file = self.artifacts_dir / "runs" / run_id / "results" / f"{arch_hash}.json"

            if not result_file.exists():
                return jsonify({"error": "Result not found"}), 404

            with open(result_file) as f:
                result = json.load(f)

            return jsonify(result)

        @self.app.route("/api/v1/architectures")
        def list_architectures():
            """List all architectures."""
            index_file = self.artifacts_dir / "architectures" / "index.json"

            if not index_file.exists():
                return jsonify({"architectures": [], "total": 0})

            with open(index_file) as f:
                index = json.load(f)

            # Apply filters
            services = request.args.get("services", "")
            if services:
                service_list = services.split(",")
                index = {
                    h: data for h, data in index.items()
                    if any(s in data.get("services", []) for s in service_list)
                }

            limit = request.args.get("limit", 100, type=int)
            offset = request.args.get("offset", 0, type=int)

            archs = list(index.items())[offset:offset + limit]

            return jsonify({
                "architectures": [
                    {"hash": h, **data} for h, data in archs
                ],
                "total": len(index),
                "limit": limit,
                "offset": offset,
            })

        @self.app.route("/api/v1/architectures/<arch_hash>")
        def get_architecture(arch_hash: str):
            """Get details of a specific architecture."""
            index_file = self.artifacts_dir / "architectures" / "index.json"

            if index_file.exists():
                with open(index_file) as f:
                    index = json.load(f)
                if arch_hash in index:
                    arch_data = index[arch_hash]

                    # Get latest validation result
                    latest_result = self._get_latest_result(arch_hash)

                    return jsonify({
                        "hash": arch_hash,
                        **arch_data,
                        "latest_result": latest_result,
                    })

            return jsonify({"error": "Architecture not found"}), 404

        @self.app.route("/api/v1/stats")
        def get_stats():
            """Get overall statistics."""
            return jsonify(self._compute_stats())

        @self.app.route("/api/v1/services")
        def list_services():
            """List all services with their compatibility stats."""
            return jsonify(self._get_service_stats())

        @self.app.route("/api/v1/qa/flaky-tests")
        def get_flaky_tests():
            """Get flaky test information."""
            stability_file = self.artifacts_dir / "qa" / "test_stability.json"

            if not stability_file.exists():
                return jsonify({"flaky_tests": [], "total": 0})

            with open(stability_file) as f:
                data = json.load(f)

            flaky = [
                {**record, "key": key}
                for key, record in data.items()
                if record.get("is_flaky", False)
            ]

            return jsonify({"flaky_tests": flaky, "total": len(flaky)})

        @self.app.route("/api/v1/qa/error-clusters")
        def get_error_clusters():
            """Get error cluster information."""
            clusters_file = self.artifacts_dir / "qa" / "error_clusters.json"

            if not clusters_file.exists():
                return jsonify({"clusters": [], "total": 0})

            with open(clusters_file) as f:
                data = json.load(f)

            clusters = sorted(
                data.values(),
                key=lambda c: c.get("occurrences", 0),
                reverse=True,
            )

            limit = request.args.get("limit", 20, type=int)
            return jsonify({"clusters": clusters[:limit], "total": len(clusters)})

        @self.app.route("/api/v1/qa/performance")
        def get_performance():
            """Get performance baseline information."""
            baselines_file = self.artifacts_dir / "qa" / "performance_baselines.json"

            if not baselines_file.exists():
                return jsonify({"baselines": {}, "summary": {}})

            with open(baselines_file) as f:
                data = json.load(f)

            # Group by metric type
            by_type: dict[str, list] = {}
            for _key, baseline in data.items():
                metric_type = baseline.get("metric_type", "unknown")
                if metric_type not in by_type:
                    by_type[metric_type] = []
                by_type[metric_type].append(baseline)

            summary = {
                metric_type: {
                    "count": len(baselines),
                    "avg_duration": sum(b["baseline_duration"] for b in baselines) / len(baselines)
                    if baselines else 0,
                }
                for metric_type, baselines in by_type.items()
            }

            return jsonify({"baselines": data, "summary": summary})

    def _get_latest_result(self, arch_hash: str) -> dict | None:
        """Get the latest validation result for an architecture."""
        runs_dir = self.artifacts_dir / "runs"

        if not runs_dir.exists():
            return None

        for run_dir in sorted(runs_dir.iterdir(), reverse=True):
            result_file = run_dir / "results" / f"{arch_hash}.json"
            if result_file.exists():
                with open(result_file) as f:
                    return json.load(f)

        return None

    def _compute_stats(self) -> dict:
        """Compute overall statistics."""
        stats = {
            "total_architectures": 0,
            "total_runs": 0,
            "latest_run": None,
            "overall_pass_rate": 0.0,
        }

        # Count architectures
        index_file = self.artifacts_dir / "architectures" / "index.json"
        if index_file.exists():
            with open(index_file) as f:
                stats["total_architectures"] = len(json.load(f))

        # Count runs and get latest
        runs_dir = self.artifacts_dir / "runs"
        if runs_dir.exists():
            runs = sorted(runs_dir.iterdir(), reverse=True)
            stats["total_runs"] = len(runs)

            if runs:
                latest_summary = runs[0] / "summary.json"
                if latest_summary.exists():
                    with open(latest_summary) as f:
                        summary = json.load(f)
                    stats["latest_run"] = {
                        "run_id": runs[0].name,
                        "summary": summary.get("summary", {}),
                    }

                    total = summary.get("summary", {}).get("total", 0)
                    passed = summary.get("summary", {}).get("passed", 0)
                    stats["overall_pass_rate"] = passed / total if total > 0 else 0

        return stats

    def _get_service_stats(self) -> dict:
        """Get service compatibility statistics."""
        service_stats: dict[str, dict] = {}

        runs_dir = self.artifacts_dir / "runs"
        if not runs_dir.exists():
            return {"services": service_stats}

        # Get latest run
        runs = sorted(runs_dir.iterdir(), reverse=True)
        if not runs:
            return {"services": service_stats}

        results_dir = runs[0] / "results"
        if not results_dir.exists():
            return {"services": service_stats}

        # Aggregate by service
        for result_file in results_dir.glob("*.json"):
            with open(result_file) as f:
                result = json.load(f)

            status = result.get("status", "UNKNOWN")
            services = result.get("services", [])

            for service in services:
                if service not in service_stats:
                    service_stats[service] = {"passed": 0, "failed": 0, "total": 0}

                service_stats[service]["total"] += 1
                if status == "PASSED":
                    service_stats[service]["passed"] += 1
                elif status in ["FAILED", "ERROR"]:
                    service_stats[service]["failed"] += 1

        # Calculate rates
        for _service, stats in service_stats.items():
            total = stats["total"]
            stats["pass_rate"] = stats["passed"] / total if total > 0 else 0

        return {
            "services": dict(sorted(
                service_stats.items(),
                key=lambda x: x[1]["total"],
                reverse=True,
            ))
        }

    def run(self, host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
        """Run the API server.

        Args:
            host: Host to bind to
            port: Port to listen on
            debug: Enable debug mode
        """
        if self.logger:
            self.logger.info(f"Starting API server on {host}:{port}")

        self.app.run(host=host, port=port, debug=debug)


def create_api_server(
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> "ResultsAPI":
    """Create an API server instance.

    Args:
        artifacts_dir: Path to artifacts directory
        logger: Optional logger

    Returns:
        ResultsAPI instance
    """
    return ResultsAPI(artifacts_dir, logger)


# API documentation
API_DOCS = """
# LSQM REST API

## Endpoints

### Health Check
- `GET /health` - Check API health

### Runs
- `GET /api/v1/runs` - List all validation runs
  - Query params: `limit` (default: 20)
- `GET /api/v1/runs/<run_id>` - Get run details
- `GET /api/v1/runs/<run_id>/results/<arch_hash>` - Get specific result

### Architectures
- `GET /api/v1/architectures` - List architectures
  - Query params: `limit`, `offset`, `services` (comma-separated)
- `GET /api/v1/architectures/<arch_hash>` - Get architecture details

### Statistics
- `GET /api/v1/stats` - Overall statistics
- `GET /api/v1/services` - Service compatibility stats

### Quality Assurance
- `GET /api/v1/qa/flaky-tests` - Get flaky test information
- `GET /api/v1/qa/error-clusters` - Get error cluster information
- `GET /api/v1/qa/performance` - Get performance baselines
"""
