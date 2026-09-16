import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.intelligence.engine import RuleEngine
from app.intelligence.rules import GIB, MIB, RULE_VERSION
from app.intelligence.store import CandidateStore, InvalidCandidateScope
from app.scanner.models import DirectoryStats, FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.snapshots.store import SnapshotStore, SnapshotStoreError
from tests.asgi_client import request


COMPLETED = "2026-09-14T00:00:00+00:00"
OLD = "2026-08-01T00:00:00+00:00"
RECENT = "2026-09-13T23:00:00+00:00"


def file(path, size=2 * GIB, mtime=OLD):
    return {"relative_path": path, "name": path.rsplit("/", 1)[-1],
            "size_bytes": size, "mtime": mtime}


def snapshot(snapshot_id="synthetic", scope="system_drive_c"):
    return {"snapshot_id": snapshot_id, "scope_key": scope, "completed_at": COMPLETED}


class RuleEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = RuleEngine()

    def classify(self, path, size=2 * GIB, mtime=OLD):
        return self.engine.classify(file(path, size, mtime), "file", snapshot())

    def test_protected_system_files_and_specific_priority(self):
        expected = {"hiberfil.sys": "hibernation_file", "PAGEFILE.SYS": "pagefile",
                    "swapfile.sys": "swapfile"}
        for path, category in expected.items():
            with self.subTest(path=path):
                item = self.classify(path)
                self.assertEqual((item["category"], item["risk_level"], item["confidence"]),
                                 (category, "protected", "high"))
                self.assertEqual(item["recommended_action"], "system_managed")
                self.assertNotIn("safe_to_delete", item)

    def test_service_dump_is_review_high_confidence_and_generic_dump_is_not(self):
        service = self.classify(r"WINDOWS\ServiceProfiles\LocalService\AppData\Local\Temp\A.DMP", 12 * GIB)
        self.assertEqual((service["category"], service["risk_level"], service["confidence"]),
                         ("crash_dump", "review", "high"))
        self.assertEqual(service["reason_code"], "CRASH_DUMP_IN_SERVICE_TEMP")
        self.assertGreaterEqual(len(service["evidence"]), 2)
        document = self.classify("Users/Test/Documents/debug.dmp")
        self.assertEqual((document["category"], document["risk_level"]), ("user_document", "high"))
        arbitrary = self.classify("random/debug.dmp")
        self.assertEqual((arbitrary["category"], arbitrary["risk_level"]), ("unknown", "high"))

    def test_user_application_and_windows_contexts_are_conservative(self):
        expected = {
            "Users/Test/Downloads/large.iso": ("user_download", "review"),
            "Users/Test/Desktop/video.mp4": ("user_desktop", "high"),
            "Users/Test/AppData/Local/SomeApp/data.bin": ("application_managed", "high"),
            "Users/Test/AppData/Local/SomeApp/Cache/cache.bin": ("application_cache", "review"),
            "Program Files/SomeApp/data.bin": ("application_managed", "high"),
            "Windows/System32/kernel.bin": ("system_managed", "protected"),
            "ProgramData/SomeApp/data.bin": ("application_managed", "high"),
        }
        for path, (category, risk) in expected.items():
            with self.subTest(path=path):
                item = self.classify(path)
                self.assertEqual((item["category"], item["risk_level"]), (category, risk))

    def test_temp_age_and_size_are_not_deletion_authority(self):
        path = "Users/Test/AppData/Local/Temp/item.tmp"
        recent = self.classify(path, 2 * MIB, RECENT)
        stale = self.classify(path, 2 * MIB, OLD)
        self.assertEqual((recent["risk_level"], recent["reason_code"]),
                         ("high", "RECENT_USER_TEMP_FILE"))
        self.assertEqual((stale["risk_level"], stale["reason_code"]),
                         ("review", "STALE_USER_TEMP_FILE"))
        self.assertIsNone(self.classify(path, 100, OLD))
        self.assertEqual(stale["rule_version"], RULE_VERSION)
        self.assertGreaterEqual(len(stale["evidence"]), 2)

    def test_directory_rules_grouping_determinism_and_no_target_reads(self):
        files = [file("Windows/ServiceProfiles/LocalService/AppData/Local/Temp/a.dmp"),
                 file("Windows/ServiceProfiles/LocalService/AppData/Local/Temp/b.dmp"),
                 file("hiberfil.sys")]
        directories = [{"relative_path": "Windows", "subtree_bytes": 50 * GIB,
                        "coverage": "limited"},
                       {"relative_path": "Users/Test/AppData/Local/SomeApp/Cache",
                        "subtree_bytes": 2 * GIB, "coverage": "complete"}]
        with patch("builtins.open", side_effect=AssertionError("target opened")):
            first = self.engine.analyze(snapshot(), files, directories)
            second = self.engine.analyze(snapshot(), files, directories)
        self.assertEqual(first, second)
        groups = [item for item in first if item["object_type"] == "group"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["logical_bytes"], 4 * GIB)
        self.assertEqual(sum(item["group_id"] == groups[0]["candidate_id"] for item in first), 2)
        self.assertTrue(any(item["reason_code"] == "WINDOWS_MANAGED_DIRECTORY" for item in first))


class CandidatePersistenceAndApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "m5.db"
        self.snapshots = SnapshotStore(self.database)
        self.candidates = CandidateStore(self.snapshots)
        self.headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}",
                        "origin": LOCAL_ORIGIN}
        api_patch = patch("app.api.candidates.candidate_store", self.candidates)
        api_patch.start()
        self.addCleanup(api_patch.stop)

    def save(self, scan_id="one", limited=True):
        paths = ["hiberfil.sys", "pagefile.sys", "swapfile.sys",
                 "Windows/ServiceProfiles/LocalService/AppData/Local/Temp/a.dmp",
                 "Windows/ServiceProfiles/LocalService/AppData/Local/Temp/b.dmp",
                 "Users/Test/Downloads/large.iso",
                 "Users/Test/Documents/important.dmp",
                 "Users/Test/AppData/Local/SomeApp/Cache/cache.bin",
                 "Program Files/SomeApp/data.bin", "unknown/huge.bin"]
        files = [FileMetadata(Path(path).name, path, path.rpartition("/")[0],
                              2 * GIB, OLD) for path in paths]
        directories = {
            "": DirectoryStats("", None, subtree_bytes=len(files) * 2 * GIB,
                               file_count=len(files), children_count=1),
            "Windows": DirectoryStats("Windows", "", subtree_bytes=4 * GIB,
                                      file_count=2),
        }
        result = ScanResult(directories=directories, top_files=files,
                            files_seen=len(files), dirs_seen=2,
                            logical_bytes=len(files) * 2 * GIB,
                            errors_count=int(limited), skipped_count=int(limited),
                            limited_directories={"Windows"} if limited else set())
        status = {"scan_id": scan_id, "root": "system_drive_c", "state": "completed",
                  "started_at": COMPLETED, "finished_at": COMPLETED, "elapsed_ms": 100}
        return self.snapshots.save(status, result, Path("C:\\"))

    def call(self, method, path, body=None, query=""):
        return asyncio.run(request(method, path, body, self.headers, query))

    def test_v1_migration_preserves_snapshots_and_persists_latest_run(self):
        snapshot_id = self.save()
        # Controlled temporary database shaped like M3's v1 schema.
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("DROP TABLE cleanup_candidates")
            connection.execute("DROP TABLE candidate_runs")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
        first = self.candidates.analyze_snapshot(snapshot_id)
        second = CandidateStore(SnapshotStore(self.database)).analyze_snapshot(snapshot_id)
        self.assertEqual(first["run"]["run_id"], second["run"]["run_id"])
        self.assertEqual(first["run"]["analysis_coverage"], "top_k_and_directories")
        self.assertEqual(first["run"]["rule_version"], RULE_VERSION)
        self.assertEqual(first["run"]["snapshot_coverage"], "limited")
        self.assertEqual(self.snapshots.get(snapshot_id)["scope_key"], "system_drive_c")
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidate_runs").fetchone()[0], 1)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM cleanup_candidates").fetchone()[0], 0)
            self.assertTrue(connection.execute("SELECT evidence_json FROM cleanup_candidates LIMIT 1").fetchone()[0])

    def test_api_snapshot_only_summary_filters_detail_and_scope_isolation(self):
        snapshot_id = self.save()
        code, _, before = self.call("GET", "/api/v1/candidates")
        self.assertEqual((code, before["latest_snapshot"]["snapshot_id"], before["run"]),
                         (200, snapshot_id, None))
        with patch("app.tasks.manager.scan_fixture", side_effect=AssertionError("scanner called")):
            code, _, analyzed = self.call("POST", f"/api/v1/snapshots/{snapshot_id}/analyze")
        self.assertEqual(code, 200)
        self.assertEqual(analyzed["run"]["snapshot_id"], snapshot_id)
        code, _, listing = self.call("GET", "/api/v1/candidates")
        self.assertEqual(code, 200)
        self.assertGreater(listing["summary"]["candidate_count"], 0)
        self.assertEqual(listing["run"]["snapshot_coverage"], "limited")
        self.assertEqual(listing["run"]["analysis_coverage"], "top_k_and_directories")
        self.assertTrue(any(item["category"] == "hibernation_file" for item in listing["items"]))
        self.assertTrue(any(item["object_type"] == "group" for item in listing["items"]))
        code, _, filtered = self.call("GET", "/api/v1/candidates", query="scope_key=system_drive_c&risk=protected&category=hibernation_file&confidence=high")
        self.assertEqual((code, filtered["total"]), (200, 1))
        candidate_id = filtered["items"][0]["candidate_id"]
        code, _, detail = self.call("GET", f"/api/v1/candidates/{candidate_id}")
        self.assertEqual((code, detail["candidate"]["risk_level"]), (200, "protected"))
        code, _, _ = self.call("GET", f"/api/v1/candidates/{candidate_id}", query="scope_key=project_workspace")
        self.assertEqual(code, 404)
        code, _, _ = self.call("GET", "/api/v1/candidates", query="scope_key=invalid")
        self.assertEqual(code, 400)
        code, _, _ = self.call("POST", "/api/v1/snapshots/missing/analyze")
        self.assertEqual(code, 404)
        code, _, runs = self.call("GET", "/api/v1/candidate-runs")
        self.assertEqual((code, len(runs["items"])), (200, 1))

    def test_latest_snapshot_after_restart_is_independent_of_task_memory(self):
        first = self.save("first")
        self.candidates.analyze_snapshot(first)
        second = self.save("second")
        restarted = CandidateStore(SnapshotStore(self.database))
        latest = restarted.list_latest("system_drive_c")
        self.assertEqual(latest["latest_snapshot"]["snapshot_id"], second)
        self.assertEqual(latest["run"]["snapshot_id"], first)
        restarted.analyze_snapshot(second)
        self.assertEqual(restarted.list_latest("system_drive_c")["run"]["snapshot_id"], second)

    def test_candidate_run_cascades_when_old_snapshot_expires(self):
        first = self.save("first")
        self.candidates.analyze_snapshot(first)
        for index in range(20):
            self.save(f"later-{index}")
        self.assertEqual(len(self.snapshots.list("system_drive_c")), 20)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM candidate_runs WHERE snapshot_id = ?", (first,),
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cleanup_candidates").fetchone()[0], 0)

    def test_corrupt_db_returns_unavailable_without_scanner_work(self):
        self.database.write_bytes(b"not a sqlite database")
        with self.assertRaises(SnapshotStoreError):
            self.candidates.list_latest("system_drive_c")
        code, _, payload = self.call("GET", "/api/v1/candidates")
        self.assertEqual((code, payload["detail"]), (503, "SNAPSHOT_DATABASE_UNAVAILABLE"))
        with self.assertRaises(InvalidCandidateScope):
            self.candidates.list_latest("C:\\")


if __name__ == "__main__":
    unittest.main()
