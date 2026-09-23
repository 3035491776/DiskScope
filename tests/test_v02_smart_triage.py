"""v0.2 bounded smart triage classification, query, and safety tests."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path

from app.cleanup.categories import (
    CATEGORY_LABELS, EXTENSION_CATEGORY, category_for_name, is_blocked_extension,
    normalize_extension,
)
from app.cleanup.classification import (
    DO_NOT_TOUCH, REVIEW_REQUIRED, CleanupClassificationService, ManualReviewPolicy,
)
from app.cleanup.triage import TriageQuery, TriageQueryService, TriageSelectionError
from app.core.config import PROJECT_ROOT
from app.intelligence.store import CandidateNotFound
from app.scanner.models import ScanResult
from app.scanner.triage import TriageCollector, TriageFile
from app.snapshots.store import SnapshotStore


NOW = datetime.now(timezone.utc)


class SmartTriageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "triage.db"
        self.store = SnapshotStore(self.database)
        old = (NOW - timedelta(days=400)).isoformat()
        recent = (NOW - timedelta(days=10)).isoformat()
        files = [
            TriageFile("Users/Test/Downloads/MOVIE.MKV", "MOVIE.MKV", ".mkv", 6*1024**3, old, "video", "downloads", REVIEW_REQUIRED, 32),
            TriageFile("Users/Test/Downloads/archive.ZIP", "archive.ZIP", ".zip", 2*1024**3, old, "archive", "downloads", REVIEW_REQUIRED, 32),
            TriageFile("Users/Test/Documents/report.pdf", "report.pdf", ".pdf", 10*1024**2, recent, "document", "documents", REVIEW_REQUIRED, 32),
            TriageFile("Users/Test/Downloads/setup.exe", "setup.exe", ".exe", 700*1024**2, old, "installer", "downloads", DO_NOT_TOUCH, 32),
            TriageFile("Users/Test/Desktop/noextension", "noextension", "", 7, "", "other", "desktop", REVIEW_REQUIRED, 32),
        ]
        result = ScanResult(files_seen=5, dirs_seen=4, logical_bytes=sum(item.size_bytes for item in files),
                            triage_files=files, triage_observed_count=5,
                            triage_persisted_count=5, triage_coverage="complete",
                            triage_index_limit=100_000)
        status = {"scan_id": "triage", "root": "system_drive_c", "state": "completed",
                  "started_at": old, "finished_at": NOW.isoformat(), "elapsed_ms": 100}
        self.snapshot_id = self.store.save(status, result, Path("C:\\"))
        self.service = TriageQueryService(self.store)

    def test_all_extension_groups_case_unknown_and_no_extension(self):
        groups = {
            "video": "mp4 mkv avi mov wmv flv webm m4v ts mts m2ts 3gp mpg mpeg vob",
            "image": "jpg jpeg png gif bmp webp tif tiff heic heif svg ico raw cr2 cr3 nef arw dng orf rw2",
            "audio": "mp3 flac wav aac m4a ogg opus wma aiff ape",
            "document": "pdf doc docx xls xlsx ppt pptx txt rtf odt ods odp md epub mobi",
            "archive": "zip 7z rar tar gz tgz bz2 xz zst",
            "disk_image": "iso img vhd vhdx vmdk vdi qcow2",
            "backup": "bak backup old",
            "data": "db sqlite sqlite3 csv tsv json jsonl ndjson xml parquet feather avro",
            "diagnostic": "log trace etl dump dmp",
            "temporary": "tmp temp cache",
            "installer": "exe msi msp msix appx appxbundle dll sys drv com scr cmd bat ps1",
            "development": "py pyc js ts tsx jsx java class jar c cpp h cs go rs swift kt ipynb",
            "creative": "psd psb ai aep prproj blend c4d max fbx obj dwg dxf",
        }
        expected = {f".{extension}": category
                    for category, extensions in groups.items() for extension in extensions.split()}
        self.assertEqual(set(groups), set(CATEGORY_LABELS) - {"other"})
        self.assertEqual(EXTENSION_CATEGORY, expected)
        for extension, category in expected.items():
            with self.subTest(extension=extension):
                self.assertEqual(category_for_name("sample" + extension.upper()), category)
        self.assertEqual(category_for_name("README"), "other")
        self.assertEqual(category_for_name("sample.unlisted"), "other")
        self.assertEqual(normalize_extension(".ZIP"), ".zip")
        self.assertTrue(all(value.startswith(".") for value in EXTENSION_CATEGORY))

    def test_canonical_deny_extensions_never_become_review_authority(self):
        for extension in (".exe", ".dll", ".sys", ".ps1", ".bat", ".cmd", ".msi", ".dmp"):
            with self.subTest(extension=extension):
                self.assertTrue(is_blocked_extension(extension))
        result = self.service.query("system_drive_c", TriageQuery(
            extensions=(".exe",), classifications=(DO_NOT_TOUCH,), limit=50))
        self.assertEqual(result["matched_count"], 1)
        with self.assertRaises(TriageSelectionError) as caught:
            self.service.select_filtered("system_drive_c", TriageQuery(extensions=(".exe",)))
        self.assertEqual(caught.exception.code, "TRIAGE_PROTECTED_SELECTION_BLOCKED")

    def test_filters_sort_aggregates_facets_and_pagination(self):
        result = self.service.query("system_drive_c", TriageQuery(
            locations=("downloads",), categories=("video", "archive"),
            min_size=1024**3, older_than_days=180, classifications=(REVIEW_REQUIRED,),
            sort="mtime_asc", limit=25,
        ))
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["matched_bytes"], 8*1024**3)
        self.assertEqual([item["category"] for item in result["items"]], ["archive", "video"])
        category_facets = {item["value"]: (item["count"], item["bytes"])
                           for item in result["facets"]["category"]}
        self.assertEqual(category_facets["video"], (1, 6*1024**3))
        searched = self.service.query("system_drive_c", TriageQuery(
            extensions=("ZIP",), search="ARCHIVE", sort="name_asc", limit=25))
        self.assertEqual(searched["items"][0]["name"], "archive.ZIP")
        self.assertTrue(any(view["key"] == "large_old" and view["count"] >= 2
                            for view in searched["smart_views"]))

    def test_filtered_selection_requires_filter_and_refuses_over_cap(self):
        with self.assertRaises(TriageSelectionError) as caught:
            self.service.select_filtered("system_drive_c", TriageQuery(
                classifications=(REVIEW_REQUIRED,)))
        self.assertEqual(caught.exception.code, "TRIAGE_FILTER_REQUIRED")
        chosen = self.service.select_filtered("system_drive_c", TriageQuery(
            categories=("video",), classifications=(REVIEW_REQUIRED,)))
        self.assertEqual(chosen["matched_count"], 1)
        self.assertTrue(chosen["item_ids"][0].startswith("triage:"))

        many = [TriageFile(f"Users/Test/Downloads/a{i}.zip", f"a{i}.zip", ".zip", 1,
                           NOW.isoformat(), "archive", "downloads", REVIEW_REQUIRED, 32)
                for i in range(201)]
        result = ScanResult(files_seen=201, dirs_seen=1, logical_bytes=201,
                            triage_files=many, triage_observed_count=201,
                            triage_persisted_count=201, triage_coverage="complete",
                            triage_index_limit=100_000)
        status = {"scan_id": "many", "root": "system_drive_c", "state": "completed",
                  "started_at": NOW.isoformat(), "finished_at": (NOW+timedelta(seconds=1)).isoformat(),
                  "elapsed_ms": 100}
        self.store.save(status, result, Path("C:\\"))
        with self.assertRaises(TriageSelectionError) as caught:
            self.service.select_filtered("system_drive_c", TriageQuery(categories=("archive",)))
        self.assertEqual(caught.exception.code, "TRIAGE_SELECTION_TOO_LARGE")

    def test_triage_candidate_is_reloaded_server_side_and_filters_are_not_authority(self):
        service = CleanupClassificationService(
            self.store, review_policy=ManualReviewPolicy(user_profile="C:\\Users\\Test"))
        archive_id = self.service.query("system_drive_c", TriageQuery(
            extensions=(".zip",), limit=25))["items"][0]["item_id"]
        archive = service.candidate(archive_id, "system_drive_c")
        self.assertEqual(archive["logical_bytes"], 2*1024**3)
        self.assertEqual(service.decide(archive, "system_drive_c").classification, REVIEW_REQUIRED)
        executable_id = self.service.query("system_drive_c", TriageQuery(
            extensions=(".exe",), classifications=(DO_NOT_TOUCH,), limit=25))["items"][0]["item_id"]
        executable = service.candidate(executable_id, "system_drive_c")
        decision = service.decide(executable, "system_drive_c")
        self.assertEqual(decision.classification, DO_NOT_TOUCH)
        self.assertIn("EXECUTION_EXTENSION_BLOCKED", decision.reason_codes)

    def test_old_snapshot_is_honest_and_retention_cascades(self):
        old_result = ScanResult(files_seen=1, logical_bytes=1)
        status = {"scan_id": "old", "root": "system_drive_c", "state": "completed",
                  "started_at": NOW.isoformat(), "finished_at": (NOW+timedelta(seconds=1)).isoformat(),
                  "elapsed_ms": 100}
        old_id = self.store.save(status, old_result, Path("C:\\"))
        unavailable = self.service.query("system_drive_c", TriageQuery(limit=25))
        self.assertEqual(unavailable["snapshot_id"], old_id)
        self.assertFalse(unavailable["index_available"])
        classifications = CleanupClassificationService(self.store)
        with self.assertRaises(CandidateNotFound):
            classifications.candidate("triage:1", "system_drive_c")
        with self.store._connection() as connection:
            connection.execute("DELETE FROM scan_snapshots WHERE id=?", (self.snapshot_id,))
            connection.commit()
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM triage_files WHERE snapshot_id=?", (self.snapshot_id,)).fetchone()[0], 0)

    def test_bounded_hybrid_is_deterministic_and_invalid_time_not_oldest(self):
        collector = TriageCollector(Path("C:\\"), True, limit=4,
                                    root_map={"downloads": "Users/Test/Downloads"})
        timestamps = [1.0, 2.0, 3.0, 4.0, 5.0, 10**30]
        for index, timestamp in enumerate(timestamps):
            collector.add_observation(f"f{index}.zip", f"Users/Test/Downloads/f{index}.zip",
                                      "Users/Test/Downloads", index + 1, timestamp, 32)
        selected = collector.selected()
        self.assertEqual(collector.observed_count, 6)
        self.assertEqual(len(selected), 4)
        self.assertIn("Users/Test/Downloads/f5.zip", {item.relative_path for item in selected})
        invalid = next(item for item in selected if item.relative_path.endswith("f5.zip"))
        self.assertEqual(invalid.mtime, "")

        for index in range(5000):
            collector.add_observation("outside.bin", f"Windows/X{index}/outside.bin",
                                      f"Windows/X{index}", 1, 1.0, 32)
        self.assertLessEqual(len(collector._parent_locations), 4096)

    def test_v7_to_v8_migration_integrity(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("DROP TABLE triage_files")
            connection.execute("PRAGMA user_version = 7")
            connection.commit()
        self.store.list()
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
