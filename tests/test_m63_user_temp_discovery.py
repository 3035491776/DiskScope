import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from app.cleanup.policy import ExecutionPolicyEngine
from app.core.config import PROJECT_ROOT
from app.intelligence.engine import RuleEngine
from app.intelligence.store import CandidateStore
from app.scanner.models import DirectoryStats, FileMetadata, ScanResult
from app.scanner.path_guard import InvalidScanRoot
from app.scanner.scope_registry import resolve_scan_scope
from app.scanner.service import scan_fixture
from app.scanner.user_temp import CURRENT_USER_TEMP_PERSISTENCE_LIMIT
from app.snapshots.store import SnapshotScopeMismatch, SnapshotStore


OLD = "2026-01-01T00:00:00+00:00"
COMPLETED = "2026-09-16T00:00:00+00:00"


def completed_status(scan_id: str, root: str) -> dict[str, object]:
    return {"scan_id": scan_id, "root": root, "state": "completed",
            "started_at": COMPLETED, "finished_at": COMPLETED, "elapsed_ms": 10}


class FixedScopeTests(unittest.TestCase):
    def test_scope_rejects_caller_root_before_server_resolution(self):
        with self.assertRaises(InvalidScanRoot):
            resolve_scan_scope(r"C:\Users\other\AppData\Local\Temp", "current_user_temp")

    def test_localappdata_is_resolved_server_side_and_unsafe_forms_are_rejected(self):
        expected = Path(os.path.abspath(Path(os.environ["LOCALAPPDATA"]) / "Temp"))
        self.assertEqual(resolve_scan_scope(scope_key="current_user_temp").root, expected)
        cases = (
            {"USERPROFILE": r"C:\Users\me", "LOCALAPPDATA": r"\\server\share", "SystemDrive": "C:"},
            {"USERPROFILE": r"C:\Users\me", "LOCALAPPDATA": r"\\?\C:\Users\me\Temp", "SystemDrive": "C:"},
            {"USERPROFILE": r"C:\Users\me", "LOCALAPPDATA": r"C:\Users\other\Temp", "SystemDrive": "C:"},
            {"USERPROFILE": r"C:\Users\me", "LOCALAPPDATA": r"D:\Temp", "SystemDrive": "C:"},
        )
        for environment in cases:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(InvalidScanRoot):
                    resolve_scan_scope(scope_key="current_user_temp")


class BoundedPersistenceTests(unittest.TestCase):
    @staticmethod
    def _make_files(root: Path, count: int) -> None:
        for index in range(count):
            (root / f"f-{index:05d}.tmp").touch()

    def test_complete_and_limited_real_metadata_fixtures(self):
        fixture_root = PROJECT_ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory(dir=fixture_root) as small_name:
            small = Path(small_name)
            self._make_files(small, 100)
            result = scan_fixture(small, Event(), file_persistence_mode="bounded_scope",
                                  file_persistence_limit=CURRENT_USER_TEMP_PERSISTENCE_LIMIT)
            self.assertEqual((result.files_seen, len(result.top_files), result.file_metadata_coverage),
                             (100, 100, "complete"))
        with tempfile.TemporaryDirectory(dir=fixture_root) as large_name:
            large = Path(large_name)
            self._make_files(large, 15_000)
            result = scan_fixture(large, Event(), file_persistence_mode="bounded_scope",
                                  file_persistence_limit=CURRENT_USER_TEMP_PERSISTENCE_LIMIT)
            self.assertEqual(result.files_seen, 15_000)
            self.assertEqual(len(result.top_files), CURRENT_USER_TEMP_PERSISTENCE_LIMIT)
            self.assertEqual(result.file_metadata_coverage, "limited")
            self.assertEqual(len({item.relative_path for item in result.top_files}), 10_000)
            cancel = Event()
            cancel.set()
            self.assertTrue(scan_fixture(large, cancel, file_persistence_mode="bounded_scope",
                                         file_persistence_limit=10_000).cancelled)


class ScopedSnapshotCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / "m63.db")

    @staticmethod
    def result(name: str = "old.tmp") -> ScanResult:
        return ScanResult(
            directories={"": DirectoryStats("", None, subtree_bytes=2 * 1024 * 1024,
                                               file_count=1)},
            top_files=[FileMetadata(name, name, "", 2 * 1024 * 1024, OLD)],
            files_seen=1, dirs_seen=1, logical_bytes=2 * 1024 * 1024,
            file_persistence_mode="bounded_scope", file_persistence_limit=10_000,
            persisted_file_count=1, observed_file_count=1,
            file_metadata_coverage="complete",
        )

    def test_snapshot_isolation_candidate_generation_and_read_only_eligibility(self):
        root = Path(r"C:\Users\Test\AppData\Local\Temp")
        temp_id = self.store.save(completed_status("temp", "current_user_temp"), self.result(), root)
        c_id = self.store.save(completed_status("c", "system_drive_c"), self.result("Users/Test/file.bin"), Path("C:\\"))
        self.assertEqual(len(self.store.list("current_user_temp")), 1)
        self.assertEqual(len(self.store.list("system_drive_c")), 1)
        with self.assertRaises(SnapshotScopeMismatch):
            self.store.compare(temp_id, c_id)

        analyzed = CandidateStore(self.store).analyze_snapshot(temp_id)
        self.assertEqual(analyzed["run"]["rule_version"], "rules-v1.1.0")
        self.assertEqual(analyzed["run"]["analysis_coverage"], "bounded_scope_files")
        candidate = CandidateStore(self.store).execution_candidates("current_user_temp")[0]
        self.assertEqual((candidate["category"], candidate["risk_level"], candidate["confidence"]),
                         ("temporary_file", "low", "high"))
        policy = ExecutionPolicyEngine(
            user_profile=r"C:\Users\Test", local_app_data=r"C:\Users\Test\AppData\Local",
            now=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc),
        )
        self.assertEqual(policy.discovery_reasons(
            candidate, "current_user_temp", candidate["snapshot_mtime"]), [])
        self.assertIn("EXECUTION_EXTENSION_BLOCKED", policy.discovery_reasons(
            {**candidate, "display_path": candidate["display_path"][:-3] + "dmp",
             "relative_path": "old.dmp"}, "current_user_temp", candidate["snapshot_mtime"]))
        self.assertEqual(self.store.get(temp_id)["persisted_file_count"], 1)
        with self.store._connection() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_age_does_not_promote_nested_temp_files_to_low_risk(self):
        snapshot = {"snapshot_id": "scope", "scope_key": "current_user_temp",
                    "root_path": r"C:\Users\Test\AppData\Local\Temp",
                    "completed_at": COMPLETED}
        engine = RuleEngine()
        direct = engine.classify({"relative_path": "direct.bin", "name": "direct.bin",
                                  "size_bytes": 2 * 1024 * 1024, "mtime": OLD}, "file", snapshot)
        nested = engine.classify({"relative_path": "installer/payload.bin", "name": "payload.bin",
                                  "size_bytes": 2 * 1024 * 1024, "mtime": OLD}, "file", snapshot)
        self.assertEqual((direct["risk_level"], direct["confidence"]), ("low", "high"))
        self.assertEqual((nested["risk_level"], nested["confidence"], nested["reason_code"]),
                         ("high", "high", "NESTED_USER_TEMP_FILE"))


if __name__ == "__main__":
    unittest.main()
