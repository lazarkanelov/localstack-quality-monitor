"""GitHub operations - clone, pull, push, issue creation."""

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
            raise RuntimeError(f"Git clone failed: {e.stderr or e.stdout or str(e)}")

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


def delete_old_runs(artifacts_dir: Path, keep: int = 52, logger: logging.Logger | None = None) -> int:
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
        title = f"[LSQM] Regression: {regression.get('architecture_name', regression['arch_hash'][:8])}"
        body = f"""## Regression Detected

**Architecture**: {regression.get('architecture_name', 'Unknown')}
**Hash**: `{regression['arch_hash']}`
**Services**: {', '.join(regression.get('services_affected', []))}

### Status Change
- **Previous**: {regression['from_status']}
- **Current**: {regression['to_status']}

### Run Information
- From run: `{regression['from_run_id'][:8]}`
- To run: `{regression['to_run_id'][:8]}`
- Detected: {regression['detected_at']}

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
    subprocess.run(["git", "push"], cwd=artifacts_dir, capture_output=True, check=True)

    if logger:
        logger.info(f"Pushed commit: {commit_sha[:7]}")

    return {"commit_sha": commit_sha, "message": message}
