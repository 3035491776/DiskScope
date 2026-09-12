"""M1.5 metadata-only real workspace probe; never opens scanned file contents."""

import json
import os
import time
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.scanner.exclusions import project_exclusion
from app.scanner.path_guard import is_reparse_point
from app.tasks.manager import ScanTaskManager


def metadata_snapshot() -> dict[str, tuple[object, ...]]:
    """Independent read-only inventory for before/after structure and mtime comparison."""
    inventory: dict[str, tuple[object, ...]] = {}
    pending = [PROJECT_ROOT]
    while pending:
        directory = pending.pop()
        relative_directory = directory.relative_to(PROJECT_ROOT).as_posix()
        if relative_directory == ".":
            relative_directory = ""
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    relative = (
                        f"{relative_directory}/{entry.name}"
                        if relative_directory else entry.name
                    )
                    if project_exclusion(relative) is not None:
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        inventory[relative] = ("unavailable", type(exc).__name__)
                        continue
                    if is_reparse_point(info):
                        inventory[relative] = ("reparse",)
                    elif entry.is_dir(follow_symlinks=False):
                        inventory[relative] = ("directory", info.st_mtime_ns)
                        pending.append(Path(entry.path))
                    else:
                        inventory[relative] = ("file", info.st_size, info.st_mtime_ns)
        except OSError as exc:
            inventory[relative_directory] = ("directory_unavailable", type(exc).__name__)
    return inventory


def wait_for_scan(manager: ScanTaskManager, scan_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = manager.status(scan_id)
        if status["state"] == "completed":
            return status
        if status["state"] in {"failed", "cancelled"}:
            raise RuntimeError(f"Workspace scan ended in {status['state']}: {status['error_code']}")
        time.sleep(0.05)
    raise TimeoutError("Workspace scan did not complete within 120 seconds")


def main() -> None:
    before = metadata_snapshot()
    manager = ScanTaskManager()
    statuses = []
    for _ in range(2):
        created = manager.create(str(PROJECT_ROOT))
        statuses.append(wait_for_scan(manager, created["scan_id"]))
    after = metadata_snapshot()
    result = manager.result(statuses[0]["scan_id"])
    second = manager.result(statuses[1]["scan_id"])
    root_directories = sorted(
        (directory for directory in result.directories.values() if directory.parent == ""),
        key=lambda directory: (-directory.subtree_bytes, directory.relative_path),
    )
    output = {
        "root": str(PROJECT_ROOT),
        "metadata_before_after_equal": before == after,
        "inventory_entries_before": len(before),
        "inventory_entries_after": len(after),
        "first": {
            "files_seen": result.files_seen,
            "dirs_seen": result.dirs_seen,
            "logical_bytes": result.logical_bytes,
            "skipped_count": result.skipped_count,
            "errors_count": result.errors_count,
            "duration_seconds": round(statuses[0]["elapsed_ms"] / 1000, 3),
            "files_per_second": round(
                result.files_seen / max(statuses[0]["elapsed_ms"] / 1000, 0.001)
            ),
            "errors": result.errors,
            "exclusions": result.exclusions,
            "top_20": [
                {"path": file.relative_path, "size_bytes": file.size_bytes}
                for file in result.top_files[:20]
            ],
            "root_directories": [
                {"path": directory.relative_path, "subtree_bytes": directory.subtree_bytes}
                for directory in root_directories
            ],
        },
        "second": {
            "files_seen": second.files_seen,
            "dirs_seen": second.dirs_seen,
            "logical_bytes": second.logical_bytes,
            "duration_seconds": round(statuses[1]["elapsed_ms"] / 1000, 3),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output["metadata_before_after_equal"]:
        raise AssertionError("Workspace metadata changed during the two scanner runs")


if __name__ == "__main__":
    main()
