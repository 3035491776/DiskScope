"""Reproducible, fixture-only M1 scan timing."""

import json
import threading
import time
import tracemalloc

from app.scanner.service import scan_fixture
from app.scanner.metrics import ScanResourceMonitor
from tests.fixtures.generate_sample import (
    EXPECTED_MEDIUM_BYTES,
    EXPECTED_MEDIUM_DIRS,
    EXPECTED_MEDIUM_FILES,
    MEDIUM_ROOT,
    SAMPLE_ROOT,
    EXPECTED_SAMPLE_FILES,
    EXPECTED_SAMPLE_DIRS,
    EXPECTED_SAMPLE_BYTES,
    generate_sample,
    generate_medium,
)


def measure(root, expected) -> dict[str, object]:
    monitor = ScanResourceMonitor()
    last_sample = 0

    def progress(result) -> None:
        nonlocal last_sample
        items = result.files_seen + result.dirs_seen
        if items - last_sample >= 256:
            monitor.sample()
            last_sample = items

    tracemalloc.start()
    started = time.perf_counter()
    result = scan_fixture(root, threading.Event(), progress)
    seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert (result.files_seen, result.dirs_seen, result.logical_bytes) == expected
    return {
        "files": result.files_seen,
        "directories": result.dirs_seen,
        "logical_bytes": result.logical_bytes,
        "seconds": round(seconds, 3),
        "files_per_second": round(result.files_seen / seconds),
        "peak_python_allocated_mib": round(peak_bytes / 1024 / 1024, 2),
        "errors_count": result.errors_count,
        "skipped_count": result.skipped_count,
        "process_metrics": monitor.finish(result.files_seen, round(seconds * 1000)),
    }


def main() -> None:
    generate_sample()
    sample = measure(
        SAMPLE_ROOT, (EXPECTED_SAMPLE_FILES, EXPECTED_SAMPLE_DIRS, EXPECTED_SAMPLE_BYTES)
    )
    generate_medium()
    medium = measure(
        MEDIUM_ROOT, (EXPECTED_MEDIUM_FILES, EXPECTED_MEDIUM_DIRS, EXPECTED_MEDIUM_BYTES)
    )
    print(json.dumps({"sample": sample, "medium": medium}, indent=2))


if __name__ == "__main__":
    main()
