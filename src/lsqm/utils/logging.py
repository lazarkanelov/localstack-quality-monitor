"""Structured JSON logging with stage timing."""

import json
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format log records as JSON with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add extra fields if present
        if hasattr(record, "stage"):
            log_data["stage"] = record.stage
        if hasattr(record, "duration"):
            log_data["duration_seconds"] = record.duration
        if hasattr(record, "error_type"):
            log_data["error"] = {
                "type": record.error_type,
                "message": getattr(record, "error_message", ""),
            }
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        return json.dumps(log_data)


class StageTimer:
    """Track timing for a pipeline stage."""

    def __init__(self, stage_name: str, logger: logging.Logger):
        self.stage_name = stage_name
        self.logger = logger
        self.start_time: float = 0
        self.end_time: float = 0

    def start(self) -> None:
        """Mark stage start."""
        self.start_time = time.time()
        self.logger.info(
            f"Stage {self.stage_name} started",
            extra={"stage": self.stage_name, "extra": {"event": "stage_start"}},
        )

    def end(self, success: bool = True) -> float:
        """Mark stage end and return duration."""
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        event = "stage_complete" if success else "stage_failed"
        self.logger.info(
            f"Stage {self.stage_name} {'completed' if success else 'failed'} in {duration:.2f}s",
            extra={
                "stage": self.stage_name,
                "duration": duration,
                "extra": {"event": event, "success": success},
            },
        )
        return duration


def get_logger(name: str, verbose: bool = False) -> logging.Logger:
    """Get a logger configured for LSQM."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)

        if verbose:
            handler.setFormatter(JSONFormatter())
            logger.setLevel(logging.DEBUG)
        else:
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.setLevel(logging.INFO)

        logger.addHandler(handler)

    return logger


@contextmanager
def stage_context(stage_name: str, logger: logging.Logger):
    """Context manager for timing a pipeline stage."""
    timer = StageTimer(stage_name, logger)
    timer.start()
    try:
        yield timer
        timer.end(success=True)
    except Exception as e:
        timer.end(success=False)
        logger.error(
            f"Stage {stage_name} error: {e}",
            extra={
                "stage": stage_name,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise


def log_error(
    logger: logging.Logger,
    message: str,
    error: Exception,
    stage: str | None = None,
    **extra: Any,
) -> None:
    """Log an error with structured context."""
    log_extra: dict[str, Any] = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    if stage:
        log_extra["stage"] = stage
    if extra:
        log_extra["extra"] = extra

    logger.error(message, extra=log_extra)
