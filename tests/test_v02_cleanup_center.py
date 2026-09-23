"""v0.2 Cleanup Center security, classification, batch, and migration tests."""

import asyncio
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.cleanup.batch import BatchCleanupService, MAX_BATCH_ITEMS
from app.cleanup.classification import (
    DO_NOT_TOUCH, REVIEW_REQUIRED, SAFE_ACTIONABLE,
    CleanupClassificationService, ManualReviewPolicy,
)
from app.cleanup.policy import ExecutionPolicyEngine
from app.cleanup.recycle import RecycleError, RecycleResult
from app.cleanup.service import CleanupError
from app.core.config import PROJECT_ROOT
from app.intelligence.store import CandidateStore
from app.scanner.models import FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.snapshots.store import SnapshotStore
from tests.asgi_client import request

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=45)).isoformat()
SIZE = 200 * 1024 * 1024
PATHS = {
    "safe": "C:\\Users\\Test\\AppData\\Local\\Temp\\safe.tmp",
    "download": "C:\\Users\\Test\\Downloads\\archive.zip",
    "movie": "C:\\Users\\Test\\Downloads\\movie.mkv",
    "desktop": "C:\\Users\\Test\\Desktop\\video.mp4",
    "system": "C:\\Windows\\System32\\kernel.dll",
    "program": "C:\\Program Files\\Example\\app.dll",
    "executable": "C:\\Users\\Test\\Downloads\\setup.exe",
}


def relative(path: str) -> str:
    return path[3:].replace("\\", "/")


def info(mode, size=0, path_time=OLD, *, device=1, inode=2, attributes=0):
    timestamp = datetime.fromisoformat(path_time).timestamp()
    return SimpleNamespace(
        st_mode=mode, st_size=size, st_mtime=timestamp,
        st_mtime_ns=int(timestamp * 1e9), st_ctime_ns=7,
        st_file_attributes=attributes, st_dev=device, st_ino=inode,
    )


class FakeFilesystem:
    def __init__(self):
        self.entries = {"c:\\": info(stat.S_IFDIR | 0o755)}
        for index, path in enumerate(PATHS.values(), 10):
            prefix = "C:"
            for part in path[3:].split("\\")[:-1]:
                prefix += "\\" + part
                self.entries.setdefault(prefix.casefold(), info(stat.S_IFDIR | 0o755))
            self.entries[path.casefold()] = info(stat.S_IFREG | 0o644, SIZE, inode=index)

    def lookup(self, path):
        try:
            return self.entries[str(path).casefold()]
        except KeyError:
            raise FileNotFoundError(path) from None


class SelectiveRecycle:
    def __init__(self):
        self.calls = []
        self.fail_paths = set()

    def recycle(self, path):
        self.calls.append(path)
        if path in self.fail_paths:
            raise RecycleError("ACCESS_DENIED")
        return RecycleResult("test_backend", "success", True)


class CleanupCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "v02.db"
        self.store = SnapshotStore(self.database)
        files = [FileMetadata(Path(path).name, relative(path), relative(path).rpartition("/")[0], SIZE, OLD)
                 for path in PATHS.values()]
        result = ScanResult(directories={}, top_files=files, files_seen=len(files),
                            dirs_seen=0, logical_bytes=SIZE * len(files))
        status = {"scan_id": "v02", "root": "system_drive_c", "state": "completed",
                  "started_at": OLD, "finished_at": NOW.isoformat(), "elapsed_ms": 100}
        self.snapshot_id = self.store.save(status, result, Path("C:\\"))
        CandidateStore(self.store).analyze_snapshot(self.snapshot_id)
        with self.store._connection() as connection:
            connection.execute("""UPDATE cleanup_candidates SET confidence='high', risk_level='low'
                WHERE relative_path=?""", (relative(PATHS["safe"]),))
            connection.commit()
            rows = connection.execute(
                "SELECT candidate_id, relative_path FROM cleanup_candidates WHERE object_type='file'").fetchall()
            self.ids = {next(name for name, path in PATHS.items() if relative(path) == row["relative_path"]):
                        row["candidate_id"] for row in rows}
        self.fs = FakeFilesystem()
        safe = ExecutionPolicyEngine(
            "C:\\Users\\Test", self.fs.lookup, lambda: NOW,
            local_app_data="C:\\Users\\Test\\AppData\\Local",
        )
        review = ManualReviewPolicy("C:\\Users\\Test", self.fs.lookup)
        self.classifications = CleanupClassificationService(self.store, safe, review)
        self.backend = SelectiveRecycle()
        self.batch = BatchCleanupService(
            self.store, self.classifications, probes=None, recycle_backend=self.backend)
        self.batch.probes = None
        self.headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}",
                        "origin": LOCAL_ORIGIN}

    def call(self, method, path, body=None):
        return asyncio.run(request(method, path, body, self.headers))

    def test_three_tier_classification_is_fail_closed(self):
        listing = self.classifications.listing("system_drive_c")
        by_id = {item["candidate_id"]: item["classification"]
                 for items in listing["items"].values() for item in items}
        self.assertEqual(by_id[self.ids["safe"]], SAFE_ACTIONABLE)
        self.assertEqual(by_id[self.ids["download"]], REVIEW_REQUIRED)
        self.assertEqual(by_id[self.ids["desktop"]], REVIEW_REQUIRED)
        for name in ("system", "program", "executable"):
            self.assertEqual(by_id[self.ids[name]], DO_NOT_TOUCH)
        unknown = dict(self.classifications.candidate(self.ids["download"], "system_drive_c"))
        unknown["reason_code"] = None
        self.assertEqual(self.classifications.decide(unknown, "system_drive_c").classification,
                         DO_NOT_TOUCH)
        directory = dict(unknown, object_type="directory", reason_code="USER_DOWNLOAD_DIRECTORY")
        self.assertEqual(self.classifications.decide(directory, "system_drive_c").classification,
                         DO_NOT_TOUCH)

    def test_safe_and_review_routes_cannot_bypass_each_other(self):
        safe_as_review = self.batch.prepare([self.ids["safe"]], "review", "system_drive_c")
        review_as_safe = self.batch.prepare([self.ids["download"]], "safe", "system_drive_c")
        protected_safe = self.batch.prepare([self.ids["system"]], "safe", "system_drive_c")
        protected_review = self.batch.prepare([self.ids["system"]], "review", "system_drive_c")
        for result in (safe_as_review, review_as_safe, protected_safe, protected_review):
            self.assertFalse(result["real_execution_enabled"])
            self.assertEqual(result["approved_count"], 0)
            self.assertEqual(result["items"][0]["reason"], "BATCH_CLASSIFICATION_MISMATCH")
        self.assertEqual(self.backend.calls, [])

    def test_bounded_server_ids_token_single_use_and_api_path_rejection(self):
        with self.assertRaises(CleanupError):
            self.batch.prepare(["x"] * (MAX_BATCH_ITEMS + 1), "safe", "system_drive_c")
        missing = self.batch.prepare(["not-a-server-item"], "safe", "system_drive_c")
        self.assertFalse(missing["execution_token"])
        other_scope = self.batch.prepare(
            [self.ids["safe"]], "safe", "current_user_temp")
        self.assertFalse(other_scope["execution_token"])
        self.assertEqual(other_scope["items"][0]["reason"], "BATCH_ITEM_NOT_FOUND")
        prepared = self.batch.prepare([self.ids["safe"]], "safe", "system_drive_c")
        self.assertTrue(prepared["execution_token"])
        with patch("app.cleanup.batch.os.path.lexists", return_value=False):
            executed = self.batch.execute(prepared["execution_token"])
        self.assertEqual((executed["status"], executed["success_count"]), ("completed", 1))
        with self.assertRaises(CleanupError) as caught:
            self.batch.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "BATCH_ALREADY_EXECUTED")

        with patch("app.api.cleanup.batch_cleanup_service", self.batch):
            code, _, _ = self.call("POST", "/api/v1/cleanup/batches/prepare", {
                "item_ids": [self.ids["safe"]], "mode": "safe",
                "scope_key": "system_drive_c", "path": PATHS["safe"],
            })
        self.assertEqual(code, 422)

    def test_partial_success_continues_and_audits_each_item(self):
        selected = [self.ids["movie"], self.ids["download"], self.ids["desktop"]]
        prepared = self.batch.prepare(selected, "review", "system_drive_c")
        self.assertEqual(prepared["approved_count"], 3)
        self.fs.entries[PATHS["download"].casefold()] = info(
            stat.S_IFREG | 0o644, SIZE + 1, inode=99)
        self.backend.fail_paths.add(PATHS["desktop"])
        with patch("app.cleanup.batch.os.path.lexists", return_value=False):
            result = self.batch.execute(prepared["execution_token"])
        self.assertEqual(result["status"], "completed_with_partial_result")
        self.assertEqual((result["success_count"], result["skipped_count"], result["failed_count"]),
                         (1, 1, 1))
        reasons = {item["reason"] for item in result["items"] if item["reason"]}
        self.assertIn("TARGET_CHANGED_SINCE_PREPARE", reasons)
        self.assertIn("ACCESS_DENIED", reasons)
        audit = self.batch.detail(prepared["batch_id"])
        self.assertEqual(len(audit["items"]), 3)
        self.assertEqual(audit["batch"]["success_count"], 1)

    def test_execute_reparse_cross_volume_expiry_restart_and_item_tamper_fail_closed(self):
        cases = (
            (info(stat.S_IFLNK | 0o777, SIZE), "EXECUTION_REPARSE_POINT_BLOCKED"),
            (info(stat.S_IFREG | 0o644, SIZE, device=2), "EXECUTION_CROSS_VOLUME_BLOCKED"),
        )
        for replacement, expected in cases:
            with self.subTest(expected=expected):
                self.fs.entries[PATHS["movie"].casefold()] = info(stat.S_IFREG | 0o644, SIZE, inode=11)
                prepared = self.batch.prepare([self.ids["movie"]], "review", "system_drive_c")
                self.fs.entries[PATHS["movie"].casefold()] = replacement
                result = self.batch.execute(prepared["execution_token"])
                self.assertEqual(result["items"][0]["reason"], expected)
                self.assertEqual(result["success_count"], 0)

        self.fs.entries[PATHS["movie"].casefold()] = info(stat.S_IFREG | 0o644, SIZE, inode=11)
        expired = self.batch.prepare([self.ids["movie"]], "review", "system_drive_c")
        with self.store._connection() as connection:
            connection.execute("UPDATE cleanup_batches SET expires_at=? WHERE id=?",
                               ("2020-01-01T00:00:00+00:00", expired["batch_id"]))
            connection.commit()
        with self.assertRaises(CleanupError) as caught:
            self.batch.execute(expired["execution_token"])
        self.assertEqual(caught.exception.code, "BATCH_TOKEN_EXPIRED")

        restarted = self.batch.prepare([self.ids["movie"]], "review", "system_drive_c")
        other_process = BatchCleanupService(self.store, self.classifications,
                                            probes=None, recycle_backend=self.backend)
        with self.assertRaises(CleanupError) as caught:
            other_process.execute(restarted["execution_token"])
        self.assertEqual(caught.exception.code, "BATCH_TOKEN_EXPIRED")

        tampered = self.batch.prepare([self.ids["movie"]], "review", "system_drive_c")
        with self.store._connection() as connection:
            connection.execute("UPDATE cleanup_batch_items SET item_id='changed' WHERE batch_id=?",
                               (tampered["batch_id"],))
            connection.commit()
        with self.assertRaises(CleanupError) as caught:
            self.batch.execute(tampered["execution_token"])
        self.assertEqual(caught.exception.code, "BATCH_ITEM_SET_CHANGED")

    def test_v6_to_v7_migration_preserves_existing_rows_and_integrity(self):
        with closing(sqlite3.connect(self.database)) as connection:
            before = connection.execute("SELECT COUNT(*) FROM scan_snapshots").fetchone()[0]
            connection.execute("DROP TABLE cleanup_batch_items")
            connection.execute("DROP TABLE cleanup_batches")
            connection.execute("PRAGMA user_version = 6")
            connection.commit()
        self.assertEqual(self.store.get(self.snapshot_id)["snapshot_id"], self.snapshot_id)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM scan_snapshots").fetchone()[0], before)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
