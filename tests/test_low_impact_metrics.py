import unittest
import time
from pathlib import Path
from unittest.mock import patch

from app.scanner.metrics import ProcessSample, ScanResourceMonitor
from app.tasks.manager import ScanTask


class LowImpactMetricsTests(unittest.TestCase):
    def test_process_deltas_and_observed_peak(self) -> None:
        before = ProcessSample(100, 2.0, 200, 300, 4, 5)
        during = ProcessSample(rss_bytes=150)
        after = ProcessSample(120, 2.5, 1200, 340, 14, 6)
        with patch("app.scanner.metrics.read_process_sample", side_effect=[before, during, after]):
            monitor = ScanResourceMonitor()
            monitor.sample(force=True)
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

    def test_running_current_and_peak_then_terminal_freeze(self) -> None:
        samples = [ProcessSample(100, 1.0), ProcessSample(140, 1.2),
                   ProcessSample(120, 1.5), ProcessSample(125, 1.6)]
        with patch("app.scanner.metrics.read_process_sample", side_effect=samples):
            monitor = ScanResourceMonitor()
            monitor.sample(force=True)
            running = monitor.snapshot(files=20, duration_ms=2000)
            self.assertEqual((running["rss_current_bytes"], running["rss_peak_observed_bytes"]), (140, 140))
            self.assertAlmostEqual(running["cpu_seconds"], 0.2)
            self.assertEqual(running["files_per_second"], 10.0)
            monitor.sample(force=True)
            later = monitor.snapshot(files=30, duration_ms=3000)
            self.assertEqual((later["rss_current_bytes"], later["rss_peak_observed_bytes"]), (120, 140))
            self.assertGreaterEqual(later["cpu_seconds"], running["cpu_seconds"])
            final = monitor.finish(files=40, duration_ms=4000)
            self.assertEqual((final["rss_current_bytes"], final["rss_peak_observed_bytes"]), (125, 140))

    def test_metrics_provider_failure_is_isolated(self) -> None:
        with patch("app.scanner.metrics.read_process_sample", side_effect=OSError("counter unavailable")):
            monitor = ScanResourceMonitor()
            self.assertIsNone(monitor.snapshot(1, 1000, force=True)["rss_current_bytes"])
            self.assertIsNone(monitor.finish(1, 1000)["cpu_seconds"])

    def test_task_status_updates_while_running_and_freezes_after_terminal_state(self) -> None:
        for state in ("completed", "cancelled"):
            with self.subTest(state=state), patch("app.scanner.metrics.read_process_sample",
                                                 side_effect=[ProcessSample(100, 1.0),
                                                              ProcessSample(150, 1.2),
                                                              ProcessSample(120, 1.3)]):
                monitor = ScanResourceMonitor()
                task = ScanTask("test", "fixture", Path("tests/fixtures"), state="running",
                                started_clock=time.monotonic() - 2, files_seen=20, monitor=monitor)
                monitor.sample(force=True)
                running = task.public_status()
                self.assertGreater(running["metrics"]["duration_ms"], 1000)
                self.assertEqual(running["metrics"]["rss_current_bytes"], 150)
                self.assertGreater(running["metrics"]["files_per_second"], 0)
                task.state = state
                task.finished_clock = time.monotonic()
                task.metrics = monitor.finish(20, 2000)
                task.monitor = None
                first = task.public_status()["metrics"]
                second = task.public_status()["metrics"]
                self.assertEqual(first, second)
                self.assertEqual(first["rss_peak_observed_bytes"], 150)


if __name__ == "__main__":
    unittest.main()
