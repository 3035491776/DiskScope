"""User-facing cleanup classification without granting execution authority."""

from __future__ import annotations

import ntpath
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from app.cleanup.policy import (
    BLOCKED_EXTENSIONS, POLICY_EVALUATION_ERROR, PROTECTED_NAMES, PROTECTED_ROOTS,
    REPARSE_FLAG, ExecutionPolicyEngine, _parts,
)
from app.cleanup.categories import REVIEW_ROOTS
from app.intelligence.store import CandidateNotFound
from app.snapshots.store import SnapshotStore, snapshot_store


SAFE_ACTIONABLE = "SAFE_ACTIONABLE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
DO_NOT_TOUCH = "DO_NOT_TOUCH"
REVIEW_POLICY_ID = "USER_PROFILE_MANUAL_REVIEW_V1"
REVIEW_POLICY_VERSION = "review-policy-v1.0.0"


def _mtime(info: os.stat_result) -> str | None:
    try:
        return datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


class ManualReviewPolicy:
    """Deny-by-default authorization for ordinary files in explicit user folders."""

    def __init__(self, user_profile: str | None = None,
                 lstat: Callable[[str], os.stat_result] = os.lstat):
        self.user_profile = user_profile if user_profile is not None else os.environ.get("USERPROFILE", "")
        self.lstat = lstat

    def static_reasons(self, candidate: Mapping[str, object], scope_key: str) -> list[str]:
        path = str(candidate.get("display_path", ""))
        parts = _parts(path)
        profile = _parts(self.user_profile)
        reasons: list[str] = []
        if scope_key != "system_drive_c":
            reasons.append("MANUAL_REVIEW_SCOPE_BLOCKED")
        if candidate.get("object_type") != "file":
            reasons.append("DIRECTORY_EXECUTION_NOT_SUPPORTED")
        if parts is None or profile is None:
            reasons.append("MANUAL_REVIEW_PATH_BLOCKED")
        else:
            if parts[0] in PROTECTED_ROOTS or parts[-1] in PROTECTED_NAMES:
                reasons.append("EXECUTION_PROTECTED_PATH")
            if (len(parts) <= len(profile) + 1 or parts[:len(profile)] != profile or
                    parts[len(profile)] not in REVIEW_ROOTS):
                reasons.append("MANUAL_REVIEW_LOCATION_BLOCKED")
            if ntpath.splitext(parts[-1])[1].casefold() in BLOCKED_EXTENSIONS:
                reasons.append("EXECUTION_EXTENSION_BLOCKED")
        if candidate.get("execution_state") == "recycled":
            reasons.append("ALREADY_EXECUTED")
        if candidate.get("reason_code") in {None, "", POLICY_EVALUATION_ERROR}:
            reasons.append("MANUAL_REVIEW_UNKNOWN_SAFETY")
        return list(dict.fromkeys(reasons))

    def preflight(self, candidate: Mapping[str, object], scope_key: str,
                  snapshot_mtime: str | None) -> dict[str, object]:
        reasons = self.static_reasons(candidate, scope_key)
        path = str(candidate.get("display_path", ""))
        fingerprint = None
        current_size = None
        current_mtime = None
        checks: list[dict[str, object]] = []
        parts = _parts(path)
        if not reasons and parts is not None:
            prefixes = ["C:\\"]
            for index in range(1, len(parts) + 1):
                prefixes.append(ntpath.join("C:\\", *parts[:index]))
            try:
                root = self.lstat(prefixes[0])
                root_device = root.st_dev
                for index, prefix in enumerate(prefixes[1:], 1):
                    info = self.lstat(prefix)
                    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_FLAG:
                        reasons.append("EXECUTION_REPARSE_POINT_BLOCKED")
                        break
                    if info.st_dev != root_device:
                        reasons.append("EXECUTION_CROSS_VOLUME_BLOCKED")
                        break
                    if index < len(prefixes) - 1 and not stat.S_ISDIR(info.st_mode):
                        reasons.append("EXECUTION_PARENT_CHANGED")
                        break
                    if index == len(prefixes) - 1:
                        if not stat.S_ISREG(info.st_mode):
                            reasons.append("DIRECTORY_EXECUTION_NOT_SUPPORTED")
                            break
                        current_size = info.st_size
                        current_mtime = _mtime(info)
                        fingerprint = {
                            "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                            "ctime_ns": getattr(info, "st_ctime_ns", 0),
                            "mode": stat.S_IFMT(info.st_mode), "device": info.st_dev,
                            "inode": info.st_ino,
                            "attributes": getattr(info, "st_file_attributes", 0),
                        }
            except FileNotFoundError:
                reasons.append("TARGET_NO_LONGER_EXISTS")
            except PermissionError:
                reasons.append("ACCESS_DENIED")
            except OSError as exc:
                reasons.append("TARGET_IN_USE" if getattr(exc, "winerror", None) == 32 else "TARGET_METADATA_ERROR")
        if fingerprint is not None:
            try:
                recorded = datetime.fromisoformat(str(snapshot_mtime).replace("Z", "+00:00"))
                same_mtime = abs(recorded.timestamp() - fingerprint["mtime_ns"] / 1e9) < 0.000001
            except (ValueError, TypeError, OverflowError):
                same_mtime = False
            if current_size != int(candidate.get("logical_bytes", -1)) or not same_mtime:
                reasons.append("TARGET_CHANGED_SINCE_SCAN")
        checks.extend([
            {"check": "manual_review_static_boundary", "passed": not self.static_reasons(candidate, scope_key)},
            {"check": "current_filesystem_metadata", "passed": fingerprint is not None},
            {"check": "snapshot_fingerprint", "passed": fingerprint is not None and "TARGET_CHANGED_SINCE_SCAN" not in reasons},
        ])
        reasons = list(dict.fromkeys(reasons))
        return {
            "candidate_id": candidate.get("candidate_id"), "current_path": path,
            "policy_rule_id": REVIEW_POLICY_ID, "execution_rule_id": REVIEW_POLICY_ID,
            "snapshot_size": candidate.get("logical_bytes"), "snapshot_mtime": snapshot_mtime,
            "current_size": current_size, "current_mtime": current_mtime,
            "eligibility": "eligible_for_review" if not reasons else "ineligible",
            "allowed_actions": ["recycle"] if not reasons else [],
            "checks": checks, "block_reasons": reasons,
            "planned_action": "recycle" if not reasons else "none",
            "fingerprint": fingerprint,
        }


@dataclass(frozen=True)
class ClassificationDecision:
    classification: str
    reason: str
    reason_codes: tuple[str, ...]
    authorization_policy: str | None


class CleanupClassificationService:
    def __init__(self, snapshots: SnapshotStore = snapshot_store,
                 safe_policy: ExecutionPolicyEngine | None = None,
                 review_policy: ManualReviewPolicy | None = None):
        self.snapshots = snapshots
        self.safe_policy = safe_policy or ExecutionPolicyEngine()
        self.review_policy = review_policy or ManualReviewPolicy()

    def decide(self, candidate: Mapping[str, object], scope_key: str) -> ClassificationDecision:
        if candidate.get("execution_state") == "recycled":
            return ClassificationDecision(DO_NOT_TOUCH, "这个文件已经处理过。", ("ALREADY_EXECUTED",), None)
        safe = self.safe_policy.evaluate(candidate, scope_key, candidate.get("snapshot_mtime"))
        if safe.eligibility == "eligible_for_recycle":
            return ClassificationDecision(
                SAFE_ACTIONABLE, "较旧的临时文件，已通过 DiskScope 当前的安全检查。",
                tuple(safe.reason_codes), safe.policy_rule_id,
            )
        review_reasons = self.review_policy.static_reasons(candidate, scope_key)
        if not review_reasons:
            path_parts = _parts(str(candidate.get("display_path", ""))) or ()
            folder = path_parts[len(_parts(self.review_policy.user_profile) or ())] if path_parts else ""
            return ClassificationDecision(
                REVIEW_REQUIRED,
                f"这是你“{folder.title()}”文件夹中的文件，DiskScope 无法判断你是否仍然需要它。",
                tuple(safe.reason_codes), REVIEW_POLICY_ID,
            )
        codes = tuple(dict.fromkeys((*safe.reason_codes, *review_reasons)))
        if candidate.get("object_type") != "file":
            reason = "DiskScope 不处理文件夹。"
        elif "EXECUTION_EXTENSION_BLOCKED" in codes:
            reason = "这种文件类型受到安全规则保护。"
        elif "EXECUTION_PROTECTED_PATH" in codes:
            reason = "这个文件位于受保护位置。"
        elif "MANUAL_REVIEW_LOCATION_BLOCKED" in codes:
            reason = "这个位置不在允许人工确认处理的个人文件夹范围内。"
        else:
            reason = "当前安全信息不足，DiskScope 不建议处理。"
        return ClassificationDecision(DO_NOT_TOUCH, reason, codes, None)

    def _latest(self, scope_key: str) -> tuple[dict[str, object], list[dict[str, object]]]:
        if scope_key not in {"system_drive_c", "current_user_temp"}:
            raise CandidateNotFound("CLEANUP_SCOPE_NOT_AVAILABLE")
        with self.snapshots._connection() as connection:
            run = connection.execute("""SELECT r.id, r.snapshot_id, r.created_at,
                s.completed_at AS scan_completed_at, s.coverage, s.scope_key
                FROM candidate_runs r JOIN scan_snapshots s ON s.id = r.snapshot_id
                WHERE s.scope_key = ? AND r.status = 'completed'
                ORDER BY s.completed_at DESC, r.created_at DESC, r.id DESC LIMIT 1""",
                (scope_key,)).fetchone()
            if run is None:
                raise CandidateNotFound("CANDIDATE_RUN_NOT_FOUND")
            items = [dict(row) for row in connection.execute("""SELECT c.*,
                f.mtime AS snapshot_mtime, f.size_bytes AS recorded_size,
                CASE WHEN EXISTS(SELECT 1 FROM cleanup_execution_runs e
                    WHERE e.candidate_id = c.candidate_id AND e.status = 'completed'
                    AND e.target_mutation = 'recycle_bin')
                    OR EXISTS(SELECT 1 FROM cleanup_batch_items bi
                    WHERE bi.candidate_id = c.candidate_id AND bi.execute_result = 'recycled')
                    THEN 'recycled' ELSE 'available' END AS execution_state
                FROM cleanup_candidates c
                JOIN candidate_runs r ON r.id = c.run_id
                LEFT JOIN file_snapshots f ON f.snapshot_id = r.snapshot_id
                    AND f.relative_path = c.relative_path
                WHERE c.run_id = ? AND c.group_id IS NULL
                ORDER BY c.logical_bytes DESC, c.relative_path""", (run["id"],))]
            return dict(run), items

    def listing(self, scope_key: str, per_class_limit: int = 200) -> dict[str, object]:
        run, candidates = self._latest(scope_key)
        groups = {SAFE_ACTIONABLE: [], REVIEW_REQUIRED: [], DO_NOT_TOUCH: []}
        summary = {key: {"count": 0, "bytes": 0} for key in groups}
        for candidate in candidates:
            decision = self.decide(candidate, scope_key)
            summary[decision.classification]["count"] += 1
            summary[decision.classification]["bytes"] += int(candidate["logical_bytes"])
            if len(groups[decision.classification]) < per_class_limit:
                public = {key: candidate.get(key) for key in (
                    "candidate_id", "display_path", "relative_path", "object_type",
                    "logical_bytes", "snapshot_mtime", "title", "category", "risk_level",
                    "confidence", "reason_code", "source_rule_id", "execution_state",
                )}
                public.update({
                    "classification": decision.classification, "reason": decision.reason,
                    "reason_codes": list(decision.reason_codes),
                    "authorization_policy": decision.authorization_policy,
                })
                groups[decision.classification].append(public)
        return {
            "scope_key": scope_key, "run": run, "summary": summary,
            "items": groups, "per_class_limit": per_class_limit,
            "truncated": {key: summary[key]["count"] > len(groups[key]) for key in groups},
        }

    def candidate(self, candidate_id: str, scope_key: str) -> dict[str, object]:
        if candidate_id.startswith("triage:"):
            try:
                row_id = int(candidate_id.removeprefix("triage:"))
            except ValueError as exc:
                raise CandidateNotFound(candidate_id) from exc
            with self.snapshots._connection() as connection:
                row = connection.execute("""SELECT t.*, s.root_path, s.scope_key,
                    CASE WHEN EXISTS(SELECT 1 FROM cleanup_batch_items bi
                        WHERE bi.candidate_id=? AND bi.execute_result='recycled')
                        THEN 'recycled' ELSE 'available' END AS execution_state
                    FROM triage_files t JOIN scan_snapshots s ON s.id=t.snapshot_id
                    WHERE t.id=? AND s.scope_key=? AND t.snapshot_id=(
                        SELECT id FROM scan_snapshots WHERE scope_key=?
                        ORDER BY completed_at DESC, created_at DESC, id DESC LIMIT 1
                    )""", (candidate_id, row_id, scope_key, scope_key)).fetchone()
                if row is None:
                    raise CandidateNotFound(candidate_id)
                item = dict(row)
                return {
                    "candidate_id": candidate_id,
                    "display_path": ntpath.join(str(item["root_path"]), str(item["relative_path"]).replace("/", "\\")),
                    "relative_path": item["relative_path"], "object_type": "file",
                    "logical_bytes": item["size_bytes"], "recorded_size": item["size_bytes"],
                    "snapshot_mtime": item["mtime"], "title": item["name"],
                    "category": item["category"], "risk_level": "review",
                    "confidence": "medium", "reason_code": "TRIAGE_PERSONAL_FILE",
                    "source_rule_id": "TRIAGE_PERSONAL_FILE_V1",
                    "execution_state": item["execution_state"],
                }
        _, candidates = self._latest(scope_key)
        item = next((item for item in candidates if item["candidate_id"] == candidate_id), None)
        if item is None:
            raise CandidateNotFound(candidate_id)
        return item


cleanup_classifications = CleanupClassificationService()
