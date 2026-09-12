"""Reproducible, fixture-only M1 scan timing."""

import json
import threading
import time
import tracemalloc

from app.scanner.service import scan_fixture
from tests.fixtures.generate_sample import (
    EXPECTED_MEDIUM_BYTES,
    EXPECTED_MEDIUM_DIRS,
    EXPECTED_MEDIUM_FILES,
    MEDIUM_ROOT,
    generate_medium,
)


def main() -> None:
    generate_medium()
    tracemalloc.start()
    started = time.perf_counter()
    result = scan_fixture(MEDIUM_ROOT, threading.Event())
    seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert (result.files_seen, result.dirs_seen, result.logical_bytes) == (
        EXPECTED_MEDIUM_FILES,
        EXPECTED_MEDIUM_DIRS,
        EXPECTED_MEDIUM_BYTES,
    )
    print(
        json.dumps(
            {
                "files": result.files_seen,
                "directories": result.dirs_seen,
                "logical_bytes": result.logical_bytes,
                "seconds": round(seconds, 3),
                "files_per_second": round(result.files_seen / seconds),
                "peak_python_allocated_mib": round(peak_bytes / 1024 / 1024, 2),
                "errors_count": result.errors_count,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
