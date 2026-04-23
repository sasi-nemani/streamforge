"""Multi-stream supervisor — manages one worker process per stream assignment.

Pattern: Gunicorn/Celery supervisor. Workers are independent, crash-isolated,
and auto-restartable. State is shared via filesystem (checkpoints).
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import signal
import time as _time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import StreamAssignment, SupervisorConfig

logger = logging.getLogger(__name__)


class WorkerState:
    def __init__(self, assignment: StreamAssignment) -> None:
        self.assignment = assignment
        self.process: multiprocessing.Process | None = None
        self.restart_count: int = 0
        self.restart_timestamps: list[float] = []
        self.status: str = "pending"

    def recent_restarts(self, window_seconds: int = 3600) -> int:
        cutoff = _time.time() - window_seconds
        self.restart_timestamps = [t for t in self.restart_timestamps if t > cutoff]
        return len(self.restart_timestamps)

    def backoff_delay(self, attempt: int, base: float = 5.0, cap: float = 120.0) -> float:
        """Exponential backoff delay for restart attempts.

        delay = min(base * 2^attempt, cap)
        Resets to base if last restart was >10 minutes ago.
        """
        # If last restart was long ago, reset backoff
        if self.restart_timestamps:
            seconds_since_last = _time.time() - self.restart_timestamps[-1]
            if seconds_since_last > 600:  # 10 minutes stable
                return base
        return min(base * (2 ** attempt), cap)


def _worker_main(assignment: StreamAssignment) -> None:
    """Entry point for each worker process.

    Uses the source factory to dispatch to the correct watch loop —
    no hardcoded string matching for source types.
    """
    try:
        import setproctitle
        setproctitle.setproctitle(f"streamforge-worker:{assignment.stream_uri}")
    except ImportError:
        pass

    from .connectors.factory import resolve_stream_source
    source_type, parsed_id = resolve_stream_source(assignment.stream_uri)

    if source_type == "kafka":
        from .detector.watch import watch_stream_kafka
        from .config import load as load_config
        cfg = load_config()
        cfg.namespace = assignment.namespace
        watch_stream_kafka(
            topic=parsed_id,
            kafka_cfg=cfg.kafka,
            schema_path=assignment.schema_path,
            poll_interval_seconds=assignment.poll_interval_seconds,
            sample_size=assignment.sample_size,
            window_capacity=assignment.window_capacity,
            webhook_url=assignment.webhook_url,
        )
    else:
        from .detector.watch import watch_stream
        watch_stream(
            stream_path=parsed_id,
            schema_path=assignment.schema_path,
            poll_interval_seconds=assignment.poll_interval_seconds,
            sample_size=assignment.sample_size,
            window_capacity=assignment.window_capacity,
            webhook_url=assignment.webhook_url,
        )


class Supervisor:
    """Manages N worker processes, one per stream assignment."""

    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config
        self.workers: dict[str, WorkerState] = {}
        self._shutdown = False

        for assignment in config.assignments:
            self.workers[assignment.stream_uri] = WorkerState(assignment)

    def _write_pid_file(self) -> None:
        """Write supervisor PID to file for HA monitoring.

        Uses O_CREAT|O_EXCL for atomic creation — prevents two supervisors
        from both believing they're primary. If a stale PID file exists
        (dead process), it is removed and recreated atomically.
        """
        pid_path = Path(self.config.pid_file)
        my_pid = str(os.getpid())
        try:
            # Try atomic exclusive creation first
            fd = os.open(str(pid_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, my_pid.encode())
            os.close(fd)
            logger.info("Supervisor PID file: %s (PID=%s)", pid_path, my_pid)
            return
        except FileExistsError:
            pass  # PID file exists — check if stale

        # PID file exists — check if the process is alive
        try:
            old_pid = int(pid_path.read_text().strip())
            try:
                os.kill(old_pid, 0)  # check if alive
                logger.warning("Supervisor PID %d is still alive — overwriting PID file", old_pid)
            except OSError:
                logger.info("Stale PID file (PID %d dead) — overwriting", old_pid)
        except (ValueError, OSError):
            logger.info("Corrupt PID file — overwriting")

        # Remove stale/corrupt file and recreate atomically
        try:
            pid_path.unlink(missing_ok=True)
            fd = os.open(str(pid_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, my_pid.encode())
            os.close(fd)
            logger.info("Supervisor PID file: %s (PID=%s)", pid_path, my_pid)
        except Exception as e:
            logger.warning("Failed to write PID file: %s", e)

    def _remove_pid_file(self) -> None:
        """Remove PID file on graceful shutdown."""
        try:
            Path(self.config.pid_file).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Failed to remove PID file: %s", e)

    def start(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Spawn all workers
        for uri, ws in self.workers.items():
            self._spawn_worker(ws)

        # Monitor loop
        while not self._shutdown:
            for uri, ws in self.workers.items():
                if ws.process and not ws.process.is_alive():
                    exit_code = ws.process.exitcode
                    logger.warning("Worker %s exited with code %s", uri, exit_code)
                    ws.status = "crashed"

                    if ws.recent_restarts() < self.config.max_restart_count:
                        attempt = ws.recent_restarts()
                        delay = ws.backoff_delay(attempt, base=self.config.restart_delay_seconds)
                        logger.info("Restarting worker %s (attempt %d, backoff %.1fs)", uri, attempt + 1, delay)
                        _time.sleep(delay)
                        self._spawn_worker(ws)
                    else:
                        logger.critical("Worker %s exceeded max restarts (%d/hr) — FAILED",
                                       uri, self.config.max_restart_count)
                        ws.status = "failed"

            self._write_health()
            _time.sleep(self.config.health_check_interval)

        self._shutdown_all()

    def _spawn_worker(self, ws: WorkerState) -> None:
        p = multiprocessing.Process(
            target=_worker_main,
            args=(ws.assignment,),
            name=f"sf-worker-{ws.assignment.stream_uri}",
            daemon=False,
        )
        p.start()
        ws.process = p
        ws.status = "running"
        ws.restart_timestamps.append(_time.time())
        logger.info("Spawned worker PID=%d for %s", p.pid, ws.assignment.stream_uri)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info("Supervisor received signal %d — shutting down", signum)
        self._shutdown = True

    def _shutdown_all(self) -> None:
        for uri, ws in self.workers.items():
            if ws.process and ws.process.is_alive():
                logger.info("Sending SIGTERM to worker %s (PID=%d)", uri, ws.process.pid)
                ws.process.terminate()

        deadline = _time.time() + 10
        for uri, ws in self.workers.items():
            if ws.process:
                remaining = max(0, deadline - _time.time())
                ws.process.join(timeout=remaining)
                if ws.process.is_alive():
                    logger.warning("Worker %s did not exit — sending SIGKILL", uri)
                    ws.process.kill()
                ws.status = "stopped"

    def _write_health(self) -> None:
        try:
            health = {
                "timestamp": datetime.now(UTC).isoformat(),
                "workers": {
                    uri: {
                        "status": ws.status,
                        "pid": ws.process.pid if ws.process else None,
                        "restarts_last_hour": ws.recent_restarts(),
                    }
                    for uri, ws in self.workers.items()
                },
            }
            Path("supervisor_health.json").write_text(json.dumps(health, indent=2))
        except OSError as e:
            logger.warning("Failed to write supervisor health: %s", e)
