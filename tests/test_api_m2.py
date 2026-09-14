import asyncio
import time
import unittest
from unittest.mock import patch

from app.security.session import COOKIE_NAME, LOCAL_ORIGIN, local_session
from app.system.volumes import capacity_record
from app.tasks.manager import ScanTaskManager
from tests.asgi_client import request
from tests.fixtures.generate_sample import generate_sample


class M2ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_sample()

    def setUp(self) -> None:
        self.manager = ScanTaskManager()
        self.manager_patch = patch("app.api.scans.scan_tasks", new=self.manager)
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)
        self.headers = {
            "cookie": f"{COOKIE_NAME}={local_session.session_token}",
            "origin": LOCAL_ORIGIN,
        }

    def call(self, method: str, path: str, body=None, query: str = ""):
        return asyncio.run(request(method, path, body, self.headers, query))

    def completed_scan_id(self, root: str = "tests/fixtures/sample_disk") -> str:
        status, _, created = self.call("POST", "/api/v1/scans", {"root": root})
        self.assertEqual(status, 202)
        scan_id = created["scan_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.manager.status(scan_id)["state"]
            if state == "completed":
                return scan_id
            if state == "failed":
                self.fail("Fixture scan failed")
            time.sleep(0.01)
        self.fail("Fixture scan timed out")

    def test_volume_capacity_is_integer_bytes_and_only_c_has_opt_in_scan(self) -> None:
        expected = capacity_record("C:", 1000, 250)
        self.assertEqual(expected, {
            "drive": "C:", "total_bytes": 1000, "used_bytes": 750,
            "free_bytes": 250, "scan_allowed": True,
        })
        with patch("app.api.volumes.list_fixed_volumes", return_value=[expected]):
            status, _, payload = self.call("GET", "/api/v1/volumes")
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [expected])
        status, _, _ = asyncio.run(request("GET", "/api/v1/volumes"))
        self.assertEqual(status, 401)

    def test_directory_endpoint_returns_only_current_level_and_empty_directory(self) -> None:
        scan_id = self.completed_scan_id()
        status, _, root = self.call("GET", f"/api/v1/scans/{scan_id}/directories")
        self.assertEqual(status, 200)
        self.assertTrue(all(item["parent"] == "" for item in root["items"]))
        self.assertTrue(all({"node_id", "name", "file_count", "coverage", "subtree_bytes"} <= item.keys() for item in root["items"]))
        self.assertTrue(all(item["coverage"] == "complete" for item in root["items"]))
        status, _, nested = self.call(
            "GET", f"/api/v1/scans/{scan_id}/directories", query="parent_id=Nested"
        )
        self.assertEqual(status, 200)
        self.assertEqual({item["name"] for item in nested["items"]}, {"A", "C"})
        status, _, empty = self.call(
            "GET", f"/api/v1/scans/{scan_id}/directories", query="parent_id=EmptyDir"
        )
        self.assertEqual(status, 200)
        self.assertEqual(empty["items"], [])

    def test_top_files_and_directories_are_sorted_and_whole_volume_gate_remains(self) -> None:
        scan_id = self.completed_scan_id()
        status, _, files = self.call(
            "GET", f"/api/v1/scans/{scan_id}/top", query="kind=file&limit=3"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(files["items"]), 3)
        self.assertEqual(files["items"][0]["size_bytes"], 5 * 1024 * 1024)
        status, _, directories = self.call(
            "GET", f"/api/v1/scans/{scan_id}/top", query="kind=directory&limit=3"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(directories["items"]), 3)
        sizes = [item["subtree_bytes"] for item in directories["items"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        for root in ("C:\\", "D:\\"):
            status, _, denial = self.call("POST", "/api/v1/scans", {"root": root})
            self.assertEqual(status, 403)
            self.assertEqual(denial["detail"], "WHOLE_VOLUME_SCAN_NOT_APPROVED")

    def test_empty_directory_has_no_top_files_or_children(self) -> None:
        scan_id = self.completed_scan_id("tests/fixtures/sample_disk/EmptyDir")
        status, _, files = self.call(
            "GET", f"/api/v1/scans/{scan_id}/top", query="kind=file&limit=100"
        )
        self.assertEqual(status, 200)
        self.assertEqual(files["items"], [])
        status, _, directories = self.call("GET", f"/api/v1/scans/{scan_id}/directories")
        self.assertEqual(status, 200)
        self.assertEqual(directories["items"], [])


if __name__ == "__main__":
    unittest.main()
