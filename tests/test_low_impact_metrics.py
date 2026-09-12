import unittest
from unittest.mock import patch

from app.scanner.metrics import ProcessSample, ScanResourceMonitor


class LowImpactMetricsTests(unittest.TestCase):
    def test_process_deltas_and_observed_peak(self) -> None:
        before = ProcessSample(100, 2.0, 200, 300, 4, 5)
        during = ProcessSample(rss_bytes=150)
        after = ProcessSample(120, 2.5, 1200, 340, 14, 6)
        with patch("app.scanner.metrics.read_process_sample", side_effect=[before, during, after]):
            monitor = ScanResourceMonitor()
            monitor.sample()
            result = monitor.finish(files=10, duration_ms=2000)
        self.assertEqual(result["rss_peak_observed_bytes"], 150)
        self.assertEqual(result["files_per_second"], 5.0)
        self.assertEqual(result["cpu_seconds"], 0.5)
        self.assertEqual(result["delta_read_bytes"], 1000)
        self.assertEqual(result["delta_write_bytes"], 40)
        self.assertEqual(result["delta_read_operations"], 10)
        self.assertEqual(result["delta_write_operations"], 1)

    def test_unavailable_counters_remain_unavailable(self) -> None:
        with patch("app.scanner.metrics.read_process_sample", return_value=ProcessSample()):
            monitor = ScanResourceMonitor()
            result = monitor.finish(files=0, duration_ms=100)
        for field in (
            "rss_peak_observed_bytes", "cpu_seconds", "delta_read_bytes",
            "delta_write_bytes", "delta_read_operations", "delta_write_operations",
        ):
            self.assertIsNone(result[field])


if __name__ == "__main__":
    unittest.main()
