import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from app.scanner.models import ScanResult
from app.security.session import LOCAL_ORIGIN, local_session
from app.tasks.manager import ScanTaskManager
from tests.asgi_client import request
from tests.fixtures.generate_sample import (
    EXPECTED_SAMPLE_BYTES,
    EXPECTED_SAMPLE_DIRS,
    EXPECTED_SAMPLE_FILES,
    generate_sample,
)


class ApiScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()
        status, headers, _ = asyncio.run(
            request(
                "POST", "/api/v1/session/bootstrap",
                {"token": local_session.bootstrap_token},
                {"origin": LOCAL_ORIGIN},
            )
        )
        assert status == 204
        cls.cookie = headers["set-cookie"].split(";", 1)[0]

    def setUp(self) -> None:
        self.manager_patch = patch("app.api.scans.scan_tasks", new=ScanTaskManager())
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)

    def call(self, method: str, path: str, body=None, query: str = ""):
        return asyncio.run(
            request(
                method, path, body,
                {"cookie": self.cookie, "origin": LOCAL_ORIGIN}, query,
            )
        )

    def test_fixture_scan_and_results(self) -> None:
        status, _, created = self.call(
            "POST", "/api/v1/scans", {"root": "tests/fixtures/sample_disk"}
        )
        self.assertEqual(status, 202)
        scan_id = created["scan_id"]
        for _ in range(300):
            status, _, state = self.call("GET", f"/api/v1/scans/{scan_id}")
            self.assertEqual(status, 200)
            if state["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        self.assertEqual(state["state"], "completed")
        self.assertEqual(state["files_seen"], EXPECTED_SAMPLE_FILES)
        self.assertEqual(state["dirs_seen"], EXPECTED_SAMPLE_DIRS)
        self.assertEqual(state["logical_bytes"], EXPECTED_SAMPLE_BYTES)
        self.assertEqual(state["root"], "tests/fixtures/sample_disk")

        status, _, top = self.call("GET", f"/api/v1/scans/{scan_id}/top", query="kind=file&limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(len(top["items"]), 10)
        self.assertEqual(top["items"][0]["size_bytes"], 5 * 1024 * 1024)
        self.assertFalse(any(item["relative_path"].startswith("D:") for item in top["items"]))

        status, _, directories = self.call("GET", f"/api/v1/scans/{scan_id}/directories")
        self.assertEqual(status, 200)
        by_path = {item["relative_path"]: item for item in directories["items"]}
        self.assertEqual(by_path["Nested"]["subtree_bytes"], 15 * 1024)
        self.assertEqual(by_path["EmptyDir"]["subtree_bytes"], 0)

    def test_forbidden_roots_and_missing_session(self) -> None:
        for root in ("C:\\", "C:\\Users", "\\\\server\\share", "../../"):
            with self.subTest(root=root):
                status, _, _ = self.call("POST", "/api/v1/scans", {"root": root})
                self.assertEqual(status, 403)
        status, _, _ = asyncio.run(
            request(
                "POST", "/api/v1/scans",
                {"root": "tests/fixtures/sample_disk"},
                {"origin": LOCAL_ORIGIN},
            )
        )
        self.assertEqual(status, 401)
        status, _, _ = asyncio.run(
            request(
                "POST", "/api/v1/scans",
                {"root": "tests/fixtures/sample_disk"},
                {"cookie": self.cookie, "origin": "http://example.invalid"},
            )
        )
        self.assertEqual(status, 403)

    def test_second_active_scan_returns_409(self) -> None:
        started = threading.Event()

        def controlled_scan(root, cancel, on_progress):
            started.set()
            cancel.wait(timeout=3)
            return ScanResult(cancelled=True)

        with patch("app.tasks.manager.scan_fixture", side_effect=controlled_scan):
            status, _, first = self.call(
                "POST", "/api/v1/scans", {"root": "tests/fixtures/sample_disk"}
            )
            self.assertEqual(status, 202)
            self.assertTrue(started.wait(timeout=3))
            status, _, _ = self.call(
                "POST", "/api/v1/scans", {"root": "tests/fixtures/sample_disk"}
            )
            self.assertEqual(status, 409)
            status, _, cancelled = self.call(
                "POST", f"/api/v1/scans/{first['scan_id']}/cancel"
            )
            self.assertEqual(status, 200)
            self.assertEqual(cancelled["state"], "cancelling")

    def test_health_still_public(self) -> None:
        status, _, health = asyncio.run(request("GET", "/health"))
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["version"], "0.1.1")


if __name__ == "__main__":
    unittest.main()
