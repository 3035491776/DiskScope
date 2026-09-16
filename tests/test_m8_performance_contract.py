import threading
import unittest
from unittest.mock import patch

from app.scanner.models import DirectoryStats, FileMetadata
from app.scanner.service import scan_fixture
from tests.fixtures.generate_sample import MEDIUM_ROOT, generate_medium


class M8PerformanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_medium()

    def test_root_authorization_is_not_repeated_per_directory(self) -> None:
        from app.scanner import path_guard

        with patch.object(
            path_guard, "validate_scan_root", wraps=path_guard.validate_scan_root
        ) as validate:
            result = scan_fixture(MEDIUM_ROOT, threading.Event())
        self.assertEqual(result.dirs_seen, 1_001)
        self.assertEqual(validate.call_count, 1)

    def test_progress_is_batched_after_early_cancel_window(self) -> None:
        updates: list[tuple[int, int]] = []
        result = scan_fixture(
            MEDIUM_ROOT,
            threading.Event(),
            lambda current: updates.append((current.files_seen, current.dirs_seen)),
        )
        self.assertEqual(result.files_seen, 10_000)
        self.assertTrue(any(directories >= 3 for _, directories in updates[:4]))
        self.assertLess(len(updates), 100)
        self.assertEqual(updates[-1], (10_000, 1_001))

    def test_high_cardinality_metadata_models_use_slots(self) -> None:
        self.assertFalse(hasattr(DirectoryStats("", None), "__dict__"))
        self.assertFalse(hasattr(FileMetadata("a", "a", "", 1, "now"), "__dict__"))


if __name__ == "__main__":
    unittest.main()
