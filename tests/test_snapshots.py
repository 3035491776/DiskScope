import asyncio
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.scanner.models import DirectoryStats, FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, local_session
from app.snapshots.compare import compare_directories, compare_top_files, delta_ratio
from app.snapshots.store import SnapshotScopeMismatch, SnapshotStore, SnapshotStoreError
from app.tasks.manager import ScanTaskManager
from tests.asgi_client import request
from tests.fixtures.generate_sample import generate_sample


def result(size=10, *, limited=False, error=False, cancelled=False):
    return ScanResult(
        directories={
            "": DirectoryStats("", None, subtree_bytes=size, file_count=1, children_count=1),
            "child": DirectoryStats("child", "", direct_bytes=size, subtree_bytes=size,
                                    direct_file_count=1, file_count=1),
        },
        top_files=[FileMetadata("item.bin", "child/item.bin", "child", size, "2026-01-01T00:00:00Z")],
        files_seen=1, dirs_seen=2, logical_bytes=size,
        skipped_count=int(limited), errors_count=int(error),
        limited_directories={"", "child"} if limited or error else set(),
        cancelled=cancelled,
    )


def status(scan_id, root="project_workspace", *, seconds=0):
    return {"scan_id": scan_id, "root": root, "state": "completed",
            "started_at": f"2026-01-01T00:00:{seconds:02d}Z",
            "finished_at": f"2026-01-01T00:00:{seconds:02d}Z", "elapsed_ms": 100}


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "test.db"
        self.store = SnapshotStore(self.database)

    def save(self, name, size=10, root="project_workspace", **kwargs):
        return self.store.save(status(name, root), result(size, **kwargs), PROJECT_ROOT)

    def test_schema_and_complete_metadata_without_file_contents(self):
        snapshot_id = self.save("one")
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM directory_snapshots").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM file_snapshots").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT scope_key FROM scan_snapshots").fetchone()[0], "project_workspace")
        with self.store._connection() as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        summary = self.store.get(snapshot_id)
        self.assertNotIn("root_path", summary)
        self.assertNotIn("directories", summary)
        self.assertEqual(self.store.directories(snapshot_id, "")[0]["relative_path"], "child")
        self.assertEqual(self.store.directories(snapshot_id, "child"), [])

    def test_completed_limited_and_error_snapshots_are_saved(self):
        limited = self.save("limited", limited=True)
        errored = self.save("errored", error=True)
        self.assertEqual(self.store.get(limited)["coverage"], "limited")
        self.assertEqual(self.store.get(errored)["error_count"], 1)
        self.assertEqual(self.store.compare(limited, errored)["comparison_coverage_limited"], True)

    def test_noncompleted_and_cancelled_are_rejected(self):
        for state in ("queued", "running", "cancelling", "cancelled", "failed"):
            with self.assertRaises(ValueError):
                self.store.save({**status(state), "state": state}, result(), PROJECT_ROOT)
        with self.assertRaises(ValueError):
            self.store.save(status("cancelled-result"), result(cancelled=True), PROJECT_ROOT)
        self.assertEqual(self.store.list(), [])

    def test_compare_and_same_scope_guard(self):
        first = self.save("first", 0)
        second = self.save("second", 10)
        comparison = self.store.compare(first, second)
        self.assertEqual(comparison["total_bytes_delta"], 10)
        self.assertIsNone(comparison["total_bytes_delta_ratio"])
        self.assertEqual(comparison["growth_by_bytes"][0]["relative_path"], "child")
        fixture = self.save("fixture", root="tests/fixtures/sample_disk")
        with self.assertRaises(SnapshotScopeMismatch):
            self.store.compare(first, fixture)
        self.assertEqual(self.store.get(fixture)["scope_key"], "fixture_sample")

    def test_retention_is_per_scope_and_cascades(self):
        for index in range(21):
            self.store.save(status(f"p{index}", seconds=index), result(), PROJECT_ROOT)
        self.save("fixture", root="tests/fixtures/sample_disk")
        self.assertEqual(len(self.store.list("project_workspace")), 20)
        self.assertEqual(len(self.store.list("fixture_sample")), 1)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM directory_snapshots").fetchone()[0], 42)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM file_snapshots").fetchone()[0], 21)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM scan_snapshots WHERE scan_id='p0'").fetchone()[0], 0)

    def test_failed_insert_rolls_back_before_retention(self):
        for index in range(20):
            self.store.save(status(f"p{index}", seconds=index), result(), PROJECT_ROOT)
        with self.assertRaises(SnapshotStoreError):
            self.store.save(status("p19", seconds=30), result(), PROJECT_ROOT)
        self.assertEqual(len(self.store.list("project_workspace")), 20)

    def test_version_and_corruption_are_unavailable_without_rebuild(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version = 7")
        with self.assertRaises(SnapshotStoreError) as caught:
            self.store.list()
        self.assertEqual(caught.exception.code, "SNAPSHOT_DATABASE_VERSION_UNSUPPORTED")
        self.database.write_bytes(b"not a sqlite database")
        with self.assertRaises(SnapshotStoreError) as caught:
            self.store.list()
        self.assertEqual(caught.exception.code, "SNAPSHOT_DATABASE_UNAVAILABLE")
        self.assertEqual(self.database.read_bytes(), b"not a sqlite database")

    def test_top_k_only_persists_existing_result_entries(self):
        scan_result = result()
        scan_result.top_files = [FileMetadata(f"f{i}", f"child/f{i}", "child", i, "now") for i in range(1000)]
        self.store.save(status("topk"), scan_result, PROJECT_ROOT)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM file_snapshots").fetchone()[0], 1000)


class ComparisonTests(unittest.TestCase):
    @staticmethod
    def row(path, size):
        return {"relative_path": path, "name": path or "root", "subtree_bytes": size}

    def test_zero_ratio_rules(self):
        self.assertEqual(delta_ratio(0, 0), 0)
        self.assertIsNone(delta_ratio(0, 10))
        self.assertEqual(delta_ratio(10, 5), -0.5)

    def test_directory_types_and_two_rankings(self):
        base = [self.row("", 100), self.row("grown", 300_000), self.row("shrunk", 10),
                self.row("removed", 5), self.row("unchanged", 9), self.row("tiny", 1)]
        target = [self.row("", 200), self.row("grown", 2_000_000), self.row("shrunk", 5),
                  self.row("added", 8), self.row("unchanged", 9), self.row("tiny", 1000)]
        compared = compare_directories(base, target)
        types = {item["relative_path"]: item["change_type"] for item in compared["directory_changes"]}
        self.assertEqual(types, {"grown": "grown", "shrunk": "shrunk", "removed": "removed",
                                 "added": "added", "unchanged": "unchanged", "tiny": "grown"})
        self.assertEqual(compared["growth_by_bytes"][0]["relative_path"], "grown")
        self.assertEqual([item["relative_path"] for item in compared["growth_by_ratio"]], ["grown"])

    def test_top_files_are_only_top_k_view(self):
        def file(path, size):
            return {"relative_path": path, "name": path, "size_bytes": size}
        changes = compare_top_files(
            [file("removed", 2), file("grown", 1), file("shrunk", 4)],
            [file("new", 5), file("grown", 3), file("shrunk", 1)],
        )
        for key, path in (("new_large_files", "new"), ("removed_large_files", "removed"),
                          ("grown_large_files", "grown"), ("shrunk_large_files", "shrunk")):
            self.assertEqual(changes[key][0]["relative_path"], path)


class SnapshotLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generate_sample()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / "history.db")

    def wait(self, manager, scan_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            latest = manager.status(scan_id)
            if latest["state"] in {"cancelled", "failed"} or latest["snapshot_status"] in {"saved", "failed"}:
                return latest
            time.sleep(0.01)
        self.fail("scan did not reach a terminal snapshot state")

    def test_completed_auto_saves_and_db_failure_isolated(self):
        manager = ScanTaskManager(self.store)
        created = manager.create("tests/fixtures/sample_disk")
        latest = self.wait(manager, created["scan_id"])
        self.assertEqual((latest["state"], latest["snapshot_status"]), ("completed", "saved"))
        self.assertEqual(len(self.store.list("fixture_sample")), 1)
        with patch.object(self.store, "save", side_effect=SnapshotStoreError("SNAPSHOT_DATABASE_UNAVAILABLE")):
            created = manager.create("tests/fixtures/sample_disk")
            latest = self.wait(manager, created["scan_id"])
        self.assertEqual((latest["state"], latest["snapshot_status"]), ("completed", "failed"))
        self.assertIsNotNone(manager.result(created["scan_id"]))
        self.assertEqual(len(self.store.list("fixture_sample")), 1)

    def test_corrupt_database_keeps_health_and_current_scan_available(self):
        self.store.database.write_bytes(b"corrupt sqlite file")
        manager = ScanTaskManager(self.store)
        created = manager.create("tests/fixtures/sample_disk")
        latest = self.wait(manager, created["scan_id"])
        self.assertEqual((latest["state"], latest["snapshot_status"]), ("completed", "failed"))
        self.assertEqual(latest["snapshot_error_code"], "SNAPSHOT_DATABASE_UNAVAILABLE")
        self.assertIsNotNone(manager.result(created["scan_id"]))
        status_code, _, health = asyncio.run(request("GET", "/health"))
        self.assertEqual(status_code, 200)
        self.assertEqual(health["mode"], "guarded_cleanup")
        self.assertEqual(health["capabilities"]["scan"], "read_only")
        self.assertEqual(health["capabilities"]["cleanup"], "guarded_recycle")
        headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}"}
        with patch("app.api.snapshots.snapshot_store", self.store):
            status_code, _, payload = asyncio.run(request("GET", "/api/v1/snapshots", headers=headers))
        self.assertEqual((status_code, payload["detail"]), (503, "SNAPSHOT_DATABASE_UNAVAILABLE"))

    def test_cancelled_and_failed_do_not_save(self):
        manager = ScanTaskManager(self.store)
        with patch("app.tasks.manager.scan_fixture", return_value=result(cancelled=True)):
            created = manager.create("tests/fixtures/sample_disk")
            self.assertEqual(self.wait(manager, created["scan_id"])["state"], "cancelled")
        with patch("app.tasks.manager.scan_fixture", side_effect=OSError("failed")):
            created = manager.create("tests/fixtures/sample_disk")
            self.assertEqual(self.wait(manager, created["scan_id"])["state"], "failed")
        self.assertEqual(self.store.list(), [])

    def test_history_api_scope_guard_and_auth(self):
        first = self.store.save(status("first"), result(1), PROJECT_ROOT)
        second = self.store.save(status("second"), result(2), PROJECT_ROOT)
        fixture = self.store.save(status("fixture", "tests/fixtures/sample_disk"), result(1), PROJECT_ROOT)
        headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}"}
        with patch("app.api.snapshots.snapshot_store", self.store):
            status_code, _, payload = asyncio.run(request("GET", "/api/v1/snapshots", headers=headers,
                                                         query="scope_key=project_workspace"))
            self.assertEqual(status_code, 200)
            self.assertEqual(len(payload["items"]), 2)
            status_code, _, payload = asyncio.run(request("GET", f"/api/v1/snapshots/{first}", headers=headers))
            self.assertEqual(status_code, 200)
            self.assertEqual(payload["snapshot_id"], first)
            status_code, _, payload = asyncio.run(request("GET", f"/api/v1/snapshots/{first}/directories",
                                                         headers=headers, query="parent="))
            self.assertEqual(status_code, 200)
            self.assertEqual(len(payload["items"]), 1)
            status_code, _, payload = asyncio.run(request("GET", "/api/v1/compare", headers=headers,
                                                         query=f"base={first}&target={second}"))
            self.assertEqual(status_code, 200)
            self.assertEqual(payload["total_bytes_delta"], 1)
            status_code, _, payload = asyncio.run(request("GET", "/api/v1/compare", headers=headers,
                                                         query=f"base={first}&target={fixture}"))
            self.assertEqual((status_code, payload["detail"]), (400, "SNAPSHOT_SCOPE_MISMATCH"))
            status_code, _, payload = asyncio.run(request("GET", "/api/v1/snapshots", headers={}))
            self.assertEqual(status_code, 401)


if __name__ == "__main__":
    unittest.main()
