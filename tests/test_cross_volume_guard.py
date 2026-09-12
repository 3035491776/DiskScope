import stat
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.scanner.service import scan_fixture
from app.scanner.volume_guard import same_scan_volume
from tests.fixtures.generate_sample import FIXTURES


class CrossVolumeGuardTests(unittest.TestCase):
    def test_windows_drive_and_network_boundaries(self) -> None:
        root = Path(r"D:\Artilius\Codex\Windows-C-clear\tests\fixtures")
        self.assertTrue(same_scan_volume(root, root / "child"))
        for path in (Path("C:/simulated"), Path("E:/simulated"), Path("//server/share/simulated")):
            with self.subTest(path=path):
                self.assertFalse(same_scan_volume(root, path))

    def test_reparse_and_other_volume_entries_are_never_followed(self) -> None:
        with TemporaryDirectory(dir=FIXTURES) as temporary:
            root = Path(temporary)

            class FakeEntry:
                def __init__(self, name: str, path: str) -> None:
                    self.name = name
                    self.path = path
                    self.stat_called = False

                def stat(self, follow_symlinks=False):
                    self.stat_called = True
                    return SimpleNamespace(
                        st_mode=stat.S_IFDIR,
                        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
                    )

            entries = [
                FakeEntry("to_c", r"C:\simulated"),
                FakeEntry("to_e", r"E:\simulated"),
                FakeEntry("to_network", r"\\server\share\simulated"),
                FakeEntry("to_other_d", r"D:\outside_fixture\simulated"),
            ]

            @contextmanager
            def fake_scandir(path):
                self.assertEqual(Path(path), root)
                yield entries

            with patch("app.scanner.enumerator.os.scandir", side_effect=fake_scandir):
                result = scan_fixture(root, threading.Event())
            self.assertEqual(result.dirs_seen, 1)
            self.assertEqual(result.files_seen, 0)
            self.assertEqual(result.skipped_count, 4)
            self.assertEqual(result.errors["CROSS_VOLUME_SKIPPED"]["count"], 3)
            self.assertEqual(result.errors["REPARSE_POINT_SKIPPED"]["count"], 1)
            self.assertFalse(any(entry.stat_called for entry in entries[:3]))


if __name__ == "__main__":
    unittest.main()
