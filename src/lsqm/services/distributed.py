"""Distributed execution - run validation across multiple workers."""

import asyncio
import json
import logging
import socket
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from lsqm.models.qa_models import WorkerStatus, WorkerTask


class TaskQueue:
    """Simple file-based task queue for distributed execution."""

    def __init__(
        self,
        artifacts_dir: Path,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.logger = logger
        self.queue_dir = artifacts_dir / "qa" / "task_queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)

        self.pending_dir = self.queue_dir / "pending"
        self.running_dir = self.queue_dir / "running"
        self.completed_dir = self.queue_dir / "completed"
        self.failed_dir = self.queue_dir / "failed"

        for d in [self.pending_dir, self.running_dir, self.completed_dir, self.failed_dir]:
            d.mkdir(exist_ok=True)

    def enqueue(self, task: WorkerTask) -> str:
        """Add a task to the queue.

        Args:
            task: WorkerTask to enqueue

        Returns:
            Task ID
        """
        task_file = self.pending_dir / f"{task.task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task.to_dict(), f, indent=2)

        if self.logger:
            self.logger.debug(f"Enqueued task {task.task_id}")

        return task.task_id

    def enqueue_batch(
        self,
        architectures: list[tuple[str, dict]],
        run_id: str,
        localstack_version: str,
        timeout: int,
    ) -> list[str]:
        """Enqueue multiple tasks.

        Args:
            architectures: List of (hash, data) tuples
            run_id: Run ID
            localstack_version: LocalStack version
            timeout: Timeout per task

        Returns:
            List of task IDs
        """
        task_ids = []

        for i, (arch_hash, arch_data) in enumerate(architectures):
            task = WorkerTask(
                task_id=str(uuid.uuid4()),
                arch_hash=arch_hash,
                arch_data=arch_data,
                run_id=run_id,
                localstack_version=localstack_version,
                timeout=timeout,
                priority=len(architectures) - i,  # Earlier = higher priority
            )
            task_ids.append(self.enqueue(task))

        return task_ids

    def claim_task(self, worker_id: str) -> WorkerTask | None:
        """Claim a pending task for processing.

        Args:
            worker_id: ID of the worker claiming the task

        Returns:
            WorkerTask or None if no tasks available
        """
        # Get pending tasks sorted by priority
        pending_files = sorted(
            self.pending_dir.glob("*.json"),
            key=lambda f: json.load(open(f)).get("priority", 0),
            reverse=True,
        )

        for task_file in pending_files:
            try:
                with open(task_file) as f:
                    task_data = json.load(f)

                task = WorkerTask(
                    task_id=task_data["task_id"],
                    arch_hash=task_data["arch_hash"],
                    arch_data=task_data["arch_data"],
                    run_id=task_data["run_id"],
                    localstack_version=task_data["localstack_version"],
                    timeout=task_data["timeout"],
                    priority=task_data.get("priority", 0),
                    status="running",
                    assigned_worker=worker_id,
                )

                # Move to running
                running_file = self.running_dir / f"{task.task_id}.json"
                task_file.rename(running_file)

                with open(running_file, "w") as f:
                    json.dump(task.to_dict(), f, indent=2)

                if self.logger:
                    self.logger.info(f"Worker {worker_id} claimed task {task.task_id}")

                return task

            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to claim task: {e}")
                continue

        return None

    def complete_task(self, task_id: str, result: dict) -> None:
        """Mark a task as completed.

        Args:
            task_id: Task ID
            result: Validation result
        """
        running_file = self.running_dir / f"{task_id}.json"
        completed_file = self.completed_dir / f"{task_id}.json"

        if running_file.exists():
            with open(running_file) as f:
                task_data = json.load(f)

            task_data["status"] = "completed"
            task_data["result"] = result
            task_data["completed_at"] = datetime.utcnow().isoformat()

            with open(completed_file, "w") as f:
                json.dump(task_data, f, indent=2)

            running_file.unlink()

            if self.logger:
                self.logger.info(f"Task {task_id} completed")

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed.

        Args:
            task_id: Task ID
            error: Error message
        """
        running_file = self.running_dir / f"{task_id}.json"
        failed_file = self.failed_dir / f"{task_id}.json"

        if running_file.exists():
            with open(running_file) as f:
                task_data = json.load(f)

            task_data["status"] = "failed"
            task_data["error"] = error
            task_data["failed_at"] = datetime.utcnow().isoformat()

            with open(failed_file, "w") as f:
                json.dump(task_data, f, indent=2)

            running_file.unlink()

            if self.logger:
                self.logger.warning(f"Task {task_id} failed: {error}")

    def get_stats(self) -> dict:
        """Get queue statistics.

        Returns:
            Dict with queue stats
        """
        return {
            "pending": len(list(self.pending_dir.glob("*.json"))),
            "running": len(list(self.running_dir.glob("*.json"))),
            "completed": len(list(self.completed_dir.glob("*.json"))),
            "failed": len(list(self.failed_dir.glob("*.json"))),
        }

    def get_results(self, run_id: str) -> list[dict]:
        """Get all results for a run.

        Args:
            run_id: Run ID

        Returns:
            List of result dicts
        """
        results = []

        for completed_file in self.completed_dir.glob("*.json"):
            with open(completed_file) as f:
                task_data = json.load(f)
            if task_data.get("run_id") == run_id:
                results.append(task_data.get("result", {}))

        return results


class WorkerRegistry:
    """Registry of active workers."""

    def __init__(
        self,
        artifacts_dir: Path,
        heartbeat_timeout: int = 60,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.heartbeat_timeout = timedelta(seconds=heartbeat_timeout)
        self.logger = logger
        self.workers_dir = artifacts_dir / "qa" / "workers"
        self.workers_dir.mkdir(parents=True, exist_ok=True)

    def register(self, worker_id: str) -> WorkerStatus:
        """Register a new worker.

        Args:
            worker_id: Unique worker ID

        Returns:
            WorkerStatus
        """
        now = datetime.utcnow()
        status = WorkerStatus(
            worker_id=worker_id,
            hostname=socket.gethostname(),
            started_at=now,
            last_heartbeat=now,
            status="idle",
        )

        self._save_worker(status)

        if self.logger:
            self.logger.info(f"Worker {worker_id} registered on {status.hostname}")

        return status

    def heartbeat(self, worker_id: str, current_task: str | None = None) -> None:
        """Update worker heartbeat.

        Args:
            worker_id: Worker ID
            current_task: Currently running task ID
        """
        worker_file = self.workers_dir / f"{worker_id}.json"

        if worker_file.exists():
            with open(worker_file) as f:
                data = json.load(f)

            data["last_heartbeat"] = datetime.utcnow().isoformat()
            data["current_task"] = current_task
            data["status"] = "busy" if current_task else "idle"

            with open(worker_file, "w") as f:
                json.dump(data, f, indent=2)

    def unregister(self, worker_id: str) -> None:
        """Unregister a worker.

        Args:
            worker_id: Worker ID
        """
        worker_file = self.workers_dir / f"{worker_id}.json"
        if worker_file.exists():
            worker_file.unlink()

        if self.logger:
            self.logger.info(f"Worker {worker_id} unregistered")

    def get_active_workers(self) -> list[WorkerStatus]:
        """Get list of active workers.

        Returns:
            List of active WorkerStatus
        """
        workers = []
        now = datetime.utcnow()

        for worker_file in self.workers_dir.glob("*.json"):
            with open(worker_file) as f:
                data = json.load(f)

            last_heartbeat = datetime.fromisoformat(data["last_heartbeat"])

            if now - last_heartbeat < self.heartbeat_timeout:
                workers.append(
                    WorkerStatus(
                        worker_id=data["worker_id"],
                        hostname=data["hostname"],
                        started_at=datetime.fromisoformat(data["started_at"]),
                        last_heartbeat=last_heartbeat,
                        tasks_completed=data.get("tasks_completed", 0),
                        tasks_failed=data.get("tasks_failed", 0),
                        current_task=data.get("current_task"),
                        status=data.get("status", "idle"),
                    )
                )
            else:
                # Mark as offline
                data["status"] = "offline"
                with open(worker_file, "w") as f:
                    json.dump(data, f, indent=2)

        return workers

    def _save_worker(self, status: WorkerStatus) -> None:
        """Save worker status to file."""
        worker_file = self.workers_dir / f"{status.worker_id}.json"
        with open(worker_file, "w") as f:
            json.dump(status.to_dict(), f, indent=2)


class DistributedWorker:
    """A distributed validation worker."""

    def __init__(
        self,
        artifacts_dir: Path,
        validate_func: Callable,
        worker_id: str | None = None,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.validate_func = validate_func
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.logger = logger

        self.queue = TaskQueue(artifacts_dir, logger)
        self.registry = WorkerRegistry(artifacts_dir, logger=logger)

        self._running = False
        self._status: WorkerStatus | None = None

    async def run(self, poll_interval: float = 5.0) -> None:
        """Run the worker loop.

        Args:
            poll_interval: Seconds between queue polls
        """
        self._running = True
        self._status = self.registry.register(self.worker_id)

        if self.logger:
            self.logger.info(f"Worker {self.worker_id} starting")

        try:
            while self._running:
                # Heartbeat
                self.registry.heartbeat(self.worker_id, self._status.current_task)

                # Try to claim a task
                task = self.queue.claim_task(self.worker_id)

                if task:
                    self._status.current_task = task.task_id

                    try:
                        # Run validation
                        result = await self.validate_func(
                            task.arch_hash,
                            task.arch_data,
                            task.run_id,
                            task.localstack_version,
                            task.timeout,
                        )

                        self.queue.complete_task(task.task_id, result)
                        self._status.tasks_completed += 1

                    except Exception as e:
                        self.queue.fail_task(task.task_id, str(e))
                        self._status.tasks_failed += 1

                    finally:
                        self._status.current_task = None

                else:
                    # No tasks, wait before polling again
                    await asyncio.sleep(poll_interval)

        finally:
            self.registry.unregister(self.worker_id)
            if self.logger:
                self.logger.info(f"Worker {self.worker_id} stopped")

    def stop(self) -> None:
        """Stop the worker."""
        self._running = False


class DistributedCoordinator:
    """Coordinate distributed validation across workers."""

    def __init__(
        self,
        artifacts_dir: Path,
        logger: logging.Logger | None = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.logger = logger

        self.queue = TaskQueue(artifacts_dir, logger)
        self.registry = WorkerRegistry(artifacts_dir, logger=logger)

    def submit_validation_run(
        self,
        architectures: list[tuple[str, dict]],
        run_id: str,
        localstack_version: str,
        timeout: int,
    ) -> dict:
        """Submit a validation run for distributed execution.

        Args:
            architectures: List of (hash, data) tuples
            run_id: Run ID
            localstack_version: LocalStack version
            timeout: Timeout per architecture

        Returns:
            Dict with submission info
        """
        task_ids = self.queue.enqueue_batch(architectures, run_id, localstack_version, timeout)

        return {
            "run_id": run_id,
            "tasks_submitted": len(task_ids),
            "task_ids": task_ids,
            "active_workers": len(self.registry.get_active_workers()),
        }

    def get_run_status(self, run_id: str) -> dict:
        """Get status of a distributed run.

        Args:
            run_id: Run ID

        Returns:
            Dict with run status
        """
        stats = self.queue.get_stats()
        workers = self.registry.get_active_workers()
        results = self.queue.get_results(run_id)

        return {
            "run_id": run_id,
            "queue_stats": stats,
            "active_workers": len(workers),
            "workers": [w.to_dict() for w in workers],
            "completed_count": len(results),
            "results": results,
        }

    def wait_for_completion(
        self,
        run_id: str,
        poll_interval: float = 10.0,
        timeout: float = 3600.0,
    ) -> list[dict]:
        """Wait for a run to complete.

        Args:
            run_id: Run ID
            poll_interval: Seconds between polls
            timeout: Maximum seconds to wait

        Returns:
            List of results
        """
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            stats = self.queue.get_stats()

            # Check if all tasks are done
            if stats["pending"] == 0 and stats["running"] == 0:
                break

            time.sleep(poll_interval)

            if self.logger:
                self.logger.info(
                    f"Run {run_id}: {stats['completed']} completed, "
                    f"{stats['pending']} pending, {stats['running']} running"
                )

        return self.queue.get_results(run_id)


def start_worker(
    artifacts_dir: Path,
    validate_func: Callable,
    worker_id: str | None = None,
) -> None:
    """Start a distributed worker.

    Args:
        artifacts_dir: Path to artifacts directory
        validate_func: Async function to validate an architecture
        worker_id: Optional worker ID
    """
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("lsqm.worker")

    worker = DistributedWorker(
        artifacts_dir=artifacts_dir,
        validate_func=validate_func,
        worker_id=worker_id,
        logger=logger,
    )

    asyncio.run(worker.run())
