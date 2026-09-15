"""M6 gate tests use synthetic metadata; never touch a real C: candidate."""

import asyncio
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.cleanup.policy import ExecutionPolicyEngine
from app.cleanup.service import CleanupError, CleanupService
from app.operations import OperationConflict, operations
from app.tasks.manager import ScanAlreadyRunning, ScanTaskManager
from app.core.config import PROJECT_ROOT
from app.intelligence.store import CandidateStore
from app.scanner.models import FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.snapshots.store import SnapshotStore
from tests.asgi_client import request

OLD = "2026-08-01T00:00:00+00:00"
NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
PATH = "C:\\Users\\Test\\AppData\\Local\\Temp\\probe.bin"
RELATIVE = "Users/Test/AppData/Local/Temp/probe.bin"
SIZE = 2 * 1024 * 1024


def info(mode, size=0, when=OLD, attributes=0, device=1, inode=2):
    timestamp = datetime.fromisoformat(when).timestamp()
    return SimpleNamespace(st_mode=mode, st_size=size, st_mtime=timestamp,
                           st_mtime_ns=int(timestamp * 1e9), st_file_attributes=attributes,
                           st_dev=device, st_ino=inode)


def candidate(path=PATH, **changes):
    item = {"candidate_id": "candidate", "display_path": path,
            "relative_path": path[3:].replace("\\", "/"), "object_type": "file",
            "logical_bytes": SIZE, "category": "temporary_file", "confidence": "high",
            "risk_level": "review", "reason_code": "STALE_USER_TEMP_FILE"}
    item.update(changes)
    return item


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.entries = {"c:\\": info(stat.S_IFDIR | 0o755)}
        prefix = "C:"
        for part in PATH[3:].split("\\")[:-1]:
            prefix += "\\" + part
            self.entries[prefix.casefold()] = info(stat.S_IFDIR | 0o755)
        self.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE)
        self.policy = ExecutionPolicyEngine("C:\\Users\\Test", self.lookup, lambda: NOW)

    def lookup(self, path):
        return self.entries[path.casefold()]

    def test_positive_and_changed_metadata(self):
        plan = self.policy.preflight(candidate(), "system_drive_c", OLD)
        self.assertEqual((plan["eligibility"], plan["planned_action"]), ("eligible_for_review", "dry_run_only"))
        for changed in (info(stat.S_IFREG | 0o644, SIZE + 1),
                        info(stat.S_IFREG | 0o644, SIZE, "2026-08-02T00:00:00+00:00")):
            self.entries[PATH.casefold()] = changed
            self.assertIn("TARGET_CHANGED_SINCE_SCAN", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])

    def test_path_and_policy_denial_matrix(self):
        blocked = [
            "C:\\Windows\\ServiceProfiles\\LocalService\\AppData\\Local\\Temp\\dump.dmp",
            "C:\\Program Files\\a.bin", "C:\\Program Files (x86)\\a.bin",
            "C:\\ProgramData\\a.bin", "C:\\Recovery\\a.bin",
            "C:\\System Volume Information\\a.bin", "C:\\$Recycle.Bin\\a.bin",
            "C:\\hiberfil.sys", "C:\\pagefile.sys", "C:\\swapfile.sys",
            "C:\\Users\\Other\\AppData\\Local\\Temp\\a.bin",
            "D:\\Users\\Test\\AppData\\Local\\Temp\\a.bin",
            "\\\\server\\share\\a.bin", "\\\\?\\C:\\Users\\Test\\AppData\\Local\\Temp\\a.bin",
            "\\\\.\\C:\\Users\\Test\\AppData\\Local\\Temp\\a.bin",
            "C:\\Users\\Test\\AppData\\Local\\Temp\\..\\a.bin",
            "C:\\Users\\Test\\AppData\\Local\\Temp\\probe.bin.",
            "C:\\Users\\Test\\AppData\\Local\\Temp\\CON.txt",
        ]
        for path in blocked:
            with self.subTest(path=path):
                self.assertTrue(self.policy.static_reasons(candidate(path), "system_drive_c"))
        for changes in ({"object_type": "directory"}, {"object_type": "group"},
                        {"category": "application_cache"}, {"confidence": "low"},
                        {"risk_level": "protected"}, {"logical_bytes": 1}):
            self.assertTrue(self.policy.static_reasons(candidate(**changes), "system_drive_c"))
        self.assertIn("EXECUTION_SCOPE_BLOCKED", self.policy.static_reasons(candidate(), "fixture_sample"))

    def test_reparse_parent_target_missing_access_and_cross_volume(self):
        parent = "C:\\Users\\Test\\AppData".casefold()
        original = self.entries[parent]
        self.entries[parent] = info(stat.S_IFDIR | 0o755, attributes=0x400)
        self.assertIn("EXECUTION_REPARSE_POINT_BLOCKED", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        self.entries[parent] = original
        self.entries[PATH.casefold()] = info(stat.S_IFLNK | 0o777)
        self.assertIn("EXECUTION_REPARSE_POINT_BLOCKED", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        self.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE, device=2)
        self.assertIn("EXECUTION_CROSS_VOLUME_BLOCKED", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        del self.entries[PATH.casefold()]
        with patch.object(self.policy, "lstat", side_effect=FileNotFoundError):
            self.assertIn("TARGET_NO_LONGER_EXISTS", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        with patch.object(self.policy, "lstat", side_effect=PermissionError):
            self.assertIn("ACCESS_DENIED", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])
        sharing_violation = OSError("in use")
        sharing_violation.winerror = 32
        with patch.object(self.policy, "lstat", side_effect=sharing_violation):
            self.assertIn("TARGET_IN_USE", self.policy.preflight(candidate(), "system_drive_c", OLD)["block_reasons"])


class ServiceAndApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "m6.db"
        self.store = SnapshotStore(self.database)
        result = ScanResult(directories={}, top_files=[FileMetadata("probe.bin", RELATIVE,
                            "Users/Test/AppData/Local/Temp", SIZE, OLD)], files_seen=1, dirs_seen=0,
                            logical_bytes=SIZE)
        status = {"scan_id": "m6", "root": "system_drive_c", "state": "completed",
                  "started_at": OLD, "finished_at": NOW.isoformat(), "elapsed_ms": 100}
        self.snapshot_id = self.store.save(status, result, Path("C:\\"))
        CandidateStore(self.store).analyze_snapshot(self.snapshot_id)
        with self.store._connection() as connection:
            row = connection.execute("SELECT candidate_id FROM cleanup_candidates WHERE relative_path = ?", (RELATIVE,)).fetchone()
            self.candidate_id = row[0]
            # A synthetic high-confidence candidate exercises the positive gate without changing M5 rules.
            connection.execute("UPDATE cleanup_candidates SET confidence = 'high' WHERE candidate_id = ?", (self.candidate_id,))
            connection.commit()
        self.policy_test = PolicyTests()
        self.policy_test.setUp()
        self.service = CleanupService(self.store, self.policy_test.policy)
        p = patch("app.api.cleanup.cleanup_service", self.service)
        p.start()
        self.addCleanup(p.stop)
        self.headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}", "origin": LOCAL_ORIGIN}

    def call(self, method, path, body=None):
        return asyncio.run(request(method, path, body, self.headers))

    def test_prepare_audit_disabled_execute_and_single_use(self):
        code, _, prepared = self.call("POST", "/api/v1/cleanup/prepare",
                                      {"candidate_id": self.candidate_id, "requested_action": "recycle"})
        self.assertEqual(code, 200)
        self.assertEqual(prepared["preflight"]["eligibility"], "eligible_for_review")
        self.assertFalse(prepared["real_execution_enabled"])
        token = prepared["execution_token"]
        self.assertTrue(token)
        code, _, result = self.call("POST", "/api/v1/cleanup/execute", {"execution_token": token})
        self.assertEqual((code, result["detail"]), (409, "EXECUTION_NOT_ENABLED_YET"))
        code, _, result = self.call("POST", "/api/v1/cleanup/execute", {"execution_token": token})
        self.assertEqual((code, result["detail"]), (409, "ALREADY_EXECUTED"))
        code, _, listed = self.call("GET", "/api/v1/cleanup/executions")
        self.assertEqual((code, listed["items"][0]["status"]), (200, "blocked"))
        code, _, detail = self.call("GET", f"/api/v1/cleanup/executions/{prepared['execution_id']}")
        self.assertEqual((code, detail["failure_code"]), (200, "EXECUTION_NOT_ENABLED_YET"))
        self.assertEqual(self.policy_test.entries[PATH.casefold()].st_size, SIZE)

    def test_expiry_revalidation_and_path_api_block(self):
        prepared = self.service.prepare(self.candidate_id, "recycle")
        token = prepared["execution_token"]
        with self.store._connection() as connection:
            connection.execute("UPDATE cleanup_execution_runs SET expires_at = ? WHERE id = ?", (OLD, prepared["execution_id"]))
            connection.commit()
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(token)
        self.assertEqual(caught.exception.code, "EXECUTION_TOKEN_EXPIRED")
        expired = self.service.detail(prepared["execution_id"])
        self.assertEqual((expired["status"], expired["final_result"]),
                         ("expired", "no_target_mutation"))
        prepared = self.service.prepare(self.candidate_id, "recycle")
        self.policy_test.entries[PATH.casefold()] = info(stat.S_IFREG | 0o644, SIZE + 1)
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "TARGET_CHANGED_SINCE_SCAN")
        code, _, _ = self.call("POST", "/api/v1/cleanup/prepare", {"candidate_id": self.candidate_id, "path": PATH})
        self.assertEqual(code, 422)
        code, _, _ = self.call("POST", "/api/v1/cleanup/execute", {"path": PATH})
        self.assertEqual(code, 422)

    def test_scan_conflict_and_missing_target_are_audited(self):
        with patch.object(self.service, "_scan_running", return_value=True):
            blocked = self.service.prepare(self.candidate_id, "recycle")
        self.assertIsNone(blocked["execution_token"])
        self.assertIn("OPERATION_CONFLICT", blocked["preflight"]["block_reasons"])
        prepared = self.service.prepare(self.candidate_id, "recycle")
        with patch.object(self.service, "_scan_running", return_value=True):
            with self.assertRaises(CleanupError) as caught:
                self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "OPERATION_CONFLICT")
        prepared = self.service.prepare(self.candidate_id, "recycle")
        self.policy_test.entries.pop(PATH.casefold())
        self.policy_test.policy.lstat = lambda path: (_ for _ in ()).throw(FileNotFoundError()) if path.casefold() == PATH.casefold() else self.policy_test.lookup(path)
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "TARGET_NO_LONGER_EXISTS")
        history = self.service.list()
        self.assertEqual(history[0]["failure_code"], "TARGET_NO_LONGER_EXISTS")
        self.assertNotIn("token_hash", history[0])

    def test_protected_real_candidate_and_invalid_id_never_prepare(self):
        with self.store._connection() as connection:
            connection.execute("UPDATE cleanup_candidates SET risk_level = 'protected' WHERE candidate_id = ?", (self.candidate_id,))
            connection.commit()
        blocked = self.service.prepare(self.candidate_id, "recycle")
        self.assertIsNone(blocked["execution_token"])
        self.assertIn("EXECUTION_POLICY_BLOCKED", blocked["preflight"]["block_reasons"])
        code, _, result = self.call("POST", "/api/v1/cleanup/prepare", {"candidate_id": "not-a-candidate"})
        self.assertEqual((code, result["detail"]), (404, "CANDIDATE_NOT_FOUND"))

    def test_new_scan_is_blocked_during_cleanup_execution(self):
        manager = ScanTaskManager()
        with operations.cleanup_execution():
            with self.assertRaises(ScanAlreadyRunning) as caught:
                manager.create(requested_root="tests/fixtures/sample_disk")
            with self.assertRaises(OperationConflict) as concurrent:
                with operations.cleanup_execution():
                    pass
        self.assertEqual(str(caught.exception), "OPERATION_CONFLICT")
        self.assertEqual(str(concurrent.exception), "OPERATION_CONFLICT")

    def test_v2_migration_preserves_history_and_candidates(self):
        with closing(sqlite3.connect(self.database)) as connection:
            before = connection.execute("SELECT COUNT(*) FROM cleanup_candidates").fetchone()[0]
            connection.execute("DROP TABLE cleanup_execution_runs")
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
        self.assertEqual(self.store.get(self.snapshot_id)["snapshot_id"], self.snapshot_id)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cleanup_candidates").fetchone()[0], before)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
