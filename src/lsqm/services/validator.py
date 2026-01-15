"""LocalStack validation - run tests against LocalStack containers."""

import asyncio
import atexit
import json
import logging
import re
import shutil
import signal
import tempfile
from datetime import datetime
from pathlib import Path

import docker

from lsqm.models import (
    OperationResult,
    PytestResult,
    TerraformApplyResult,
    TestResult,
    ValidationResult,
    ValidationStatus,
)
from lsqm.models.operation_coverage import map_test_to_operations

# Track active containers for cleanup
_active_containers: list = []
_cleanup_registered = False


def _cleanup_containers_on_exit() -> None:
    """Clean up all active containers on exit."""
    for container in _active_containers[:]:
        try:
            container.stop(timeout=5)
            container.remove()
        except Exception:
            pass
    _active_containers.clear()


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGTERM/SIGINT by cleaning up containers."""
    _cleanup_containers_on_exit()
    # Re-raise the signal for default handling
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)


def _register_cleanup_handlers() -> None:
    """Register cleanup handlers once."""
    global _cleanup_registered
    if _cleanup_registered:
        return

    atexit.register(_cleanup_containers_on_exit)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    _cleanup_registered = True


def validate_architectures(
    architectures: list[tuple[str, dict]],
    run_id: str,
    localstack_version: str,
    parallel: int,
    timeout: int,
    keep_containers: bool,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> dict:
    """Validate architectures against LocalStack.

    Args:
        architectures: List of (hash, arch_data) tuples
        run_id: Current run ID
        localstack_version: LocalStack image version
        parallel: Number of concurrent validations
        timeout: Timeout per validation in seconds
        keep_containers: Whether to keep containers after validation
        artifacts_dir: Path to artifacts directory
        logger: Logger instance

    Returns:
        Dictionary with validation results
    """
    # Register cleanup handlers for graceful shutdown
    _register_cleanup_handlers()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        results = loop.run_until_complete(
            _validate_async(
                architectures=architectures,
                run_id=run_id,
                localstack_version=localstack_version,
                parallel=parallel,
                timeout=timeout,
                keep_containers=keep_containers,
                artifacts_dir=artifacts_dir,
                logger=logger,
            )
        )
    finally:
        loop.close()

    return results


async def _validate_async(
    architectures: list[tuple[str, dict]],
    run_id: str,
    localstack_version: str,
    parallel: int,
    timeout: int,
    keep_containers: bool,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> dict:
    """Async implementation of validation."""
    semaphore = asyncio.Semaphore(parallel)
    validation_results: list[ValidationResult] = []

    async def validate_one(arch_hash: str, arch_data: dict, port: int) -> ValidationResult:
        async with semaphore:
            return await _validate_single(
                arch_hash=arch_hash,
                arch_data=arch_data,
                run_id=run_id,
                port=port,
                localstack_version=localstack_version,
                timeout=timeout,
                keep_containers=keep_containers,
                artifacts_dir=artifacts_dir,
                logger=logger,
            )

    # Assign unique ports (starting at 5100 to avoid conflicts)
    base_port = 5100
    tasks = []
    for i, (arch_hash, arch_data) in enumerate(architectures):
        port = base_port + (i * 10)  # Space out ports
        tasks.append(validate_one(arch_hash, arch_data, port))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    counts = {
        "total": len(architectures),
        "passed": 0,
        "partial": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0,
    }

    for result in results:
        if isinstance(result, Exception):
            counts["error"] += 1
        elif isinstance(result, ValidationResult):
            validation_results.append(result)
            status_key = result.status.value.lower()
            if status_key in counts:
                counts[status_key] += 1

    # Save results
    run_dir = artifacts_dir / "runs" / run_id
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    for vr in validation_results:
        with open(results_dir / f"{vr.arch_hash}.json", "w") as f:
            json.dump(vr.to_dict(), f, indent=2)

    # Save summary.json for the report command
    summary = {
        "run_id": run_id,
        "started_at": datetime.utcnow().isoformat(),
        "localstack_version": localstack_version,
        "summary": counts,
    }
    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return {
        **counts,
        "validation_results": validation_results,
    }


async def _validate_single(
    arch_hash: str,
    arch_data: dict,
    run_id: str,
    port: int,
    localstack_version: str,
    timeout: int,
    keep_containers: bool,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> ValidationResult:
    """Validate a single architecture."""
    started_at = datetime.utcnow()
    container = None
    temp_dir = None

    try:
        # Create temp directory with Terraform and app files
        temp_dir = Path(tempfile.mkdtemp(prefix=f"lsqm_{arch_hash}_"))

        # Copy Terraform files (.tf and .tfvars)
        arch_dir = artifacts_dir / "architectures" / arch_hash
        if arch_dir.exists():
            for tf_file in arch_dir.glob("*.tf"):
                shutil.copy(tf_file, temp_dir)
            for tfvars_file in arch_dir.glob("*.tfvars"):
                shutil.copy(tfvars_file, temp_dir)

        # Copy app files
        app_dir = artifacts_dir / "apps" / arch_hash
        if app_dir.exists():
            for app_file in app_dir.glob("*.py"):
                shutil.copy(app_file, temp_dir)
            req_file = app_dir / "requirements.txt"
            if req_file.exists():
                shutil.copy(req_file, temp_dir)
            # Copy generated terraform.tfvars if it exists (may override arch tfvars)
            tfvars_file = app_dir / "terraform.tfvars"
            if tfvars_file.exists():
                shutil.copy(tfvars_file, temp_dir)

        # Start LocalStack container
        # Always include iam and sts as they're required by Terraform's AWS provider
        arch_services = set(arch_data.get("services", []))
        arch_services.update(["iam", "sts"])  # Required for Terraform provider

        # Add companion services that are commonly used together
        companion_services = {
            "cloudwatch": ["events", "logs"],  # EventBridge + CloudWatch Logs
            "lambda": ["logs"],  # Lambda needs CloudWatch Logs
            "apigateway": ["apigatewayv2"],  # HTTP APIs
            "s3": ["s3control"],  # S3 Control for bucket operations
        }
        for service in list(arch_services):
            if service in companion_services:
                arch_services.update(companion_services[service])

        client = docker.from_env()
        container = client.containers.run(
            f"localstack/localstack:{localstack_version}",
            detach=True,
            name=f"lsqm_{arch_hash[:8]}_{run_id[:8]}",
            ports={"4566/tcp": port},
            environment={
                "SERVICES": ",".join(sorted(arch_services)),
                "DEBUG": "0",  # Reduce log verbosity
                "LAMBDA_EXECUTOR": "docker",  # Use Docker for Lambda execution
            },
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            },
            remove=not keep_containers,
        )

        # Track container for graceful cleanup on signals
        _active_containers.append(container)

        # Wait for health check
        endpoint = f"http://localhost:{port}"
        healthy = await _wait_for_health(endpoint, timeout=60)
        if not healthy:
            return ValidationResult.create_error(
                arch_hash=arch_hash,
                run_id=run_id,
                error_message="LocalStack health check failed",
                started_at=started_at,
            )

        # Run tflocal init and apply
        tf_result = await _run_terraform(temp_dir, endpoint, timeout)

        if not tf_result.success:
            return ValidationResult(
                arch_hash=arch_hash,
                run_id=run_id,
                status=ValidationStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                duration_seconds=(datetime.utcnow() - started_at).total_seconds(),
                terraform_apply=tf_result,
                container_logs=_get_container_logs(container),
            )

        # Run pytest
        pytest_result = await _run_pytest(temp_dir, endpoint, timeout=60)

        # Determine status
        if pytest_result.failed == 0:
            status = ValidationStatus.PASSED
        elif pytest_result.passed > 0:
            status = ValidationStatus.PARTIAL
        else:
            status = ValidationStatus.FAILED

        # Run tflocal destroy
        await _run_terraform_destroy(temp_dir, endpoint)

        return ValidationResult(
            arch_hash=arch_hash,
            run_id=run_id,
            status=status,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            duration_seconds=(datetime.utcnow() - started_at).total_seconds(),
            terraform_apply=tf_result,
            pytest_results=pytest_result,
            container_logs=_get_container_logs(container)
            if status != ValidationStatus.PASSED
            else "",
        )

    except TimeoutError:
        return ValidationResult.create_timeout(
            arch_hash=arch_hash,
            run_id=run_id,
            started_at=started_at,
        )
    except Exception as e:
        return ValidationResult.create_error(
            arch_hash=arch_hash,
            run_id=run_id,
            error_message=str(e),
            started_at=started_at,
        )
    finally:
        # Cleanup
        if container:
            # Remove from tracking list
            if container in _active_containers:
                _active_containers.remove(container)

            if not keep_containers:
                try:
                    container.stop()
                    container.remove()
                except Exception:
                    pass

        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


async def _wait_for_health(endpoint: str, timeout: int = 60) -> bool:
    """Wait for LocalStack health check."""
    import aiohttp

    start = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{endpoint}/_localstack/health", timeout=5) as resp:
                    if resp.status == 200:
                        return True
        except Exception:
            pass
        await asyncio.sleep(1)

    return False


# Endpoints that tflocal may add but are not supported by the Terraform AWS provider
# These cause "unsupported provider endpoint" errors during terraform init
UNSUPPORTED_TFLOCAL_ENDPOINTS = {
    "bedrock",
    "bedrockagent",
    "bedrockruntime",
    "verifiedpermissions",
    "controltower",
    "finspace",
    "iottwinmaker",
    "ivs",
    "ivschat",
    "kendra",
    "keyspaces",
    "lakeformation",
    "lexv2models",
    "location",
    "lookoutmetrics",
    "m2",
    "managedgrafana",
    "memorydb",
    "oam",
    "opensearchserverless",
    "pipes",
    "pricing",
    "recyclebin",
    "rolesanywhere",
    "rum",
    "scheduler",
    "securitylake",
    "serverlessrepo",
    "servicecatalogappregistry",
    "ssoadmin",
    "ssmcontacts",
    "ssmincidents",
    "ssmsap",
    "timestreamwrite",
    "transcribe",
    "vpclattice",
    "workspaces",
}


def _cleanup_tflocal_overrides(work_dir: Path) -> None:
    """Remove unsupported endpoints from tflocal's provider override file.

    tflocal generates localstack_providers_override.tf with endpoints for all
    AWS services, but some (like bedrock) are not recognized by the Terraform
    AWS provider, causing validation errors.
    """
    override_file = work_dir / "localstack_providers_override.tf"
    if not override_file.exists():
        return

    content = override_file.read_text()
    original_content = content

    for endpoint in UNSUPPORTED_TFLOCAL_ENDPOINTS:
        # Remove lines like: bedrock = "http://localhost:5130"
        pattern = rf'^\s*{endpoint}\s*=\s*"[^"]+"\s*\n'
        content = re.sub(pattern, "", content, flags=re.MULTILINE)

    if content != original_content:
        override_file.write_text(content)


def _pre_create_localstack_override(work_dir: Path, endpoint: str) -> None:
    """Pre-create a LocalStack provider override file with only supported endpoints.

    This runs BEFORE tflocal init to prevent it from generating an override file
    with unsupported endpoints that would cause terraform init to fail.

    The override file configures the AWS provider to point to LocalStack.
    """
    # Standard AWS services supported by both Terraform AWS provider and LocalStack Community
    supported_services = [
        "accessanalyzer",
        "acm",
        "apigateway",
        "appconfig",
        "applicationautoscaling",
        "appmesh",
        "autoscaling",
        "backup",
        "batch",
        "ce",
        "cloudcontrol",
        "cloudformation",
        "cloudfront",
        "cloudtrail",
        "cloudwatch",
        "codecommit",
        "codeartifact",
        "codebuild",
        "codepipeline",
        "configservice",
        "dax",
        "docdb",
        "dynamodb",
        "ec2",
        "ecr",
        "ecs",
        "efs",
        "eks",
        "elasticbeanstalk",
        "elasticsearch",
        "elb",
        "elbv2",
        "events",
        "firehose",
        "fis",
        "glacier",
        "iam",
        "identitystore",
        "kafka",
        "kinesis",
        "kinesisanalytics",
        "kms",
        "lambda",
        "logs",
        "mwaa",
        "opensearch",
        "organizations",
        "ram",
        "rds",
        "redshiftdata",
        "resourcegroups",
        "resourcegroupstaggingapi",
        "route53",
        "route53domains",
        "route53resolver",
        "s3",
        "s3control",
        "sagemaker",
        "secretsmanager",
        "servicediscovery",
        "servicequotas",
        "ses",
        "sesv2",
        "sfn",
        "sns",
        "sqs",
        "ssm",
        "sts",
        "swf",
        "waf",
        "wafregional",
        "wafv2",
    ]

    # Generate the endpoints block
    endpoints_block = "\n".join(
        [f'    {svc} = "{endpoint}"' for svc in sorted(supported_services)]
    )

    override_content = f'''# Auto-generated LocalStack provider override
# This file configures Terraform to use LocalStack instead of AWS

provider "aws" {{
  access_key                  = "test"
  secret_key                  = "test"
  region                      = "us-east-1"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {{
{endpoints_block}
  }}
}}
'''

    override_file = work_dir / "localstack_providers_override.tf"
    override_file.write_text(override_content)


def _normalize_provider_versions(work_dir: Path) -> None:
    """Update AWS provider version constraints to support modern Lambda runtimes.

    Older AWS provider versions (< 5.31) don't support modern Lambda runtimes
    like python3.10, python3.11, python3.12, nodejs18.x, nodejs20.x, etc.
    This causes Terraform validation errors before LocalStack is even involved.
    """
    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()

        # Match version constraints in required_providers blocks
        # Examples: version = "~> 4.0", version = "~> 5.0", version = ">= 4.0"
        updated = re.sub(
            r'(version\s*=\s*")[~>= ]*[45]\.[0-9]+(\.[0-9]+)?(")', r"\g<1>>= 5.31\g<3>", content
        )

        if updated != content:
            tf_file.write_text(updated)


def _remove_aws_profile_references(work_dir: Path) -> None:
    """Remove AWS profile references from provider blocks.

    When Terraform files have `profile = "default"` or similar, the AWS provider
    tries to load credentials from ~/.aws/config BEFORE tflocal can override it.
    This causes "failed to get shared config profile" errors even when we set
    AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY environment variables.

    By removing the profile attribute, the provider falls back to environment
    variables, which we control.
    """
    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()
        original = content

        # Remove profile = "..." from provider blocks
        # Handles: profile = "default", profile="custom", profile  =  "any"
        content = re.sub(r'\s*profile\s*=\s*"[^"]*"\s*\n?', "\n", content)

        # Also remove shared_credentials_file and shared_config_files if present
        content = re.sub(r'\s*shared_credentials_file\s*=\s*"[^"]*"\s*\n?', "\n", content)
        content = re.sub(r'\s*shared_config_files\s*=\s*\[[^\]]*\]\s*\n?', "\n", content)

        if content != original:
            tf_file.write_text(content)


def _create_stub_lambda_sources(work_dir: Path) -> None:
    """Create stub source files for Lambda functions that reference missing files.

    Many Terraform architectures reference source files like ./src/app.js or
    ./src/handler.py that don't exist in our copy. Instead of failing, we create
    minimal stub files that allow Terraform to complete the archive_file creation.
    """
    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()

        # Find source_file references in archive_file data sources
        # e.g., source_file = "${path.module}/src/app.js"
        source_files = re.findall(
            r'source_file\s*=\s*"(?:\$\{path\.module\}/)?([^"]+)"', content
        )

        # Find source_dir references
        # e.g., source_dir = "${path.module}/src"
        source_dirs = re.findall(
            r'source_dir\s*=\s*"(?:\$\{path\.module\}/)?([^"]+)"', content
        )

        # Create stub files
        for src_file in source_files:
            file_path = work_dir / src_file
            if not file_path.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                # Create appropriate stub based on file extension
                ext = file_path.suffix.lower()
                if ext == ".js":
                    file_path.write_text('exports.handler = async (event) => { return { statusCode: 200, body: "stub" }; };\n')
                elif ext == ".py":
                    file_path.write_text('def handler(event, context):\n    return {"statusCode": 200, "body": "stub"}\n')
                elif ext == ".ts":
                    file_path.write_text('export const handler = async (event: any) => { return { statusCode: 200, body: "stub" }; };\n')
                else:
                    file_path.write_text("# stub file\n")

        # Create stub directories with index files
        for src_dir in source_dirs:
            dir_path = work_dir / src_dir
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                # Create a stub index.js file (common for Lambda)
                (dir_path / "index.js").write_text(
                    'exports.handler = async (event) => { return { statusCode: 200, body: "stub" }; };\n'
                )


def _generate_missing_tfvars(work_dir: Path) -> None:
    """Generate terraform.tfvars for required variables without defaults.

    Many Terraform modules require input variables (like 'name', 'environment')
    that have no default values. Instead of failing, we detect these and create
    a tfvars file with sensible stub values.
    """
    required_vars: dict[str, dict] = {}

    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()

        # Parse variable blocks: variable "name" { ... }
        # We need to find variables without default values
        var_blocks = re.findall(
            r'variable\s+"([^"]+)"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
            content,
            re.DOTALL,
        )

        for var_name, var_body in var_blocks:
            # Check if variable has a default
            has_default = re.search(r'\bdefault\s*=', var_body)
            if not has_default:
                # Extract type if available
                type_match = re.search(r'\btype\s*=\s*(\w+)', var_body)
                var_type = type_match.group(1) if type_match else "string"
                required_vars[var_name] = {"type": var_type}

    if not required_vars:
        return

    # Check if tfvars already exists
    tfvars_file = work_dir / "terraform.tfvars"
    existing_vars = set()
    if tfvars_file.exists():
        existing_content = tfvars_file.read_text()
        # Find already defined variables
        existing_vars = set(re.findall(r'^(\w+)\s*=', existing_content, re.MULTILINE))

    # Generate stub values for missing required variables
    new_vars = []
    for var_name, var_info in required_vars.items():
        if var_name in existing_vars:
            continue

        var_type = var_info.get("type", "string")

        # Generate appropriate stub value based on variable name and type
        if var_type in ("number", "int"):
            value = "1"
        elif var_type == "bool":
            value = "false"
        elif var_type in ("list", "set"):
            value = "[]"
        elif var_type in ("map", "object"):
            value = "{}"
        else:
            # String type - use smart defaults based on common variable names
            if var_name in ("name", "project_name", "app_name", "service_name"):
                value = '"lsqm-test"'
            elif var_name in ("environment", "env", "stage"):
                value = '"test"'
            elif var_name in ("region", "aws_region"):
                value = '"us-east-1"'
            elif "bucket" in var_name.lower():
                value = '"lsqm-test-bucket"'
            elif "domain" in var_name.lower():
                value = '"example.com"'
            elif "email" in var_name.lower():
                value = '"test@example.com"'
            elif "prefix" in var_name.lower():
                value = '"lsqm"'
            elif "suffix" in var_name.lower():
                value = '"test"'
            else:
                value = f'"lsqm-{var_name}"'

        new_vars.append(f'{var_name} = {value}')

    if new_vars:
        # Append to existing or create new tfvars
        mode = "a" if tfvars_file.exists() else "w"
        with open(tfvars_file, mode) as f:
            if mode == "a":
                f.write("\n# Auto-generated stub values for required variables\n")
            else:
                f.write("# Auto-generated stub values for required variables\n")
            f.write("\n".join(new_vars) + "\n")


# Services not available in LocalStack Community Edition
LOCALSTACK_PRO_ONLY_SERVICES = {
    "bedrock",
    "bedrockagent",
    "bedrockruntime",
    "apigatewayv2",  # HTTP APIs require Pro
    "appsync",
    "athena",
    "cognito-identity",
    "cognito-idp",
    "elasticache",
    "emr",
    "glue",
    "iot",
    "mediastore",
    "mq",
    "neptune",
    "qldb",
    "rds",
    "redshift",
    "transfer",
    "xray",
}


def _remove_pro_only_resources(work_dir: Path) -> bool:
    """Remove resources that require LocalStack Pro.

    Some Terraform files reference services only available in LocalStack Pro.
    For testing LocalStack Community Edition, we remove these resources to allow
    the rest of the architecture to be tested.

    Returns True if any resources were removed.
    """
    removed_any = False

    # Resource type prefixes that indicate Pro-only services
    pro_resource_patterns = [
        r"aws_bedrockagent_",
        r"aws_bedrock_",
        r"aws_appsync_",
        r"aws_athena_",
        r"aws_cognito_",
        r"aws_elasticache_",
        r"aws_emr_",
        r"aws_glue_",
        r"aws_iot_",
        r"aws_mediastore_",
        r"aws_mq_",
        r"aws_neptune_",
        r"aws_qldb_",
        r"aws_redshift_",
        r"aws_transfer_",
        r"aws_xray_",
    ]

    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()
        original = content

        for pattern in pro_resource_patterns:
            # Remove resource blocks for Pro-only services
            # Match: resource "aws_bedrock_xxx" "name" { ... }
            content = re.sub(
                rf'resource\s+"{pattern}[^"]*"\s+"[^"]+"\s*\{{[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)*\}}',
                "# Resource removed - requires LocalStack Pro",
                content,
                flags=re.DOTALL,
            )
            # Remove data blocks for Pro-only services
            content = re.sub(
                rf'data\s+"{pattern}[^"]*"\s+"[^"]+"\s*\{{[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)*\}}',
                "# Data source removed - requires LocalStack Pro",
                content,
                flags=re.DOTALL,
            )

        if content != original:
            tf_file.write_text(content)
            removed_any = True

    return removed_any


def _relax_module_version_constraints(work_dir: Path) -> None:
    """Relax version constraints in module source blocks only.

    Some modules have version constraints that can't be resolved because
    the exact version isn't available. We remove these constraints to allow
    Terraform to use whatever version is available.

    IMPORTANT: We only modify module blocks, NOT required_providers blocks.
    Provider version constraints must be preserved for Terraform to function.
    """
    for tf_file in work_dir.glob("*.tf"):
        content = tf_file.read_text()
        original = content

        # Find and modify module blocks only
        # Look for: module "name" { ... version = "..." ... }
        # We need to remove the version line inside module blocks

        def remove_module_version(match: re.Match) -> str:
            """Remove version constraint from a module block."""
            block = match.group(0)
            # Remove version = "..." line, preserving other content
            modified = re.sub(
                r'\n\s*version\s*=\s*"[^"]*"',
                "",
                block,
            )
            return modified

        # Match module blocks: module "name" { ... }
        # This regex handles nested braces
        content = re.sub(
            r'module\s+"[^"]+"\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
            remove_module_version,
            content,
            flags=re.DOTALL,
        )

        if content != original:
            tf_file.write_text(content)


async def _run_terraform(work_dir: Path, endpoint: str, timeout: int) -> TerraformApplyResult:
    """Run terraform init and apply against LocalStack.

    Instead of using tflocal (which can generate unsupported endpoints), we:
    1. Pre-create our own LocalStack provider override file
    2. Run terraform directly with proper AWS environment variables
    """
    import os

    # Set up AWS environment for LocalStack
    env = os.environ.copy()
    env.update(
        {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
        }
    )

    # Pre-process Terraform files to fix common issues
    _normalize_provider_versions(work_dir)
    _remove_aws_profile_references(work_dir)
    _create_stub_lambda_sources(work_dir)
    _generate_missing_tfvars(work_dir)
    _remove_pro_only_resources(work_dir)
    _relax_module_version_constraints(work_dir)

    # Create our own LocalStack provider override (instead of using tflocal)
    # This avoids tflocal generating unsupported endpoint configurations
    _pre_create_localstack_override(work_dir, endpoint)

    try:
        # terraform init
        proc = await asyncio.create_subprocess_exec(
            "terraform",
            "init",
            "-input=false",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            return TerraformApplyResult(
                success=False,
                logs=f"Init failed:\nSTDOUT: {stdout.decode()}\nSTDERR: {stderr.decode()}",
            )

        # terraform apply
        proc = await asyncio.create_subprocess_exec(
            "terraform",
            "apply",
            "-auto-approve",
            "-input=false",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        output = stdout.decode()
        error_output = stderr.decode()

        if proc.returncode != 0:
            return TerraformApplyResult(
                success=False,
                logs=f"Apply failed:\nSTDOUT: {output}\nSTDERR: {error_output}",
            )

        # Count resources
        resource_count = output.count("created")

        return TerraformApplyResult(
            success=True,
            resources_created=resource_count,
            logs=output,
        )

    except TimeoutError:
        return TerraformApplyResult(success=False, logs="Terraform timed out")
    except Exception as e:
        return TerraformApplyResult(success=False, logs=str(e))


async def _run_terraform_destroy(work_dir: Path, endpoint: str) -> None:
    """Run terraform destroy against LocalStack."""
    import os

    env = os.environ.copy()
    env.update(
        {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
        }
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "terraform",
            "destroy",
            "-auto-approve",
            "-input=false",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
    except Exception:
        pass


def _parse_pytest_verbose_output(output: str) -> list[TestResult]:
    """Parse pytest -v output to extract individual test results.

    Pytest verbose output format:
    test_app.py::test_put_object PASSED                      [ 20%]
    test_app.py::test_get_object FAILED                      [ 40%]

    Args:
        output: Full pytest stdout output

    Returns:
        List of TestResult for each individual test
    """
    results = []

    # Pattern to match test lines: filename::test_name STATUS [percentage or duration]
    pattern = re.compile(
        r"^(.+?)::(\w+)\s+(PASSED|FAILED|SKIPPED|ERROR)(?:\s+\[([^\]]+)\])?", re.MULTILINE
    )

    for match in pattern.finditer(output):
        _filename = match.group(1)
        test_name = match.group(2)
        status = match.group(3).lower()
        duration_str = match.group(4)

        # Parse duration if available (e.g., "0.23s")
        duration = 0.0
        if duration_str and "s" in duration_str:
            try:
                duration = float(duration_str.replace("s", "").strip())
            except ValueError:
                pass

        # Extract error message for failed tests
        error_message = None
        if status == "failed":
            error_message = _extract_test_error(output, test_name)

        # Map test name to AWS operations
        aws_operations = map_test_to_operations(test_name)

        results.append(
            TestResult(
                test_name=test_name,
                status=status,
                duration=duration,
                error_message=error_message,
                aws_operations=aws_operations,
            )
        )

    return results


def _extract_test_error(output: str, test_name: str) -> str | None:
    """Extract error details for a specific failed test.

    Args:
        output: Full pytest output
        test_name: Name of the failed test

    Returns:
        Error message excerpt or None
    """
    # Look for FAILURES section with this test
    # Pattern: _____ test_name _____
    pattern = rf"_{(3,)}\s+{re.escape(test_name)}\s+_{(3,)}(.*?)(?=_{(3,)}|PASSED|FAILED|={(3,)}|$)"
    match = re.search(pattern, output, re.DOTALL)
    if match:
        error_section = match.group(1).strip()
        # Extract the actual error message (last few lines usually)
        lines = [line.strip() for line in error_section.split("\n") if line.strip()]
        # Take last 5 non-empty lines
        error_lines = lines[-5:] if len(lines) > 5 else lines
        return "\n".join(error_lines)[:500]  # Limit length

    return None


def _build_operation_results(test_results: list[TestResult]) -> list[OperationResult]:
    """Build operation-level results from individual test results.

    Args:
        test_results: List of individual test results

    Returns:
        List of OperationResult for each AWS operation tested
    """
    operation_results = []

    for test in test_results:
        for operation in test.aws_operations:
            # Extract service from operation (e.g., "s3" from "s3:PutObject")
            service = operation.split(":")[0] if ":" in operation else operation

            operation_results.append(
                OperationResult(
                    operation=operation,
                    service=service,
                    succeeded=(test.status == "passed"),
                    test_name=test.test_name,
                    error_message=test.error_message if test.status == "failed" else None,
                )
            )

    return operation_results


async def _run_pytest(work_dir: Path, endpoint: str, timeout: int = 60) -> PytestResult:
    """Run pytest on test files."""
    import os

    env = os.environ.copy()
    env.update(
        {
            "LOCALSTACK_ENDPOINT": endpoint,
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
        }
    )

    try:
        # Install requirements
        req_file = work_dir / "requirements.txt"
        if req_file.exists():
            proc = await asyncio.create_subprocess_exec(
                "pip",
                "install",
                "-r",
                str(req_file),
                "-q",
                cwd=work_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)

        # Run pytest with verbose output for individual test parsing
        proc = await asyncio.create_subprocess_exec(
            "pytest",
            "test_app.py",
            "-v",
            "--tb=short",
            f"--timeout={timeout}",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        output = stdout.decode()

        # Parse individual test results from verbose output
        individual_tests = _parse_pytest_verbose_output(output)

        # Build operation-level results
        operation_results = _build_operation_results(individual_tests)

        # Calculate aggregate counts from individual results
        if individual_tests:
            passed = sum(1 for t in individual_tests if t.status == "passed")
            failed = sum(1 for t in individual_tests if t.status == "failed")
            skipped = sum(1 for t in individual_tests if t.status == "skipped")
            total = len(individual_tests)
        else:
            # Fallback to simple counting if parsing fails
            passed = output.count(" passed")
            failed = output.count(" failed")
            skipped = output.count(" skipped")
            total = passed + failed + skipped

        return PytestResult(
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            output=output,
            individual_tests=individual_tests,
            operation_results=operation_results,
        )

    except TimeoutError:
        return PytestResult(total=0, passed=0, failed=1, output="Pytest timed out")
    except Exception as e:
        return PytestResult(total=0, passed=0, failed=1, output=str(e))


def _get_container_logs(container) -> str:
    """Get logs from container."""
    try:
        return container.logs().decode("utf-8")[-5000:]  # Last 5000 chars
    except Exception:
        return ""


def cleanup_stale_containers(logger: logging.Logger | None = None) -> int:
    """Remove stale LocalStack containers from previous runs."""
    client = docker.from_env()
    removed = 0

    try:
        containers = client.containers.list(
            all=True,
            filters={"ancestor": "localstack/localstack"},
        )

        for container in containers:
            try:
                container.stop()
                container.remove()
                removed += 1
                if logger:
                    logger.info(f"Removed container: {container.id[:12]}")
            except Exception:
                pass

    except Exception as e:
        if logger:
            logger.error(f"Error cleaning containers: {e}")

    return removed
