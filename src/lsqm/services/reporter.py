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
            "logs": container_logs[:5000],
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
    """Analyze why a validation failed and what it means for LocalStack quality.

    Args:
        status: Validation status (FAILED, TIMEOUT, ERROR, etc.)
        terraform_output: Terraform apply output/logs
        container_logs: LocalStack container logs
        error_message: Optional error message from validation

    Returns:
        Dict with analysis details or None if passed
    """
    if status in ("PASSED", "PARTIAL"):
        return None

    analysis = {
        "category": "unknown",
        "summary": "",
        "root_cause": "",
        "localstack_impact": "",
        "affected_service": None,
        "affected_operation": None,
        "severity": "medium",  # low, medium, high, critical
        "suggestions": [],
    }

    combined_logs = f"{terraform_output}\n{container_logs}".lower()
    tf_lower = terraform_output.lower()

    # === TIMEOUT ANALYSIS ===
    if status == "TIMEOUT":
        analysis["category"] = "timeout"
        analysis["severity"] = "high"

        # Check for specific polling patterns
        if "describesubnets" in combined_logs or "describe_subnets" in combined_logs:
            analysis["summary"] = "EC2 Subnet State Transition Timeout"
            analysis["root_cause"] = (
                "Terraform is polling DescribeSubnets waiting for subnets to reach "
                "'available' state, but LocalStack's EC2 implementation is not "
                "transitioning the subnet state correctly."
            )
            analysis["localstack_impact"] = (
                "VPC/subnet creation workflows are blocked. Any Terraform module "
                "that creates subnets and waits for them to become available will "
                "hang indefinitely. This affects a large number of real-world "
                "infrastructure patterns."
            )
            analysis["affected_service"] = "EC2"
            analysis["affected_operation"] = "DescribeSubnets (state transition)"
            analysis["severity"] = "critical"
            analysis["suggestions"] = [
                "Check LocalStack EC2 subnet state machine implementation",
                "Verify subnet state transitions from 'pending' to 'available'",
                "Review EC2 resource lifecycle handling",
            ]

        elif "describenat" in combined_logs or "nat_gateway" in combined_logs:
            analysis["summary"] = "NAT Gateway State Transition Timeout"
            analysis["root_cause"] = (
                "Terraform is waiting for NAT Gateway to reach 'available' state, "
                "but LocalStack is not transitioning the resource state."
            )
            analysis["localstack_impact"] = (
                "Private subnet internet access patterns are broken. Applications "
                "requiring NAT Gateways cannot be deployed."
            )
            analysis["affected_service"] = "EC2"
            analysis["affected_operation"] = "DescribeNatGateways (state transition)"
            analysis["severity"] = "high"

        elif "describedbinstances" in combined_logs or "rds" in combined_logs:
            analysis["summary"] = "RDS Instance State Transition Timeout"
            analysis["root_cause"] = (
                "RDS instance is not transitioning to 'available' state within "
                "the expected timeframe."
            )
            analysis["localstack_impact"] = (
                "Database provisioning workflows are blocked. Applications requiring "
                "RDS cannot be deployed via Terraform."
            )
            analysis["affected_service"] = "RDS"
            analysis["affected_operation"] = "DescribeDBInstances (state transition)"
            analysis["severity"] = "high"

        else:
            analysis["summary"] = "Resource Provisioning Timeout"
            analysis["root_cause"] = (
                "Terraform timed out waiting for a resource to reach the expected state. "
                "This typically indicates LocalStack's resource state machine is not "
                "transitioning correctly."
            )
            analysis["localstack_impact"] = (
                "Resource creation workflows hang, preventing successful deployments."
            )
            analysis["suggestions"] = [
                "Check LocalStack logs for the specific resource being waited on",
                "Review resource state transition logic",
            ]

    # === TERRAFORM ERROR ANALYSIS ===
    elif status == "FAILED":
        analysis["category"] = "terraform_error"

        # Missing variables
        if "no value for required variable" in tf_lower or "required variable" in tf_lower:
            var_match = re.search(r'variable\s+"?(\w+)"?', terraform_output)
            var_name = var_match.group(1) if var_match else "unknown"
            analysis["summary"] = f"Missing Required Variable: {var_name}"
            analysis["root_cause"] = (
                "The Terraform module requires input variables that were not provided. "
                "This is not a LocalStack issue but a test configuration issue."
            )
            analysis["localstack_impact"] = (
                "No LocalStack impact - this is a test setup issue that needs "
                "terraform.tfvars or variable defaults."
            )
            analysis["severity"] = "low"
            analysis["category"] = "configuration"
            analysis["suggestions"] = [
                f"Add default value for variable '{var_name}' or provide terraform.tfvars",
            ]

        # Unsupported service/feature
        elif "unsupported" in tf_lower or "not implemented" in tf_lower:
            analysis["summary"] = "Unsupported AWS Feature"
            analysis["root_cause"] = (
                "Terraform tried to use an AWS API operation or feature that "
                "LocalStack does not implement."
            )
            analysis["localstack_impact"] = (
                "This AWS feature is not available in LocalStack. Architectures "
                "using this feature cannot be tested."
            )
            analysis["severity"] = "medium"
            analysis["suggestions"] = [
                "Check LocalStack feature coverage documentation",
                "Consider if this is a pro-only feature",
            ]

        # API errors
        elif "error:" in tf_lower:
            # Extract error details
            error_match = re.search(r"error[:\s]+([^\n]+)", terraform_output, re.IGNORECASE)
            error_detail = error_match.group(1).strip() if error_match else "Unknown error"

            # Service-specific errors
            if "s3" in combined_logs:
                analysis["affected_service"] = "S3"
            elif "lambda" in combined_logs:
                analysis["affected_service"] = "Lambda"
            elif "dynamodb" in combined_logs:
                analysis["affected_service"] = "DynamoDB"
            elif "sqs" in combined_logs:
                analysis["affected_service"] = "SQS"
            elif "sns" in combined_logs:
                analysis["affected_service"] = "SNS"
            elif "ec2" in combined_logs or "vpc" in combined_logs:
                analysis["affected_service"] = "EC2/VPC"
            elif "iam" in combined_logs:
                analysis["affected_service"] = "IAM"
            elif "apigateway" in combined_logs:
                analysis["affected_service"] = "API Gateway"

            analysis["summary"] = f"Terraform Error: {error_detail[:100]}"
            analysis["root_cause"] = (
                f"Terraform encountered an error during resource creation: {error_detail}"
            )
            analysis["localstack_impact"] = (
                "This error indicates a potential issue with LocalStack's implementation "
                f"of {analysis['affected_service'] or 'an AWS service'}."
            )

        # Access denied / permissions
        elif "accessdenied" in tf_lower or "access denied" in tf_lower:
            analysis["summary"] = "Access Denied Error"
            analysis["root_cause"] = (
                "LocalStack returned an AccessDenied error. In LocalStack, this "
                "usually indicates an IAM policy evaluation issue or a bug in "
                "permission handling."
            )
            analysis["localstack_impact"] = (
                "IAM policy enforcement may be incorrectly blocking operations. "
                "This could affect realistic testing scenarios."
            )
            analysis["affected_service"] = "IAM"
            analysis["severity"] = "medium"

        # Invalid parameter
        elif "invalidparameter" in tf_lower or "validationerror" in tf_lower:
            analysis["summary"] = "Invalid Parameter Error"
            analysis["root_cause"] = (
                "LocalStack rejected a parameter as invalid. This could indicate "
                "stricter validation than AWS or a bug in parameter handling."
            )
            analysis["localstack_impact"] = (
                "Parameter validation differs from AWS behavior, which could cause "
                "false negatives in testing."
            )
            analysis["severity"] = "medium"

        else:
            analysis["summary"] = "Terraform Apply Failed"
            analysis["root_cause"] = "Terraform failed to apply the configuration."
            analysis["localstack_impact"] = (
                "Unable to determine specific LocalStack impact without more details."
            )

    # === GENERAL ERROR ===
    elif status == "ERROR":
        analysis["category"] = "system_error"
        analysis["summary"] = error_message or "System Error"
        analysis["root_cause"] = (
            "A system-level error occurred during validation, not directly "
            "related to Terraform or LocalStack compatibility."
        )
        analysis["localstack_impact"] = (
            "Unable to assess LocalStack compatibility due to test infrastructure issue."
        )
        analysis["severity"] = "low"

    # === CONTAINER LOG ANALYSIS ===
    # Look for additional clues in container logs
    if "exception" in container_logs.lower() or "error" in container_logs.lower():
        exception_match = re.search(
            r"(Exception|Error):\s*([^\n]+)", container_logs, re.IGNORECASE
        )
        if exception_match and not analysis.get("container_exception"):
            analysis["container_exception"] = exception_match.group(0).strip()[:200]

    if "not implemented" in container_logs.lower():
        analysis["has_not_implemented"] = True
        if analysis["severity"] == "medium":
            analysis["severity"] = "high"

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
