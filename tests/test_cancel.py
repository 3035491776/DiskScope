import threading
import time
import unittest
from unittest.mock import patch

from app.scanner.models import ScanResult
from app.tasks.manager import ScanTaskManager
from tests.fixtures.generate_sample import generate_sample


class CancelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def test_cooperative_cancel_reaches_cancelled(self) -> None:
        manager = ScanTaskManager()
        started = threading.Event()

        def controlled_scan(root, cancel, on_progress):
            started.set()
            self.assertTrue(cancel.wait(timeout=3))
            return ScanResult(cancelled=True)

        with patch("app.tasks.manager.scan_fixture", side_effect=controlled_scan):
            created = manager.create("tests/fixtures/sample_disk")
            self.assertTrue(started.wait(timeout=3))
            cancelling = manager.cancel(created["scan_id"])
            self.assertEqual(cancelling["state"], "cancelling")
            for _ in range(300):
                latest = manager.status(created["scan_id"])
                if latest["state"] == "cancelled":
                    break
                time.sleep(0.01)
            self.assertEqual(latest["state"], "cancelled")
            self.assertTrue(latest["cancel_requested"])
            self.assertIsNotNone(latest["finished_at"])


if __name__ == "__main__":
    unittest.main()
