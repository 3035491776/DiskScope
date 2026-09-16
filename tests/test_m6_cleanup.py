"""M6.2 tests use synthetic metadata and test backends; no real user file is touched."""

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

from app.cleanup.policy import EXECUTION_RULE_ID, ExecutionPolicyEngine
from app.cleanup.recycle import RecycleError, RecycleResult
from app.cleanup.service import CleanupError, CleanupService
from app.core.config import PROJECT_ROOT
from app.intelligence.store import CandidateStore
from app.operations import OperationConflict, operations
from app.scanner.models import FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.snapshots.store import SnapshotStore
from app.tasks.manager import ScanAlreadyRunning, ScanTaskManager
from tests.asgi_client import request

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=31)).isoformat()
RECENT = (NOW - timedelta(days=29)).isoformat()
PATH = "C:\\Users\\Test\\AppData\\Local\\Temp\\candidate.tmp"
RELATIVE = "Users/Test/AppData/Local/Temp/candidate.tmp"
SIZE = 2 * 1024 * 1024


def info(mode, size=0, when=OLD, attributes=0, device=1, inode=2, ctime_ns=3):
    timestamp = datetime.fromisoformat(when).timestamp()
    return SimpleNamespace(
        st_mode=mode, st_size=size, st_mtime=timestamp,
        st_mtime_ns=int(timestamp * 1e9), st_ctime_ns=ctime_ns,
        st_file_attributes=attributes, st_dev=device, st_ino=inode,
    )


def candidate(path=PATH, **changes):
    item = {
        "candidate_id": "candidate", "display_path": path,
        "relative_path": path[3:].replace("\\", "/"), "object_type": "file",
        "logical_bytes": SIZE, "category": "temporary_file", "confidence": "high",
        "risk_level": "low", "reason_code": "STALE_USER_TEMP_FILE",
    }
    item.update(changes)
    return item


class PolicyFixture:
    def __init__(self):
        self.entries = {"c:\\": info(stat.S_IFDIR | 0o755)}
        prefix = "C:"
        for part in PATH[3:].split("\\")[:-1]:
            prefix += "\\" + part
            self.entries[prefix.casefold()] = info(stat.S_IFDIR | 0o755)
        self.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE)
        self.policy = ExecutionPolicyEngine(
            "C:\\Users\\Test", self.lookup, lambda: NOW,
            local_app_data="C:\\Users\\Test\\AppData\\Local",
        )

    def lookup(self, path):
        key = path.casefold()
        if key not in self.entries:
            raise FileNotFoundError(path)
        return self.entries[key]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PolicyFixture()
        self.policy = self.fixture.policy

    def test_stale_current_user_temp_regular_file_is_eligible(self):
        plan = self.policy.preflight(candidate(), "system_drive_c", OLD)
        self.assertEqual((plan["eligibility"], plan["planned_action"]),
                         ("eligible_for_recycle", "recycle"))
        self.assertEqual(plan["policy_rule_id"], EXECUTION_RULE_ID)
        self.assertEqual(plan["allowed_actions"], ["recycle"])
        self.assertGreaterEqual(plan["age_days"], 30)

    def test_age_threshold_and_timestamp_validation(self):
        for timestamp, expected in (
            (RECENT, "EXECUTION_FILE_TOO_RECENT"),
            ((NOW + timedelta(days=1)).isoformat(), "EXECUTION_TIMESTAMP_INVALID"),
            ("not-a-time", "EXECUTION_TIMESTAMP_INVALID"),
        ):
            with self.subTest(timestamp=timestamp):
                self.assertIn(expected, self.policy.preflight(
                    candidate(), "system_drive_c", timestamp)["block_reasons"])
        exact = (NOW - timedelta(days=30)).isoformat()
        self.fixture.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE, exact)
        self.assertEqual(self.policy.preflight(
            candidate(), "system_drive_c", exact)["eligibility"], "eligible_for_recycle")

    def test_path_boundary_denial_matrix(self):
        blocked = [
            "C:\\Windows\\ServiceProfiles\\LocalService\\AppData\\Local\\Temp\\dump.dmp",
            "C:\\Windows\\Temp\\a.tmp", "C:\\Program Files\\a.tmp",
            "C:\\Program Files (x86)\\a.tmp", "C:\\ProgramData\\a.tmp",
            "C:\\Recovery\\a.tmp", "C:\\System Volume Information\\a.tmp",
            "C:\\$Recycle.Bin\\a.tmp", "C:\\hiberfil.sys", "C:\\pagefile.sys",
            "C:\\swapfile.sys", "C:\\Users\\Other\\AppData\\Local\\Temp\\a.tmp",
            "C:\\Users\\Test\\Downloads\\a.tmp", "C:\\Users\\Test\\Desktop\\a.tmp",
            "C:\\Users\\Test\\Documents\\a.tmp", "C:\\Users\\Test\\AppData\\a.tmp",
            "D:\\Users\\Test\\AppData\\Local\\Temp\\a.tmp", "\\\\server\\share\\a.tmp",
            "\\\\?\\C:\\Users\\Test\\AppData\\Local\\Temp\\a.tmp",
            "C:\\Users\\Test\\AppData\\Local\\Temp\\..\\a.tmp",
            "C:\\Users\\Test\\AppData\\Local\\Temp\\candidate.tmp.",
        ]
        for path in blocked:
            with self.subTest(path=path):
                self.assertTrue(self.policy.static_reasons(candidate(path), "system_drive_c"))
        mismatched_identity = ExecutionPolicyEngine(
            "C:\\Users\\Test", self.fixture.lookup, lambda: NOW,
            local_app_data="C:\\Users\\Other\\AppData\\Local")
        self.assertIn("EXECUTION_CURRENT_USER_TEMP_ONLY",
                      mismatched_identity.static_reasons(candidate(), "system_drive_c"))

    def test_type_classification_risk_size_and_extension_denial_matrix(self):
        changes = [
            {"object_type": "directory"}, {"object_type": "group"},
            {"category": "application_cache"}, {"category": "unknown"},
            {"confidence": "medium"}, {"confidence": "low"},
            {"risk_level": "review"}, {"risk_level": "high"},
            {"risk_level": "protected"}, {"logical_bytes": 1},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertTrue(self.policy.static_reasons(candidate(**change), "system_drive_c"))
        for extension in ("exe", "dll", "sys", "drv", "msi", "msp", "cab",
                          "ps1", "bat", "cmd", "com", "scr", "dmp"):
            path = PATH.rsplit(".", 1)[0] + "." + extension
            self.assertIn("EXECUTION_EXTENSION_BLOCKED",
                          self.policy.static_reasons(candidate(path), "system_drive_c"))

    def test_reparse_parent_target_missing_access_cross_volume_and_changed(self):
        entries = self.fixture.entries
        parent = "C:\\Users\\Test\\AppData".casefold()
        original_parent = entries[parent]
        entries[parent] = info(stat.S_IFDIR | 0o755, attributes=0x400)
        self.assertIn("EXECUTION_REPARSE_POINT_BLOCKED",
                      self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        entries[parent] = original_parent
        entries[PATH.casefold()] = info(stat.S_IFLNK | 0o777)
        self.assertIn("EXECUTION_REPARSE_POINT_BLOCKED",
                      self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE, device=2)
        self.assertIn("EXECUTION_CROSS_VOLUME_BLOCKED",
                      self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        for changed in (info(stat.S_IFREG | 0o644, SIZE + 1),
                        info(stat.S_IFREG | 0o644, SIZE, (NOW - timedelta(days=32)).isoformat())):
            entries[PATH.casefold()] = changed
            self.assertIn("TARGET_CHANGED_SINCE_SCAN",
                          self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        entries.pop(PATH.casefold())
        self.assertIn("TARGET_NO_LONGER_EXISTS",
                      self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        with patch.object(self.policy, "lstat", side_effect=PermissionError):
            self.assertIn("ACCESS_DENIED",
                          self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])


class SuccessfulRecycle:
    def __init__(self):
        self.calls = []

    def recycle(self, path):
        self.calls.append(path)
        return RecycleResult("test_backend", "success", True)


class FailingRecycle:
    def recycle(self, path):
        raise RecycleError("RECYCLE_TEST_FAILURE")


class ServiceAndApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "m62.db"
        self.store = SnapshotStore(self.database)
        result = ScanResult(
            directories={},
            top_files=[FileMetadata("candidate.tmp", RELATIVE,
                                    "Users/Test/AppData/Local/Temp", SIZE, OLD)],
            files_seen=1, dirs_seen=0, logical_bytes=SIZE,
        )
        status = {"scan_id": "m62", "root": "system_drive_c", "state": "completed",
                  "started_at": OLD, "finished_at": NOW.isoformat(), "elapsed_ms": 100}
        self.snapshot_id = self.store.save(status, result, Path("C:\\"))
        CandidateStore(self.store).analyze_snapshot(self.snapshot_id)
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT candidate_id FROM cleanup_candidates WHERE relative_path = ?",
                (RELATIVE,)).fetchone()
            self.candidate_id = row[0]
            connection.execute("""UPDATE cleanup_candidates
                SET confidence = 'high', risk_level = 'low'
                WHERE candidate_id = ?""", (self.candidate_id,))
            connection.commit()
        self.fixture = PolicyFixture()
        self.backend = SuccessfulRecycle()
        self.service = CleanupService(
            self.store, self.fixture.policy, recycle_backend=self.backend)
        api_patch = patch("app.api.cleanup.cleanup_service", self.service)
        api_patch.start()
        self.addCleanup(api_patch.stop)
        self.headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}",
                        "origin": LOCAL_ORIGIN}

    def call(self, method, path, body=None):
        return asyncio.run(request(method, path, body, self.headers))

    def prepare(self):
        prepared = self.service.prepare(self.candidate_id, "recycle")
        self.assertTrue(prepared["execution_token"])
        return prepared

    def test_prepare_execute_audit_single_use_and_candidate_state(self):
        code, _, prepared = self.call(
            "POST", "/api/v1/cleanup/prepare",
            {"candidate_id": self.candidate_id, "requested_action": "recycle"})
        self.assertEqual(code, 200)
        self.assertTrue(prepared["real_execution_enabled"])
        self.assertEqual(prepared["preflight"]["eligibility"], "eligible_for_recycle")
        with patch("app.cleanup.service.os.path.lexists", return_value=False):
            code, _, executed = self.call(
                "POST", "/api/v1/cleanup/execute",
                {"execution_token": prepared["execution_token"]})
        self.assertEqual(code, 200)
        self.assertEqual((executed["candidate_id"], executed["target_mutation"]),
                         (self.candidate_id, "recycle_bin"))
        code, _, repeated = self.call(
            "POST", "/api/v1/cleanup/execute",
            {"execution_token": prepared["execution_token"]})
        self.assertEqual((code, repeated["detail"]), (409, "ALREADY_EXECUTED"))
        audit = self.service.detail(prepared["execution_id"])
        self.assertEqual((audit["policy_rule_id"], audit["candidate_category"],
                          audit["candidate_risk"], audit["candidate_confidence"]),
                         (EXECUTION_RULE_ID, "temporary_file", "low", "high"))
        self.assertEqual((audit["status"], audit["target_mutation"],
                          audit["recycle_api_outcome"], audit["actual_action"]),
                         ("completed", "recycle_bin", "success", "recycle"))
        listing = CandidateStore(self.store).list_latest("system_drive_c")
        self.assertEqual(listing["items"][0]["execution_state"], "recycled")
        blocked_again = self.service.prepare(self.candidate_id, "recycle")
        self.assertIn("ALREADY_EXECUTED", blocked_again["preflight"]["block_reasons"])

    def test_expiry_changed_size_mtime_identity_reparse_and_missing(self):
        prepared = self.prepare()
        with self.store._connection() as connection:
            connection.execute("UPDATE cleanup_execution_runs SET expires_at = ? WHERE id = ?",
                               ("2020-01-01T00:00:00+00:00", prepared["execution_id"]))
            connection.commit()
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "EXECUTION_TOKEN_EXPIRED")

        mutations = (
            (info(stat.S_IFREG | 0o644, SIZE + 1), "TARGET_CHANGED_SINCE_PREPARE"),
            (info(stat.S_IFREG | 0o644, SIZE, (NOW - timedelta(days=32)).isoformat()),
             "TARGET_CHANGED_SINCE_PREPARE"),
            (info(stat.S_IFREG | 0o644, SIZE, inode=99), "TARGET_CHANGED_SINCE_PREPARE"),
            (info(stat.S_IFLNK | 0o777), "EXECUTION_REPARSE_POINT_BLOCKED"),
        )
        for changed, expected in mutations:
            with self.subTest(expected=expected):
                self.fixture.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE)
                prepared = self.prepare()
                self.fixture.entries[PATH.casefold()] = changed
                with self.assertRaises(CleanupError) as caught:
                    self.service.execute(prepared["execution_token"])
                self.assertEqual(caught.exception.code, expected)
        self.fixture.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE)
        prepared = self.prepare()
        parent = "C:\\Users\\Test\\AppData".casefold()
        original_parent = self.fixture.entries[parent]
        self.fixture.entries[parent] = info(stat.S_IFDIR | 0o755, attributes=0x400)
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "EXECUTION_REPARSE_POINT_BLOCKED")
        self.fixture.entries[parent] = original_parent
        self.fixture.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE)
        prepared = self.prepare()
        self.fixture.entries.pop(PATH.casefold())
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "TARGET_NO_LONGER_EXISTS")
        self.assertEqual(self.backend.calls, [])

    def test_access_denied_scan_conflict_and_concurrent_execution(self):
        prepared = self.prepare()
        target = PATH.casefold()
        original = self.fixture.policy.lstat
        self.fixture.policy.lstat = lambda path: (_ for _ in ()).throw(
            PermissionError()) if path.casefold() == target else original(path)
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "ACCESS_DENIED")
        self.fixture.policy.lstat = original
        with patch.object(self.service, "_scan_running", return_value=True):
            blocked = self.service.prepare(self.candidate_id, "recycle")
        self.assertIn("OPERATION_CONFLICT", blocked["preflight"]["block_reasons"])
        prepared = self.prepare()
        with operations.cleanup_execution():
            with self.assertRaises(CleanupError) as caught:
                self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "OPERATION_CONFLICT")

    def test_recycle_failure_preserves_target_and_has_no_fallback(self):
        service = CleanupService(
            self.store, self.fixture.policy, recycle_backend=FailingRecycle())
        prepared = service.prepare(self.candidate_id, "recycle")
        with patch("app.cleanup.service.os.path.lexists", return_value=True):
            with self.assertRaises(CleanupError) as caught:
                service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "RECYCLE_TEST_FAILURE")
        audit = service.detail(prepared["execution_id"])
        self.assertEqual((audit["status"], audit["target_mutation"],
                          audit["final_result"]),
                         ("failed", "none", "recycle_failed"))

    def test_api_accepts_only_one_candidate_id_and_recycle_action(self):
        invalid_bodies = [
            {"candidate_id": self.candidate_id, "path": PATH},
            {"candidate_id": self.candidate_id, "requested_action": "delete"},
            {"candidate_id": self.candidate_id, "requested_action": "permanent_delete"},
            {"candidate_ids": [self.candidate_id], "requested_action": "recycle"},
        ]
        for body in invalid_bodies:
            code, _, payload = self.call("POST", "/api/v1/cleanup/prepare", body)
            self.assertIn(code, {400, 422})
            if code == 400:
                self.assertEqual(payload["detail"], "EXECUTION_ACTION_BLOCKED")
        code, _, _ = self.call("POST", "/api/v1/cleanup/execute", {"path": PATH})
        self.assertEqual(code, 422)

    def test_new_scan_is_blocked_during_cleanup_execution(self):
        manager = ScanTaskManager()
        with operations.cleanup_execution():
            with self.assertRaises(ScanAlreadyRunning) as caught:
                manager.create(requested_root="tests/fixtures/sample_disk")
            with self.assertRaises(OperationConflict):
                with operations.cleanup_execution():
                    pass
        self.assertEqual(str(caught.exception), "OPERATION_CONFLICT")

    def test_v2_migration_preserves_history_and_candidates(self):
        with closing(sqlite3.connect(self.database)) as connection:
            before = connection.execute("SELECT COUNT(*) FROM cleanup_candidates").fetchone()[0]
            connection.execute("DROP TABLE cleanup_execution_runs")
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
        self.assertEqual(self.store.get(self.snapshot_id)["snapshot_id"], self.snapshot_id)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM cleanup_candidates").fetchone()[0], before)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
