import logging
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.scanner.enumerator import RootUnavailable
from app.scanner.models import ScanResult
from app.scanner.metrics import ScanResourceMonitor
from app.scanner.path_guard import validate_scan_root
from app.scanner.policy import SCAN_POLICY
from app.scanner.service import scan_fixture


ACTIVE_STATES = {"queued", "running", "cancelling"}
RESULT_STATES = {"cancelled", "completed"}
TERMINAL_STATES = RESULT_STATES | {"failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScanAlreadyRunning(RuntimeError):
    pass


class ScanNotFound(LookupError):
    pass


class ResultNotReady(RuntimeError):
    pass


@dataclass
class ScanTask:
    scan_id: str
    root: str
    root_path: Path = field(repr=False)
    state: str = "queued"
    phase: str = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    files_seen: int = 0
    dirs_seen: int = 0
    logical_bytes: int = 0
    skipped_count: int = 0
    errors_count: int = 0
    cancel_requested: bool = False
    error_code: str | None = None
    error_message: str | None = None
    result: ScanResult | None = field(default=None, repr=False)
    metrics: dict[str, int | float | None] | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    started_clock: float | None = field(default=None, repr=False)
    finished_clock: float | None = field(default=None, repr=False)

    def public_status(self) -> dict[str, object]:
        end = self.finished_clock if self.finished_clock is not None else time.monotonic()
        elapsed_ms = round((end - self.started_clock) * 1000) if self.started_clock else 0
        return {
            "scan_id": self.scan_id,
            "root": self.root,
            "state": self.state,
            "phase": self.phase,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": elapsed_ms,
            "files_seen": self.files_seen,
            "dirs_seen": self.dirs_seen,
            "logical_bytes": self.logical_bytes,
            "skipped_count": self.skipped_count,
            "errors_count": self.errors_count,
            "errors": self.result.errors if self.result else {},
            "exclusions": self.result.exclusions if self.result else {},
            "metrics": self.metrics,
            "cancel_requested": self.cancel_requested,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


class ScanTaskManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: OrderedDict[str, ScanTask] = OrderedDict()

    def create(self, requested_root: str) -> dict[str, object]:
        root_path, root_label = validate_scan_root(requested_root)
        with self._lock:
            if sum(task.state in ACTIVE_STATES for task in self._tasks.values()) >= SCAN_POLICY.max_active_scans:
                raise ScanAlreadyRunning("A scan is already active.")
            task = ScanTask(scan_id=str(uuid.uuid4()), root=root_label, root_path=root_path)
            self._tasks[task.scan_id] = task
            self._prune_finished()
            threading.Thread(
                target=self._run, args=(task,), name="diskscope-approved-scan", daemon=True
            ).start()
            return {"scan_id": task.scan_id, "state": task.state}

    def _prune_finished(self) -> None:
        while len(self._tasks) > 8:
            oldest_id = next(iter(self._tasks))
            if self._tasks[oldest_id].state not in TERMINAL_STATES:
                break
            del self._tasks[oldest_id]

    def _run(self, task: ScanTask) -> None:
        with self._lock:
            task.started_at = utc_now()
            task.started_clock = time.monotonic()
            task.state = "cancelling" if task.cancel_requested else "running"
            task.phase = "enumerating"
        monitor = ScanResourceMonitor()
        last_sample_items = 0

        def update_progress(result: ScanResult) -> None:
            nonlocal last_sample_items
            items_seen = result.files_seen + result.dirs_seen
            if items_seen - last_sample_items >= 256:
                monitor.sample()
                last_sample_items = items_seen
            with self._lock:
                task.files_seen = result.files_seen
                task.dirs_seen = result.dirs_seen
                task.logical_bytes = result.logical_bytes
                task.skipped_count = result.skipped_count
                task.errors_count = result.errors_count

        try:
            result = scan_fixture(task.root_path, task.cancel_event, update_progress)
            with self._lock:
                task.result = result
                task.finished_at = utc_now()
                task.finished_clock = time.monotonic()
                task.state = "cancelled" if result.cancelled else "completed"
                task.phase = task.state
                task.metrics = monitor.finish(task.files_seen, round(
                    (task.finished_clock - task.started_clock) * 1000
                ))
        except RootUnavailable:
            with self._lock:
                task.finished_at = utc_now()
                task.finished_clock = time.monotonic()
                task.state = "failed"
                task.phase = "failed"
                task.error_code = "INVALID_PATH"
                task.error_message = "The approved scan root became unavailable."
                task.metrics = monitor.finish(task.files_seen, round(
                    (task.finished_clock - task.started_clock) * 1000
                ))
        except OSError as exc:
            logging.error("Approved scan failed with %s", type(exc).__name__)
            with self._lock:
                task.finished_at = utc_now()
                task.finished_clock = time.monotonic()
                task.state = "failed"
                task.phase = "failed"
                task.error_code = "IO_ERROR"
                task.error_message = "The approved scan could not finish."
                task.metrics = monitor.finish(task.files_seen, round(
                    (task.finished_clock - task.started_clock) * 1000
                ))
        except Exception as exc:
            logging.error("Approved scan failed with %s", type(exc).__name__)
            with self._lock:
                task.finished_at = utc_now()
                task.finished_clock = time.monotonic()
                task.state = "failed"
                task.phase = "failed"
                task.error_code = "IO_ERROR"
                task.error_message = "The approved scan could not finish."
                task.metrics = monitor.finish(task.files_seen, round(
                    (task.finished_clock - task.started_clock) * 1000
                ))

    def status(self, scan_id: str) -> dict[str, object]:
        with self._lock:
            return self._find(scan_id).public_status()

    def cancel(self, scan_id: str) -> dict[str, object]:
        with self._lock:
            task = self._find(scan_id)
            if task.state in ACTIVE_STATES:
                task.cancel_requested = True
                task.cancel_event.set()
                task.state = "cancelling"
                task.phase = "cancelling"
            return task.public_status()

    def result(self, scan_id: str) -> ScanResult:
        with self._lock:
            task = self._find(scan_id)
            if task.state not in RESULT_STATES or task.result is None:
                raise ResultNotReady("The scan result is not available yet.")
            return task.result

    def _find(self, scan_id: str) -> ScanTask:
        try:
            return self._tasks[scan_id]
        except KeyError as exc:
            raise ScanNotFound("Scan not found.") from exc


scan_tasks = ScanTaskManager()
