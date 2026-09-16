"""M6.1 tests mutate only server-created probes under a temporary test root."""

import asyncio
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.cleanup.probes import ControlledProbeRegistry, PROBE_SIZE
from app.cleanup.recycle import RecycleError, RecycleResult
from app.cleanup.service import CleanupError, CleanupService
from app.operations import operations
from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.snapshots.store import SnapshotStore
from app.core.config import PROJECT_ROOT
from tests.asgi_client import request


class SuccessfulTestRecycle:
    def __init__(self):
        self.calls = 0

    def recycle(self, path: str) -> RecycleResult:
        self.calls += 1
        # Test-only simulation: move the controlled fixture beside its source.
        os.replace(path, path + ".simulated-recycle-bin")
        return RecycleResult("test_backend", "success", True)


class FailingTestRecycle:
    def __init__(self):
        self.calls = 0

    def recycle(self, path: str) -> RecycleResult:
        self.calls += 1
        raise RecycleError("RECYCLE_TEST_FAILURE")


def altered(info, **changes):
    values = {
        "st_mode": info.st_mode, "st_size": info.st_size,
        "st_mtime": info.st_mtime, "st_mtime_ns": info.st_mtime_ns,
        "st_ctime_ns": info.st_ctime_ns, "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "st_file_attributes": getattr(info, "st_file_attributes", 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


class ControlledRecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base_temp = root / "Users" / "Test" / "AppData" / "Local" / "Temp"
        self.base_temp.mkdir(parents=True)
        self.store = SnapshotStore(root / "m61.db")
        self.registry = ControlledProbeRegistry(
            self.store, self.base_temp, session_id="test-session")
        self.backend = SuccessfulTestRecycle()
        self.service = CleanupService(
            self.store, probes=self.registry, recycle_backend=self.backend)
        api_patch = patch("app.api.cleanup.cleanup_service", self.service)
        api_patch.start()
        self.addCleanup(api_patch.stop)
        self.headers = {
            "cookie": f"{COOKIE_NAME}={local_session.session_token}",
            "origin": LOCAL_ORIGIN,
        }

    def call(self, method, path, body=None):
        return asyncio.run(request(method, path, body, self.headers))

    def create_prepared(self):
        probe = self.service.create_probe()
        prepared = self.service.prepare_probe(probe["probe_id"], "recycle")
        self.assertTrue(prepared["execution_token"])
        return probe, prepared

    def test_create_prepare_execute_success_audit_and_single_use(self):
        code, _, probe = self.call("POST", "/api/v1/cleanup/probes", {})
        self.assertEqual(code, 200)
        path = Path(probe["absolute_path"])
        self.assertTrue(path.is_file())
        self.assertEqual((path.stat().st_size, probe["state"]), (PROBE_SIZE, "created"))
        self.assertEqual(path.parent, self.registry.session_root)

        code, _, prepared = self.call(
            "POST", f"/api/v1/cleanup/probes/{probe['probe_id']}/prepare",
            {"requested_action": "recycle"})
        self.assertEqual(code, 200)
        self.assertTrue(prepared["real_execution_enabled"])
        self.assertEqual(prepared["preflight"]["planned_action"], "recycle")
        code, _, executed = self.call(
            "POST", "/api/v1/cleanup/execute",
            {"execution_token": prepared["execution_token"]})
        self.assertEqual(code, 200)
        self.assertEqual(
            (executed["final_result"], executed["target_mutation"], executed["original_path_absent"]),
            ("recycled", "recycle_bin", True))
        self.assertFalse(path.exists())
        code, _, repeated = self.call(
            "POST", "/api/v1/cleanup/execute",
            {"execution_token": prepared["execution_token"]})
        self.assertEqual((code, repeated["detail"]), (409, "ALREADY_EXECUTED"))
        audit = self.service.detail(prepared["execution_id"])
        self.assertEqual(
            (audit["status"], audit["probe_id"], audit["token_outcome"],
             audit["recycle_api_outcome"], audit["target_mutation"]),
            ("completed", probe["probe_id"], "consumed", "success", "recycle_bin"))
        self.assertNotIn("token_hash", audit)

    def test_api_cannot_choose_path_or_forge_probe_identity(self):
        code, _, _ = self.call(
            "POST", "/api/v1/cleanup/probes", {"path": "C:\\Windows\\notepad.exe"})
        self.assertEqual(code, 422)
        code, _, result = self.call(
            "POST", f"/api/v1/cleanup/probes/{uuid.uuid4()}/prepare",
            {"requested_action": "recycle"})
        self.assertEqual((code, result["detail"]), (404, "CONTROLLED_PROBE_NOT_FOUND"))
        self.registry._ensure_session_root()
        unregistered = self.registry.session_root / f"probe-{uuid.uuid4()}.tmp"
        unregistered.write_bytes(b"not registered")
        code, _, result = self.call(
            "POST", f"/api/v1/cleanup/probes/{uuid.uuid4()}/prepare",
            {"requested_action": "recycle"})
        self.assertEqual((code, result["detail"]), (404, "CONTROLLED_PROBE_NOT_FOUND"))
        self.assertTrue(unregistered.exists())

    def test_size_and_mtime_changes_are_blocked_before_backend(self):
        for change in ("size", "mtime"):
            with self.subTest(change=change):
                probe, prepared = self.create_prepared()
                path = Path(probe["absolute_path"])
                if change == "size":
                    with open(path, "ab") as stream:
                        stream.write(b"changed")
                else:
                    before = path.stat().st_mtime_ns
                    os.utime(path, ns=(before + 2_000_000_000, before + 2_000_000_000))
                with self.assertRaises(CleanupError) as caught:
                    self.service.execute(prepared["execution_token"])
                self.assertEqual(caught.exception.code, "TARGET_CHANGED_SINCE_PREPARE")
                self.assertTrue(path.exists())
                audit = self.service.detail(prepared["execution_id"])
                self.assertEqual((audit["target_mutation"], audit["recycle_api_outcome"]),
                                 ("none", "not_called"))
        self.assertEqual(self.backend.calls, 0)

    def test_missing_and_expired_probe_are_blocked(self):
        probe, prepared = self.create_prepared()
        path = Path(probe["absolute_path"])
        path.unlink()  # Test-only controlled probe removal to simulate an external change.
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "TARGET_NO_LONGER_EXISTS")

        probe, prepared = self.create_prepared()
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE cleanup_execution_runs SET expires_at = ? WHERE id = ?",
                ("2020-01-01T00:00:00+00:00", prepared["execution_id"]))
            connection.commit()
        with self.assertRaises(CleanupError) as caught:
            self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "EXECUTION_TOKEN_EXPIRED")
        self.assertTrue(Path(probe["absolute_path"]).exists())
        self.assertEqual(self.service.detail(prepared["execution_id"])["target_mutation"], "none")

    def test_target_parent_reparse_cross_volume_and_boundary_are_blocked(self):
        probe = self.service.create_probe()
        record = self.registry.get(probe["probe_id"])
        target = str(probe["absolute_path"]).casefold()
        parent = str(Path(probe["absolute_path"]).parent).casefold()
        real_lstat = os.lstat

        for changed_path in (target, parent):
            def reparse(path, selected=changed_path):
                info = real_lstat(path)
                return altered(info, st_file_attributes=0x400) if str(path).casefold() == selected else info
            with patch("app.cleanup.probes.os.lstat", side_effect=reparse):
                self.assertIn("EXECUTION_REPARSE_POINT_BLOCKED",
                              self.registry.preflight(record, "created")["block_reasons"])

        def other_volume(path):
            info = real_lstat(path)
            return altered(info, st_dev=info.st_dev + 1) if str(path).casefold() == target else info
        with patch("app.cleanup.probes.os.lstat", side_effect=other_volume):
            self.assertIn("EXECUTION_CROSS_VOLUME_BLOCKED",
                          self.registry.preflight(record, "created")["block_reasons"])
        for unsafe in ("C:\\Users\\Other\\probe.tmp", "C:\\Windows\\probe.tmp"):
            changed = {**record, "absolute_path": unsafe}
            self.assertIn("CONTROLLED_PROBE_BOUNDARY_BLOCKED",
                          self.registry.preflight(changed, "created")["block_reasons"])

    def test_scan_and_concurrent_cleanup_conflicts(self):
        with patch.object(self.service, "_scan_running", return_value=True):
            with self.assertRaises(CleanupError) as caught:
                self.service.create_probe()
        self.assertEqual(caught.exception.code, "OPERATION_CONFLICT")
        probe = self.service.create_probe()
        with patch.object(self.service, "_scan_running", return_value=True):
            prepared = self.service.prepare_probe(probe["probe_id"], "recycle")
        self.assertIsNone(prepared["execution_token"])
        self.assertIn("OPERATION_CONFLICT", prepared["preflight"]["block_reasons"])

        probe, prepared = self.create_prepared()
        with operations.cleanup_execution():
            with self.assertRaises(CleanupError) as caught:
                self.service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "OPERATION_CONFLICT")
        self.assertTrue(Path(probe["absolute_path"]).exists())

    def test_recycle_failure_has_no_permanent_delete_fallback(self):
        backend = FailingTestRecycle()
        service = CleanupService(self.store, probes=self.registry, recycle_backend=backend)
        probe = service.create_probe()
        prepared = service.prepare_probe(probe["probe_id"], "recycle")
        path = Path(probe["absolute_path"])
        with self.assertRaises(CleanupError) as caught:
            service.execute(prepared["execution_token"])
        self.assertEqual(caught.exception.code, "RECYCLE_TEST_FAILURE")
        self.assertTrue(path.exists())
        audit = service.detail(prepared["execution_id"])
        self.assertEqual(
            (audit["status"], audit["final_result"], audit["target_mutation"]),
            ("failed", "recycle_failed", "none"))
        self.assertEqual(backend.calls, 1)

    def test_interrupted_execution_is_never_guessed_completed(self):
        probe, prepared = self.create_prepared()
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE cleanup_execution_runs SET status = 'executing' WHERE id = ?",
                (prepared["execution_id"],))
            connection.commit()
        audit = self.service.list()[0]
        self.assertEqual(
            (audit["status"], audit["failure_code"], audit["target_mutation"]),
            ("failed", "EXECUTION_INTERRUPTED", "unknown"))
        self.assertTrue(Path(probe["absolute_path"]).exists())
        self.assertEqual(self.registry.get(probe["probe_id"])["state"], "failed")

    def test_v3_to_v4_migration_preserves_m6_audit(self):
        with self.store._connection() as connection:
            connection.commit()
        with closing(sqlite3.connect(self.store.database)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DROP TABLE cleanup_execution_runs")
            connection.execute("DROP TABLE controlled_probes")
            SnapshotStore._create_execution_table_v3(connection)
            connection.execute("""INSERT INTO cleanup_execution_runs VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("old-audit", None, "old-candidate", "old-snapshot", "rules-v1.0.0",
                 "recycle", "ineligible", datetime.now(timezone.utc).isoformat(), None,
                 None, "blocked", "C:\\Windows\\blocked.bin", 1, None, None, None,
                 None, "[]", "[]", "blocked", "EXECUTION_POLICY_BLOCKED"))
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
        with self.store._connection() as connection:
            migrated = connection.execute(
                "SELECT * FROM cleanup_execution_runs WHERE id = 'old-audit'").fetchone()
            self.assertIsNotNone(migrated)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(migrated["policy_rule_id"], "USER_TEMP_STALE_FILE_PREFLIGHT_V1")
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_v4_to_v5_migration_preserves_execution_audit(self):
        with self.store._connection() as connection:
            connection.commit()
        prepared_at = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.store.database)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DROP TABLE cleanup_execution_runs")
            SnapshotStore._create_execution_table_v4(connection)
            connection.execute("""INSERT INTO cleanup_execution_runs (
                id, token_hash, candidate_id, probe_id, snapshot_id, scope_key,
                rule_version, requested_action, planned_action, eligibility,
                prepare_time, status, original_path, snapshot_size,
                checks_json, block_reasons_json, policy_decision, token_outcome,
                target_mutation) VALUES (
                'v4-audit', NULL, 'legacy-candidate', NULL, NULL, 'system_drive_c',
                'rules-v1.0.0', 'recycle', 'dry_run_only', 'ineligible', ?, 'blocked',
                'C:\\Windows\\blocked.bin', 1, '[]', '["EXECUTION_PROTECTED_PATH"]',
                'ineligible', 'not_issued', 'none')""", (prepared_at,))
            connection.execute("PRAGMA user_version = 4")
            connection.commit()
        with self.store._connection() as connection:
            migrated = connection.execute(
                "SELECT * FROM cleanup_execution_runs WHERE id = 'v4-audit'").fetchone()
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(migrated["policy_rule_id"],
                             "USER_TEMP_STALE_FILE_PREFLIGHT_V1")
            self.assertIsNone(migrated["actual_action"])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
