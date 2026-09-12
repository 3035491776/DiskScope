import hashlib
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scanner.service import scan_fixture
from tests.fixtures.generate_sample import (
    EXPECTED_SAMPLE_BYTES,
    EXPECTED_SAMPLE_DIRS,
    EXPECTED_SAMPLE_FILES,
    SAMPLE_ROOT,
    generate_sample,
)


def fixture_fingerprint(root: Path) -> tuple[tuple[object, ...], ...]:
    """Test harness only: read file content to prove the scanner changed nothing."""
    entries: list[tuple[object, ...]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            entries.append(("directory", relative))
        else:
            info = path.stat()
            entries.append(
                (
                    "file", relative, info.st_size, info.st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return tuple(entries)


class ScannerFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def test_expected_counts_and_read_only_fingerprint(self) -> None:
        before = fixture_fingerprint(SAMPLE_ROOT)
        result = scan_fixture(SAMPLE_ROOT, threading.Event())
        after = fixture_fingerprint(SAMPLE_ROOT)
        self.assertEqual(before, after)
        self.assertEqual(result.files_seen, EXPECTED_SAMPLE_FILES)
        self.assertEqual(result.dirs_seen, EXPECTED_SAMPLE_DIRS)
        self.assertEqual(result.logical_bytes, EXPECTED_SAMPLE_BYTES)
        self.assertEqual(result.directories[""].subtree_bytes, EXPECTED_SAMPLE_BYTES)
        self.assertEqual(result.directories[""].file_count, EXPECTED_SAMPLE_FILES)
        self.assertEqual(result.directories["Nested/A"].direct_bytes, 10 * 1024)
        self.assertEqual(result.directories["Nested/A"].subtree_bytes, 14 * 1024)
        self.assertEqual(result.directories["EmptyDir"].subtree_bytes, 0)
        self.assertEqual(result.top_files[-1].size_bytes, 0)
        self.assertEqual(result.errors_count, 0)

    def test_child_errors_are_counted_and_scan_continues(self) -> None:
        real_scandir = os.scandir

        def controlled_scandir(path: Path):
            if Path(path).name == "Windows":
                raise PermissionError("synthetic access denied")
            if Path(path).name == "EmptyDir":
                raise FileNotFoundError("synthetic disappearance")
            return real_scandir(path)

        with patch("app.scanner.enumerator.os.scandir", side_effect=controlled_scandir):
            result = scan_fixture(SAMPLE_ROOT, threading.Event())
        self.assertEqual(result.errors["ACCESS_DENIED"]["count"], 1)
        self.assertEqual(result.errors["FILE_NOT_FOUND"]["count"], 1)
        self.assertEqual(result.skipped_count, 2)
        self.assertGreater(result.files_seen, 0)
        self.assertEqual(result.dirs_seen, EXPECTED_SAMPLE_DIRS)

    def test_real_scanner_loop_honors_cancel_flag(self) -> None:
        cancel = threading.Event()

        def stop_after_a_few_directories(result) -> None:
            if result.dirs_seen >= 3:
                cancel.set()

        result = scan_fixture(SAMPLE_ROOT, cancel, stop_after_a_few_directories)
        self.assertTrue(result.cancelled)
        self.assertLess(result.dirs_seen, EXPECTED_SAMPLE_DIRS)
        self.assertEqual(result.errors["CANCELLED"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
