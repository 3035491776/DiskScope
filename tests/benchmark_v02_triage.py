"""Synthetic one-pass benchmark for v0.2 triage overhead and SQLite size."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import statistics
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from app.scanner.enumerator import DirectorySeen, FileSeen
from app.scanner.metrics import ScanResourceMonitor
from app.scanner.service import scan_fixture
from app.snapshots.store import SnapshotStore


def _branch_events(prefix: str, file_count: int, first_index: int):
    directories = max(1, (file_count + 99) // 100) if file_count else 0
    for directory in range(directories):
        parent = f"{prefix}/d{directory:05d}"
        yield DirectorySeen(parent, prefix)
        branch_start = directory * 100
        for offset in range(branch_start, min(branch_start + 100, file_count)):
            index = first_index + offset
            extension = (".mkv", ".zip", ".pdf", ".exe")[index % 4]
            name = f"file-{index:06d}{extension}"
            yield FileSeen(name, f"{parent}/{name}", parent, index * 4096,
                           1_600_000_000 + index, 32)


def events(file_count: int, review_percent: float = 100.0):
    review_count = round(file_count * review_percent / 100)
    other_count = file_count - review_count
    yield DirectorySeen("", None)
    yield DirectorySeen("Users", "")
    yield DirectorySeen("Users/Test", "Users")
    yield DirectorySeen("Users/Test/Downloads", "Users/Test")
    yield from _branch_events("Users/Test/Downloads", review_count, 0)
    if other_count:
        yield DirectorySeen("Windows", "")
        yield DirectorySeen("Windows/System32", "Windows")
        yield from _branch_events("Windows/System32", other_count, review_count)


def one(file_count: int, triage: bool, review_percent: float):
    monitor = ScanResourceMonitor()
    started = time.perf_counter()
    cpu_started = time.process_time()
    options = {"scope_key": "system_drive_c"}
    if triage:
        options["triage_root_map"] = {"downloads": "Users/Test/Downloads"}
    with patch("app.scanner.service.enumerate_metadata",
               side_effect=lambda *_args, **_kwargs: events(file_count, review_percent)):
        result = scan_fixture(Path("C:\\"), threading.Event(), **options)
    wall = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    resource = monitor.finish(result.files_seen, round(wall * 1000))
    return result, {"wall_seconds": wall, "cpu_seconds": cpu,
                    "rss_bytes": resource["rss_peak_observed_bytes"] or 0}


def persist(result, file_count: int):
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "triage-benchmark.db"
        store = SnapshotStore(database)
        now = "2026-09-21T00:00:00+00:00"
        status = {"scan_id": str(uuid.uuid4()), "root": "system_drive_c",
                  "state": "completed", "started_at": now, "finished_at": now,
                  "elapsed_ms": 1}
        started = time.perf_counter()
        store.save(status, result, Path("C:\\"))
        elapsed = time.perf_counter() - started
        return elapsed, database.stat().st_size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--sizes", default="10000,50000,100000")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--review-percent", type=float, default=100.0)
    args = parser.parse_args()
    if not 0 <= args.review_percent <= 100:
        parser.error("--review-percent must be between 0 and 100")
    triage = "triage_root_map" in inspect.signature(scan_fixture).parameters
    output = {"label": args.label, "triage_enabled": triage,
              "review_percent": args.review_percent, "results": {}}
    for file_count in [int(value) for value in args.sizes.split(",")]:
        run_count = args.runs
        one(file_count, triage, args.review_percent)  # warmup
        rows, result = [], None
        for _ in range(run_count):
            result, row = one(file_count, triage, args.review_percent)
            rows.append(row)
        persistence, db_size = persist(result, file_count)
        output["results"][str(file_count)] = {
            "runs": run_count,
            "median_wall_seconds": statistics.median(row["wall_seconds"] for row in rows),
            "median_cpu_seconds": statistics.median(row["cpu_seconds"] for row in rows),
            "max_rss_bytes": max(row["rss_bytes"] for row in rows),
            "persistence_seconds": persistence, "db_size_bytes": db_size,
            "files": result.files_seen, "directories": result.dirs_seen,
            "triage_observed": getattr(result, "triage_observed_count", 0),
            "triage_persisted": getattr(result, "triage_persisted_count", 0),
        }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
