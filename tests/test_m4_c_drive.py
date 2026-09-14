import asyncio
import os
import stat
import tempfile
import threading
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.scanner.aggregator import DirectoryAggregator
from app.scanner.c_drive import (
    C_ROOT, SYSTEM_DRIVE_SCOPE_KEY, SystemDriveNotFixed, classify_system_item,
    validate_system_drive_c,
)
from app.scanner.models import DirectoryStats, FileMetadata, ScanResult
from app.scanner.path_guard import InvalidScanRoot, validate_scan_root
from app.scanner.policy import C_DRIVE_SAFE_READONLY, SCAN_POLICY
from app.scanner.scope_registry import (
    CDriveConfirmationRequired, FIXED_SCOPES, resolve_scan_scope,
)
from app.scanner.service import scan_fixture
from app.scanner.whole_volume_gate import WholeVolumeScanDenied, can_scan_whole_volume
from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.snapshots.store import SnapshotScopeMismatch, SnapshotStore
from app.system.volumes import capacity_record
from app.tasks.manager import ScanTaskManager
from tests.asgi_client import request


def synthetic_result(*, limited=False):
    return ScanResult(
        directories={"": DirectoryStats("", None, subtree_bytes=100, file_count=1,
                                         children_count=1),
                     "Windows": DirectoryStats("Windows", "", direct_bytes=100,
                                               subtree_bytes=100, direct_file_count=1,
                                               file_count=1)},
        top_files=[FileMetadata("pagefile.sys", "pagefile.sys", "", 100, "now")],
        files_seen=1, dirs_seen=2, logical_bytes=100,
        skipped_count=1 if limited else 0,
        errors_count=1 if limited else 0,
        errors={"ACCESS_DENIED": {"count": 1, "samples": ["Recovery"]}} if limited else {},
        limited_directories={""} if limited else set(),
    )


class CDrivePolicyTests(unittest.TestCase):
    def test_fixed_scope_and_policy_remain_metadata_only(self):
        scope = FIXED_SCOPES[SYSTEM_DRIVE_SCOPE_KEY]
        self.assertEqual(scope.root, C_ROOT)
        self.assertEqual(scope.label, "Windows C:")
        self.assertTrue(scope.whole_volume)
        self.assertEqual(scope.policy.mode, "c_drive_safe_readonly")
        for policy in (SCAN_POLICY, C_DRIVE_SAFE_READONLY):
            self.assertEqual(policy.concurrency, 1)
            self.assertEqual(policy.max_active_scans, 1)
            self.assertFalse(policy.follow_reparse_points)
            self.assertFalse(policy.allow_cross_volume)
            self.assertFalse(policy.read_file_contents)
            self.assertFalse(policy.hash_files)

    def test_only_c_policy_passes_whole_volume_gate(self):
        self.assertFalse(can_scan_whole_volume(C_ROOT))
        self.assertTrue(can_scan_whole_volume(C_ROOT, C_DRIVE_SAFE_READONLY))
        for root in (Path("D:\\"), Path("E:\\")):
            self.assertFalse(can_scan_whole_volume(root, C_DRIVE_SAFE_READONLY))
            with self.assertRaises(WholeVolumeScanDenied):
                validate_scan_root(str(root))
        with self.assertRaises(WholeVolumeScanDenied):
            validate_scan_root("C:\\")

    def test_scope_requires_confirmation_and_never_accepts_a_root_string(self):
        with self.assertRaises(CDriveConfirmationRequired):
            resolve_scan_scope(scope_key=SYSTEM_DRIVE_SCOPE_KEY)
        with self.assertRaises(InvalidScanRoot):
            resolve_scan_scope("C:\\", SYSTEM_DRIVE_SCOPE_KEY, True)
        with patch("app.scanner.scope_registry.validate_system_drive_c", return_value=C_ROOT):
            approved = resolve_scan_scope(scope_key=SYSTEM_DRIVE_SCOPE_KEY, confirmed_readonly=True)
        self.assertEqual(approved.root, C_ROOT)
        for root in ("\\\\server\\share", "\\\\?\\C:\\", "\\\\.\\PhysicalDrive0", "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1"):
            with self.subTest(root=root), self.assertRaises(InvalidScanRoot):
                resolve_scan_scope(root)

    def test_fixed_drive_identity_is_checked_without_opening_volume(self):
        with patch("app.scanner.c_drive.drive_type", return_value=2):
            with self.assertRaises(SystemDriveNotFixed):
                validate_system_drive_c()
        fake_stat = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
        with (
            patch("app.scanner.c_drive.drive_type", return_value=3),
            patch("app.scanner.c_drive.os.lstat", return_value=fake_stat),
            patch.object(Path, "resolve", return_value=C_ROOT),
            patch.object(Path, "is_dir", return_value=True),
        ):
            self.assertEqual(validate_system_drive_c(), C_ROOT)

    def test_categories_and_risk_labels_never_claim_deletion_safety(self):
        expected = {
            "Windows/System32": ("windows", "system_managed"),
            "Program Files/App": ("program_files", "application_managed"),
            "Program Files (x86)/App": ("program_files_x86", "application_managed"),
            "ProgramData/App": ("program_data", "application_managed"),
            "Users/Alice": ("users", "user_data"),
            "Recovery": ("recovery", "protected_system"),
            "System Volume Information": ("system_protected", "protected_system"),
            "$Recycle.Bin": ("recycle_bin", "system_managed"),
            "PerfLogs": ("perflogs", "system_managed"),
            "Unknown": ("other", "unknown"),
            "pagefile.sys": ("system_file", "system_managed"),
            "hiberfil.sys": ("system_file", "system_managed"),
            "swapfile.sys": ("system_file", "system_managed"),
        }
        for path, (category, risk) in expected.items():
            with self.subTest(path=path):
                result = classify_system_item(path)
                self.assertEqual((result["system_category"], result["risk_class"]), (category, risk))
                self.assertNotIn("safe_to_delete", result)

    def test_volume_capacity_remains_distinct_from_scanned_bytes(self):
        c = capacity_record("C:", 1000, 200)
        d = capacity_record("D:", 1000, 200)
        self.assertEqual(c["used_bytes"], 800)
        self.assertTrue(c["scan_allowed"])
        self.assertFalse(d["scan_allowed"])
        self.assertNotIn("scanned_bytes", c)

    def test_windows_like_fixture_is_metadata_only_and_bounded(self):
        fixture_base = PROJECT_ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory(dir=fixture_base) as temp:
            root = Path(temp)
            for name in ("Windows", "Program Files", "ProgramData", "Users", "Recovery"):
                directory = root / name
                directory.mkdir()
                (directory / "item.bin").write_bytes(b"x" * 10)
            result = scan_fixture(root, threading.Event())
            self.assertEqual(result.files_seen, 5)
            self.assertEqual(result.dirs_seen, 6)
            self.assertEqual(result.logical_bytes, 50)
            self.assertLessEqual(len(result.top_files), 1000)
            self.assertEqual(result.errors_count, 0)

    def test_directory_aggregation_memory_scales_with_directories_not_files(self):
        tracemalloc.start()
        try:
            aggregator = DirectoryAggregator()
            aggregator.add_directory("", None)
            for index in range(10000):
                aggregator.add_directory(f"dir_{index}", "")
            result = aggregator.finish()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(result), 10001)
        self.assertLess(peak, 30 * 1024 * 1024)


class CDriveApiAndSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / "m4.db")
        self.manager = ScanTaskManager(self.store)
        manager_patch = patch("app.api.scans.scan_tasks", self.manager)
        manager_patch.start()
        self.addCleanup(manager_patch.stop)
        self.headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}", "origin": LOCAL_ORIGIN}

    def call(self, method, path, body=None, query=""):
        return asyncio.run(request(method, path, body, self.headers, query))

    def wait(self, scan_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            latest = self.manager.status(scan_id)
            if latest["snapshot_status"] in {"saved", "failed"} or latest["state"] in {"cancelled", "failed"}:
                return latest
            time.sleep(.01)
        self.fail("mock C scan did not finish")

    def test_api_requires_fixed_scope_and_confirmation(self):
        for body, expected in (({"root": "C:\\"}, "WHOLE_VOLUME_SCAN_NOT_APPROVED"),
                               ({"scope_key": SYSTEM_DRIVE_SCOPE_KEY}, "C_DRIVE_CONFIRMATION_REQUIRED"),
                               ({"scope_key": SYSTEM_DRIVE_SCOPE_KEY, "root": "C:\\", "confirmed_readonly": True}, "Use a fixed scope_key without a root path.")):
            code, _, payload = self.call("POST", "/api/v1/scans", body)
            self.assertEqual((code, payload["detail"]), (403, expected))
        for root in ("D:\\", "\\\\server\\share", "\\\\?\\C:\\"):
            code, _, _ = self.call("POST", "/api/v1/scans", {"root": root})
            self.assertEqual(code, 403)

    def test_completed_c_scan_snapshot_coverage_and_current_status(self):
        def controlled_scan(root, cancel, on_progress, scope_key):
            scan_result = synthetic_result(limited=True)
            on_progress(scan_result)
            return scan_result
        with (
            patch("app.scanner.scope_registry.validate_system_drive_c", return_value=C_ROOT),
            patch("app.tasks.manager.scan_fixture", side_effect=controlled_scan),
        ):
            code, _, created = self.call("POST", "/api/v1/scans", {"scope_key": SYSTEM_DRIVE_SCOPE_KEY, "confirmed_readonly": True})
            self.assertEqual(code, 202)
            latest = self.wait(created["scan_id"])
        self.assertEqual((latest["state"], latest["snapshot_status"]), ("completed", "saved"))
        self.assertEqual(latest["coverage"], "limited")
        self.assertEqual(latest["coverage_summary"]["access_denied_count"], 1)
        self.assertEqual(latest["scope_key"], SYSTEM_DRIVE_SCOPE_KEY)
        self.assertEqual(latest["policy_mode"], "c_drive_safe_readonly")
        self.assertEqual(self.store.list(SYSTEM_DRIVE_SCOPE_KEY)[0]["coverage"], "limited")
        code, _, payload = self.call("GET", "/api/v1/scans/current")
        self.assertEqual(code, 200)
        self.assertEqual(payload["scan"]["scan_id"], created["scan_id"])
        code, _, directories = self.call("GET", f"/api/v1/scans/{created['scan_id']}/directories")
        self.assertEqual(code, 200)
        self.assertEqual(directories["items"][0]["system_category"], "windows")
        code, _, files = self.call("GET", f"/api/v1/scans/{created['scan_id']}/top", query="kind=file&limit=100")
        self.assertEqual(code, 200)
        self.assertEqual(files["items"][0]["system_category"], "system_file")

    def test_c_snapshot_retention_and_cross_scope_compare(self):
        for index in range(21):
            scan_status = {"scan_id": f"c{index}", "root": "system_drive_c", "state": "completed",
                           "started_at": f"2026-01-01T00:00:{index:02d}Z",
                           "finished_at": f"2026-01-01T00:00:{index:02d}Z", "elapsed_ms": 100}
            self.store.save(scan_status, synthetic_result(), C_ROOT)
        self.assertEqual(len(self.store.list(SYSTEM_DRIVE_SCOPE_KEY)), 20)
        project = self.store.save({"scan_id": "project", "root": "project_workspace", "state": "completed",
                                   "started_at": "now", "finished_at": "now", "elapsed_ms": 100}, synthetic_result(), PROJECT_ROOT)
        c = self.store.list(SYSTEM_DRIVE_SCOPE_KEY)[0]["snapshot_id"]
        self.assertEqual(self.store.compare(c, c)["total_bytes_delta"], 0)
        with self.assertRaises(SnapshotScopeMismatch):
            self.store.compare(project, c)

    def test_c_cancel_exits_worker_rejects_second_scan_then_allows_fixture(self):
        started = threading.Event()
        exited = threading.Event()

        def controlled_scan(root, cancel, on_progress, scope_key):
            started.set()
            cancel.wait(timeout=3)
            exited.set()
            return ScanResult(cancelled=True)

        with (
            patch("app.scanner.scope_registry.validate_system_drive_c", return_value=C_ROOT),
            patch("app.tasks.manager.scan_fixture", side_effect=controlled_scan),
        ):
            code, _, created = self.call("POST", "/api/v1/scans", {"scope_key": SYSTEM_DRIVE_SCOPE_KEY, "confirmed_readonly": True})
            self.assertEqual(code, 202)
            self.assertTrue(started.wait(timeout=3))
            code, _, _ = self.call("POST", "/api/v1/scans", {"root": "tests/fixtures/sample_disk"})
            self.assertEqual(code, 409)
            code, _, cancelling = self.call("POST", f"/api/v1/scans/{created['scan_id']}/cancel")
            self.assertEqual((code, cancelling["state"]), (200, "cancelling"))
            self.assertEqual(self.wait(created["scan_id"])["state"], "cancelled")
        self.assertTrue(exited.is_set())
        self.assertEqual(self.store.list(SYSTEM_DRIVE_SCOPE_KEY), [])
        with patch("app.tasks.manager.scan_fixture", return_value=synthetic_result()):
            created = self.manager.create("tests/fixtures/sample_disk")
            self.assertEqual(self.wait(created["scan_id"])["state"], "completed")

    def test_c_database_failure_preserves_completed_scan(self):
        self.store.database.write_bytes(b"corrupt sqlite")
        with (
            patch("app.scanner.scope_registry.validate_system_drive_c", return_value=C_ROOT),
            patch("app.tasks.manager.scan_fixture", return_value=synthetic_result()),
        ):
            created = self.manager.create(scope_key=SYSTEM_DRIVE_SCOPE_KEY, confirmed_readonly=True)
            latest = self.wait(created["scan_id"])
        self.assertEqual((latest["state"], latest["snapshot_status"]), ("completed", "failed"))
        self.assertEqual(latest["snapshot_error_code"], "SNAPSHOT_DATABASE_UNAVAILABLE")
        self.assertIsNotNone(self.manager.result(created["scan_id"]))


if __name__ == "__main__":
    unittest.main()
