"""One-off M3 acceptance probe; cleanup is restricted to its own fixture file."""

import json
import subprocess
import time
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.snapshots.store import snapshot_store
from app.tasks.manager import ScanTaskManager


PROBE = PROJECT_ROOT / "tests" / "fixtures" / "m3_growth_probe.bin"
PROBE_BYTES = 1_048_576


def git_status() -> str:
    return subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=PROJECT_ROOT, text=True,
    )


def completed(manager: ScanTaskManager) -> dict[str, object]:
    scan_id = manager.create(str(PROJECT_ROOT))["scan_id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        latest = manager.status(scan_id)
        if latest["snapshot_status"] == "saved":
            return latest
        if latest["state"] in {"cancelled", "failed"} or latest["snapshot_status"] == "failed":
            raise AssertionError(f"project scan did not save a snapshot: {latest}")
        time.sleep(0.05)
    raise TimeoutError("project scan timed out")


def main() -> None:
    fixture_root = (PROJECT_ROOT / "tests" / "fixtures").resolve(strict=True)
    if PROBE.parent.resolve(strict=True) != fixture_root or PROBE.exists():
        raise RuntimeError("The controlled fixture target is not safe or already exists.")
    before_status = git_status()
    manager = ScanTaskManager(snapshot_store)
    a = completed(manager)
    created = False
    try:
        PROBE.write_bytes(b"\0" * PROBE_BYTES)
        created = True
        b = completed(manager)
        comparison = snapshot_store.compare(a["snapshot_id"], b["snapshot_id"])
        by_path = {item["relative_path"]: item for item in comparison["directory_changes"]}
        assert comparison["total_bytes_delta"] == PROBE_BYTES, comparison["total_bytes_delta"]
        assert comparison["file_count_delta"] == 1, comparison["file_count_delta"]
        assert comparison["directory_count_delta"] == 0, comparison["directory_count_delta"]
        assert by_path["tests"]["delta_bytes"] == PROBE_BYTES
        assert by_path["tests/fixtures"]["delta_bytes"] == PROBE_BYTES
        assert any(item["relative_path"] == "tests/fixtures/m3_growth_probe.bin"
                   for item in comparison["new_large_files"])
        print(json.dumps({
            "snapshot_a": {key: a[key] for key in ("snapshot_id", "logical_bytes", "files_seen", "dirs_seen", "errors_count", "skipped_count", "elapsed_ms")},
            "snapshot_b": {key: b[key] for key in ("snapshot_id", "logical_bytes", "files_seen", "dirs_seen", "errors_count", "skipped_count", "elapsed_ms")},
            "comparison": {
                "total_bytes_delta": comparison["total_bytes_delta"],
                "total_bytes_delta_ratio": comparison["total_bytes_delta_ratio"],
                "file_count_delta": comparison["file_count_delta"],
                "directory_count_delta": comparison["directory_count_delta"],
                "tests_delta": by_path["tests"]["delta_bytes"],
                "fixtures_delta": by_path["tests/fixtures"]["delta_bytes"],
                "new_large_files": [item["relative_path"] for item in comparison["new_large_files"]],
                "comparison_coverage_limited": comparison["comparison_coverage_limited"],
            },
        }, ensure_ascii=False))
    finally:
        if created and PROBE.parent.resolve(strict=True) == fixture_root:
            PROBE.unlink(missing_ok=True)
        if git_status() != before_status:
            raise AssertionError("Git status changed beyond the controlled fixture probe.")


if __name__ == "__main__":
    main()
