import errno
import os
import stat
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.scanner.service import scan_fixture
from app.tasks.manager import ScanTaskManager
from tests.fixtures.generate_sample import FIXTURES, MEDIUM_ROOT, SAMPLE_ROOT, generate_medium, generate_sample


class RealworldBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def test_reparse_point_is_skipped_without_following(self) -> None:
        with TemporaryDirectory(dir=FIXTURES) as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            (target / "inside.bin").write_bytes(b"a")
            link = root / "safe_link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except OSError:
                # Some Windows hosts cannot create symlinks. Simulate the OS reparse flag.
                link.mkdir()
                (link / "must_not_enter.bin").write_bytes(b"b")
                real_scandir = os.scandir

                class MarkedEntry:
                    def __init__(self, entry):
                        self.name = entry.name
                        self.path = entry.path
                        self.entry = entry

                    def stat(self, follow_symlinks=False):
                        info = self.entry.stat(follow_symlinks=follow_symlinks)
                        return SimpleNamespace(
                            st_mode=info.st_mode,
                            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
                        )

                @contextmanager
                def marked_scandir(path):
                    with real_scandir(path) as entries:
                        if Path(path) == root:
                            yield (MarkedEntry(entry) if entry.name == "safe_link" else entry
                                   for entry in entries)
                        else:
                            yield entries

                with patch("app.scanner.enumerator.os.scandir", side_effect=marked_scandir):
                    result = scan_fixture(root, threading.Event())
            else:
                result = scan_fixture(root, threading.Event())
            self.assertEqual(result.errors["REPARSE_POINT_SKIPPED"]["count"], 1)
            self.assertEqual(result.files_seen, 1)
            self.assertNotIn("safe_link", result.directories)
            self.assertEqual(result.skipped_count, 1)

    def test_file_removed_by_fixture_harness_is_recorded_and_scan_continues(self) -> None:
        with TemporaryDirectory(dir=FIXTURES) as temporary:
            root = Path(temporary)
            missing = root / "vanish.bin"
            missing.write_bytes(b"x")
            (root / "survive.bin").write_bytes(b"y")
            ready = threading.Event()
            removed = threading.Event()
            real_scandir = os.scandir

            def remove_fixture_file() -> None:
                if ready.wait(5):
                    missing.unlink()  # Test harness only, inside tests/fixtures.
                    removed.set()

            @contextmanager
            def race_scandir(path: Path):
                with real_scandir(path) as entries:
                    if Path(path) != root:
                        yield entries
                    else:
                        class FreshEntry:
                            def __init__(self, entry):
                                self.name = entry.name
                                self.path = entry.path

                            def stat(self, follow_symlinks=False):
                                # Windows DirEntry may cache metadata; require a fresh OS stat.
                                return os.stat(self.path, follow_symlinks=follow_symlinks)

                        def iter_with_race():
                            for entry in entries:
                                if entry.name == "vanish.bin":
                                    ready.set()
                                    if not removed.wait(5):
                                        raise AssertionError("Fixture deletion did not occur")
                                    yield FreshEntry(entry)
                                else:
                                    yield entry
                        yield iter_with_race()

            worker = threading.Thread(target=remove_fixture_file)
            worker.start()
            try:
                with patch("app.scanner.enumerator.os.scandir", side_effect=race_scandir):
                    result = scan_fixture(root, threading.Event())
            finally:
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result.errors["FILE_NOT_FOUND"]["count"], 1)
            self.assertEqual(result.files_seen, 1)
            self.assertEqual(result.top_files[0].name, "survive.bin")

    def test_long_path_os_error_is_recorded_and_scan_continues(self) -> None:
        real_scandir = os.scandir

        def simulated_long_path(path):
            if Path(path).name == "Nested":
                raise OSError(errno.ENAMETOOLONG, "synthetic long path")
            return real_scandir(path)

        with patch("app.scanner.enumerator.os.scandir", side_effect=simulated_long_path):
            result = scan_fixture(SAMPLE_ROOT, threading.Event())
        self.assertEqual(result.errors["PATH_TOO_LONG"]["count"], 1)
        self.assertGreater(result.files_seen, 0)
        self.assertEqual(result.skipped_count, 1)

    def test_cancel_medium_scan_then_start_another_without_worker(self) -> None:
        generate_medium()
        manager = ScanTaskManager()
        milestone = threading.Event()
        resume = threading.Event()
        real_scan = scan_fixture

        def gated_scan(root, cancel, on_progress):
            def progress(result):
                on_progress(result)
                if result.dirs_seen >= 3 and not milestone.is_set():
                    milestone.set()
                    if not resume.wait(5):
                        raise AssertionError("Cancel test gate timed out")
            return real_scan(root, cancel, progress)

        with patch("app.tasks.manager.scan_fixture", side_effect=gated_scan):
            first = manager.create(str(MEDIUM_ROOT))
            self.assertTrue(milestone.wait(5))
            self.assertEqual(manager.status(first["scan_id"])["state"], "running")
            self.assertEqual(manager.cancel(first["scan_id"])["state"], "cancelling")
            resume.set()
            self._wait_for_state(manager, first["scan_id"], "cancelled")

        frozen_metrics = manager.status(first["scan_id"])["metrics"]
        time.sleep(0.05)
        self.assertEqual(manager.status(first["scan_id"])["metrics"], frozen_metrics)
        self.assertFalse(any(
            thread.name == "diskscope-approved-scan" and thread.is_alive()
            for thread in threading.enumerate()
        ))
        second = manager.create(str(SAMPLE_ROOT))
        self._wait_for_state(manager, second["scan_id"], "completed")

    @staticmethod
    def _wait_for_state(manager: ScanTaskManager, scan_id: str, target: str) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = manager.status(scan_id)["state"]
            if state == target:
                return
            if state == "failed":
                raise AssertionError("Scan unexpectedly failed")
            time.sleep(0.01)
        raise AssertionError(f"Scan did not reach {target}")


if __name__ == "__main__":
    unittest.main()
