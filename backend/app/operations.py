"""Small process-local coordinator for scan/cleanup mutual exclusion."""

from __future__ import annotations

import threading
from contextlib import contextmanager


class OperationConflict(RuntimeError):
    pass


class OperationCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cleanup_executing = False

    @property
    def cleanup_executing(self) -> bool:
        with self._lock:
            return self._cleanup_executing

    @contextmanager
    def cleanup_execution(self):
        with self._lock:
            if self._cleanup_executing:
                raise OperationConflict("OPERATION_CONFLICT")
            self._cleanup_executing = True
        try:
            yield
        finally:
            with self._lock:
                self._cleanup_executing = False


operations = OperationCoordinator()
