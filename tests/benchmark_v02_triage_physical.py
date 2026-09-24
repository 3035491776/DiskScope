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

import app.scanner.enumerator as enumerator_module
import app.scanner.path_guard as path_guard_module
from app.scanner.metrics import ScanResourceMonitor
from app.scanner.service import scan_fixture
from app.snapshots.store import SnapshotStore


def _generate_branch(root: Path, file_count: int):
    root.mkdir(parents=True, exist_ok=True)
    for directory_index in range((file_count + 99) // 100):
        directory = root / f"dir_{directory_index:05d}"; directory.mkdir()
        for file_index in range(min(100, file_count - directory_index * 100)):
            path = directory / f"file_{file_index:03d}.bin"; path.touch()
            os.utime(path, (1_704_067_200, 1_704_067_200))


def generate_large(root: Path, file_count: int, review_percent: float):
    review_count = round(file_count * review_percent / 100)
    if review_percent >= 100:
        _generate_branch(root, review_count)
    else:
        _generate_branch(root / "Downloads", review_count)
        _generate_branch(root / "Windows", file_count - review_count)


def measure(root: Path, triage: bool, review_percent: float):
    monitor = ScanResourceMonitor()
    review_root = "" if review_percent >= 100 else "Downloads"
    options = {"triage_root_map": {"downloads": review_root}} if triage else {}
    started = time.perf_counter(); cpu_started = time.process_time()
    result = scan_fixture(root, threading.Event(), **options)
    wall = time.perf_counter() - started; cpu = time.process_time() - cpu_started
    metrics = monitor.finish(result.files_seen, round(wall * 1000))
    return result, {"wall_seconds": wall, "cpu_seconds": cpu,
                    "rss_bytes": metrics["rss_peak_observed_bytes"] or 0,
                    "read_bytes": metrics["delta_read_bytes"] or 0,
                    "write_bytes": metrics["delta_write_bytes"] or 0}


def persist(result, root: Path):
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "bench.db"; store = SnapshotStore(database)
        now = "2026-09-21T00:00:00+00:00"
        status = {"scan_id": str(uuid.uuid4()), "root": str(root),
                  "state": "completed", "started_at": now, "finished_at": now, "elapsed_ms": 1}
        started = time.perf_counter(); store.save(status, result, root)
        return time.perf_counter() - started, database.stat().st_size


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--label", required=True)
    parser.add_argument("--sizes", default="10000,50000,100000")
    parser.add_argument("--review-percent", type=float, default=100.0)
    parser.add_argument("--fixture-root")
    parser.add_argument("--fixture-project-root")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.review_percent <= 100:
        parser.error("--review-percent must be between 0 and 100")
    counts = [int(value) for value in args.sizes.split(",")]
    if args.fixture_root and len(counts) != 1:
        parser.error("--fixture-root requires exactly one --sizes value")
    if args.fixture_project_root:
        benchmark_project = Path(args.fixture_project_root).resolve()
        path_guard_module.PROJECT_ROOT = benchmark_project
        path_guard_module.FIXTURE_ROOT = benchmark_project / "tests" / "fixtures"
        path_guard_module.ALLOWED_REAL_ROOTS = (benchmark_project,)
        enumerator_module.PROJECT_ROOT = benchmark_project
    if args.prepare_only:
        if not args.fixture_root:
            parser.error("--prepare-only requires --fixture-root")
        root = Path(args.fixture_root)
        generate_large(root, counts[0], args.review_percent)
        print(json.dumps({"fixture_root": str(root), "files": counts[0],
                          "review_percent": args.review_percent}, indent=2))
        return
    triage = "triage_root_map" in inspect.signature(scan_fixture).parameters
    output = {"label": args.label, "triage_enabled": triage,
              "review_percent": args.review_percent, "results": {}}
    for count in counts:
        if args.fixture_root:
            roots = (Path(args.fixture_root),)
        else:
            temporary_context = tempfile.TemporaryDirectory(prefix="v02_triage_")
            roots = (Path(temporary_context.name),)
        try:
            for root in roots:
                if not args.fixture_root:
                    generate_large(root, count, args.review_percent)
                measure(root, triage, args.review_percent)
                rows=[]; final=None
                for _ in range(3):
                    final,row=measure(root,triage,args.review_percent); rows.append(row)
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
        finally:
            if not args.fixture_root:
                temporary_context.cleanup()
    print(json.dumps(output,indent=2))


if __name__ == "__main__": main()
