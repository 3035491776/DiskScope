"""Read-only eligibility explanations over persisted candidate metadata."""

from __future__ import annotations

import json
import ntpath
import time
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from app.cleanup.policy import (
    ELIGIBLE_REASON, EXECUTION_POLICY_VERSION, EXECUTION_RULE_ID,
    POLICY_EVALUATION_ERROR, ExecutionPolicyEngine, PolicyDecision,
)
from app.intelligence.store import CandidateStore, candidate_store


DIAGNOSTIC_SCOPES = frozenset({"current_user_temp", "system_drive_c"})
FILTERS = frozenset({"all", "eligible", "blocked", "high_risk", "recent", "extension_blocked"})
SORTS = frozenset({"size_desc", "age_desc"})


class InvalidDiagnosticsRequest(ValueError):
    pass


def _size(candidate: dict[str, object]) -> int:
    try:
        return max(0, int(candidate.get("logical_bytes", 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _distribution(entries: Iterable[tuple[str, int]]) -> list[dict[str, object]]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for code, size in entries:
        totals[code][0] += 1
        totals[code][1] += size
    return [
        {"reason_code": code, "candidate_count": values[0], "total_bytes": values[1]}
        for code, values in sorted(totals.items(), key=lambda item: (-item[1][0], item[0]))
    ]


class EligibilityDiagnostics:
    """Advisory evaluation only; it never calls prepare or execution services."""

    def __init__(self, candidates: CandidateStore = candidate_store,
                 policy: ExecutionPolicyEngine | None = None):
        self.candidates = candidates
        self.policy = policy or ExecutionPolicyEngine()

    @staticmethod
    def _validate_scope(scope_key: str) -> str:
        if scope_key not in DIAGNOSTIC_SCOPES:
            raise InvalidDiagnosticsRequest("INVALID_DIAGNOSTICS_SCOPE")
        return scope_key

    def _evaluate(self, scope_key: str) -> tuple[dict[str, object], datetime, list[tuple[dict[str, object], PolicyDecision]]]:
        self._validate_scope(scope_key)
        dataset = self.candidates.diagnostics_dataset(scope_key)
        evaluated_at = self.policy.now()
        decisions = [
            (candidate, self.policy.evaluate(
                candidate, scope_key, candidate.get("snapshot_mtime"), evaluated_at,
            ))
            for candidate in dataset["candidates"]
        ]
        return dataset, evaluated_at, decisions

    @staticmethod
    def _candidate_payload(candidate: dict[str, object], decision: PolicyDecision,
                           context: dict[str, object]) -> dict[str, object]:
        relative_path = str(candidate.get("relative_path", ""))
        try:
            candidate_evidence = json.loads(str(candidate.get("evidence_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            candidate_evidence = []
        return {
            "candidate_id": candidate.get("candidate_id"),
            "file_name": ntpath.basename(relative_path.replace("/", "\\")),
            "relative_path": relative_path,
            "display_path": candidate.get("display_path"),
            "logical_bytes": _size(candidate),
            "snapshot_time": context.get("scan_completed_at"),
            "snapshot_mtime": candidate.get("snapshot_mtime"),
            "age_days": decision.evidence.get("age_days"),
            "object_type": candidate.get("object_type"),
            "category": candidate.get("category"),
            "risk_level": candidate.get("risk_level"),
            "confidence": candidate.get("confidence"),
            "candidate_reason_code": candidate.get("reason_code"),
            "candidate_rule_id": candidate.get("source_rule_id"),
            "candidate_rule_version": candidate.get("rule_version"),
            "candidate_evidence": candidate_evidence,
            "decision": decision.to_dict(),
            "limitations": ["historical_metadata_is_advisory", "prepare_preflight_required"],
        }

    @staticmethod
    def _age_distribution(decisions: list[tuple[dict[str, object], PolicyDecision]]) -> list[dict[str, object]]:
        buckets = {key: [0, 0] for key in ("under_7_days", "7_to_14_days", "14_to_30_days",
                                                   "30_to_90_days", "90_plus_days", "unknown")}
        for candidate, decision in decisions:
            age = decision.evidence.get("age_days")
            if not isinstance(age, (int, float)):
                key = "unknown"
            elif age < 7:
                key = "under_7_days"
            elif age < 14:
                key = "7_to_14_days"
            elif age < 30:
                key = "14_to_30_days"
            elif age < 90:
                key = "30_to_90_days"
            else:
                key = "90_plus_days"
            buckets[key][0] += 1
            buckets[key][1] += _size(candidate)
        return [{"bucket": key, "candidate_count": values[0], "total_bytes": values[1]}
                for key, values in buckets.items()]

    def summary(self, scope_key: str) -> dict[str, object]:
        started = time.perf_counter()
        dataset, evaluated_at, decisions = self._evaluate(scope_key)
        run = dataset["run"]
        snapshot = dataset["snapshot"]
        eligible = [(candidate, decision) for candidate, decision in decisions
                    if decision.eligibility == "eligible_for_recycle"]
        blocked = [(candidate, decision) for candidate, decision in decisions
                   if decision.eligibility != "eligible_for_recycle"]
        primary = _distribution((decision.primary_reason, _size(candidate))
                                for candidate, decision in decisions)
        all_reasons = _distribution((code, _size(candidate))
                                    for candidate, decision in decisions
                                    for code in decision.reason_codes)
        return {
            "scope": scope_key,
            "snapshot_id": run["snapshot_id"],
            "candidate_analysis_run_id": run["run_id"],
            "candidate_rule_version": run["rule_version"],
            "policy_rule_id": EXECUTION_RULE_ID,
            "execution_policy_version": EXECUTION_POLICY_VERSION,
            "evaluation_basis": "snapshot_only",
            "execution_authority": False,
            "evaluated_at": evaluated_at.isoformat(),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "evaluated_candidate_count": len(decisions),
            "eligible_count": len(eligible),
            "blocked_count": len(blocked),
            "eligible_bytes": sum(_size(candidate) for candidate, _ in eligible),
            "blocked_bytes": sum(_size(candidate) for candidate, _ in blocked),
            "evaluation_error_count": sum(
                decision.primary_reason == POLICY_EVALUATION_ERROR for _, decision in decisions
            ),
            "primary_reason_distribution": primary,
            "all_reason_distribution": all_reasons,
            "age_distribution": self._age_distribution(decisions),
            "coverage": {
                "snapshot_coverage": snapshot["coverage"],
                "file_persistence_mode": snapshot["file_persistence_mode"],
                "file_persistence_limit": snapshot["file_persistence_limit"],
                "persisted_file_count": snapshot["persisted_file_count"],
                "observed_file_count": snapshot["observed_file_count"],
                "file_metadata_coverage": (
                    "complete" if snapshot["persisted_file_count"] == snapshot["observed_file_count"]
                    else "limited"
                ),
            },
            "semantics": {
                "primary_reason_counts_sum_to_evaluated": True,
                "all_reason_counts_may_overlap": True,
                "zero_eligible_means": "no_evaluated_candidate_met_every_policy_condition",
            },
        }

    @staticmethod
    def _matches(filter_key: str, candidate: dict[str, object], decision: PolicyDecision) -> bool:
        if filter_key == "all":
            return True
        if filter_key == "eligible":
            return decision.eligibility == "eligible_for_recycle"
        if filter_key == "blocked":
            return decision.eligibility != "eligible_for_recycle"
        if filter_key == "high_risk":
            return candidate.get("risk_level") == "high"
        if filter_key == "recent":
            return "EXECUTION_FILE_TOO_RECENT" in decision.reason_codes
        return "EXECUTION_EXTENSION_BLOCKED" in decision.reason_codes

    def list(self, scope_key: str, limit: int = 50, offset: int = 0,
             filter_key: str = "all", sort: str = "size_desc") -> dict[str, object]:
        if filter_key not in FILTERS:
            raise InvalidDiagnosticsRequest("INVALID_DIAGNOSTICS_FILTER")
        if sort not in SORTS:
            raise InvalidDiagnosticsRequest("INVALID_DIAGNOSTICS_SORT")
        dataset, evaluated_at, decisions = self._evaluate(scope_key)
        filtered = [(candidate, decision) for candidate, decision in decisions
                    if self._matches(filter_key, candidate, decision)]
        if sort == "age_desc":
            filtered.sort(key=lambda item: (
                item[1].evidence.get("age_days") is None,
                -float(item[1].evidence.get("age_days") or 0),
                str(item[0].get("relative_path", "")).casefold(),
            ))
        else:
            filtered.sort(key=lambda item: (
                -_size(item[0]), str(item[0].get("relative_path", "")).casefold(),
            ))
        page = filtered[offset:offset + limit]
        return {
            "scope": scope_key,
            "snapshot_id": dataset["run"]["snapshot_id"],
            "candidate_analysis_run_id": dataset["run"]["run_id"],
            "policy_rule_id": EXECUTION_RULE_ID,
            "execution_policy_version": EXECUTION_POLICY_VERSION,
            "evaluation_basis": "snapshot_only",
            "execution_authority": False,
            "evaluated_at": evaluated_at.isoformat(),
            "filter": filter_key,
            "sort": sort,
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "items": [self._candidate_payload(candidate, decision, dataset["run"])
                      for candidate, decision in page],
        }

    def detail(self, candidate_id: str, scope_key: str) -> dict[str, object]:
        self._validate_scope(scope_key)
        candidate = self.candidates.diagnostics_candidate(candidate_id, scope_key)
        evaluated_at = self.policy.now()
        decision = self.policy.evaluate(
            candidate, scope_key, candidate.get("snapshot_mtime"), evaluated_at,
        )
        return {
            "scope": scope_key,
            "snapshot_id": candidate["snapshot_id"],
            "candidate_analysis_run_id": candidate["candidate_analysis_run_id"],
            "coverage": {
                "snapshot_coverage": candidate["snapshot_coverage"],
                "file_persistence_mode": candidate["file_persistence_mode"],
                "file_persistence_limit": candidate["file_persistence_limit"],
                "persisted_file_count": candidate["persisted_file_count"],
                "observed_file_count": candidate["observed_file_count"],
            },
            "candidate": self._candidate_payload(candidate, decision, candidate),
        }


eligibility_diagnostics = EligibilityDiagnostics()
