"""HTML report generation using Jinja2."""

import json
import logging
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def generate_html_report(
    run_data: dict,
    artifacts_dir: Path,
    output_dir: Path,
    logger: logging.Logger | None = None,
) -> Path:
    """Generate HTML compatibility dashboard.

    Args:
        run_data: Run results data
        artifacts_dir: Path to artifacts directory
        output_dir: Output directory for report
        logger: Logger instance

    Returns:
        Path to generated report
    """
    # Load template
    templates_dir = Path(__file__).parent.parent / "templates"

    if templates_dir.exists():
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("report.html.j2")
    else:
        # Use inline template if file doesn't exist
        template_content = _get_inline_template()
        env = Environment(autoescape=select_autoescape(["html"]))
        template = env.from_string(template_content)

    # Prepare template context
    summary = run_data.get("summary", {})
    results = run_data.get("results", {})

    # Calculate pass rate
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    pass_rate = (passed / total * 100) if total > 0 else 0

    # Load architecture index for names
    index = _load_architecture_index(artifacts_dir)
    architectures = index.get("architectures", {})

    # Get artifact repo URL from environment
    artifact_repo = os.environ.get("ARTIFACT_REPO", "")
    artifact_repo_url = f"https://github.com/{artifact_repo}" if artifact_repo else ""

    # Track totals for tests and service stats
    total_tests = 0
    total_tests_passed = 0
    total_tests_failed = 0
    service_counts: dict[str, dict[str, int]] = {}  # {service: {passed: N, failed: N}}

    # Prepare results for template
    result_rows = []
    for arch_hash, result in results.items():
        arch_data = architectures.get(arch_hash, {})
        services = arch_data.get("services", [])
        status = result.get("status", "UNKNOWN")

        # Get pytest results
        pytest_results = result.get("pytest_results") or {}
        pytest_passed = pytest_results.get("passed", 0)
        pytest_failed = pytest_results.get("failed", 0)
        pytest_output = pytest_results.get("output", "")

        # Accumulate test totals
        total_tests += pytest_passed + pytest_failed
        total_tests_passed += pytest_passed
        total_tests_failed += pytest_failed

        # Track per-service stats
        for svc in services:
            if svc not in service_counts:
                service_counts[svc] = {"passed": 0, "failed": 0}
            if status == "PASSED":
                service_counts[svc]["passed"] += 1
            elif status in ("FAILED", "TIMEOUT", "ERROR"):
                service_counts[svc]["failed"] += 1

        # Load terraform files for this architecture
        terraform_files = _load_terraform_files(artifacts_dir, arch_hash)

        # Load app files (generated test code)
        app_files = _load_app_files(artifacts_dir, arch_hash)

        # Extract test features from app code
        test_features = _extract_test_features(app_files)

        # Extract test cases (use cases) from test files
        test_cases = _extract_test_cases(app_files)

        # Get terraform apply output
        terraform_apply = result.get("terraform_apply") or {}
        terraform_output = _strip_ansi(terraform_apply.get("logs", ""))

        # Build artifact URLs for this architecture
        arch_artifact_url = f"{artifact_repo_url}/tree/main/architectures/{arch_hash}" if artifact_repo_url else ""
        app_artifact_url = f"{artifact_repo_url}/tree/main/apps/{arch_hash}" if artifact_repo_url else ""

        # Analyze failures for LocalStack quality insights
        container_logs = result.get("container_logs", "")
        failure_analysis = analyze_failure(
            status=status,
            terraform_output=terraform_output,
            container_logs=container_logs,
            error_message=result.get("error_message"),
        )

        result_rows.append({
            "hash": arch_hash,
            "name": arch_data.get("name", arch_hash[:8]),
            "services": services,
            "status": status,
            "duration": result.get("duration_seconds", 0),
            "pytest_passed": pytest_passed,
            "pytest_failed": pytest_failed,
            "pytest_output": pytest_output,
            "terraform_output": terraform_output,
            "logs": container_logs,  # Full logs - no truncation
            "terraform_files": terraform_files,
            "app_files": app_files,
            "test_features": test_features,
            "test_cases": test_cases,
            "source_url": arch_data.get("source_url", ""),
            "source_type": arch_data.get("source_type", ""),
            "original_format": arch_data.get("original_format", "terraform"),
            "arch_artifact_url": arch_artifact_url,
            "app_artifact_url": app_artifact_url,
            "failure_analysis": failure_analysis,
        })

    # Calculate test pass rate
    test_pass_rate = (total_tests_passed / total_tests * 100) if total_tests > 0 else 0

    # Build service stats for template
    service_stats = []
    for svc_name, counts in service_counts.items():
        svc_total = counts["passed"] + counts["failed"]
        svc_pass_rate = (counts["passed"] / svc_total * 100) if svc_total > 0 else 0
        service_stats.append({
            "name": svc_name,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "pass_rate": svc_pass_rate,
        })
    service_stats.sort(key=lambda s: s["pass_rate"], reverse=True)

    # Sort by status (failures first)
    status_order = {"FAILED": 0, "TIMEOUT": 1, "ERROR": 2, "PARTIAL": 3, "PASSED": 4}
    result_rows.sort(key=lambda r: status_order.get(r["status"], 5))

    # Load service trends
    service_trends = _load_service_trends(artifacts_dir)

    # Load regression data
    regressions = _load_regressions(artifacts_dir)

    # Load run history for charts
    run_history = _load_run_history(artifacts_dir, limit=12)

    context = {
        "run_id": run_data.get("run_id", "unknown"),
        "run_date": run_data.get("started_at", "")[:10],
        "localstack_version": run_data.get("localstack_version", "latest"),
        "total": total,
        "passed": passed,
        "partial": summary.get("partial", 0),
        "failed": summary.get("failed", 0),
        "timeout": summary.get("timeout", 0),
        "error": summary.get("error", 0),
        "pass_rate": pass_rate,
        "duration": summary.get("duration_seconds", 0),
        "results": result_rows,
        "services": service_trends,
        "regressions": regressions,
        "run_history": run_history,
        "has_regressions": len(regressions) > 0,
        # New fields for enhanced template
        "total_tests": total_tests,
        "total_tests_passed": total_tests_passed,
        "total_tests_failed": total_tests_failed,
        "test_pass_rate": test_pass_rate,
        "service_stats": service_stats,
    }

    # Render template
    html_content = template.render(**context)

    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"

    with open(output_path, "w") as f:
        f.write(html_content)

    if logger:
        logger.info(f"Report generated: {output_path}")

    return output_path


def _load_architecture_index(artifacts_dir: Path) -> dict:
    """Load architecture index."""
    index_path = artifacts_dir / "architectures" / "index.json"
    if not index_path.exists():
        return {"architectures": {}}
    with open(index_path) as f:
        return json.load(f)


def _load_service_trends(artifacts_dir: Path) -> list[dict]:
    """Load service trend data for display."""
    trends_path = artifacts_dir / "trends" / "services.json"
    if not trends_path.exists():
        return []

    with open(trends_path) as f:
        data = json.load(f)

    services = []
    for name, trend in data.get("services", {}).items():
        services.append({
            "name": name,
            "pass_rate": trend.get("current_pass_rate", 0) * 100,
            "trend": trend.get("trend", "stable"),
            "count": trend.get("architecture_count", 0),
        })

    # Sort by pass rate
    services.sort(key=lambda s: s["pass_rate"], reverse=True)
    return services


def _load_regressions(artifacts_dir: Path) -> list[dict]:
    """Load recent regressions."""
    reg_path = artifacts_dir / "trends" / "regressions.json"
    if not reg_path.exists():
        return []

    with open(reg_path) as f:
        regressions = json.load(f)

    # Return most recent 10
    return regressions[:10]


def _load_run_history(artifacts_dir: Path, limit: int = 12) -> list[dict]:
    """Load run history for trend charts."""
    runs_dir = artifacts_dir / "runs"
    if not runs_dir.exists():
        return []

    history = []
    run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)

    for run_dir in run_dirs[:limit]:
        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            with open(summary_path) as f:
                data = json.load(f)
            summary = data.get("summary", {})
            total = summary.get("total", 0)
            passed = summary.get("passed", 0)
            history.append({
                "run_id": data.get("run_id", run_dir.name)[:8],
                "date": data.get("started_at", "")[:10],
                "pass_rate": (passed / total * 100) if total > 0 else 0,
                "total": total,
            })

    # Reverse to show oldest first (for chart)
    return list(reversed(history))


def _load_terraform_files(artifacts_dir: Path, arch_hash: str) -> dict[str, str]:
    """Load terraform files for an architecture."""
    arch_dir = artifacts_dir / "architectures" / arch_hash
    tf_files = {}

    if arch_dir.exists():
        for tf_file in arch_dir.glob("*.tf"):
            try:
                content = tf_file.read_text()
                tf_files[tf_file.name] = content
            except Exception:
                pass

    return tf_files


def _load_app_files(artifacts_dir: Path, arch_hash: str) -> dict[str, str]:
    """Load generated application/test files for an architecture."""
    app_dir = artifacts_dir / "apps" / arch_hash
    app_files = {}

    if app_dir.exists():
        for py_file in app_dir.glob("*.py"):
            try:
                content = py_file.read_text()
                app_files[py_file.name] = content
            except Exception:
                pass
        # Also include requirements.txt if present
        req_file = app_dir / "requirements.txt"
        if req_file.exists():
            try:
                app_files["requirements.txt"] = req_file.read_text()
            except Exception:
                pass

    return app_files


def _extract_test_features(app_files: dict[str, str]) -> list[str]:
    """Extract test feature tags from test application code."""
    features = set()

    # Common AWS service operations to detect
    feature_patterns = {
        r"create_bucket|put_object|get_object|list_objects": "S3 Operations",
        r"create_table|put_item|get_item|query|scan": "DynamoDB Operations",
        r"create_queue|send_message|receive_message": "SQS Operations",
        r"create_topic|publish|subscribe": "SNS Operations",
        r"invoke|create_function": "Lambda Invocation",
        r"create_api|create_resource|create_method": "API Gateway",
        r"start_execution|describe_execution": "Step Functions",
        r"put_events|create_event_bus": "EventBridge",
        r"create_secret|get_secret": "Secrets Manager",
        r"get_parameter|put_parameter": "SSM Parameter Store",
        r"assert.*==|assert.*True|assertEqual": "Assertions",
        r"pytest\.fixture|@fixture": "Fixtures",
        r"boto3\.client|boto3\.resource": "AWS SDK",
    }

    for filename, content in app_files.items():
        if filename.endswith(".py"):
            for pattern, feature in feature_patterns.items():
                if re.search(pattern, content, re.IGNORECASE):
                    features.add(feature)

    return sorted(features)


def _extract_test_cases(app_files: dict[str, str]) -> list[dict[str, str]]:
    """Extract test case names and their docstrings from test files."""
    test_cases = []

    # Pattern to match test functions
    func_pattern = re.compile(r'def\s+(test_\w+)\s*\([^)]*\)\s*:', re.MULTILINE)
    # Pattern to match docstring after function definition
    docstring_pattern = re.compile(r'^\s*"""(.+?)"""', re.DOTALL)

    for filename, content in app_files.items():
        if filename.startswith("test_") and filename.endswith(".py"):
            for match in func_pattern.finditer(content):
                test_name = match.group(1)
                # Look for docstring after the function definition
                rest_of_content = content[match.end():]
                docstring = ""
                doc_match = docstring_pattern.match(rest_of_content)
                if doc_match:
                    docstring = doc_match.group(1).strip()

                # Convert test_name to human readable format
                readable_name = test_name.replace("test_", "").replace("_", " ").title()
                test_cases.append({
                    "name": test_name,
                    "readable_name": readable_name,
                    "description": docstring,
                })

    return test_cases


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


def analyze_failure(
    status: str,
    terraform_output: str,
    container_logs: str,
    error_message: str | None = None,
) -> dict | None:
    """Extract the actual error from terraform/container logs.

    Args:
        status: Validation status (FAILED, TIMEOUT, ERROR, etc.)
        terraform_output: Terraform apply output/logs
        container_logs: LocalStack container logs
        error_message: Optional error message from validation

    Returns:
        Dict with extracted error details or None if passed
    """
    if status in ("PASSED", "PARTIAL"):
        return None

    analysis = {
        "category": status.lower(),
        "error_message": None,  # The actual error - this is the key field
        "aws_error_code": None,  # e.g., InvalidParameterValueException
        "affected_service": None,
        "affected_resource": None,
        "is_localstack_issue": True,  # vs test setup issue
    }

    # === EXTRACT ACTUAL ERROR FROM TERRAFORM OUTPUT ===
    if terraform_output:
        # Pattern 1: AWS API errors (most common)
        # e.g., "Error: creating Lambda Function: InvalidParameterValueException: The runtime parameter..."
        aws_error = re.search(
            r"Error:\s*([^:]+):\s*(\w+Exception|\w+Error):\s*(.+?)(?=\n\n|\nwith|\n\s*$)",
            terraform_output,
            re.DOTALL,
        )
        if aws_error:
            operation = aws_error.group(1).strip()
            error_code = aws_error.group(2).strip()
            message = aws_error.group(3).strip().replace("\n", " ")
            analysis["error_message"] = f"{error_code}: {message}"
            analysis["aws_error_code"] = error_code
            analysis["affected_resource"] = operation

        # Pattern 2: Generic terraform errors
        # e.g., "Error: error creating S3 Bucket: BucketAlreadyExists"
        if not analysis["error_message"]:
            generic_error = re.search(
                r"Error:\s*(.+?)(?=\n\n|\nwith|\n\s*on\s|\n\s*$)",
                terraform_output,
                re.DOTALL,
            )
            if generic_error:
                analysis["error_message"] = generic_error.group(1).strip().replace("\n", " ")[:300]

        # Pattern 3: Variable errors (not a LocalStack issue)
        if "no value for required variable" in terraform_output.lower():
            var_match = re.search(r'variable\s+"(\w+)"', terraform_output)
            var_name = var_match.group(1) if var_match else "unknown"
            analysis["error_message"] = f"Missing required variable: {var_name}"
            analysis["is_localstack_issue"] = False
            analysis["category"] = "config"

        # Pattern 4: Lambda runtime validation errors (Terraform provider issue, not LocalStack)
        if "expected runtime to be one of" in terraform_output:
            runtime_match = re.search(r'got\s+(\S+)', terraform_output)
            runtime = runtime_match.group(1) if runtime_match else "unknown"
            analysis["error_message"] = f"Unsupported Lambda runtime in Terraform provider validation: {runtime}"
            analysis["is_localstack_issue"] = False
            analysis["category"] = "provider_version"

        # Pattern 5: tflocal override issues (tflocal bug, not LocalStack)
        if "Unsupported argument" in terraform_output and "localstack_providers_override.tf" in terraform_output:
            arg_match = re.search(r'argument named "(\w+)"', terraform_output)
            arg_name = arg_match.group(1) if arg_match else "unknown"
            analysis["error_message"] = f"tflocal generated unsupported provider endpoint: {arg_name}"
            analysis["is_localstack_issue"] = False
            analysis["category"] = "tflocal_bug"

        # Pattern 6: Context variable issues (module configuration, not LocalStack)
        if "var.context" in terraform_output and "Unsupported attribute" in terraform_output:
            analysis["error_message"] = "Module requires external context object (null-label pattern)"
            analysis["is_localstack_issue"] = False
            analysis["category"] = "config"

    # === DETECT AFFECTED SERVICE ===
    combined = f"{terraform_output}\n{container_logs}".lower()
    service_patterns = [
        (r"aws_lambda|lambda[_\s]function", "Lambda"),
        (r"aws_s3|s3[_\s]bucket", "S3"),
        (r"aws_dynamodb|dynamodb[_\s]table", "DynamoDB"),
        (r"aws_sqs|sqs[_\s]queue", "SQS"),
        (r"aws_sns|sns[_\s]topic", "SNS"),
        (r"aws_apigateway|api[_\s]gateway", "API Gateway"),
        (r"aws_iam|iam[_\s]role", "IAM"),
        (r"aws_ec2|ec2[_\s]instance|aws_vpc|aws_subnet", "EC2/VPC"),
        (r"aws_rds|rds[_\s]instance", "RDS"),
        (r"aws_events|eventbridge|event[_\s]rule", "EventBridge"),
        (r"aws_stepfunctions|state[_\s]machine", "Step Functions"),
        (r"aws_secretsmanager|secret", "Secrets Manager"),
    ]

    for pattern, service in service_patterns:
        if re.search(pattern, combined):
            analysis["affected_service"] = service
            break

    # === TIMEOUT: Extract what it was waiting for ===
    if status == "TIMEOUT":
        analysis["error_message"] = "Terraform timed out waiting for resource"

        # Find what API was being polled
        polling_match = re.search(r"Still (creating|waiting|reading)[^\n]+", terraform_output)
        if polling_match:
            analysis["error_message"] = polling_match.group(0)

    # === ERROR STATUS ===
    if status == "ERROR" and not analysis["error_message"]:
        analysis["error_message"] = error_message or "Validation process error"
        analysis["is_localstack_issue"] = False

    # === EXTRACT LOCALSTACK-SPECIFIC ERROR FROM CONTAINER LOGS ===
    if container_logs:
        # Look for Python exceptions in LocalStack
        ls_exception = re.search(
            r"(\w+Error|\w+Exception):\s*(.+?)(?=\n\s*at\s|\n\s*File|\n\n|\n\s*$)",
            container_logs,
        )
        if ls_exception:
            analysis["localstack_exception"] = f"{ls_exception.group(1)}: {ls_exception.group(2).strip()}"

        # Look for "not implemented" messages
        not_impl = re.search(r"not\s+implemented[^\n]*", container_logs, re.IGNORECASE)
        if not_impl:
            analysis["not_implemented"] = not_impl.group(0).strip()

    return analysis


def _get_inline_template() -> str:
    """Return inline HTML template when file not available."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LocalStack Quality Monitor - {{ run_date }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .status-passed { background-color: #10b981; }
        .status-partial { background-color: #f59e0b; }
        .status-failed { background-color: #ef4444; }
        .status-timeout { background-color: #8b5cf6; }
        .status-error { background-color: #6b7280; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    {% if has_regressions %}
    <div class="bg-red-600 text-white px-4 py-3 text-center font-bold">
        ⚠️ {{ regressions|length }} REGRESSIONS DETECTED
    </div>
    {% endif %}

    <div class="container mx-auto px-4 py-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-gray-800">LocalStack Quality Monitor</h1>
            <p class="text-gray-600">Run: {{ run_id }} | {{ run_date }} | LocalStack {{ localstack_version }}</p>
        </header>

        <!-- Summary Cards -->
        <div class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-8">
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <div class="text-3xl font-bold text-gray-800">{{ total }}</div>
                <div class="text-sm text-gray-500">Total</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <div class="text-3xl font-bold text-green-600">{{ passed }}</div>
                <div class="text-sm text-gray-500">Passed</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <div class="text-3xl font-bold text-yellow-600">{{ partial }}</div>
                <div class="text-sm text-gray-500">Partial</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <div class="text-3xl font-bold text-red-600">{{ failed }}</div>
                <div class="text-sm text-gray-500">Failed</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <div class="text-3xl font-bold text-purple-600">{{ timeout }}</div>
                <div class="text-sm text-gray-500">Timeout</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <div class="text-3xl font-bold text-blue-600">{{ "%.1f"|format(pass_rate) }}%</div>
                <div class="text-sm text-gray-500">Pass Rate</div>
            </div>
        </div>

        <!-- Charts Row -->
        <div class="grid md:grid-cols-2 gap-8 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">Pass Rate Trend</h2>
                <canvas id="trendChart"></canvas>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">Service Compatibility</h2>
                <div class="space-y-2 max-h-64 overflow-y-auto">
                    {% for svc in services %}
                    <div class="flex items-center justify-between">
                        <span class="text-gray-700">{{ svc.name }}</span>
                        <div class="flex items-center">
                            <div class="w-32 bg-gray-200 rounded-full h-2 mr-2">
                                <div class="bg-green-600 h-2 rounded-full" style="width: {{ svc.pass_rate }}%"></div>
                            </div>
                            <span class="text-sm text-gray-500">{{ "%.0f"|format(svc.pass_rate) }}%</span>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <!-- Results Table -->
        <div class="bg-white rounded-lg shadow overflow-hidden">
            <h2 class="text-xl font-semibold p-6 border-b">Architecture Results</h2>
            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Architecture</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Services</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tests</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Duration</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200">
                        {% for result in results %}
                        <tr class="hover:bg-gray-50">
                            <td class="px-6 py-4">
                                <div class="text-sm font-medium text-gray-900">{{ result.name }}</div>
                                <div class="text-xs text-gray-500">{{ result.hash }}</div>
                            </td>
                            <td class="px-6 py-4">
                                <div class="flex flex-wrap gap-1">
                                    {% for svc in result.services[:3] %}
                                    <span class="px-2 py-1 text-xs bg-gray-100 rounded">{{ svc }}</span>
                                    {% endfor %}
                                    {% if result.services|length > 3 %}
                                    <span class="px-2 py-1 text-xs bg-gray-100 rounded">+{{ result.services|length - 3 }}</span>
                                    {% endif %}
                                </div>
                            </td>
                            <td class="px-6 py-4">
                                <span class="px-2 py-1 text-xs font-semibold text-white rounded status-{{ result.status|lower }}">
                                    {{ result.status }}
                                </span>
                            </td>
                            <td class="px-6 py-4 text-sm">
                                <span class="text-green-600">{{ result.pytest_passed }}</span> /
                                <span class="text-red-600">{{ result.pytest_failed }}</span>
                            </td>
                            <td class="px-6 py-4 text-sm text-gray-500">
                                {{ "%.1f"|format(result.duration) }}s
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('trendChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: [{% for run in run_history %}"{{ run.date }}"{% if not loop.last %}, {% endif %}{% endfor %}],
                datasets: [{
                    label: 'Pass Rate %',
                    data: [{% for run in run_history %}{{ run.pass_rate }}{% if not loop.last %}, {% endif %}{% endfor %}],
                    borderColor: 'rgb(16, 185, 129)',
                    tension: 0.1,
                    fill: false
                }]
            },
            options: {
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100
                    }
                }
            }
        });
    </script>
</body>
</html>"""
