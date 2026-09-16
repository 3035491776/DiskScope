"""Versioned candidate runs over saved SQLite metadata, without target access."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from app.intelligence.engine import RuleEngine
from app.intelligence.rules import RULE_VERSION
from app.snapshots.store import SUMMARY_COLUMNS, SnapshotNotFound, SnapshotStore, snapshot_store


ALLOWED_SCOPES = frozenset({"fixture_sample", "project_workspace", "system_drive_c"})
ANALYSIS_COVERAGE = "top_k_and_directories"
RISK_ORDER = {"review": 0, "low": 1, "high": 2, "protected": 3}


class InvalidCandidateScope(ValueError):
    pass


class CandidateNotFound(LookupError):
    pass


def validate_scope(scope_key: str) -> str:
    if scope_key not in ALLOWED_SCOPES:
        raise InvalidCandidateScope("INVALID_CANDIDATE_SCOPE")
    return scope_key


class CandidateStore:
    def __init__(self, snapshots: SnapshotStore = snapshot_store,
                 engine: RuleEngine | None = None):
        self.snapshots = snapshots
        self.engine = engine or RuleEngine()

    def analyze_snapshot(self, snapshot_id: str) -> dict[str, object]:
        with self.snapshots._connection() as connection:
            snapshot_row = connection.execute(
                f"SELECT {SUMMARY_COLUMNS} FROM scan_snapshots WHERE id = ?", (snapshot_id,),
            ).fetchone()
            if snapshot_row is None:
                raise SnapshotNotFound(snapshot_id)
            snapshot = dict(snapshot_row)
            validate_scope(str(snapshot["scope_key"]))
            existing = connection.execute(
                "SELECT id FROM candidate_runs WHERE snapshot_id = ? AND rule_version = ?",
                (snapshot_id, RULE_VERSION),
            ).fetchone()
            if existing:
                return self.get_run(str(existing["id"]))
            started = time.perf_counter()
            files = (dict(row) for row in connection.execute(
                "SELECT relative_path, name, size_bytes, mtime FROM file_snapshots "
                "WHERE snapshot_id = ? ORDER BY relative_path", (snapshot_id,),
            ))
            # Stream directory rows: a real C snapshot can have hundreds of thousands.
            directories = (dict(row) for row in connection.execute(
                "SELECT relative_path, subtree_bytes, coverage FROM directory_snapshots "
                "WHERE snapshot_id = ? ORDER BY relative_path", (snapshot_id,),
            ))
            candidates = self.engine.analyze(snapshot, files, directories)
            duration_ms = round((time.perf_counter() - started) * 1000)

        run_id = str(uuid.uuid4())
        with self.snapshots._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                # The unique pair makes concurrent or repeated analysis idempotent.
                existing = connection.execute(
                    "SELECT id FROM candidate_runs WHERE snapshot_id = ? AND rule_version = ?",
                    (snapshot_id, RULE_VERSION),
                ).fetchone()
                if existing:
                    connection.commit()
                    return self.get_run(str(existing["id"]))
                connection.execute("""INSERT INTO candidate_runs
                    (id, snapshot_id, rule_version, created_at, status, duration_ms, analysis_coverage)
                    VALUES (?, ?, ?, ?, 'completed', ?, ?)""", (
                    run_id, snapshot_id, RULE_VERSION, datetime.now(timezone.utc).isoformat(),
                    duration_ms, ANALYSIS_COVERAGE,
                ))
                connection.executemany("""INSERT INTO cleanup_candidates
                    (candidate_id, run_id, relative_path, display_path, object_type,
                     logical_bytes, category, risk_level, confidence, reason_code,
                     title, summary, explanation, evidence_json, recommended_action,
                     requires_manual_review, source_rule_id, rule_version, group_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    (item["candidate_id"], run_id, item["relative_path"], item["display_path"],
                     item["object_type"], item["logical_bytes"], item["category"],
                     item["risk_level"], item["confidence"], item["reason_code"],
                     item["title"], item["summary"], item["explanation"],
                     json.dumps(item["evidence"], ensure_ascii=False), item["recommended_action"],
                     int(bool(item["requires_manual_review"])), item["source_rule_id"],
                     item["rule_version"], item["group_id"])
                    for item in candidates
                ))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_run(run_id)

    @staticmethod
    def _candidate(row) -> dict[str, object]:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json"))
        item["requires_manual_review"] = bool(item["requires_manual_review"])
        recycled = bool(item.pop("was_recycled", 0))
        item["execution_state"] = "recycled" if recycled else "available"
        return item

    @staticmethod
    def _summary(connection, run_id: str) -> dict[str, object]:
        rows = [dict(row) for row in connection.execute(
            "SELECT object_type, logical_bytes, category, risk_level, confidence, group_id "
            "FROM cleanup_candidates WHERE run_id = ?", (run_id,),
        )]
        visible = [row for row in rows if row["group_id"] is None]
        def count_by(key: str) -> dict[str, int]:
            result: dict[str, int] = {}
            for row in visible:
                value = str(row[key])
                result[value] = result.get(value, 0) + 1
            return dict(sorted(result.items()))
        return {
            "candidate_count": len(visible),
            # Count leaf files only. Groups and directories may overlap those files.
            "candidate_bytes": sum(int(row["logical_bytes"]) for row in rows
                                   if row["object_type"] == "file" and row["risk_level"] in {"review", "low"}),
            "by_category": count_by("category"), "by_risk": count_by("risk_level"),
            "by_confidence": count_by("confidence"),
            "protected_count": sum(row["risk_level"] == "protected" for row in visible),
            "review_count": sum(row["risk_level"] == "review" for row in visible),
            "low_count": sum(row["risk_level"] == "low" for row in visible),
            "unknown_count": sum(row["category"] == "unknown" for row in visible),
        }

    @staticmethod
    def _run(connection, run_id: str) -> dict[str, object]:
        row = connection.execute("""SELECT r.id AS run_id, r.snapshot_id, r.rule_version,
            r.created_at, r.status, r.duration_ms, r.analysis_coverage,
            s.scope_key, s.scope_label, s.completed_at AS scan_completed_at,
            s.coverage AS snapshot_coverage, s.error_count, s.skipped_count
            FROM candidate_runs r JOIN scan_snapshots s ON s.id = r.snapshot_id
            WHERE r.id = ?""", (run_id,)).fetchone()
        if row is None:
            raise CandidateNotFound(run_id)
        return dict(row)

    def get_run(self, run_id: str) -> dict[str, object]:
        with self.snapshots._connection() as connection:
            run = self._run(connection, run_id)
            return {"run": run, "summary": self._summary(connection, run_id)}

    def list_runs(self, scope_key: str, limit: int = 20) -> list[dict[str, object]]:
        validate_scope(scope_key)
        with self.snapshots._connection() as connection:
            rows = connection.execute("""SELECT r.id FROM candidate_runs r
                JOIN scan_snapshots s ON s.id = r.snapshot_id WHERE s.scope_key = ?
                AND r.status = 'completed' ORDER BY s.completed_at DESC,
                r.created_at DESC, r.id DESC LIMIT ?""", (scope_key, limit)).fetchall()
            return [self._run(connection, str(row["id"])) for row in rows]

    def list_latest(self, scope_key: str, category: str | None = None,
                    risk: str | None = None, confidence: str | None = None,
                    limit: int = 200) -> dict[str, object]:
        validate_scope(scope_key)
        with self.snapshots._connection() as connection:
            latest_snapshot = connection.execute(
                f"SELECT {SUMMARY_COLUMNS} FROM scan_snapshots WHERE scope_key = ? "
                "ORDER BY completed_at DESC, created_at DESC, id DESC LIMIT 1", (scope_key,),
            ).fetchone()
            row = connection.execute("""SELECT r.id FROM candidate_runs r
                JOIN scan_snapshots s ON s.id = r.snapshot_id WHERE s.scope_key = ?
                AND r.status = 'completed' ORDER BY s.completed_at DESC,
                r.created_at DESC, r.id DESC LIMIT 1""", (scope_key,)).fetchone()
            if row is None:
                return {"latest_snapshot": dict(latest_snapshot) if latest_snapshot else None,
                        "run": None, "summary": None, "items": [], "total": 0}
            run_id = str(row["id"])
            conditions = ["c.run_id = ?", "c.group_id IS NULL"]
            params: list[object] = [run_id]
            for column, value in (("category", category), ("risk_level", risk), ("confidence", confidence)):
                if value:
                    conditions.append(f"c.{column} = ?")
                    params.append(value)
            where = " AND ".join(conditions)
            total = connection.execute(
                f"SELECT COUNT(*) FROM cleanup_candidates c WHERE {where}", params).fetchone()[0]
            rows = connection.execute(
                f"""SELECT c.*, f.mtime AS snapshot_mtime,
                EXISTS(SELECT 1 FROM cleanup_execution_runs e
                    WHERE e.candidate_id = c.candidate_id AND e.status = 'completed'
                    AND e.target_mutation = 'recycle_bin') AS was_recycled
                FROM cleanup_candidates c
                JOIN candidate_runs cr ON cr.id = c.run_id
                LEFT JOIN file_snapshots f ON f.snapshot_id = cr.snapshot_id
                    AND f.relative_path = c.relative_path
                WHERE {where} """
                "ORDER BY CASE c.risk_level WHEN 'review' THEN 0 WHEN 'low' THEN 1 "
                "WHEN 'high' THEN 2 ELSE 3 END, c.logical_bytes DESC, c.relative_path LIMIT ?",
                (*params, limit),
            ).fetchall()
            items = sorted((self._candidate(item) for item in rows),
                           key=lambda item: (RISK_ORDER.get(str(item["risk_level"]), 4),
                                             -int(item["logical_bytes"]), str(item["relative_path"]).casefold()))
            return {"latest_snapshot": dict(latest_snapshot) if latest_snapshot else None,
                    "run": self._run(connection, run_id), "summary": self._summary(connection, run_id),
                    "items": items, "total": total}

    def detail(self, candidate_id: str, scope_key: str) -> dict[str, object]:
        validate_scope(scope_key)
        with self.snapshots._connection() as connection:
            row = connection.execute("""SELECT c.*, f.mtime AS snapshot_mtime,
                EXISTS(SELECT 1 FROM cleanup_execution_runs e
                    WHERE e.candidate_id = c.candidate_id AND e.status = 'completed'
                    AND e.target_mutation = 'recycle_bin') AS was_recycled
                FROM cleanup_candidates c
                JOIN candidate_runs r ON r.id = c.run_id
                JOIN scan_snapshots s ON s.id = r.snapshot_id
                LEFT JOIN file_snapshots f ON f.snapshot_id = r.snapshot_id
                    AND f.relative_path = c.relative_path
                WHERE c.candidate_id = ? AND s.scope_key = ?""", (candidate_id, scope_key)).fetchone()
            if row is None:
                raise CandidateNotFound(candidate_id)
            item = self._candidate(row)
            members = []
            if item["object_type"] == "group":
                members = [self._candidate(member) for member in connection.execute(
                    "SELECT * FROM cleanup_candidates WHERE group_id = ? ORDER BY logical_bytes DESC, relative_path",
                    (candidate_id,),
                )]
            return {"candidate": item, "members": members}


candidate_store = CandidateStore()
