"""Physical empty-file metadata benchmark for smart triage overhead."""

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

from app.core.config import PROJECT_ROOT
from app.scanner.metrics import ScanResourceMonitor
from app.scanner.service import scan_fixture
from app.snapshots.store import SnapshotStore


def generate_large(root: Path, file_count: int):
    root.mkdir(parents=True, exist_ok=True)
    for directory_index in range(file_count // 100):
        directory = root / f"dir_{directory_index:05d}"; directory.mkdir()
        for file_index in range(100):
            path = directory / f"file_{file_index:03d}.bin"; path.touch()
            os.utime(path, (1_704_067_200, 1_704_067_200))


def measure(root: Path, triage: bool):
    monitor = ScanResourceMonitor()
    options = {"triage_root_map": {"downloads": ""}} if triage else {}
    started = time.perf_counter(); cpu_started = time.process_time()
    result = scan_fixture(root, threading.Event(), **options)
    wall = time.perf_counter() - started; cpu = time.process_time() - cpu_started
    metrics = monitor.finish(result.files_seen, round(wall * 1000))
    return result, {"wall_seconds": wall, "cpu_seconds": cpu,
                    "rss_bytes": metrics["rss_peak_observed_bytes"] or 0,
                    "read_bytes": metrics["delta_read_bytes"] or 0,
                    "write_bytes": metrics["delta_write_bytes"] or 0}


def persist(result, root: Path):
    with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data") as temporary:
        database = Path(temporary) / "bench.db"; store = SnapshotStore(database)
        now = "2026-09-21T00:00:00+00:00"
        status = {"scan_id": str(uuid.uuid4()), "root": str(root.relative_to(PROJECT_ROOT)),
                  "state": "completed", "started_at": now, "finished_at": now, "elapsed_ms": 1}
        started = time.perf_counter(); store.save(status, result, root)
        return time.perf_counter() - started, database.stat().st_size


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--label", required=True)
    parser.add_argument("--sizes", default="10000,50000,100000"); args = parser.parse_args()
    triage = "triage_root_map" in inspect.signature(scan_fixture).parameters
    output = {"label": args.label, "triage_enabled": triage, "results": {}}
    for count in [int(value) for value in args.sizes.split(",")]:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tests" / "fixtures", prefix="v02_triage_") as temporary:
            root = Path(temporary); generate_large(root, count); measure(root, triage)
            rows=[]; final=None
            for _ in range(2 if count >= 100_000 else 3):
                final,row=measure(root,triage); rows.append(row)
            persisted,db_size=persist(final,root)
            output["results"][str(count)]={
                "runs":len(rows), "median_wall_seconds":statistics.median(r["wall_seconds"] for r in rows),
                "median_cpu_seconds":statistics.median(r["cpu_seconds"] for r in rows),
                "max_rss_bytes":max(r["rss_bytes"] for r in rows),
                "median_read_bytes":statistics.median(r["read_bytes"] for r in rows),
                "median_write_bytes":statistics.median(r["write_bytes"] for r in rows),
                "persistence_seconds":persisted,"db_size_bytes":db_size,
                "files":final.files_seen,"directories":final.dirs_seen,
                "triage_observed":getattr(final,"triage_observed_count",0),
                "triage_persisted":getattr(final,"triage_persisted_count",0)}
    print(json.dumps(output,indent=2))


if __name__ == "__main__": main()
