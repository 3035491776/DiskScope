"""M6.4 diagnostics tests are snapshot-only and never call cleanup execution."""

import asyncio
import json
import stat
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.cleanup.diagnostics import EligibilityDiagnostics, InvalidDiagnosticsRequest
from app.cleanup.policy import (
    ELIGIBLE_REASON, EXECUTION_POLICY_VERSION, POLICY_EVALUATION_ERROR,
    ExecutionPolicyEngine,
)
from app.core.config import PROJECT_ROOT
from app.intelligence.store import CandidateStore
from app.scanner.models import FileMetadata, ScanResult
from app.security.session import COOKIE_NAME, local_session
from app.snapshots.store import SnapshotStore
from tests.asgi_client import request


NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=31)).isoformat()
RECENT = (NOW - timedelta(days=12)).isoformat()
ROOT = r"C:\Users\Test\AppData\Local\Temp"
SIZE = 2 * 1024 * 1024


def candidate(name="candidate.tmp", **changes):
    item = {
        "candidate_id": name, "relative_path": name,
        "display_path": ROOT + "\\" + name.replace("/", "\\"),
        "object_type": "file", "logical_bytes": SIZE,
        "category": "temporary_file", "confidence": "high", "risk_level": "low",
        "reason_code": "STALE_USER_TEMP_FILE", "source_rule_id": "test-rule",
        "rule_version": "rules-v1.1.0", "snapshot_mtime": OLD,
    }
    item.update(changes)
    return item


class PolicyDecisionTests(unittest.TestCase):
    def setUp(self):
        self.lstat = Mock(side_effect=AssertionError("diagnostics must not stat"))
        self.policy = ExecutionPolicyEngine(
            user_profile=r"C:\Users\Test", local_app_data=r"C:\Users\Test\AppData\Local",
            lstat=self.lstat, now=lambda: NOW,
        )

    def evaluate(self, item=None, mtime=OLD):
        return self.policy.evaluate(item or candidate(), "current_user_temp", mtime)

    def test_valid_candidate_is_advisory_eligible(self):
        decision = self.evaluate()
        self.assertEqual(decision.eligibility, "eligible_for_recycle")
        self.assertEqual(decision.allowed_actions, ("recycle",))
        self.assertEqual(decision.reason_codes, (ELIGIBLE_REASON,))
        self.assertEqual(decision.execution_policy_version, EXECUTION_POLICY_VERSION)
        self.assertEqual((decision.evaluation_basis, decision.execution_authority),
                         ("snapshot_only", False))
        self.assertEqual(decision.evidence["required_age_days"], 30)
        self.lstat.assert_not_called()

    def test_decision_matrix_and_unknown_values_fail_closed(self):
        cases = (
            (candidate(), RECENT, "EXECUTION_FILE_TOO_RECENT"),
            (candidate(risk_level="high"), OLD, "EXECUTION_RISK_BLOCKED"),
            (candidate(confidence="medium"), OLD, "EXECUTION_CONFIDENCE_BLOCKED"),
            (candidate(category="application_cache"), OLD, "EXECUTION_CATEGORY_BLOCKED"),
            (candidate("blocked.exe"), OLD, "EXECUTION_EXTENSION_BLOCKED"),
            (candidate("dump.dmp"), OLD, "EXECUTION_EXTENSION_BLOCKED"),
            (candidate(object_type="directory"), OLD, "DIRECTORY_EXECUTION_NOT_SUPPORTED"),
            (candidate(display_path=r"C:\Users\Other\AppData\Local\Temp\a.tmp"), OLD,
             "EXECUTION_CURRENT_USER_TEMP_ONLY"),
            (candidate(display_path=r"C:\Windows\Temp\a.tmp"), OLD,
             "EXECUTION_PROTECTED_PATH"),
            (candidate(risk_level=None), OLD, "UNKNOWN_RISK"),
            (candidate(confidence=None), OLD, "UNKNOWN_CONFIDENCE"),
            (candidate(category=None), OLD, "UNKNOWN_CATEGORY"),
            (candidate(), None, "UNKNOWN_MTIME"),
        )
        for item, mtime, expected in cases:
            with self.subTest(expected=expected):
                decision = self.evaluate(item, mtime)
                self.assertEqual(decision.eligibility, "ineligible")
                self.assertIn(expected, decision.reason_codes)

    def test_primary_reason_is_deterministic_with_multiple_reasons(self):
        item = candidate("blocked.exe", risk_level="high")
        decisions = [self.evaluate(item, RECENT) for _ in range(5)]
        self.assertEqual({decision.primary_reason for decision in decisions},
                         {"EXECUTION_RISK_BLOCKED"})
        self.assertEqual({decision.reason_codes for decision in decisions}, {
            ("EXECUTION_RISK_BLOCKED", "EXECUTION_EXTENSION_BLOCKED",
             "EXECUTION_FILE_TOO_RECENT")
        })

    def test_evaluation_error_fails_closed(self):
        decision = self.evaluate(candidate(logical_bytes=[]))
        self.assertEqual((decision.eligibility, decision.primary_reason),
                         ("ineligible", POLICY_EVALUATION_ERROR))
        self.assertEqual(decision.allowed_actions, ())

    def test_realtime_reparse_cross_volume_and_missing_remain_preflight_only(self):
        def info(mode, device=1):
            timestamp = datetime.fromisoformat(OLD).timestamp()
            return SimpleNamespace(
                st_mode=mode, st_size=SIZE, st_mtime=timestamp,
                st_mtime_ns=int(timestamp * 1e9), st_ctime_ns=1,
                st_file_attributes=0, st_dev=device, st_ino=1,
            )
        prefixes = {"c:\\": info(stat.S_IFDIR | 0o755)}
        current = "C:"
        for part in r"Users\Test\AppData\Local\Temp".split("\\"):
            current += "\\" + part
            prefixes[current.casefold()] = info(stat.S_IFDIR | 0o755)
        prefixes[(ROOT + r"\candidate.tmp").casefold()] = info(stat.S_IFREG | 0o644, device=2)
        policy = ExecutionPolicyEngine(
            r"C:\Users\Test", lambda path: prefixes[path.casefold()], lambda: NOW,
            local_app_data=r"C:\Users\Test\AppData\Local",
        )
        self.assertIn("EXECUTION_CROSS_VOLUME_BLOCKED", policy.preflight(
            candidate(), "current_user_temp", OLD)["block_reasons"])


class DiagnosticsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / "m64.db")
        files = [
            FileMetadata("eligible.tmp", "eligible.tmp", "", SIZE, OLD),
            FileMetadata("recent.tmp", "recent.tmp", "", SIZE, RECENT),
            FileMetadata("blocked.dmp", "blocked.dmp", "", SIZE, OLD),
            FileMetadata("nested.tmp", "app/nested.tmp", "app", SIZE, OLD),
        ]
        result = ScanResult(
            top_files=files, files_seen=4, dirs_seen=1, logical_bytes=4 * SIZE,
            file_persistence_mode="bounded_scope", file_persistence_limit=10_000,
            persisted_file_count=4, observed_file_count=4, file_metadata_coverage="complete",
        )
        status = {"scan_id": "m64", "root": "current_user_temp", "state": "completed",
                  "started_at": OLD, "finished_at": NOW.isoformat(), "elapsed_ms": 10}
        self.snapshot_id = self.store.save(status, result, Path(ROOT))
        self.candidates = CandidateStore(self.store)
        self.candidates.analyze_snapshot(self.snapshot_id)
        self.policy = ExecutionPolicyEngine(
            r"C:\Users\Test", now=lambda: NOW,
            local_app_data=r"C:\Users\Test\AppData\Local",
        )
        self.service = EligibilityDiagnostics(self.candidates, self.policy)

    def test_summary_counts_distributions_bytes_and_coverage(self):
        summary = self.service.summary("current_user_temp")
        self.assertEqual((summary["evaluated_candidate_count"], summary["eligible_count"],
                          summary["blocked_count"]), (4, 1, 3))
        self.assertEqual((summary["eligible_bytes"], summary["blocked_bytes"]),
                         (SIZE, 3 * SIZE))
        primary = {item["reason_code"]: item["candidate_count"]
                   for item in summary["primary_reason_distribution"]}
        self.assertEqual(primary, {
            ELIGIBLE_REASON: 1, "EXECUTION_EXTENSION_BLOCKED": 1,
            "EXECUTION_FILE_TOO_RECENT": 1, "EXECUTION_RISK_BLOCKED": 1,
        })
        self.assertEqual(sum(primary.values()), summary["evaluated_candidate_count"])
        all_total = sum(item["candidate_count"] for item in summary["all_reason_distribution"])
        self.assertGreaterEqual(all_total, summary["evaluated_candidate_count"])
        self.assertEqual(summary["coverage"]["file_metadata_coverage"], "complete")
        self.assertFalse(summary["execution_authority"])

    def test_pagination_filter_sort_detail_and_scope_isolation(self):
        first = self.service.list("current_user_temp", limit=2, offset=0)
        second = self.service.list("current_user_temp", limit=2, offset=2)
        self.assertEqual((len(first["items"]), len(second["items"]), first["total"]), (2, 2, 4))
        self.assertFalse({item["candidate_id"] for item in first["items"]} &
                         {item["candidate_id"] for item in second["items"]})
        self.assertEqual(self.service.list(
            "current_user_temp", filter_key="eligible")["total"], 1)
        self.assertEqual(self.service.list(
            "current_user_temp", filter_key="recent")["total"], 1)
        ordered = self.service.list("current_user_temp", sort="age_desc")["items"]
        self.assertGreaterEqual(ordered[0]["age_days"], ordered[-1]["age_days"])
        detail = self.service.detail(first["items"][0]["candidate_id"], "current_user_temp")
        serialized = json.dumps(detail)
        self.assertIn("decision", detail["candidate"])
        for secret in ("execution_token", "token_hash", "token_digest", "probe_nonce"):
            self.assertNotIn(secret, serialized)
        with self.assertRaises(InvalidDiagnosticsRequest):
            self.service.summary("fixture_sample")

    def test_get_api_is_read_only(self):
        headers = {"cookie": f"{COOKIE_NAME}={local_session.session_token}"}
        before = self._counts()
        with patch("app.api.cleanup.eligibility_diagnostics", self.service):
            code, _, unauthorized = asyncio.run(request(
                "GET", "/api/v1/cleanup/eligibility/summary",
                None, {}, "scope=current_user_temp"))
            self.assertEqual(code, 401)
            self.assertEqual(unauthorized["detail"], "A local session is required.")
            code, _, summary = asyncio.run(request(
                "GET", "/api/v1/cleanup/eligibility/summary",
                None, headers, "scope=current_user_temp"))
            self.assertEqual((code, summary["eligible_count"]), (200, 1))
            code, _, listing = asyncio.run(request(
                "GET", "/api/v1/cleanup/eligibility/candidates",
                None, headers,
                "scope=current_user_temp&limit=1&offset=0&filter=blocked&sort=age_desc"))
            self.assertEqual((code, listing["limit"], listing["filter"], listing["sort"]),
                             (200, 1, "blocked", "age_desc"))
            candidate_id = str(listing["items"][0]["candidate_id"])
            code, _, detail = asyncio.run(request(
                "GET", f"/api/v1/cleanup/eligibility/candidates/{candidate_id}",
                None, headers, "scope=current_user_temp"))
            self.assertEqual(code, 200)
            self.assertFalse(detail["candidate"]["decision"]["execution_authority"])
        self.assertEqual(self._counts(), before)

    def _counts(self):
        with self.store._connection() as connection:
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("scan_snapshots", "candidate_runs", "cleanup_candidates",
                                       "cleanup_execution_runs", "controlled_probes"))


class LargeDiagnosticsFixtureTests(unittest.TestCase):
    def test_ten_thousand_candidate_summary_is_linear_and_bounded(self):
        template = candidate()
        candidates = [
            {**template, "candidate_id": f"c-{index}", "relative_path": f"f-{index}.tmp",
             "display_path": ROOT + f"\\f-{index}.tmp", "snapshot_mtime": RECENT,
             "evidence_json": "[]"}
            for index in range(10_000)
        ]
        dataset = {
            "run": {"run_id": "run", "snapshot_id": "snapshot", "rule_version": "rules-v1.1.0",
                    "scan_completed_at": NOW.isoformat()},
            "snapshot": {"coverage": "complete", "file_persistence_mode": "bounded_scope",
                         "file_persistence_limit": 10_000, "persisted_file_count": 10_000,
                         "observed_file_count": 10_000},
            "candidates": candidates,
        }
        store = Mock()
        store.diagnostics_dataset.return_value = dataset
        policy = ExecutionPolicyEngine(
            r"C:\Users\Test", now=lambda: NOW,
            local_app_data=r"C:\Users\Test\AppData\Local",
        )
        started = time.perf_counter()
        summary = EligibilityDiagnostics(store, policy).summary("current_user_temp")
        self.assertEqual((summary["evaluated_candidate_count"], summary["blocked_count"]),
                         (10_000, 10_000))
        self.assertLess(time.perf_counter() - started, 5)
        store.diagnostics_dataset.assert_called_once_with("current_user_temp")


if __name__ == "__main__":
    unittest.main()
