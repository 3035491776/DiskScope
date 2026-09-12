import unittest
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.scanner.path_guard import InvalidScanRoot, PROJECT_ROOT_LABEL, validate_scan_root


class RealRootPolicyTests(unittest.TestCase):
    def test_only_exact_project_root_is_allowed(self) -> None:
        root, label = validate_scan_root(str(PROJECT_ROOT))
        self.assertEqual(root, PROJECT_ROOT)
        self.assertEqual(label, PROJECT_ROOT_LABEL)

        for candidate in (
            str(PROJECT_ROOT.parent),
            str(PROJECT_ROOT / "backend"),
            "D:\\",
            "C:\\",
            "\\\\server\\share",
            "\\\\?\\D:\\Artilius\\Codex\\Windows-C-clear",
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(InvalidScanRoot):
                    validate_scan_root(candidate)

    def test_reparse_project_root_is_rejected(self) -> None:
        with patch("app.scanner.path_guard.is_reparse_point", return_value=True):
            with self.assertRaises(InvalidScanRoot):
                validate_scan_root(str(PROJECT_ROOT))


if __name__ == "__main__":
    unittest.main()
