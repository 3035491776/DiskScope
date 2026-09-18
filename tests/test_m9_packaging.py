import os
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.api.health import health
from app.scanner.path_guard import InvalidScanRoot
from app.scanner import scope_registry
from launcher import bootstrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_health_uses_release_version_and_explicit_developer_mode(self) -> None:
        payload = health()
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["mode"], "guarded_cleanup")
        self.assertIs(payload["developer_mode"], False)
        self.assertEqual(payload["capabilities"]["scan"], "read_only")

    def test_packaged_layout_separates_resources_from_writable_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / "bundle"
            runtime = base / "portable"
            bundle.mkdir()
            runtime.mkdir()
            code = (
                "import pathlib,sys; "
                f"sys.frozen=True; sys._MEIPASS={str(bundle)!r}; "
                f"sys.executable={str(runtime / 'DiskScope.exe')!r}; "
                "from app.core import config; "
                "print(config.FRONTEND_DIST); print(config.DATA_DIR); print(config.LOG_DIR); "
                "print(config.DEVELOPER_MODE)"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(PROJECT_ROOT / "backend")
            output = subprocess.check_output(
                [sys.executable, "-c", code], text=True, env=environment
            ).splitlines()
        self.assertEqual(Path(output[0]), bundle / "frontend" / "dist")
        self.assertEqual(Path(output[1]), runtime / "data")
        self.assertEqual(Path(output[2]), runtime / "logs")
        self.assertEqual(output[3], "False")

    def test_packaged_release_rejects_development_scopes_and_paths(self) -> None:
        with patch.object(scope_registry, "PACKAGED_RELEASE", True):
            for scope in ("fixture_sample", "project_workspace"):
                with self.subTest(scope=scope), self.assertRaises(InvalidScanRoot):
                    scope_registry.resolve_scan_scope(scope_key=scope)
            with self.assertRaises(InvalidScanRoot):
                scope_registry.resolve_scan_scope("tests/fixtures/sample_disk")

    def test_source_no_longer_embeds_the_development_machine_path(self) -> None:
        source = (PROJECT_ROOT / "backend" / "app" / "scanner" / "path_guard.py").read_text()
        self.assertNotIn("D:\\Artilius", source)
        self.assertNotIn("Windows-C-clear", source)

    def test_browser_open_failure_prints_one_time_local_fallback(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdin = io.StringIO()
                self.finished = False

            def wait(self, timeout=None):
                self.finished = True
                return 0

            def poll(self):
                return 0 if self.finished else None

            def terminate(self) -> None:
                self.finished = True

            def kill(self) -> None:
                self.finished = True

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "frontend"
            dist.mkdir()
            (dist / "index.html").write_text("<div id=\"app\"></div>", encoding="utf-8")
            output = io.StringIO()
            process = FakeProcess()
            with (
                patch.object(bootstrap, "ROOT", root),
                patch.object(bootstrap, "LOGS", root / "logs"),
                patch.object(bootstrap, "DIST", dist),
                patch.object(bootstrap, "check_port_available"),
                patch.object(bootstrap, "backend_command", return_value=["DiskScope.exe", "--serve"]),
                patch.object(bootstrap, "wait_for_health"),
                patch.object(bootstrap.logging, "basicConfig"),
                patch.object(bootstrap.subprocess, "Popen", return_value=process),
                patch.object(bootstrap.webbrowser, "open", return_value=False),
                redirect_stdout(output),
            ):
                exit_code = bootstrap.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Open this one-time local address in your browser:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
