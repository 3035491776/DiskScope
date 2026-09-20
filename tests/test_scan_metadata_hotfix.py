"""Regression coverage for invalid real-world filesystem metadata."""

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.scanner.enumerator import DirectorySeen, FileSeen, RootUnavailable
from app.scanner.service import scan_fixture
from app.scanner.topk import BoundedHybridFiles, TopKFiles
from app.snapshots.store import SnapshotStore
from app.tasks.manager import ScanTaskManager
from tests.fixtures.generate_sample import SAMPLE_ROOT, generate_sample


INVALID_MTIME = 1e30


def wait_for_terminal(manager: ScanTaskManager, scan_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = manager.status(scan_id)
        if status["state"] in {"completed", "cancelled", "failed"}:
            if status["snapshot_status"] != "pending":
                return status
        time.sleep(0.01)
    raise AssertionError("scan did not reach a terminal state")


class InvalidMetadataHotfixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    @staticmethod
    def events():
        return iter((
            DirectorySeen("", None),
            FileSeen("before.bin", "before.bin", "", 5, 10, None),
            FileSeen("invalid.bin", "invalid.bin", "", 100, INVALID_MTIME, None),
            FileSeen("after-one.bin", "after-one.bin", "", 10, 20, None),
            FileSeen("after-two.bin", "after-two.bin", "", 20, 30, None),
        ))

    def test_invalid_timestamp_is_a_bounded_warning_and_scan_snapshot_complete(self) -> None:
        with TemporaryDirectory(dir=PROJECT_ROOT / "data") as temporary:
            store = SnapshotStore(Path(temporary) / "metadata-hotfix.db")
            manager = ScanTaskManager(store)
            with patch("app.scanner.service.enumerate_metadata", return_value=self.events()):
                created = manager.create(str(SAMPLE_ROOT))
                status = wait_for_terminal(manager, created["scan_id"])

            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["snapshot_status"], "saved")
            self.assertEqual(status["files_seen"], 4)
            self.assertEqual(status["logical_bytes"], 135)
            self.assertEqual(status["skipped_count"], 0)
            self.assertEqual(status["metadata_warning_count"], 1)
            self.assertEqual(status["errors_count"], 1)
            self.assertEqual(status["coverage"], "limited")
            self.assertEqual(
                status["errors"]["INVALID_FILE_METADATA"],
                {"count": 1, "samples": ["invalid.bin"]},
            )
            result = manager.result(created["scan_id"])
            self.assertEqual(result.directories[""].file_count, 4)
            self.assertEqual(result.directories[""].subtree_bytes, 135)
            self.assertEqual(result.top_files[0].relative_path, "invalid.bin")
            self.assertEqual(result.top_files[0].mtime, "")
            snapshot = store.get(str(status["snapshot_id"]))
            self.assertEqual(snapshot["file_count"], 4)
            self.assertEqual(snapshot["total_bytes"], 135)
            self.assertEqual(snapshot["error_count"], 1)
            self.assertEqual(snapshot["skipped_count"], 0)
            self.assertEqual(snapshot["coverage"], "limited")

    def test_invalid_timestamp_remains_in_size_top_k(self) -> None:
        top = TopKFiles(2)
        self.assertFalse(top.add_observation(
            "invalid.bin", "invalid.bin", "", 100, INVALID_MTIME, None))
        self.assertTrue(top.add_observation("later.bin", "later.bin", "", 50, 20, None))
        self.assertEqual(
            [(item.relative_path, item.size_bytes, item.mtime) for item in top.sorted_files()],
            [("invalid.bin", 100, ""), ("later.bin", 50, "1970-01-01T00:00:20+00:00")],
        )

    def test_temp_hybrid_excludes_invalid_time_from_oldest_but_keeps_hard_cap(self) -> None:
        observations = (
            ("invalid", 100, INVALID_MTIME),
            ("large", 90, 50),
            ("oldest", 1, 1),
            ("second-oldest", 2, 2),
            ("middle", 80, 30),
        )

        def selected(rows):
            hybrid = BoundedHybridFiles(4)
            outcomes = {}
            for path, size, mtime in rows:
                outcomes[path] = hybrid.add_observation(path, path, "", size, mtime, None)
            return outcomes, hybrid.selected_files(len(observations))

        forward_outcomes, forward = selected(observations)
        reverse_outcomes, reverse = selected(reversed(observations))
        expected = {"invalid", "large", "oldest", "second-oldest"}
        self.assertFalse(forward_outcomes["invalid"])
        self.assertFalse(reverse_outcomes["invalid"])
        self.assertEqual({item.relative_path for item in forward}, expected)
        self.assertEqual([item.relative_path for item in forward],
                         [item.relative_path for item in reverse])
        self.assertEqual(len(forward), 4)

    def test_unexpected_internal_error_still_fails_and_logs_context(self) -> None:
        manager = ScanTaskManager()
        with patch("app.tasks.manager.logging.exception") as logged, patch(
            "app.tasks.manager.scan_fixture", side_effect=KeyError("synthetic defect")
        ):
            created = manager.create(str(SAMPLE_ROOT))
            status = wait_for_terminal(manager, created["scan_id"])
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["error_code"], "INTERNAL_ERROR")
        logged.assert_called_once()
        self.assertEqual(logged.call_args.args[1], created["scan_id"])
        self.assertEqual(logged.call_args.args[4:], ("KeyError", "'synthetic defect'"))

    def test_root_and_unhandled_io_errors_remain_fatal(self) -> None:
        for failure, code in (
            (RootUnavailable("root unavailable"), "INVALID_PATH"),
            (OSError("unhandled I/O"), "IO_ERROR"),
        ):
            with self.subTest(code=code):
                manager = ScanTaskManager()
                with patch("app.tasks.manager.logging.exception"), patch(
                    "app.tasks.manager.scan_fixture", side_effect=failure
                ):
                    created = manager.create(str(SAMPLE_ROOT))
                    status = wait_for_terminal(manager, created["scan_id"])
                self.assertEqual(status["state"], "failed")
                self.assertEqual(status["error_code"], code)


if __name__ == "__main__":
    unittest.main()
