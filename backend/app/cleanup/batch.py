"""Bounded, sequential batch orchestration over existing guarded recycle policies."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

from app.cleanup.classification import (
    REVIEW_POLICY_ID, REVIEW_REQUIRED, SAFE_ACTIONABLE,
    CleanupClassificationService, cleanup_classifications,
)
from app.cleanup.policy import EXECUTION_RULE_ID
from app.cleanup.probes import ControlledProbeRegistry, ProbeError, PROBE_RULE_VERSION
from app.cleanup.recycle import RecycleError, WindowsRecycleBackend
from app.cleanup.service import CleanupError, TOKEN_LIFETIME_SECONDS, cleanup_service
from app.operations import OperationConflict, operations
from app.snapshots.store import SnapshotStore, snapshot_store
from app.tasks.manager import scan_tasks


MAX_BATCH_ITEMS = 200
BATCH_MODES = frozenset({"safe", "review", "controlled_probe"})


class BatchCleanupService:
    def __init__(self, snapshots: SnapshotStore = snapshot_store,
                 classifications: CleanupClassificationService | None = None,
                 probes: ControlledProbeRegistry | None = None,
                 recycle_backend=None):
        self.snapshots = snapshots
        self.classifications = classifications or cleanup_classifications
        self.recycle_backend = recycle_backend or WindowsRecycleBackend()
        self.session_id = secrets.token_hex(16)
        self._lock = threading.RLock()
        self.probes = probes
        if self.probes is None:
            try:
                self.probes = ControlledProbeRegistry.production(snapshots)
            except ProbeError:
                self.probes = None

    @staticmethod
    def _validate_ids(item_ids: list[str]) -> list[str]:
        if not isinstance(item_ids, list) or not item_ids or len(item_ids) > MAX_BATCH_ITEMS:
            raise CleanupError("BATCH_SIZE_INVALID", 400)
        if any(not isinstance(item, str) or not item or len(item) > 256 for item in item_ids):
            raise CleanupError("BATCH_ITEM_ID_INVALID", 400)
        if len(set(item_ids)) != len(item_ids):
            raise CleanupError("BATCH_ITEM_DUPLICATE", 400)
        return item_ids

    @staticmethod
    def _digest(value: object) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _scan_running(self) -> bool:
        return scan_tasks.has_active_scan()

    def prepare(self, item_ids: list[str], mode: str, scope_key: str) -> dict[str, object]:
        item_ids = self._validate_ids(item_ids)
        if mode not in {"safe", "review"}:
            raise CleanupError("BATCH_MODE_BLOCKED", 400)
        if scope_key not in {"system_drive_c", "current_user_temp"}:
            raise CleanupError("BATCH_SCOPE_BLOCKED", 400)
        if self._scan_running():
            raise CleanupError("OPERATION_CONFLICT")
        prepared: list[dict[str, object]] = []
        requested_bytes = 0
        for ordinal, candidate_id in enumerate(item_ids):
            try:
                candidate = self.classifications.candidate(candidate_id, scope_key)
            except Exception:
                prepared.append({
                    "ordinal": ordinal, "item_id": candidate_id, "candidate_id": candidate_id,
                    "probe_id": None, "classification": "UNKNOWN", "requested_bytes": 0,
                    "decision": "skipped", "reason": "BATCH_ITEM_NOT_FOUND", "plan": None,
                })
                continue
            size = int(candidate.get("logical_bytes", 0))
            requested_bytes += size
            decision = self.classifications.decide(candidate, scope_key)
            expected = SAFE_ACTIONABLE if mode == "safe" else REVIEW_REQUIRED
            if decision.classification != expected:
                plan = None
                reason = "BATCH_CLASSIFICATION_MISMATCH"
            else:
                policy = (self.classifications.safe_policy if mode == "safe"
                          else self.classifications.review_policy)
                plan = policy.preflight(candidate, scope_key, candidate.get("snapshot_mtime"))
                reason = plan["block_reasons"][0] if plan["block_reasons"] else None
                if (mode == "safe" and candidate.get("recorded_size") != candidate.get("logical_bytes")):
                    reason = "SNAPSHOT_RECORD_MISMATCH"
                    plan["block_reasons"].append(reason)
                    plan["eligibility"] = "ineligible"
                    plan["planned_action"] = "none"
            prepared.append({
                "ordinal": ordinal, "item_id": candidate_id, "candidate_id": candidate_id,
                "probe_id": None, "classification": decision.classification,
                "requested_bytes": size, "decision": "approved" if not reason else "skipped",
                "reason": reason, "plan": plan,
            })
        return self._store_prepare(prepared, mode, scope_key, requested_bytes)

    def prepare_probes(self, probe_ids: list[str]) -> dict[str, object]:
        probe_ids = self._validate_ids(probe_ids)
        if self.probes is None:
            raise CleanupError("PROBE_BACKEND_UNAVAILABLE", 503)
        if self._scan_running():
            raise CleanupError("OPERATION_CONFLICT")
        prepared: list[dict[str, object]] = []
        requested_bytes = 0
        with self.snapshots._connection() as connection:
            for ordinal, probe_id in enumerate(probe_ids):
                row = connection.execute(
                    "SELECT * FROM controlled_probes WHERE probe_id = ? AND session_id = ?",
                    (probe_id, self.probes.session_id)).fetchone()
                if row is None:
                    prepared.append({
                        "ordinal": ordinal, "item_id": probe_id, "candidate_id": None,
                        "probe_id": probe_id, "classification": "CONTROLLED_PROBE",
                        "requested_bytes": 0, "decision": "skipped",
                        "reason": "CONTROLLED_PROBE_NOT_FOUND", "plan": None,
                    })
                    continue
                record = dict(row)
                size = int(record["expected_size"])
                requested_bytes += size
                plan = self.probes.preflight(record, "created")
                reason = plan["block_reasons"][0] if plan["block_reasons"] else None
                prepared.append({
                    "ordinal": ordinal, "item_id": probe_id, "candidate_id": None,
                    "probe_id": probe_id, "classification": "CONTROLLED_PROBE",
                    "requested_bytes": size, "decision": "approved" if not reason else "skipped",
                    "reason": reason, "plan": plan,
                })
        result = self._store_prepare(prepared, "controlled_probe", "controlled_probe", requested_bytes)
        if result["execution_token"]:
            with self.snapshots._connection() as connection:
                for item in prepared:
                    if item["decision"] == "approved":
                        self.probes.update_state(connection, str(item["probe_id"]), "prepared")
                connection.commit()
        return result

    def _store_prepare(self, items: list[dict[str, object]], mode: str,
                       scope_key: str, requested_bytes: int) -> dict[str, object]:
        approved = [item for item in items if item["decision"] == "approved"]
        prepared_at = datetime.now(timezone.utc)
        expires_at = prepared_at + timedelta(seconds=TOKEN_LIFETIME_SECONDS)
        token = secrets.token_urlsafe(32) if approved else None
        batch_id = secrets.token_hex(16)
        item_set_digest = self._digest([item["item_id"] for item in approved])
        decision_digest = self._digest([{
            "item_id": item["item_id"], "classification": item["classification"],
            "fingerprint": item["plan"]["fingerprint"],
            "policy_rule_id": item["plan"]["policy_rule_id"],
        } for item in approved])
        approved_bytes = sum(int(item["requested_bytes"]) for item in approved)
        with self._lock, self.snapshots._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("""INSERT INTO cleanup_batches (
                    id, token_hash, session_id, mode, scope_key, status, created_at,
                    expires_at, requested_count, approved_count, skipped_count,
                    success_count, failed_count, requested_bytes, approved_bytes,
                    recycled_bytes, item_set_digest, decision_digest, token_outcome)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, 0, ?, ?, ?)""", (
                    batch_id, hashlib.sha256(token.encode()).hexdigest() if token else None,
                    self.session_id, mode, scope_key, "prepared" if token else "blocked",
                    prepared_at.isoformat(), expires_at.isoformat() if token else None,
                    len(items), len(approved), len(items) - len(approved), requested_bytes,
                    approved_bytes, item_set_digest, decision_digest,
                    "active" if token else "not_issued",
                ))
                connection.executemany("""INSERT INTO cleanup_batch_items (
                    batch_id, ordinal, item_id, candidate_id, probe_id, classification,
                    requested_bytes, original_path, prepare_decision, prepare_reason,
                    policy_rule_id, prepared_fingerprint_json, checks_json,
                    execute_result, execute_reason, recycled_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0)""", (
                    (batch_id, item["ordinal"], item["item_id"], item["candidate_id"],
                     item["probe_id"], item["classification"], item["requested_bytes"],
                     item["plan"]["current_path"] if item["plan"] else None,
                     item["decision"], item["reason"],
                     item["plan"]["policy_rule_id"] if item["plan"] else None,
                     json.dumps(item["plan"]["fingerprint"]) if item["plan"] else None,
                     json.dumps(item["plan"]["checks"]) if item["plan"] else "[]")
                    for item in items
                ))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {
            "batch_id": batch_id, "execution_token": token,
            "expires_at": expires_at.isoformat() if token else None,
            "mode": mode, "scope_key": scope_key, "requested_count": len(items),
            "approved_count": len(approved), "skipped_count": len(items) - len(approved),
            "requested_bytes": requested_bytes, "approved_bytes": approved_bytes,
            "real_execution_enabled": token is not None,
            "items": [{
                "item_id": item["item_id"], "candidate_id": item["candidate_id"],
                "probe_id": item["probe_id"], "classification": item["classification"],
                "decision": item["decision"], "reason": item["reason"],
            } for item in items],
        }

    def execute(self, token: str) -> dict[str, object]:
        if not isinstance(token, str) or not token:
            raise CleanupError("BATCH_TOKEN_INVALID", 404)
        try:
            with operations.cleanup_execution():
                return self._execute_guarded(token)
        except OperationConflict as exc:
            raise CleanupError("OPERATION_CONFLICT") from exc

    def _execute_guarded(self, token: str) -> dict[str, object]:
        if self._scan_running():
            raise CleanupError("OPERATION_CONFLICT")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock, self.snapshots._connection() as connection:
            batch = connection.execute(
                "SELECT * FROM cleanup_batches WHERE token_hash = ?", (token_hash,)).fetchone()
            if batch is None:
                raise CleanupError("BATCH_TOKEN_INVALID", 404)
            batch = dict(batch)
            if batch["session_id"] != self.session_id:
                connection.execute("UPDATE cleanup_batches SET status='expired', token_outcome='expired' WHERE id=?", (batch["id"],))
                connection.commit()
                raise CleanupError("BATCH_TOKEN_EXPIRED")
            if batch["status"] != "prepared":
                raise CleanupError("BATCH_ALREADY_EXECUTED" if batch["status"] != "expired" else "BATCH_TOKEN_EXPIRED")
            if datetime.now(timezone.utc) >= datetime.fromisoformat(batch["expires_at"]):
                connection.execute("UPDATE cleanup_batches SET status='expired', token_outcome='expired' WHERE id=?", (batch["id"],))
                connection.commit()
                raise CleanupError("BATCH_TOKEN_EXPIRED")
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM cleanup_batch_items WHERE batch_id = ? ORDER BY ordinal", (batch["id"],))]
            approved = [row for row in rows if row["prepare_decision"] == "approved"]
            if self._digest([row["item_id"] for row in approved]) != batch["item_set_digest"]:
                raise CleanupError("BATCH_ITEM_SET_CHANGED")
            decision_payload = [{
                "item_id": row["item_id"], "classification": row["classification"],
                "fingerprint": json.loads(row["prepared_fingerprint_json"]),
                "policy_rule_id": row["policy_rule_id"],
            } for row in approved]
            if self._digest(decision_payload) != batch["decision_digest"]:
                raise CleanupError("BATCH_DECISION_CHANGED")
            connection.execute("""UPDATE cleanup_batches SET status='executing', started_at=?,
                token_outcome='consumed' WHERE id=?""", (datetime.now(timezone.utc).isoformat(), batch["id"]))
            connection.commit()

        for row in approved:
            self._execute_item(batch, row)

        with self._lock, self.snapshots._connection() as connection:
            all_rows = [dict(row) for row in connection.execute(
                "SELECT * FROM cleanup_batch_items WHERE batch_id = ? ORDER BY ordinal", (batch["id"],))]
            success = sum(row["execute_result"] == "recycled" for row in all_rows)
            failed = sum(row["execute_result"] == "failed" for row in all_rows)
            skipped = len(all_rows) - success - failed
            recycled_bytes = sum(int(row["recycled_bytes"]) for row in all_rows)
            status = "completed" if success == len(all_rows) else "completed_with_partial_result"
            connection.execute("""UPDATE cleanup_batches SET status=?, completed_at=?,
                success_count=?, skipped_count=?, failed_count=?, recycled_bytes=? WHERE id=?""",
                (status, datetime.now(timezone.utc).isoformat(), success, skipped, failed,
                 recycled_bytes, batch["id"]))
            connection.commit()
        return {
            "batch_id": batch["id"], "status": status, "mode": batch["mode"],
            "requested_count": len(all_rows), "success_count": success,
            "skipped_count": skipped, "failed_count": failed,
            "requested_bytes": batch["requested_bytes"], "recycled_bytes": recycled_bytes,
            "target_mutation": "recycle_bin" if success else "none",
            "items": [{
                "item_id": row["item_id"], "candidate_id": row["candidate_id"],
                "probe_id": row["probe_id"],
                "result": row["execute_result"] or "skipped",
                "reason": row["execute_reason"] or row["prepare_reason"],
                "recycled_bytes": row["recycled_bytes"],
            } for row in all_rows],
        }

    def _execute_item(self, batch: dict[str, object], row: dict[str, object]) -> None:
        plan = None
        path = row["original_path"]
        reason = None
        try:
            if batch["mode"] == "controlled_probe":
                if self.probes is None:
                    reason = "PROBE_BACKEND_UNAVAILABLE"
                else:
                    record = self.probes.get(str(row["probe_id"]))
                    plan = self.probes.preflight(record, "prepared")
            else:
                candidate = self.classifications.candidate(str(row["candidate_id"]), str(batch["scope_key"]))
                decision = self.classifications.decide(candidate, str(batch["scope_key"]))
                expected = SAFE_ACTIONABLE if batch["mode"] == "safe" else REVIEW_REQUIRED
                if decision.classification != expected:
                    reason = "BATCH_CLASSIFICATION_CHANGED"
                policy = (self.classifications.safe_policy if batch["mode"] == "safe"
                          else self.classifications.review_policy)
                plan = policy.preflight(candidate, str(batch["scope_key"]), candidate.get("snapshot_mtime"))
                path = candidate["display_path"]
                if path != row["original_path"]:
                    reason = "TARGET_PATH_CHANGED"
                if batch["mode"] == "safe" and plan["policy_rule_id"] != EXECUTION_RULE_ID:
                    reason = "EXECUTION_POLICY_CHANGED"
                if (batch["mode"] == "safe" and
                        candidate.get("recorded_size") != candidate.get("logical_bytes")):
                    reason = "SNAPSHOT_RECORD_MISMATCH"
                if batch["mode"] == "review" and plan["policy_rule_id"] != REVIEW_POLICY_ID:
                    reason = "EXECUTION_POLICY_CHANGED"
        except Exception:
            reason = "BATCH_ITEM_NO_LONGER_AVAILABLE"
        if plan is not None:
            if plan["block_reasons"]:
                reason = str(plan["block_reasons"][0])
            prepared_fingerprint = json.loads(row["prepared_fingerprint_json"])
            if plan["fingerprint"] is not None and plan["fingerprint"] != prepared_fingerprint:
                reason = "TARGET_CHANGED_SINCE_PREPARE"
        if reason:
            self._record_item(row, "skipped", reason, 0, plan)
            return
        try:
            result = self.recycle_backend.recycle(str(path))
            if not result.original_path_absent or os.path.lexists(str(path)):
                raise RecycleError("RECYCLE_ORIGINAL_PATH_REMAINS")
        except RecycleError as exc:
            self._record_item(row, "failed", exc.code, 0, plan)
            if row["probe_id"] and self.probes:
                with self.snapshots._connection() as connection:
                    self.probes.update_state(connection, str(row["probe_id"]), "failed", exc.code)
                    connection.commit()
            return
        self._record_item(row, "recycled", None, int(row["requested_bytes"]), plan)
        if row["probe_id"] and self.probes:
            with self.snapshots._connection() as connection:
                self.probes.update_state(connection, str(row["probe_id"]), "recycled")
                connection.commit()

    def _record_item(self, row: dict[str, object], result: str, reason: str | None,
                     recycled_bytes: int, plan: dict[str, object] | None) -> None:
        with self.snapshots._connection() as connection:
            connection.execute("""UPDATE cleanup_batch_items SET execute_result=?,
                execute_reason=?, recycled_bytes=?, execute_fingerprint_json=?, completed_at=?
                WHERE id=?""", (
                result, reason, recycled_bytes,
                json.dumps(plan["fingerprint"]) if plan else None,
                datetime.now(timezone.utc).isoformat(), row["id"],
            ))
            connection.commit()

    def list(self, limit: int = 20) -> list[dict[str, object]]:
        with self.snapshots._connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM cleanup_batches ORDER BY created_at DESC LIMIT ?", (limit,))]

    def detail(self, batch_id: str) -> dict[str, object]:
        with self.snapshots._connection() as connection:
            batch = connection.execute("SELECT * FROM cleanup_batches WHERE id=?", (batch_id,)).fetchone()
            if batch is None:
                raise CleanupError("BATCH_NOT_FOUND", 404)
            items = [dict(row) for row in connection.execute(
                "SELECT * FROM cleanup_batch_items WHERE batch_id=? ORDER BY ordinal", (batch_id,))]
            return {"batch": dict(batch), "items": items}


batch_cleanup_service = BatchCleanupService(probes=cleanup_service.probes)
