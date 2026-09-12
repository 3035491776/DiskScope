import unittest
from pathlib import Path

from app.api.scans import _api_error
from app.core.config import PROJECT_ROOT
from app.scanner.path_guard import InvalidScanRoot, validate_scan_root
from app.scanner.whole_volume_gate import (
    WHOLE_VOLUME_SCAN_NOT_APPROVED, WholeVolumeScanDenied,
    can_scan_whole_volume,
)
from tests.fixtures.generate_sample import SAMPLE_ROOT, generate_sample


class WholeVolumeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def test_every_whole_volume_root_has_a_dedicated_denial(self) -> None:
        for raw in ("C:\\", "D:\\", "E:\\"):
            with self.subTest(raw=raw):
                self.assertFalse(can_scan_whole_volume(Path(raw)))
                with self.assertRaises(WholeVolumeScanDenied) as caught:
                    validate_scan_root(raw)
                self.assertEqual(caught.exception.code, WHOLE_VOLUME_SCAN_NOT_APPROVED)
                self.assertEqual(_api_error(caught.exception).detail, WHOLE_VOLUME_SCAN_NOT_APPROVED)

    def test_approved_roots_remain_available_and_network_is_rejected(self) -> None:
        self.assertEqual(validate_scan_root(str(PROJECT_ROOT))[0], PROJECT_ROOT)
        self.assertEqual(validate_scan_root(str(SAMPLE_ROOT))[0], SAMPLE_ROOT)
        for raw in ("\\\\server\\share", "D:", "\\\\?\\C:\\"):
            with self.subTest(raw=raw), self.assertRaises(InvalidScanRoot):
                validate_scan_root(raw)


if __name__ == "__main__":
    unittest.main()
