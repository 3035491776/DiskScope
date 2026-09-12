import unittest

from app.scanner.path_guard import InvalidScanRoot, validate_scan_root
from tests.fixtures.generate_sample import SAMPLE_ROOT, generate_sample


class PathBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def test_fixture_and_child_are_allowed(self) -> None:
        root, label = validate_scan_root("tests/fixtures/sample_disk")
        self.assertEqual(root, SAMPLE_ROOT.resolve())
        self.assertEqual(label, "tests/fixtures/sample_disk")
        child, _ = validate_scan_root("tests/fixtures/sample_disk/Nested")
        self.assertEqual(child, (SAMPLE_ROOT / "Nested").resolve())

    def test_escape_and_real_paths_are_rejected(self) -> None:
        for candidate in (
            "../../",
            "C:\\",
            "C:\\Users",
            "D:\\",
            "\\\\server\\share",
            "\\\\?\\C:\\Windows",
            str(SAMPLE_ROOT.parents[2]),
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(InvalidScanRoot):
                    validate_scan_root(candidate)

    def test_file_is_not_a_scan_root(self) -> None:
        with self.assertRaises(InvalidScanRoot):
            validate_scan_root(str(SAMPLE_ROOT / "Windows" / "system.bin"))


if __name__ == "__main__":
    unittest.main()
