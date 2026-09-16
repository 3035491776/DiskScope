"""Audited M6.2 single-file recycle gate for probes and strict user Temp candidates."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

from app.cleanup.policy import EXECUTION_RULE_ID, ExecutionPolicyEngine
from app.cleanup.probes import ControlledProbeRegistry, ProbeError, PROBE_RULE_VERSION
from app.cleanup.recycle import RecycleError, WindowsRecycleBackend
from app.operations import OperationConflict, operations
from app.snapshots.store import SnapshotStore, snapshot_store
from app.tasks.manager import scan_tasks

TOKEN_LIFETIME_SECONDS = 90


class CleanupError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class CleanupService:
    def __init__(self, snapshots: SnapshotStore = snapshot_store,
                 policy: ExecutionPolicyEngine | None = None,
                 probes: ControlledProbeRegistry | None = None,
                 recycle_backend=None):
        self.snapshots = snapshots
        self.policy = policy or ExecutionPolicyEngine()
        self._probe_setup_error: ProbeError | None = None
        if probes is None:
            try:
                probes = ControlledProbeRegistry.production(snapshots)
            except ProbeError as exc:
                self._probe_setup_error = exc
        self.probes = probes
        self.recycle_backend = recycle_backend or WindowsRecycleBackend()
        self._lock = threading.RLock()

    @staticmethod
    def _candidate(connection, candidate_id: str):
        row = connection.execute("""SELECT c.*, r.snapshot_id, s.scope_key,
            f.mtime AS snapshot_mtime, f.size_bytes AS recorded_size
            FROM cleanup_candidates c
            JOIN candidate_runs r ON r.id = c.run_id
            JOIN scan_snapshots s ON s.id = r.snapshot_id
            LEFT JOIN file_snapshots f ON f.snapshot_id = r.snapshot_id
                AND f.relative_path = c.relative_path
            WHERE c.candidate_id = ?""", (candidate_id,)).fetchone()
        if row is None:
            raise CleanupError("CANDIDATE_NOT_FOUND", 404)
        return dict(row)

    def _require_probes(self) -> ControlledProbeRegistry:
        if self.probes is None:
            error = self._probe_setup_error
            raise CleanupError(error.code if error else "PROBE_BACKEND_UNAVAILABLE", 503)
        return self.probes

    @staticmethod
    def _public(row) -> dict[str, object]:
        item = dict(row)
        for key in ("checks_json", "block_reasons_json", "fingerprint_json"):
            item[key.removesuffix("_json")] = json.loads(item.pop(key)) if item[key] else None
        item.pop("fingerprint", None)
        item.pop("token_hash", None)
        return item

    @staticmethod
    def _expire_prepared(connection) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection.execute("""UPDATE controlled_probes SET state = 'failed',
            updated_at = ?, failure_code = 'EXECUTION_INTERRUPTED'
            WHERE state = 'prepared' AND probe_id IN (
                SELECT probe_id FROM cleanup_execution_runs WHERE status = 'executing'
            )""", (now,))
        connection.execute("""UPDATE cleanup_execution_runs
            SET status = 'failed', failure_code = 'EXECUTION_INTERRUPTED',
                final_result = 'execution_interrupted', token_outcome = 'consumed',
                recycle_api_outcome = 'unknown_after_restart', target_mutation = 'unknown'
            WHERE status = 'executing'""")
        connection.execute("""UPDATE controlled_probes SET state = 'created',
            updated_at = ?, failure_code = NULL WHERE state = 'prepared' AND probe_id IN (
                SELECT probe_id FROM cleanup_execution_runs
                WHERE status = 'prepared' AND expires_at IS NOT NULL AND expires_at <= ?
            )""", (now, now))
        connection.execute("""UPDATE cleanup_execution_runs
            SET status = 'expired', failure_code = 'EXECUTION_TOKEN_EXPIRED',
                final_result = 'no_target_mutation', token_outcome = 'expired',
                target_mutation = 'none'
            WHERE status = 'prepared' AND expires_at IS NOT NULL AND expires_at <= ?""",
            (now,))

    def _scan_running(self) -> bool:
        return scan_tasks.has_active_scan()

    def create_probe(self) -> dict[str, object]:
        if self._scan_running():
            raise CleanupError("OPERATION_CONFLICT")
        try:
            return self._require_probes().create()
        except ProbeError as exc:
            raise CleanupError(exc.code, exc.status_code) from exc

    def list_probes(self) -> list[dict[str, object]]:
        return self._require_probes().list_current()

    def prepare(self, candidate_id: str, requested_action: str) -> dict[str, object]:
        """Prepare one persisted candidate; no path supplied by the caller is accepted."""
        if requested_action != "recycle":
            raise CleanupError("EXECUTION_ACTION_BLOCKED", 400)
        with self._lock, self.snapshots._connection() as connection:
            candidate = self._candidate(connection, candidate_id)
            if candidate["recorded_size"] != candidate["logical_bytes"]:
                plan = self.policy.preflight(candidate, candidate["scope_key"], candidate["snapshot_mtime"])
                plan["block_reasons"].append("SNAPSHOT_RECORD_MISMATCH")
                plan["eligibility"] = "ineligible"
                plan["planned_action"] = "none"
            else:
                plan = self.policy.preflight(candidate, candidate["scope_key"], candidate["snapshot_mtime"])
            if self._scan_running():
                plan["block_reasons"].append("OPERATION_CONFLICT")
                plan["eligibility"] = "ineligible"
                plan["planned_action"] = "none"
            already_recycled = connection.execute("""SELECT 1 FROM cleanup_execution_runs
                WHERE candidate_id = ? AND status = 'completed'
                AND target_mutation = 'recycle_bin' LIMIT 1""", (candidate_id,)).fetchone()
            if already_recycled:
                plan["block_reasons"].append("ALREADY_EXECUTED")
                plan["eligibility"] = "ineligible"
                plan["planned_action"] = "none"
                plan["allowed_actions"] = []
            return self._store_prepare(connection, plan, candidate_id=candidate_id,
                probe_id=None, snapshot_id=candidate["snapshot_id"],
                scope_key=candidate["scope_key"], rule_version=candidate["rule_version"],
                policy_rule_id=str(plan["policy_rule_id"]), requested_action=requested_action,
                candidate_category=str(candidate["category"]),
                candidate_risk=str(candidate["risk_level"]),
                candidate_confidence=str(candidate["confidence"]),
                real_execution_enabled=True)

    def prepare_probe(self, probe_id: str, requested_action: str) -> dict[str, object]:
        if requested_action != "recycle":
            raise CleanupError("EXECUTION_ACTION_BLOCKED", 400)
        probes = self._require_probes()
        with self._lock, self.snapshots._connection() as connection:
            row = connection.execute(
                "SELECT * FROM controlled_probes WHERE probe_id = ? AND session_id = ?",
                (probe_id, probes.session_id)).fetchone()
            if row is None:
                raise CleanupError("CONTROLLED_PROBE_NOT_FOUND", 404)
            record = dict(row)
            plan = probes.preflight(record, "created")
            if self._scan_running():
                plan["block_reasons"].append("OPERATION_CONFLICT")
                plan["eligibility"] = "ineligible"
                plan["planned_action"] = "none"
            response = self._store_prepare(connection, plan, candidate_id=None,
                probe_id=probe_id, snapshot_id=None, scope_key="controlled_probe",
                rule_version=PROBE_RULE_VERSION, policy_rule_id=PROBE_RULE_VERSION,
                requested_action=requested_action, candidate_category=None,
                candidate_risk=None, candidate_confidence=None,
                real_execution_enabled=True)
            if response["execution_token"]:
                probes.update_state(connection, probe_id, "prepared")
            elif "OPERATION_CONFLICT" not in plan["block_reasons"]:
                probes.update_state(connection, probe_id, "invalidated", plan["block_reasons"][0])
            connection.commit()
            return response

    def _store_prepare(self, connection, plan: dict[str, object], *,
                       candidate_id: str | None, probe_id: str | None,
                       snapshot_id: str | None, scope_key: str, rule_version: str,
                       policy_rule_id: str, requested_action: str,
                       candidate_category: str | None, candidate_risk: str | None,
                       candidate_confidence: str | None,
                       real_execution_enabled: bool) -> dict[str, object]:
        prepared_at = datetime.now(timezone.utc)
        expires_at = prepared_at + timedelta(seconds=TOKEN_LIFETIME_SECONDS)
        token = secrets.token_urlsafe(32) if plan["eligibility"] == "eligible_for_recycle" else None
        token_hash = hashlib.sha256(token.encode()).hexdigest() if token else None
        run_id = secrets.token_hex(16)
        status = "prepared" if token else "blocked"
        planned_action = str(plan["planned_action"])
        connection.execute("""INSERT INTO cleanup_execution_runs (
            id, token_hash, candidate_id, probe_id, snapshot_id, scope_key,
            rule_version, requested_action, planned_action, eligibility,
            prepare_time, expires_at, status, original_path, snapshot_size,
            snapshot_mtime, preflight_size, preflight_mtime, fingerprint_json,
            checks_json, block_reasons_json, policy_decision, token_outcome,
            recycle_api_outcome, final_result, failure_code, target_mutation,
            policy_rule_id, candidate_category, candidate_risk, candidate_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    NULL, ?, ?, 'none', ?, ?, ?, ?)""",
            (run_id, token_hash, candidate_id, probe_id, snapshot_id, scope_key,
             rule_version, requested_action, planned_action, plan["eligibility"],
             prepared_at.isoformat(), expires_at.isoformat() if token else None,
             status, plan["current_path"], plan["snapshot_size"], plan["snapshot_mtime"],
             plan["current_size"], plan["current_mtime"], json.dumps(plan["fingerprint"]),
             json.dumps(plan["checks"]), json.dumps(plan["block_reasons"]),
             plan["eligibility"], "active" if token else "not_issued",
              "ready" if token else "blocked",
             plan["block_reasons"][0] if not token and plan["block_reasons"] else None,
             policy_rule_id, candidate_category, candidate_risk, candidate_confidence))
        connection.commit()
        return {"execution_id": run_id, "execution_token": token,
                "expires_at": expires_at.isoformat() if token else None,
                "preflight": {key: value for key, value in plan.items() if key != "fingerprint"},
                "real_execution_enabled": real_execution_enabled and token is not None}

    def execute(self, token: str) -> dict[str, object]:
        if not isinstance(token, str) or not token:
            raise CleanupError("EXECUTION_TOKEN_INVALID", 404)
        try:
            with operations.cleanup_execution():
                return self._execute_guarded(token)
        except OperationConflict as exc:
            raise CleanupError("OPERATION_CONFLICT") from exc

    def _execute_guarded(self, token: str) -> dict[str, object]:
        with self._lock, self.snapshots._connection() as connection:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            row = connection.execute(
                "SELECT * FROM cleanup_execution_runs WHERE token_hash = ?", (token_hash,)).fetchone()
            if row is None:
                raise CleanupError("EXECUTION_TOKEN_INVALID", 404)
            if row["status"] != "prepared":
                raise CleanupError(
                    "ALREADY_EXECUTED" if row["status"] != "expired" else "EXECUTION_TOKEN_EXPIRED")
            if datetime.now(timezone.utc) >= datetime.fromisoformat(row["expires_at"]):
                self._expire_one(connection, row, "EXECUTION_TOKEN_EXPIRED", "expired")
                raise CleanupError("EXECUTION_TOKEN_EXPIRED")
            if self._scan_running():
                self._block_execution(connection, row, "OPERATION_CONFLICT")
                if row["probe_id"] and self.probes:
                    self.probes.update_state(connection, row["probe_id"], "created")
                    connection.commit()
                raise CleanupError("OPERATION_CONFLICT")
            if row["probe_id"]:
                return self._execute_probe(connection, row)
            return self._execute_candidate(connection, row)

    def _expire_one(self, connection, row, code: str, status: str) -> None:
        connection.execute("""UPDATE cleanup_execution_runs SET status = ?, execute_time = ?,
            failure_code = ?, final_result = 'no_target_mutation', token_outcome = 'expired',
            target_mutation = 'none' WHERE id = ?""",
            (status, datetime.now(timezone.utc).isoformat(), code, row["id"]))
        if row["probe_id"] and self.probes:
            self.probes.update_state(connection, row["probe_id"], "created")
        connection.commit()

    @staticmethod
    def _block_execution(connection, row, code: str, plan: dict[str, object] | None = None) -> None:
        checks = json.dumps(plan["checks"]) if plan else row["checks_json"]
        reasons = json.dumps(plan["block_reasons"]) if plan else row["block_reasons_json"]
        size = plan["current_size"] if plan else row["preflight_size"]
        mtime = plan["current_mtime"] if plan else row["preflight_mtime"]
        connection.execute("""UPDATE cleanup_execution_runs SET status = 'blocked',
            execute_time = ?, execute_size = ?, execute_mtime = ?, checks_json = ?,
            block_reasons_json = ?, failure_code = ?, final_result = 'no_target_mutation',
            token_outcome = 'consumed', recycle_api_outcome = 'not_called',
            target_mutation = 'none' WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), size, mtime, checks, reasons, code, row["id"]))
        connection.commit()

    def _execute_candidate(self, connection, row) -> dict[str, object]:
        candidate = self._candidate(connection, row["candidate_id"])
        plan = self.policy.preflight(candidate, candidate["scope_key"], candidate["snapshot_mtime"])
        already_recycled = connection.execute("""SELECT 1 FROM cleanup_execution_runs
            WHERE candidate_id = ? AND id <> ? AND status = 'completed'
            AND target_mutation = 'recycle_bin' LIMIT 1""",
            (row["candidate_id"], row["id"])).fetchone()
        if already_recycled:
            plan["block_reasons"].insert(0, "ALREADY_EXECUTED")
        prepared_fingerprint = json.loads(row["fingerprint_json"])
        if plan["fingerprint"] is not None and plan["fingerprint"] != prepared_fingerprint:
            plan["block_reasons"].insert(0, "TARGET_CHANGED_SINCE_PREPARE")
        if candidate["recorded_size"] != candidate["logical_bytes"]:
            plan["block_reasons"].insert(0, "SNAPSHOT_RECORD_MISMATCH")
        if (row["planned_action"] != "recycle" or row["requested_action"] != "recycle" or
                row["scope_key"] != "system_drive_c" or
                row["snapshot_id"] != candidate["snapshot_id"] or
                row["rule_version"] != candidate["rule_version"] or
                row["policy_rule_id"] != EXECUTION_RULE_ID or
                plan["policy_rule_id"] != EXECUTION_RULE_ID or
                row["candidate_category"] != candidate["category"] or
                row["candidate_risk"] != candidate["risk_level"] or
                row["candidate_confidence"] != candidate["confidence"]):
            plan["block_reasons"].append("EXECUTION_POLICY_CHANGED")
        plan["block_reasons"] = list(dict.fromkeys(plan["block_reasons"]))
        if plan["block_reasons"]:
            code = plan["block_reasons"][0]
            self._block_execution(connection, row, code, plan)
            raise CleanupError(code)
        return self._perform_recycle(
            connection, row, candidate["display_path"], plan, probes=None)

    def _execute_probe(self, connection, row) -> dict[str, object]:
        probes = self._require_probes()
        probe_row = connection.execute(
            "SELECT * FROM controlled_probes WHERE probe_id = ? AND session_id = ?",
            (row["probe_id"], probes.session_id)).fetchone()
        if probe_row is None:
            self._block_execution(connection, row, "CONTROLLED_PROBE_NOT_FOUND")
            raise CleanupError("CONTROLLED_PROBE_NOT_FOUND")
        record = dict(probe_row)
        plan = probes.preflight(record, "prepared")
        prepared_fingerprint = json.loads(row["fingerprint_json"])
        if plan["fingerprint"] is not None and plan["fingerprint"] != prepared_fingerprint:
            plan["block_reasons"].insert(0, "TARGET_CHANGED_SINCE_PREPARE")
        if row["planned_action"] != "recycle" or row["requested_action"] != "recycle":
            plan["block_reasons"].append("EXECUTION_ACTION_BLOCKED")
        plan["block_reasons"] = list(dict.fromkeys(plan["block_reasons"]))
        if plan["block_reasons"]:
            code = plan["block_reasons"][0]
            self._block_execution(connection, row, code, plan)
            probes.update_state(connection, row["probe_id"], "invalidated", code)
            connection.commit()
            raise CleanupError(code)

        return self._perform_recycle(
            connection, row, record["absolute_path"], plan, probes=probes)

    def _perform_recycle(self, connection, row, path: str,
                         plan: dict[str, object], *,
                         probes: ControlledProbeRegistry | None) -> dict[str, object]:
        execution_time = datetime.now(timezone.utc).isoformat()
        connection.execute("""UPDATE cleanup_execution_runs SET status = 'executing',
            execute_time = ?, execute_size = ?, execute_mtime = ?, checks_json = ?,
            block_reasons_json = '[]', token_outcome = 'consumed',
            recycle_api_outcome = 'calling', target_mutation = 'none'
            WHERE id = ?""", (execution_time, plan["current_size"], plan["current_mtime"],
                              json.dumps(plan["checks"]), row["id"]))
        connection.commit()
        try:
            result = self.recycle_backend.recycle(str(path))
        except RecycleError as exc:
            target_exists = os.path.lexists(str(path))
            mutation = "none" if target_exists else "unknown"
            connection.execute("""UPDATE cleanup_execution_runs SET status = 'failed',
                recycle_api_outcome = ?, final_result = 'recycle_failed', failure_code = ?,
                target_mutation = ? WHERE id = ?""",
                (exc.code, exc.code, mutation, row["id"]))
            if probes is not None:
                probes.update_state(connection, row["probe_id"], "failed", exc.code)
            connection.commit()
            raise CleanupError(exc.code) from exc

        if not result.original_path_absent or os.path.lexists(str(path)):
            code = "RECYCLE_ORIGINAL_PATH_REMAINS"
            connection.execute("""UPDATE cleanup_execution_runs SET status = 'failed',
                recycle_api_outcome = ?, final_result = 'recycle_failed', failure_code = ?,
                target_mutation = 'none' WHERE id = ?""",
                (code, code, row["id"]))
            if probes is not None:
                probes.update_state(connection, row["probe_id"], "failed", code)
            connection.commit()
            raise CleanupError(code)
        connection.execute("""UPDATE cleanup_execution_runs SET status = 'completed',
            recycle_api_outcome = 'success', final_result = 'recycled', failure_code = NULL,
            target_mutation = 'recycle_bin', actual_action = 'recycle' WHERE id = ?""",
            (row["id"],))
        if probes is not None:
            probes.update_state(connection, row["probe_id"], "recycled")
        connection.commit()
        return {"execution_id": row["id"], "probe_id": row["probe_id"],
                "candidate_id": row["candidate_id"],
                "status": "completed", "final_result": "recycled",
                "target_mutation": "recycle_bin", "original_path_absent": True,
                "message": "已移入回收站"}

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        # Keep crash recovery from observing this process's own in-flight
        # recycle call as a stale `executing` row.
        with self._lock, self.snapshots._connection() as connection:
            self._expire_prepared(connection)
            rows = [self._public(row) for row in connection.execute(
                "SELECT * FROM cleanup_execution_runs ORDER BY prepare_time DESC LIMIT ?", (limit,))]
            connection.commit()
            return rows

    def detail(self, execution_id: str) -> dict[str, object]:
        with self._lock, self.snapshots._connection() as connection:
            self._expire_prepared(connection)
            row = connection.execute(
                "SELECT * FROM cleanup_execution_runs WHERE id = ?", (execution_id,)).fetchone()
            if row is None:
                raise CleanupError("EXECUTION_NOT_FOUND", 404)
            connection.commit()
            return self._public(row)


cleanup_service = CleanupService()
