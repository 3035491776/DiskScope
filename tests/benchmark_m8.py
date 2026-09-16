"""Repeatable metadata-only M8 benchmark; fixture creation is outside measurements."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import threading
import time
import uuid
from pathlib import Path

from app.scanner.metrics import ScanResourceMonitor
from app.scanner.scope_registry import resolve_scan_scope
from app.scanner.service import scan_fixture
from app.snapshots.store import SnapshotStore
from tests.fixtures.generate_sample import (
    EXPECTED_MEDIUM_BYTES,
    EXPECTED_MEDIUM_DIRS,
    EXPECTED_MEDIUM_FILES,
    EXPECTED_SAMPLE_BYTES,
    EXPECTED_SAMPLE_DIRS,
    EXPECTED_SAMPLE_FILES,
    FIXTURES,
    MEDIUM_ROOT,
    SAMPLE_ROOT,
    generate_medium,
    generate_sample,
)


def generate_large(root: Path, file_count: int) -> tuple[int, int, int]:
    files_per_directory = 10
    directory_count = file_count // files_per_directory
    root.mkdir(parents=True, exist_ok=True)
    fixed_mtime = 1_704_067_200
    for directory_index in range(directory_count):
        directory = root / f"dir_{directory_index:05d}"
        directory.mkdir()
        for file_index in range(files_per_directory):
            path = directory / f"file_{file_index:02d}.bin"
            path.touch()
            os.utime(path, (fixed_mtime, fixed_mtime))
    return file_count, directory_count + 1, 0


def measure_once(
    root: Path,
    expected: tuple[int, int, int],
    scan_options: dict[str, object] | None = None,
) -> tuple[dict[str, object], object]:
    monitor = ScanResourceMonitor()
    last_sample_items = 0

    def progress(result) -> None:
        nonlocal last_sample_items
        items = result.files_seen + result.dirs_seen
        if items - last_sample_items >= 256:
            monitor.sample()
            last_sample_items = items

    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    result = scan_fixture(root, threading.Event(), progress, **(scan_options or {}))
    cpu_seconds = time.process_time() - cpu_started
    seconds = time.perf_counter() - wall_started
    if (result.files_seen, result.dirs_seen, result.logical_bytes) != expected:
        raise AssertionError("Benchmark correctness mismatch")
    metrics = monitor.finish(result.files_seen, round(seconds * 1000))
    row = {
        "duration_seconds": round(seconds, 6),
        "files_per_second": round(result.files_seen / max(seconds, 0.000001), 1),
        "directories_per_second": round(result.dirs_seen / max(seconds, 0.000001), 1),
        "cpu_seconds": round(cpu_seconds, 6),
        "rss_peak_bytes": metrics["rss_peak_observed_bytes"],
        "read_bytes": metrics["delta_read_bytes"],
        "write_bytes": metrics["delta_write_bytes"],
        "read_operations": metrics["delta_read_operations"],
        "write_operations": metrics["delta_write_operations"],
        "files": result.files_seen,
        "directories": result.dirs_seen,
        "logical_bytes": result.logical_bytes,
        "errors": result.errors_count,
        "skipped": result.skipped_count,
        "top_k_count": len(result.top_files),
        "root_subtree_bytes": result.directories[""].subtree_bytes,
        "root_file_count": result.directories[""].file_count,
    }
    return row, result


def persistence_seconds(result, root: Path) -> float:
    with tempfile.TemporaryDirectory(dir=FIXTURES, prefix="m8_db_") as temporary:
        store = SnapshotStore(Path(temporary) / "benchmark.db")
        store.list()
        now = "2026-09-16T00:00:00+00:00"
        status = {
            "scan_id": str(uuid.uuid4()),
            "root": str(root),
            "state": "completed",
            "started_at": now,
            "finished_at": now,
            "elapsed_ms": 1,
        }
        started = time.perf_counter()
        store.save(status, result, root)
        return time.perf_counter() - started


def summarize(rows: list[dict[str, object]], persistence: float) -> dict[str, object]:
    durations = [float(row["duration_seconds"]) for row in rows]
    rates = [float(row["files_per_second"]) for row in rows]
    cpu = [float(row["cpu_seconds"]) for row in rows]
    summary = {
        "runs": rows,
        "median_duration_seconds": round(statistics.median(durations), 6),
        "median_files_per_second": round(statistics.median(rates), 1),
        "median_cpu_seconds": round(statistics.median(cpu), 6),
        "max_rss_peak_bytes": max(int(row["rss_peak_bytes"] or 0) for row in rows),
        "median_read_bytes": statistics.median(int(row["read_bytes"] or 0) for row in rows),
        "median_write_bytes": statistics.median(int(row["write_bytes"] or 0) for row in rows),
        "snapshot_persistence_seconds": round(persistence, 6),
    }
    return summary


def benchmark(
    root: Path,
    expected: tuple[int, int, int],
    runs: int,
    scan_options: dict[str, object] | None = None,
) -> dict[str, object]:
    measure_once(root, expected, scan_options)  # Warmup; excluded.
    rows = []
    final_result = None
    for _ in range(runs):
        row, final_result = measure_once(root, expected, scan_options)
        rows.append(row)
    assert final_result is not None
    return summarize(rows, persistence_seconds(final_result, root))


def cancel_latency(root: Path) -> dict[str, object]:
    cancel = threading.Event()
    started = threading.Event()
    finished = threading.Event()
    result_holder = []

    def progress(result) -> None:
        if result.files_seen >= 1_000:
            started.set()

    def scan() -> None:
        result_holder.append(scan_fixture(root, cancel, progress))
        finished.set()

    worker = threading.Thread(target=scan, name="m8-cancel-benchmark")
    worker.start()
    if not started.wait(30):
        raise TimeoutError("Cancel benchmark did not reach its trigger")
    cancel_started = time.perf_counter()
    cancel.set()
    if not finished.wait(30):
        raise TimeoutError("Cancel benchmark did not stop")
    worker.join()
    return {
        "latency_seconds": round(time.perf_counter() - cancel_started, 6),
        "cancelled": result_holder[0].cancelled,
        "files_before_stop": result_holder[0].files_seen,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--large-files", type=int, default=50_000)
    parser.add_argument("--skip-large", action="store_true")
    parser.add_argument("--real-temp", action="store_true")
    parser.add_argument("--temp-runs", type=int, default=2)
    args = parser.parse_args()
    if args.runs < 2:
        raise ValueError("Use at least two measured runs")

    generate_sample()
    generate_medium()
    output = {
        "method": "single worker, metadata only, one warmup then measured runs",
        "small": benchmark(
            SAMPLE_ROOT,
            (EXPECTED_SAMPLE_FILES, EXPECTED_SAMPLE_DIRS, EXPECTED_SAMPLE_BYTES),
            args.runs,
        ),
        "medium": benchmark(
            MEDIUM_ROOT,
            (EXPECTED_MEDIUM_FILES, EXPECTED_MEDIUM_DIRS, EXPECTED_MEDIUM_BYTES),
            args.runs,
        ),
        "cancel": cancel_latency(MEDIUM_ROOT),
    }
    if not args.skip_large:
        with tempfile.TemporaryDirectory(dir=FIXTURES, prefix="m8_large_") as temporary:
            large_root = Path(temporary)
            expected = generate_large(large_root, args.large_files)
            output["large"] = benchmark(large_root, expected, args.runs)
    if args.real_temp:
        scope = resolve_scan_scope(scope_key="current_user_temp")
        options = {
            "scope_key": scope.scope_key,
            "file_persistence_mode": scope.file_persistence_mode,
            "file_persistence_limit": scope.file_persistence_limit,
        }
        warm = scan_fixture(scope.root, threading.Event(), **options)
        expected = (warm.files_seen, warm.dirs_seen, warm.logical_bytes)
        rows = []
        final_result = warm
        for _ in range(args.temp_runs):
            row, final_result = measure_once(scope.root, expected, options)
            rows.append(row)
        output["real_temp"] = summarize(
            rows, persistence_seconds(final_result, scope.root)
        )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
