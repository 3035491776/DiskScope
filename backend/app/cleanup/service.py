"""Audited prepare/execute contract; actual cleanup is disabled in M6 V1."""

from __future__ import annotations

import json
import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone

from app.cleanup.policy import ExecutionPolicyEngine
from app.snapshots.store import SnapshotStore, snapshot_store
from app.tasks.manager import scan_tasks
from app.operations import OperationConflict, operations

TOKEN_LIFETIME_SECONDS = 90


class CleanupError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class CleanupService:
    def __init__(self, snapshots: SnapshotStore = snapshot_store,
                 policy: ExecutionPolicyEngine | None = None):
        self.snapshots = snapshots
        self.policy = policy or ExecutionPolicyEngine()
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
        connection.execute("""UPDATE cleanup_execution_runs
            SET status = 'expired', failure_code = 'EXECUTION_TOKEN_EXPIRED',
                final_result = 'no_target_mutation'
            WHERE status = 'prepared' AND expires_at IS NOT NULL AND expires_at <= ?""",
            (datetime.now(timezone.utc).isoformat(),))

    def _scan_running(self) -> bool:
        return scan_tasks.has_active_scan()

    def prepare(self, candidate_id: str, requested_action: str) -> dict[str, object]:
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
            prepared_at = datetime.now(timezone.utc)
            expires_at = prepared_at + timedelta(seconds=TOKEN_LIFETIME_SECONDS)
            token = secrets.token_urlsafe(32) if plan["eligibility"] != "ineligible" else None
            token_hash = hashlib.sha256(token.encode()).hexdigest() if token else None
            run_id = secrets.token_hex(16)
            status = "prepared" if token else "blocked"
            connection.execute("""INSERT INTO cleanup_execution_runs
                (id, token_hash, candidate_id, snapshot_id, rule_version, requested_action,
                 eligibility, prepare_time, expires_at, status, original_path,
                 snapshot_size, snapshot_mtime, preflight_size, preflight_mtime,
                 fingerprint_json, checks_json, block_reasons_json, final_result, failure_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, token_hash, candidate_id, candidate["snapshot_id"], candidate["rule_version"],
                 requested_action, plan["eligibility"], prepared_at.isoformat(),
                 expires_at.isoformat() if token else None, status, candidate["display_path"],
                 candidate["logical_bytes"], candidate["snapshot_mtime"], plan["current_size"],
                 plan["current_mtime"], json.dumps(plan["fingerprint"]),
                 json.dumps(plan["checks"]), json.dumps(plan["block_reasons"]),
                 "dry_run_only" if token else "blocked", plan["block_reasons"][0] if not token and plan["block_reasons"] else None))
            connection.commit()
            return {"execution_id": run_id, "execution_token": token,
                    "expires_at": expires_at.isoformat() if token else None,
                    "preflight": {key: value for key, value in plan.items() if key != "fingerprint"},
                    "real_execution_enabled": False}

    def execute(self, token: str) -> dict[str, object]:
        try:
            with operations.cleanup_execution():
                return self._execute_guarded(token)
        except OperationConflict as exc:
            raise CleanupError("OPERATION_CONFLICT") from exc

    def _execute_guarded(self, token: str) -> dict[str, object]:
        with self._lock, self.snapshots._connection() as connection:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            row = connection.execute("SELECT * FROM cleanup_execution_runs WHERE token_hash = ?", (token_hash,)).fetchone()
            if row is None:
                raise CleanupError("EXECUTION_TOKEN_INVALID", 404)
            if row["status"] != "prepared":
                raise CleanupError("ALREADY_EXECUTED" if row["status"] != "expired" else "EXECUTION_TOKEN_EXPIRED")
            if datetime.now(timezone.utc) >= datetime.fromisoformat(row["expires_at"]):
                connection.execute("""UPDATE cleanup_execution_runs
                    SET status = 'expired', execute_time = ?,
                        failure_code = 'EXECUTION_TOKEN_EXPIRED',
                        final_result = 'no_target_mutation'
                    WHERE id = ?""",
                    (datetime.now(timezone.utc).isoformat(), row["id"]))
                connection.commit()
                raise CleanupError("EXECUTION_TOKEN_EXPIRED")
            if self._scan_running():
                connection.execute("""UPDATE cleanup_execution_runs SET status = 'blocked',
                    execute_time = ?, failure_code = 'OPERATION_CONFLICT',
                    final_result = 'no_target_mutation' WHERE id = ?""",
                    (datetime.now(timezone.utc).isoformat(), row["id"]))
                connection.commit()
                raise CleanupError("OPERATION_CONFLICT")
            candidate = self._candidate(connection, row["candidate_id"])
            plan = self.policy.preflight(candidate, candidate["scope_key"], candidate["snapshot_mtime"])
            if (plan["fingerprint"] != json.loads(row["fingerprint_json"]) or
                    candidate["recorded_size"] != candidate["logical_bytes"]):
                plan["block_reasons"].append("TARGET_CHANGED_SINCE_PREPARE")
            failure = plan["block_reasons"][0] if plan["block_reasons"] else "EXECUTION_NOT_ENABLED_YET"
            connection.execute("""UPDATE cleanup_execution_runs SET status = 'blocked',
                execute_time = ?, preflight_size = ?, preflight_mtime = ?,
                checks_json = ?, block_reasons_json = ?, failure_code = ?, final_result = ?
                WHERE id = ?""", (datetime.now(timezone.utc).isoformat(), plan["current_size"],
                plan["current_mtime"], json.dumps(plan["checks"]),
                json.dumps(plan["block_reasons"]), failure, "no_target_mutation", row["id"]))
            connection.commit()
            raise CleanupError(failure)

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        with self.snapshots._connection() as connection:
            self._expire_prepared(connection)
            rows = [self._public(row) for row in connection.execute(
                "SELECT * FROM cleanup_execution_runs ORDER BY prepare_time DESC LIMIT ?", (limit,))]
            connection.commit()
            return rows

    def detail(self, execution_id: str) -> dict[str, object]:
        with self.snapshots._connection() as connection:
            self._expire_prepared(connection)
            row = connection.execute("SELECT * FROM cleanup_execution_runs WHERE id = ?", (execution_id,)).fetchone()
            if row is None:
                raise CleanupError("EXECUTION_NOT_FOUND", 404)
            connection.commit()
            return self._public(row)


cleanup_service = CleanupService()
