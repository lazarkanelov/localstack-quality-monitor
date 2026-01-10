"""LocalStack validation - run tests against LocalStack containers."""

import asyncio
import atexit
import json
import logging
import shutil
import signal
import tempfile
from datetime import datetime
from pathlib import Path

import docker

from lsqm.models import (
    PytestResult,
    TerraformApplyResult,
    ValidationResult,
    ValidationStatus,
)

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

        client = docker.from_env()
        container = client.containers.run(
            f"localstack/localstack:{localstack_version}",
            detach=True,
            name=f"lsqm_{arch_hash[:8]}_{run_id[:8]}",
            ports={"4566/tcp": port},
            environment={
                "SERVICES": ",".join(sorted(arch_services)),
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
            container_logs=_get_container_logs(container) if status != ValidationStatus.PASSED else "",
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


async def _run_terraform(work_dir: Path, endpoint: str, timeout: int) -> TerraformApplyResult:
    """Run tflocal init and apply."""
    import os
    from urllib.parse import urlparse

    # Parse the endpoint to extract hostname and port
    parsed = urlparse(endpoint)
    hostname = parsed.hostname or "localhost"
    port = str(parsed.port or 4566)

    # Start with current environment and add our variables
    # tflocal uses LOCALSTACK_HOSTNAME and EDGE_PORT (not LOCALSTACK_ENDPOINT)
    env = os.environ.copy()
    env.update({
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
        "LOCALSTACK_HOSTNAME": hostname,
        "EDGE_PORT": port,
        "LOCALSTACK_ENDPOINT": endpoint,  # For backward compatibility
    })

    try:
        # tflocal init
        proc = await asyncio.create_subprocess_exec(
            "tflocal", "init",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            return TerraformApplyResult(
                success=False,
                logs=f"Init failed:\nSTDOUT: {stdout.decode()}\nSTDERR: {stderr.decode()}",
            )

        # tflocal apply
        proc = await asyncio.create_subprocess_exec(
            "tflocal", "apply", "-auto-approve", "-input=false",
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
    """Run tflocal destroy."""
    import os
    from urllib.parse import urlparse

    # Parse the endpoint to extract hostname and port
    parsed = urlparse(endpoint)
    hostname = parsed.hostname or "localhost"
    port = str(parsed.port or 4566)

    env = os.environ.copy()
    env.update({
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
        "LOCALSTACK_HOSTNAME": hostname,
        "EDGE_PORT": port,
        "LOCALSTACK_ENDPOINT": endpoint,
    })

    try:
        proc = await asyncio.create_subprocess_exec(
            "tflocal", "destroy", "-auto-approve", "-input=false",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
    except Exception:
        pass


async def _run_pytest(work_dir: Path, endpoint: str, timeout: int = 60) -> PytestResult:
    """Run pytest on test files."""
    import os

    env = os.environ.copy()
    env.update({
        "LOCALSTACK_ENDPOINT": endpoint,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
    })

    try:
        # Install requirements
        req_file = work_dir / "requirements.txt"
        if req_file.exists():
            proc = await asyncio.create_subprocess_exec(
                "pip", "install", "-r", str(req_file), "-q",
                cwd=work_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)

        # Run pytest
        proc = await asyncio.create_subprocess_exec(
            "pytest", "test_app.py", "-v", "--tb=short", f"--timeout={timeout}",
            cwd=work_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        output = stdout.decode()

        # Parse pytest output
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
