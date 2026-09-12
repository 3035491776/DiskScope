import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import PROJECT_ROOT
from app.scanner.exclusions import project_exclusion
from app.scanner.service import scan_fixture


class ExclusionsTests(unittest.TestCase):
    def test_rules_match_path_components(self) -> None:
        expected = {
            ".git": ".git",
            ".venv": ".venv",
            "frontend/node_modules": "frontend/node_modules",
            "frontend/dist": "frontend/dist",
            "logs": "logs",
            "data": "data",
        }
        for path, rule in expected.items():
            with self.subTest(path=path):
                self.assertEqual(project_exclusion(path), rule)
                self.assertEqual(project_exclusion(path + "/child"), rule)
        for path in (".github", ".gitkeep", ".venvs", "frontend/node_modules_extra", "data.txt"):
            with self.subTest(path=path):
                self.assertIsNone(project_exclusion(path))
        self.assertEqual(project_exclusion("FRONTEND/Node_Modules/pkg"), "frontend/node_modules")

    def test_project_scan_does_not_enter_excluded_directories(self) -> None:
        blocked = {PROJECT_ROOT / path for path in (
            ".git", ".venv", "frontend/node_modules", "frontend/dist", "logs", "data",
        )}
        real_scandir = __import__("os").scandir
        seen: list[Path] = []

        def guarded_scandir(path: Path):
            resolved = Path(path)
            seen.append(resolved)
            if any(resolved == excluded or excluded in resolved.parents for excluded in blocked):
                raise AssertionError(f"Excluded path was entered: {resolved}")
            return real_scandir(path)

        with patch("app.scanner.enumerator.os.scandir", side_effect=guarded_scandir):
            result = scan_fixture(PROJECT_ROOT, threading.Event())
        self.assertIn(PROJECT_ROOT, seen)
        for path in blocked:
            if path.exists():
                rule = path.relative_to(PROJECT_ROOT).as_posix()
                self.assertIn(rule, result.exclusions)
        self.assertGreaterEqual(result.skipped_count, len(result.exclusions))


if __name__ == "__main__":
    unittest.main()
