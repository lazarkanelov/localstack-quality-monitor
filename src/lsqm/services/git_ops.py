"""GitHub operations - clone, pull, push, issue creation."""

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from lsqm.utils.config import get_artifacts_dir


def clone_or_pull_artifacts(
    repo: str,
    token: str,
    force: bool = False,
    logger: logging.Logger | None = None,
) -> Path:
    """Clone or pull the artifact repository.

    Args:
        repo: Repository in owner/name format
        token: GitHub personal access token
        force: Force fresh clone even if exists
        logger: Logger instance

    Returns:
        Path to artifacts directory
    """
    import shutil

    artifacts_dir = get_artifacts_dir()

    if force and artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)

    if artifacts_dir.exists() and (artifacts_dir / ".git").exists():
        # Pull latest
        if logger:
            logger.info(f"Pulling latest from {repo}")
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=artifacts_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                if logger:
                    logger.warning(f"Git pull failed: {result.stderr}")
                # Try to continue anyway - might be up to date or have local changes
        except Exception as e:
            if logger:
                logger.warning(f"Git pull error: {e}")
    else:
        # Clone - remove existing directory first if it exists but isn't a git repo
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)

        # Ensure parent directory exists
        artifacts_dir.parent.mkdir(parents=True, exist_ok=True)

        if logger:
            logger.info(f"Cloning {repo}")

        clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        try:
            result = subprocess.run(
                ["git", "clone", clone_url, str(artifacts_dir)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(f"Git clone failed: {error_msg}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git clone failed: {e.stderr or e.stdout or str(e)}") from e

    # Ensure basic directory structure exists
    (artifacts_dir / "architectures").mkdir(exist_ok=True)
    (artifacts_dir / "apps").mkdir(exist_ok=True)
    (artifacts_dir / "runs").mkdir(exist_ok=True)

    return artifacts_dir


def load_architecture_index(artifacts_dir: Path) -> dict:
    """Load the architecture index from artifacts directory.

    Args:
        artifacts_dir: Path to artifacts directory

    Returns:
        Architecture index dictionary
    """
    index_path = artifacts_dir / "architectures" / "index.json"
    if not index_path.exists():
        return {"version": 1, "architectures": {}}

    with open(index_path) as f:
        return json.load(f)


def load_run_results(artifacts_dir: Path, run_id: str = "latest") -> dict | None:
    """Load results for a specific run.

    Args:
        artifacts_dir: Path to artifacts directory
        run_id: Run ID or "latest" or "previous"

    Returns:
        Run results dictionary or None if not found
    """
    runs_dir = artifacts_dir / "runs"
    if not runs_dir.exists():
        return None

    if run_id == "latest":
        # Find most recent run
        run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not run_dirs:
            return None
        run_dir = run_dirs[0]
    elif run_id == "previous":
        # Find second most recent run
        run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(run_dirs) < 2:
            return None
        run_dir = run_dirs[1]
    else:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            return None

    # Load summary
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return None

    with open(summary_path) as f:
        run_data = json.load(f)

    # Load individual results
    results_dir = run_dir / "results"
    if results_dir.exists():
        run_data["results"] = {}
        for result_file in results_dir.glob("*.json"):
            arch_hash = result_file.stem
            with open(result_file) as f:
                run_data["results"][arch_hash] = json.load(f)

    return run_data


def load_service_trends(artifacts_dir: Path) -> dict:
    """Load service trend data.

    Args:
        artifacts_dir: Path to artifacts directory

    Returns:
        Service trends dictionary
    """
    trends_path = artifacts_dir / "trends" / "services.json"
    if not trends_path.exists():
        return {}

    with open(trends_path) as f:
        data = json.load(f)
    return data.get("services", {})


def save_architecture(
    arch,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> bool:
    """Save an architecture and its terraform files to the artifacts directory.

    Args:
        arch: Architecture object with terraform_files
        artifacts_dir: Path to artifacts directory
        logger: Logger instance

    Returns:
        True if saved successfully
    """
    arch_dir = artifacts_dir / "architectures" / arch.hash
    arch_dir.mkdir(parents=True, exist_ok=True)

    # Save terraform files
    tf_files = getattr(arch, "tf_files", {}) or getattr(arch, "terraform_files", {})
    if tf_files:
        for filename, content in tf_files.items():
            # Handle nested paths
            file_path = arch_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w") as f:
                f.write(content)

    # Save architecture metadata
    metadata = arch.to_dict()
    with open(arch_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    if logger:
        logger.info(f"Saved architecture {arch.hash[:8]} ({arch.name or 'unnamed'})")

    return True


def update_architecture_index(
    artifacts_dir: Path,
    architectures: list | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Update architecture index with new discoveries.

    Args:
        artifacts_dir: Path to artifacts directory
        architectures: List of Architecture objects to add (optional, scans directory if not provided)
        logger: Logger instance

    Returns:
        Number of new architectures added
    """
    index_path = artifacts_dir / "architectures" / "index.json"
    arch_base_dir = artifacts_dir / "architectures"

    # Load existing index
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
    else:
        index = {"version": 1, "architectures": {}}
        arch_base_dir.mkdir(parents=True, exist_ok=True)

    added = 0

    # If architectures provided, add them
    if architectures:
        for arch in architectures:
            if arch.hash not in index["architectures"]:
                index["architectures"][arch.hash] = arch.to_dict()
                added += 1
    else:
        # Scan directory for architectures not in index
        if arch_base_dir.exists():
            for arch_dir in arch_base_dir.iterdir():
                if arch_dir.is_dir() and arch_dir.name != "index.json":
                    arch_hash = arch_dir.name
                    if arch_hash not in index["architectures"]:
                        metadata_path = arch_dir / "metadata.json"
                        if metadata_path.exists():
                            with open(metadata_path) as f:
                                index["architectures"][arch_hash] = json.load(f)
                            added += 1

    # Save updated index
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

    if logger and added > 0:
        logger.info(f"Added {added} architectures to index")

    return added


def save_generated_app(
    arch_hash: str,
    files: dict[str, str],
    metadata: dict,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> bool:
    """Save generated application files to the artifacts directory.

    Args:
        arch_hash: Architecture hash
        files: Dictionary of filename -> content
        metadata: Generation metadata
        artifacts_dir: Path to artifacts directory
        logger: Logger instance

    Returns:
        True if saved successfully
    """
    app_dir = artifacts_dir / "apps" / arch_hash
    app_dir.mkdir(parents=True, exist_ok=True)

    # Save all generated files
    for filename, content in files.items():
        file_path = app_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)

    # Save metadata
    with open(app_dir / "generation_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    if logger:
        logger.info(f"Saved generated app for {arch_hash[:8]}")

    return True


def load_generated_app(
    arch_hash: str,
    artifacts_dir: Path,
) -> dict[str, str] | None:
    """Load generated application files for an architecture.

    Args:
        arch_hash: Architecture hash
        artifacts_dir: Path to artifacts directory

    Returns:
        Dictionary of filename -> content, or None if not found
    """
    app_dir = artifacts_dir / "apps" / arch_hash
    if not app_dir.exists():
        return None

    files = {}
    for file_path in app_dir.iterdir():
        if file_path.is_file() and file_path.name != "generation_metadata.json":
            with open(file_path) as f:
                files[file_path.name] = f.read()

    return files if files else None


def mark_architecture_has_app(
    arch_hash: str,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> bool:
    """Mark an architecture as having a generated app in the index.

    Args:
        arch_hash: Architecture hash
        artifacts_dir: Path to artifacts directory
        logger: Logger instance

    Returns:
        True if successfully updated
    """
    index_path = artifacts_dir / "architectures" / "index.json"

    if not index_path.exists():
        return False

    with open(index_path) as f:
        index = json.load(f)

    if arch_hash in index.get("architectures", {}):
        index["architectures"][arch_hash]["has_app"] = True
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)
        if logger:
            logger.debug(f"Marked {arch_hash[:8]} as has_app=True")
        return True

    return False


def update_trends(artifacts_dir: Path, logger: logging.Logger | None = None) -> None:
    """Update trend files with latest run data.

    Args:
        artifacts_dir: Path to artifacts directory
        logger: Logger instance
    """
    # This will be implemented with full trend logic
    pass


def delete_old_runs(
    artifacts_dir: Path, keep: int = 52, logger: logging.Logger | None = None
) -> int:
    """Delete runs older than the retention limit.

    Args:
        artifacts_dir: Path to artifacts directory
        keep: Number of runs to retain
        logger: Logger instance

    Returns:
        Number of runs deleted
    """
    import shutil

    runs_dir = artifacts_dir / "runs"
    if not runs_dir.exists():
        return 0

    run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    deleted = 0

    for run_dir in run_dirs[keep:]:
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
            deleted += 1
            if logger:
                logger.info(f"Deleted old run: {run_dir.name}")

    return deleted


def create_regression_issues(
    artifacts_dir: Path,
    repo: str,
    token: str,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Create GitHub issues for regressions.

    Args:
        artifacts_dir: Path to artifacts directory
        repo: Repository to create issues in
        token: GitHub personal access token
        logger: Logger instance

    Returns:
        List of created issue URLs
    """
    from github import Github

    # Load regressions from latest run
    regressions_path = artifacts_dir / "trends" / "regressions.json"
    if not regressions_path.exists():
        return []

    with open(regressions_path) as f:
        regressions = json.load(f)

    # Filter to regressions without existing issues
    new_regressions = [r for r in regressions if not r.get("github_issue_url")]
    if not new_regressions:
        return []

    g = Github(token)
    issue_repo = g.get_repo(repo)
    created_urls = []

    for regression in new_regressions:
        title = (
            f"[LSQM] Regression: {regression.get('architecture_name', regression['arch_hash'][:8])}"
        )
        body = f"""## Regression Detected

**Architecture**: {regression.get("architecture_name", "Unknown")}
**Hash**: `{regression["arch_hash"]}`
**Services**: {", ".join(regression.get("services_affected", []))}

### Status Change
- **Previous**: {regression["from_status"]}
- **Current**: {regression["to_status"]}

### Run Information
- From run: `{regression["from_run_id"][:8]}`
- To run: `{regression["to_run_id"][:8]}`
- Detected: {regression["detected_at"]}

---
*Automatically created by LocalStack Quality Monitor*
"""
        try:
            issue = issue_repo.create_issue(title=title, body=body, labels=["lsqm-regression"])
            created_urls.append(issue.html_url)
            regression["github_issue_url"] = issue.html_url
            if logger:
                logger.info(f"Created issue: {issue.html_url}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to create issue: {e}")

    # Update regressions file with issue URLs
    with open(regressions_path, "w") as f:
        json.dump(regressions, f, indent=2)

    return created_urls


def create_gap_issues(
    artifacts_dir: Path,
    run_id: str,
    issue_repo: str,
    token: str,
    dry_run: bool = False,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Create GitHub issues for LocalStack gaps found in validation.

    This function analyzes validation results and creates issues for
    failures that are determined to be LocalStack issues (not config
    or setup problems).

    Args:
        artifacts_dir: Path to artifacts directory
        run_id: Run ID to analyze (or "latest")
        issue_repo: Repository to create issues in (e.g., "localstack/localstack")
        token: GitHub personal access token
        dry_run: If True, don't actually create issues, just log what would be created
        logger: Logger instance

    Returns:
        List of created issue URLs
    """
    from github import Github

    # Load run results
    run_data = load_run_results(artifacts_dir, run_id)
    if not run_data:
        if logger:
            logger.warning(f"No run data found for {run_id}")
        return []

    results = run_data.get("results", {})
    actual_run_id = run_data.get("run_id", run_id)

    # Load filed issues tracking
    filed_issues_path = artifacts_dir / "trends" / "filed_issues.json"
    if filed_issues_path.exists():
        with open(filed_issues_path) as f:
            filed_issues = json.load(f)
    else:
        filed_issues = {"issues": [], "signatures": {}}

    # Load architecture index for names
    arch_index = load_architecture_index(artifacts_dir)
    architectures = arch_index.get("architectures", {})

    # Find gaps (LocalStack issues)
    gaps = []
    for arch_hash, result in results.items():
        failure_analysis = result.get("failure_analysis")
        if not failure_analysis:
            continue

        # Only consider failures that are LocalStack issues
        if not failure_analysis.get("is_localstack_issue", False):
            continue

        arch_data = architectures.get(arch_hash, {})
        error_code = failure_analysis.get("aws_error_code", "")
        error_message = failure_analysis.get("error_message", "")
        affected_service = failure_analysis.get("affected_service", "Unknown")

        # Generate signature for deduplication
        signature = _generate_error_signature(
            service=affected_service,
            error_code=error_code,
            error_message=error_message,
        )

        # Skip if we've already filed an issue for this signature
        if signature in filed_issues.get("signatures", {}):
            existing_url = filed_issues["signatures"][signature]
            if logger:
                logger.debug(f"Skipping duplicate issue for {arch_hash[:8]}: {existing_url}")
            continue

        gaps.append(
            {
                "arch_hash": arch_hash,
                "arch_name": arch_data.get("name", arch_hash[:8]),
                "services": arch_data.get("services", []),
                "error_code": error_code,
                "error_message": error_message,
                "affected_service": affected_service,
                "signature": signature,
                "status": result.get("status", "FAILED"),
                "parity_result": failure_analysis.get("parity_result"),
                "localstack_exception": failure_analysis.get("localstack_exception"),
                "not_implemented": failure_analysis.get("not_implemented"),
            }
        )

    if not gaps:
        if logger:
            logger.info("No new LocalStack gaps to file issues for")
        return []

    if logger:
        logger.info(f"Found {len(gaps)} new LocalStack gaps to file")

    if dry_run:
        for gap in gaps:
            title = _build_issue_title(gap)
            if logger:
                logger.info(f"[DRY RUN] Would create issue: {title}")
        return []

    # Initialize GitHub client
    g = Github(token)
    repo = g.get_repo(issue_repo)
    created_urls = []

    for gap in gaps:
        # Check if a similar issue already exists in the repo
        existing_issue = _find_existing_issue(repo, gap, logger)
        if existing_issue:
            if logger:
                logger.info(
                    f"Found existing issue for {gap['arch_hash'][:8]}: {existing_issue.html_url}"
                )
            # Track the existing issue to avoid re-checking
            filed_issues["signatures"][gap["signature"]] = existing_issue.html_url
            continue

        # Build issue content
        title = _build_issue_title(gap)
        body = _build_issue_body(gap, actual_run_id, artifacts_dir)

        # Determine labels
        labels = ["lsqm-gap"]
        if gap.get("affected_service"):
            service_label = f"aws:{gap['affected_service'].lower().replace(' ', '-')}"
            labels.append(service_label)
        if gap.get("not_implemented"):
            labels.append("not-implemented")
        if gap.get("parity_result") and not gap["parity_result"].get("has_parity"):
            labels.append("parity-issue")

        try:
            # Create only labels that exist
            existing_labels = [label.name for label in repo.get_labels()]
            valid_labels = [lbl for lbl in labels if lbl in existing_labels]

            issue = repo.create_issue(title=title, body=body, labels=valid_labels)
            created_urls.append(issue.html_url)

            # Track filed issue
            filed_issues["signatures"][gap["signature"]] = issue.html_url
            filed_issues["issues"].append(
                {
                    "url": issue.html_url,
                    "signature": gap["signature"],
                    "arch_hash": gap["arch_hash"],
                    "service": gap["affected_service"],
                    "error_code": gap["error_code"],
                    "run_id": actual_run_id,
                    "created_at": issue.created_at.isoformat() if issue.created_at else "",
                }
            )

            if logger:
                logger.info(f"Created issue: {issue.html_url}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to create issue for {gap['arch_hash'][:8]}: {e}")

    # Save filed issues tracking
    filed_issues_path.parent.mkdir(parents=True, exist_ok=True)
    with open(filed_issues_path, "w") as f:
        json.dump(filed_issues, f, indent=2)

    return created_urls


def _generate_error_signature(
    service: str,
    error_code: str,
    error_message: str,
) -> str:
    """Generate a unique signature for an error for deduplication.

    Args:
        service: AWS service name
        error_code: AWS error code
        error_message: Error message

    Returns:
        Hash signature string
    """
    # Normalize the error message (remove dynamic parts)
    normalized_msg = error_message.lower() if error_message else ""
    # Remove UUIDs, timestamps, ARNs, etc.
    import re

    normalized_msg = re.sub(
        r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "<uuid>", normalized_msg
    )
    normalized_msg = re.sub(r"arn:aws:[^:\s]+:[^:\s]*:[^:\s]*:[^\s]+", "<arn>", normalized_msg)
    normalized_msg = re.sub(
        r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}", "<timestamp>", normalized_msg
    )
    normalized_msg = re.sub(r"\d{10,}", "<id>", normalized_msg)  # Long numbers

    # Take first 100 chars of normalized message
    normalized_msg = normalized_msg[:100]

    # Create hash
    content = f"{service}:{error_code}:{normalized_msg}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _find_existing_issue(repo, gap: dict, logger: logging.Logger | None = None) -> object | None:
    """Search for an existing issue that matches this gap.

    Args:
        repo: GitHub repository object
        gap: Gap dictionary
        logger: Logger instance

    Returns:
        Existing issue object or None
    """
    try:
        # Search for issues with similar error code and service
        service = gap.get("affected_service", "").lower()
        error_code = gap.get("error_code", "")

        if not error_code and not service:
            return None

        # Search through open issues for a match
        issues = repo.get_issues(state="open")

        # Check first 20 issues for a match
        for issue in issues[:20]:
            if error_code and error_code in issue.title:
                return issue
            if error_code and error_code in (issue.body or ""):
                return issue

        return None
    except Exception as e:
        if logger:
            logger.debug(f"Issue search failed: {e}")
        return None


def _build_issue_title(gap: dict) -> str:
    """Build a descriptive issue title.

    Args:
        gap: Gap dictionary

    Returns:
        Issue title string
    """
    service = gap.get("affected_service", "Unknown")
    error_code = gap.get("error_code", "")

    if error_code:
        return f"[{service}] {error_code}: Parity gap detected"
    elif gap.get("not_implemented"):
        return f"[{service}] Feature not implemented"
    else:
        return f"[{service}] Compatibility issue in {gap.get('arch_name', 'validation')}"


def _build_issue_body(gap: dict, run_id: str, artifacts_dir: Path) -> str:
    """Build the issue body with details and reproduction steps.

    Args:
        gap: Gap dictionary
        run_id: Run ID where gap was found
        artifacts_dir: Path to artifacts for linking

    Returns:
        Issue body markdown string
    """
    arch_hash = gap["arch_hash"]

    body = f"""## LocalStack Compatibility Gap

**Service**: {gap.get("affected_service", "Unknown")}
**Error Code**: `{gap.get("error_code", "N/A")}`
**Architecture**: {gap.get("arch_name", arch_hash[:8])} (`{arch_hash[:12]}`)

### Error Details

```
{gap.get("error_message", "No error message available")[:500]}
```
"""

    # Add parity analysis if available
    parity = gap.get("parity_result")
    if parity:
        body += f"""
### Error Parity Analysis

- **Has AWS Parity**: {"Yes" if parity.get("has_parity") else "No"}
- **Similarity Score**: {parity.get("similarity_score", 0):.1%}
"""
        if parity.get("issues"):
            body += "- **Issues Found**:\n"
            for issue in parity["issues"][:3]:
                body += f"  - {issue}\n"

    # Add LocalStack exception if present
    if gap.get("localstack_exception"):
        body += f"""
### LocalStack Exception

```
{gap["localstack_exception"][:300]}
```
"""

    # Add not implemented warning
    if gap.get("not_implemented"):
        body += f"""
### Not Implemented

The following feature appears to be not implemented:
```
{gap["not_implemented"][:200]}
```
"""

    body += f"""
### Detection Information

- **Run ID**: `{run_id}`
- **Status**: {gap.get("status", "FAILED")}
- **Services in Architecture**: {", ".join(gap.get("services", [])[:5])}

### Reproduction

This issue was detected by the LocalStack Quality Monitor during automated validation.
The architecture uses Terraform to provision AWS resources and runs pytest-based validation tests.

---
*Automatically created by [LocalStack Quality Monitor](https://github.com/localstack/localstack-quality-monitor)*
"""

    return body


def push_artifacts(
    artifacts_dir: Path,
    message: str,
    token: str,
    logger: logging.Logger | None = None,
) -> dict:
    """Push artifacts to remote repository.

    Args:
        artifacts_dir: Path to artifacts directory
        message: Commit message
        token: GitHub personal access token
        logger: Logger instance

    Returns:
        Dictionary with commit info
    """
    # Stage all changes
    subprocess.run(["git", "add", "-A"], cwd=artifacts_dir, capture_output=True, check=True)

    # Check if there are changes to commit
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=artifacts_dir,
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        if logger:
            logger.info("No changes to commit")
        return {"commit_sha": "", "message": "No changes"}

    # Commit
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=artifacts_dir,
        capture_output=True,
        check=True,
    )

    # Get commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=artifacts_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    commit_sha = result.stdout.strip()

    # Push
    push_result = subprocess.run(
        ["git", "push"],
        cwd=artifacts_dir,
        capture_output=True,
        text=True,
    )
    if push_result.returncode != 0:
        error_msg = push_result.stderr or push_result.stdout or "Unknown error"
        if (
            "permission" in error_msg.lower()
            or "403" in error_msg
            or "authentication" in error_msg.lower()
        ):
            raise RuntimeError(
                f"Git push failed - permission denied. "
                f"Make sure ARTIFACT_REPO_TOKEN secret is set with repo scope. "
                f"Error: {error_msg}"
            )
        raise RuntimeError(f"Git push failed: {error_msg}")

    if logger:
        logger.info(f"Pushed commit: {commit_sha[:7]}")

    return {"commit_sha": commit_sha, "message": message}
