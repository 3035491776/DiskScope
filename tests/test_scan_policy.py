import builtins
import hashlib
import os
import shutil
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scanner.policy import SCAN_POLICY, ScanPolicy
from app.scanner.service import scan_fixture
from tests.fixtures.generate_sample import SAMPLE_ROOT, generate_sample


class ScanPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def test_standard_is_the_only_safe_policy(self) -> None:
        self.assertEqual(SCAN_POLICY.mode, "standard")
        self.assertEqual(SCAN_POLICY.concurrency, 1)
        self.assertEqual(SCAN_POLICY.max_active_scans, 1)
        self.assertFalse(SCAN_POLICY.follow_reparse_points)
        self.assertFalse(SCAN_POLICY.allow_cross_volume)
        self.assertFalse(SCAN_POLICY.read_file_contents)
        self.assertFalse(SCAN_POLICY.hash_files)
        for field, value in (("mode", "fast"), ("concurrency", 2), ("hash_files", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ScanPolicy(**{field: value})

    def test_scanner_uses_no_content_hash_or_mutation_apis(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("Scanner attempted a forbidden target operation")

        with (
            patch.object(builtins, "open", side_effect=forbidden),
            patch.object(Path, "open", side_effect=forbidden),
            patch.object(Path, "read_bytes", side_effect=forbidden),
            patch.object(hashlib, "sha256", side_effect=forbidden),
            patch.object(os, "remove", side_effect=forbidden),
            patch.object(os, "unlink", side_effect=forbidden),
            patch.object(os, "rename", side_effect=forbidden),
            patch.object(shutil, "move", side_effect=forbidden),
        ):
            result = scan_fixture(SAMPLE_ROOT, threading.Event())
        self.assertEqual(result.files_seen, 10)


if __name__ == "__main__":
    unittest.main()
