"""Saved-result browsing is scoped, read-only, and independent of task memory."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.results.service import ResultResolver
from app.scanner.models import DirectoryStats, FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, local_session
from app.snapshots.store import SnapshotNotFound, SnapshotStore
from app.tasks.manager import ScanTask, ScanTaskManager
from tests.asgi_client import request


class ResultRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "results.db"
        self.snapshots = SnapshotStore(self.database)
        self.tasks = ScanTaskManager()
        self.resolver = ResultResolver(self.tasks, self.snapshots)

    def save(self, scan_id: str, root: str = "system_drive_c", seconds: int = 0) -> str:
        result = ScanResult(
            directories={
                "": DirectoryStats("", None, subtree_bytes=300, file_count=1, children_count=1),
                "Windows": DirectoryStats("Windows", "", subtree_bytes=300, file_count=1, children_count=1),
                "Windows/System32": DirectoryStats("Windows/System32", "Windows", direct_bytes=300,
                                                    subtree_bytes=300, direct_file_count=1, file_count=1),
            },
            top_files=[FileMetadata("hiberfil.sys", "hiberfil.sys", "", 300, "2026-01-01T00:00:00Z")],
            files_seen=1, dirs_seen=3, logical_bytes=300,
        )
        status = {"scan_id": scan_id, "root": root, "state": "completed",
                  "started_at": f"2026-01-01T00:00:{seconds:02d}Z",
                  "finished_at": f"2026-01-01T00:00:{seconds:02d}Z", "elapsed_ms": 1000}
        return self.snapshots.save(status, result, Path("C:\\"))

    def task(self, scan_id: str, state: str, scope: str = "system_drive_c") -> ScanTask:
        task = ScanTask(scan_id, "system_drive_c", Path("C:\\"), scope_key=scope, state=state)
        task.finished_at = "2026-01-01T00:00:59Z"
        task.result = ScanResult(files_seen=2, dirs_seen=1, logical_bytes=500) if state == "completed" else None
        if task.result is not None:
            task.files_seen, task.dirs_seen, task.logical_bytes = 2, 1, 500
        self.tasks._tasks[scan_id] = task
        return task

    def test_restart_restores_snapshot_metadata_drilldown_and_top_items(self):
        saved = self.save("one")
        restarted = ResultResolver(ScanTaskManager(), SnapshotStore(self.database))
        latest = restarted.latest("system_drive_c")
        self.assertEqual((latest["source_type"], latest["snapshot_id"], latest["scope_key"]),
                         ("snapshot", saved, "system_drive_c"))
        self.assertEqual((latest["summary"]["total_bytes"], latest["summary"]["file_count"],
                          latest["summary"]["directory_count"]), (300, 1, 3))
        root = restarted.directories("system_drive_c", "snapshot", saved, "")
        child = restarted.directories("system_drive_c", "snapshot", saved, "Windows")
        self.assertEqual((root[0]["relative_path"], child[0]["relative_path"]),
                         ("Windows", "Windows/System32"))
        files, _ = restarted.top("system_drive_c", "snapshot", saved, "file", 100)
        directories, _ = restarted.top("system_drive_c", "snapshot", saved, "directory", 100)
        self.assertEqual(files[0]["name"], "hiberfil.sys")
        self.assertEqual(directories[0]["relative_path"], "Windows")
        self.assertIsNone(directories[0]["direct_file_count"])

    def test_live_preferred_but_failed_and_cancelled_tasks_do_not_replace_completed(self):
        saved = self.save("one")
        self.task("failed", "failed")
        self.task("cancelled", "cancelled")
        self.assertEqual(self.resolver.latest("system_drive_c")["snapshot_id"], saved)
        self.task("live", "completed")
        live = self.resolver.latest("system_drive_c")
        self.assertEqual((live["source_type"], live["result_id"], live["summary"]["total_bytes"]),
                         ("live", "live", 500))

    def test_newer_snapshot_wins_and_scope_isolation(self):
        self.save("old")
        newer = self.save("new", seconds=1)
        project = self.save("project", root="project_workspace")
        fixture = self.save("fixture", root="tests/fixtures/sample_disk")
        self.assertEqual(self.resolver.latest("system_drive_c")["snapshot_id"], newer)
        self.assertEqual(self.resolver.latest("project_workspace")["snapshot_id"], project)
        self.assertEqual(self.resolver.latest("fixture_sample")["snapshot_id"], fixture)
        with self.assertRaises(SnapshotNotFound):
            self.resolver.top("project_workspace", "snapshot", newer, "file", 10)

    def test_unavailable_database_returns_no_result_without_affecting_scanner(self):
        self.database.write_bytes(b"not a database")
        latest = self.resolver.latest("system_drive_c")
        self.assertEqual((latest["source_type"], latest["storage_status"]), ("none", "unavailable"))
        self.assertIsNone(self.tasks.latest_status())

    def test_api_source_contract_and_scoped_read_endpoints(self):
        saved = self.save("one")
        headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}"}
        with patch("app.api.results.result_resolver", self.resolver):
            code, _, latest = asyncio.run(request("GET", "/api/v1/results/latest", headers=headers,
                                                  query="scope_key=system_drive_c"))
            self.assertEqual((code, latest["source_type"], latest["snapshot_id"]), (200, "snapshot", saved))
            code, _, root = asyncio.run(request("GET", f"/api/v1/results/snapshot/{saved}/directories",
                                                headers=headers, query="scope_key=system_drive_c"))
            self.assertEqual((code, root["items"][0]["name"]), (200, "Windows"))
            code, _, files = asyncio.run(request("GET", f"/api/v1/results/snapshot/{saved}/top",
                                                 headers=headers, query="scope_key=system_drive_c&kind=file&limit=10"))
            self.assertEqual((code, files["items"][0]["name"]), (200, "hiberfil.sys"))
            code, _, _ = asyncio.run(request("GET", f"/api/v1/results/snapshot/{saved}/top",
                                             headers=headers, query="scope_key=project_workspace&kind=file"))
            self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
