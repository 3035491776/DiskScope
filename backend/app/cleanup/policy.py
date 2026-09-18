"""Independent, deny-by-default execution policy and metadata-only preflight."""

from __future__ import annotations

import ntpath
import os
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

PROTECTED_ROOTS = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "recovery", "system volume information", "$recycle.bin", "boot", "efi",
})
PROTECTED_NAMES = frozenset({"hiberfil.sys", "pagefile.sys", "swapfile.sys", "bootmgr"})
MIN_BYTES = 1024 * 1024
MIN_AGE_DAYS = 30
EXECUTION_RULE_ID = "USER_TEMP_STALE_FILE_V1"
EXECUTION_POLICY_VERSION = "execution-policy-v1.0.0"
EVALUATION_BASIS = "snapshot_only"
ELIGIBLE_REASON = "ELIGIBLE_USER_TEMP_STALE_FILE"
POLICY_EVALUATION_ERROR = "POLICY_EVALUATION_ERROR"
BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".msi", ".msp", ".cab",
    ".ps1", ".bat", ".cmd", ".com", ".scr", ".dmp",
})
REPARSE_FLAG = 0x400
RESERVED_DOS_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})

# The first matching code is the primary reason. Keep this explicit and stable:
# summary counts and candidate explanations depend on the order.
REASON_PRIORITY = (
    "EXECUTION_PROTECTED_PATH",
    "EXECUTION_SCOPE_BLOCKED",
    "EXECUTION_CURRENT_USER_TEMP_ONLY",
    "EXECUTION_PATH_BLOCKED",
    "DIRECTORY_EXECUTION_NOT_SUPPORTED",
    "EXECUTION_REPARSE_POINT_BLOCKED",
    "EXECUTION_PARENT_CHANGED",
    "EXECUTION_CROSS_VOLUME_BLOCKED",
    "UNKNOWN_CATEGORY",
    "EXECUTION_CATEGORY_BLOCKED",
    "UNKNOWN_RISK",
    "EXECUTION_RISK_BLOCKED",
    "UNKNOWN_CONFIDENCE",
    "EXECUTION_CONFIDENCE_BLOCKED",
    "EXECUTION_POLICY_BLOCKED",
    "EXECUTION_EXTENSION_BLOCKED",
    "EXECUTION_SIZE_BELOW_THRESHOLD",
    "UNKNOWN_MTIME",
    "EXECUTION_TIMESTAMP_INVALID",
    "EXECUTION_FILE_TOO_RECENT",
    "TARGET_CHANGED_SINCE_SCAN",
    "TARGET_NO_LONGER_EXISTS",
    "TARGET_METADATA_ERROR",
    POLICY_EVALUATION_ERROR,
)
REASON_RANK = {code: index for index, code in enumerate(REASON_PRIORITY)}


@dataclass(frozen=True)
class PolicyDecision:
    """Read-only policy explanation; never an authorization to execute."""

    policy_rule_id: str
    execution_policy_version: str
    eligibility: str
    allowed_actions: tuple[str, ...]
    primary_reason: str
    reason_codes: tuple[str, ...]
    evidence: dict[str, object]
    evaluated_at: str
    evaluation_basis: str = EVALUATION_BASIS
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["allowed_actions"] = list(self.allowed_actions)
        result["reason_codes"] = list(self.reason_codes)
        return result


def ordered_reasons(reasons: list[str]) -> list[str]:
    """Deduplicate and order by the documented deterministic safety priority."""
    unique = set(reasons)
    return sorted(unique, key=lambda code: (REASON_RANK.get(code, len(REASON_RANK)), code))


def _parts(path: str) -> tuple[str, ...] | None:
    if not isinstance(path, str) or not path or "\x00" in path or "/" in path:
        return None
    drive, tail = ntpath.splitdrive(path)
    if drive.casefold() != "c:" or not tail.startswith("\\") or tail.startswith("\\\\"):
        return None
    parts = tail[1:].split("\\")
    if not parts or any(
        part in {"", ".", ".."} or ":" in part or part.rstrip(" .") != part or
        part.split(".", 1)[0].casefold() in RESERVED_DOS_NAMES for part in parts
    ):
        return None
    if ntpath.normpath(path).casefold() != path.casefold():
        return None
    return tuple(part.casefold() for part in parts)


def _mtime(info: os.stat_result) -> str:
    return datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()


class ExecutionPolicyEngine:
    def __init__(self, user_profile: str | None = None,
                 lstat: Callable[[str], os.stat_result] = os.lstat,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 local_app_data: str | None = None):
        explicit_profile = user_profile is not None
        self.user_profile = user_profile if explicit_profile else os.environ.get("USERPROFILE", "")
        self.local_app_data = local_app_data if local_app_data is not None else (
            ntpath.join(self.user_profile, "AppData", "Local") if explicit_profile
            else os.environ.get("LOCALAPPDATA", "")
        )
        self.lstat = lstat
        self.now = now

    def _temp_parts(self) -> tuple[str, ...] | None:
        profile_parts = _parts(self.user_profile)
        local_parts = _parts(self.local_app_data)
        if (not profile_parts or not local_parts or
                local_parts != (*profile_parts, "appdata", "local")):
            return None
        return (*local_parts, "temp")

    def static_reasons(self, candidate: Mapping[str, object], scope_key: str) -> list[str]:
        path = str(candidate.get("display_path", ""))
        parts = _parts(path)
        relative = str(candidate.get("relative_path", ""))
        reasons: list[str] = []
        if scope_key not in {"system_drive_c", "current_user_temp"}:
            reasons.append("EXECUTION_SCOPE_BLOCKED")
        relative_parts = tuple(relative.split("/")) if relative else ()
        valid_relative = bool(relative_parts) and all(
            part not in {"", ".", ".."} and "\\" not in part and ":" not in part
            for part in relative_parts
        )
        temp_parts = self._temp_parts()
        expected_root = ("C:\\" if scope_key == "system_drive_c" else
                         ntpath.join("C:\\", *temp_parts) if temp_parts else "")
        expected_path = ntpath.join(expected_root, *relative_parts) if valid_relative and expected_root else ""
        if parts is None or not valid_relative or expected_path.casefold() != path.casefold():
            reasons.append("EXECUTION_PATH_BLOCKED")
        if parts and (parts[0] in PROTECTED_ROOTS or parts[-1] in PROTECTED_NAMES):
            reasons.append("EXECUTION_PROTECTED_PATH")
        if candidate.get("object_type") != "file":
            reasons.append("DIRECTORY_EXECUTION_NOT_SUPPORTED")
        if (not parts or not temp_parts or parts[:len(temp_parts)] != temp_parts or
                len(parts) <= len(temp_parts)):
            reasons.append("EXECUTION_CURRENT_USER_TEMP_ONLY")
        category = candidate.get("category")
        confidence = candidate.get("confidence")
        risk = candidate.get("risk_level")
        if category in {None, "", "unknown"}:
            reasons.append("UNKNOWN_CATEGORY")
        elif category != "temporary_file":
            reasons.append("EXECUTION_CATEGORY_BLOCKED")
        if confidence in {None, "", "unknown"}:
            reasons.append("UNKNOWN_CONFIDENCE")
        elif confidence != "high":
            reasons.append("EXECUTION_CONFIDENCE_BLOCKED")
        if risk in {None, "", "unknown"}:
            reasons.append("UNKNOWN_RISK")
        elif risk != "low":
            reasons.append("EXECUTION_RISK_BLOCKED")
        if candidate.get("reason_code") != "STALE_USER_TEMP_FILE":
            reasons.append("EXECUTION_POLICY_BLOCKED")
        if parts and ntpath.splitext(parts[-1])[1].casefold() in BLOCKED_EXTENSIONS:
            reasons.append("EXECUTION_EXTENSION_BLOCKED")
        if int(candidate.get("logical_bytes", 0)) < MIN_BYTES:
            reasons.append("EXECUTION_SIZE_BELOW_THRESHOLD")
        return ordered_reasons(reasons)

    def _timestamp_reasons(self, value: str | None,
                           evaluated_at: datetime | None = None) -> tuple[list[str], float | None]:
        if value in {None, ""}:
            return ["UNKNOWN_MTIME"], None
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError
            reference = evaluated_at or self.now()
            age_seconds = (reference - timestamp.astimezone(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError, OSError):
            return ["EXECUTION_TIMESTAMP_INVALID"], None
        if age_seconds < 0:
            return ["EXECUTION_TIMESTAMP_INVALID"], age_seconds / 86400
        if age_seconds < MIN_AGE_DAYS * 86400:
            return ["EXECUTION_FILE_TOO_RECENT"], age_seconds / 86400
        return [], age_seconds / 86400

    @staticmethod
    def _file_type(candidate: Mapping[str, object]) -> str:
        return "regular_file" if candidate.get("object_type") == "file" else str(
            candidate.get("object_type") or "unknown"
        )

    def evaluate(self, candidate: Mapping[str, object], scope_key: str,
                 snapshot_mtime: str | None,
                 evaluated_at: datetime | None = None) -> PolicyDecision:
        """Explain snapshot eligibility without stat, token creation, or mutation."""
        reference = evaluated_at or self.now()
        try:
            reasons = self.static_reasons(candidate, scope_key)
            timestamp_reasons, age = self._timestamp_reasons(snapshot_mtime, reference)
            reasons = ordered_reasons([*reasons, *timestamp_reasons])
            path = str(candidate.get("display_path", ""))
            extension = ntpath.splitext(path)[1].casefold() if path else ""
            evidence = {
                "path_scope": scope_key,
                "file_type": self._file_type(candidate),
                "logical_bytes": int(candidate.get("logical_bytes", 0)),
                "minimum_bytes": MIN_BYTES,
                "snapshot_mtime": snapshot_mtime,
                "age_days": round(age, 6) if age is not None else None,
                "required_age_days": MIN_AGE_DAYS,
                "category": candidate.get("category"),
                "required_category": "temporary_file",
                "risk": candidate.get("risk_level"),
                "required_risk": "low",
                "confidence": candidate.get("confidence"),
                "required_confidence": "high",
                "candidate_reason_code": candidate.get("reason_code"),
                "required_candidate_reason_code": "STALE_USER_TEMP_FILE",
                "extension": extension,
                "extension_blocked": extension in BLOCKED_EXTENSIONS,
            }
            if reasons:
                eligibility = "ineligible"
                allowed_actions: tuple[str, ...] = ()
                reason_codes = tuple(reasons)
                primary_reason = reasons[0]
            else:
                eligibility = "eligible_for_recycle"
                allowed_actions = ("recycle",)
                reason_codes = (ELIGIBLE_REASON,)
                primary_reason = ELIGIBLE_REASON
            return PolicyDecision(
                policy_rule_id=EXECUTION_RULE_ID,
                execution_policy_version=EXECUTION_POLICY_VERSION,
                eligibility=eligibility,
                allowed_actions=allowed_actions,
                primary_reason=primary_reason,
                reason_codes=reason_codes,
                evidence=evidence,
                evaluated_at=reference.astimezone(timezone.utc).isoformat(),
            )
        except Exception:
            return PolicyDecision(
                policy_rule_id=EXECUTION_RULE_ID,
                execution_policy_version=EXECUTION_POLICY_VERSION,
                eligibility="ineligible",
                allowed_actions=(),
                primary_reason=POLICY_EVALUATION_ERROR,
                reason_codes=(POLICY_EVALUATION_ERROR,),
                evidence={
                    "path_scope": scope_key,
                    "file_type": self._file_type(candidate),
                    "snapshot_mtime": snapshot_mtime,
                },
                evaluated_at=reference.astimezone(timezone.utc).isoformat(),
            )

    def discovery_reasons(self, candidate: Mapping[str, object], scope_key: str,
                          snapshot_mtime: str | None) -> list[str]:
        decision = self.evaluate(candidate, scope_key, snapshot_mtime)
        return [] if decision.eligibility == "eligible_for_recycle" else list(decision.reason_codes)

    def preflight(self, candidate: Mapping[str, object], scope_key: str,
                  snapshot_mtime: str | None) -> dict[str, object]:
        reasons = self.discovery_reasons(candidate, scope_key, snapshot_mtime)
        path = str(candidate.get("display_path", ""))
        checks: list[dict[str, object]] = []
        fingerprint = None
        current_size = None
        current_mtime = None
        if not reasons:
            parts = _parts(path)
            assert parts is not None
            # Check every component without following links. No target content is opened.
            prefixes = ["C:\\"]
            for index in range(1, len(parts) + 1):
                prefixes.append(ntpath.join("C:\\", *parts[:index]))
            try:
                root_info = self.lstat(prefixes[0])
                root_device = root_info.st_dev
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
                        current_size = info.st_size
                        current_mtime = _mtime(info)
                        fingerprint = {"size": info.st_size, "mtime_ns": info.st_mtime_ns,
                                       "ctime_ns": getattr(info, "st_ctime_ns", 0),
                                       "mode": stat.S_IFMT(info.st_mode), "device": info.st_dev,
                                       "inode": info.st_ino,
                                       "attributes": getattr(info, "st_file_attributes", 0)}
            except FileNotFoundError:
                reasons.append("TARGET_NO_LONGER_EXISTS")
            except PermissionError:
                reasons.append("ACCESS_DENIED")
            except OSError as exc:
                reasons.append("TARGET_IN_USE" if getattr(exc, "winerror", None) == 32 else "TARGET_METADATA_ERROR")
        if fingerprint is not None:
            try:
                old = datetime.fromisoformat(str(snapshot_mtime).replace("Z", "+00:00"))
                same_mtime = abs(old.timestamp() - fingerprint["mtime_ns"] / 1e9) < 0.000001
            except (ValueError, TypeError, OverflowError):
                same_mtime = False
            if current_size != int(candidate.get("logical_bytes", -1)) or not same_mtime:
                reasons.append("TARGET_CHANGED_SINCE_SCAN")
            current_timestamp_reasons, age_days = self._timestamp_reasons(current_mtime)
            reasons.extend(current_timestamp_reasons)
        else:
            age_days = None
        checks.append({"check": "current_filesystem_metadata", "passed": fingerprint is not None})
        checks.append({"check": "snapshot_fingerprint", "passed": fingerprint is not None and "TARGET_CHANGED_SINCE_SCAN" not in reasons})
        return {"candidate_id": candidate.get("candidate_id"), "current_path": path,
                "execution_rule_id": EXECUTION_RULE_ID, "policy_rule_id": EXECUTION_RULE_ID,
                "snapshot_size": candidate.get("logical_bytes"), "snapshot_mtime": snapshot_mtime,
                "current_size": current_size, "current_mtime": current_mtime,
                "age_days": age_days,
                "category": candidate.get("category"), "risk_level": candidate.get("risk_level"),
                "confidence": candidate.get("confidence"),
                "eligibility": "eligible_for_recycle" if not reasons else "ineligible",
                "allowed_actions": ["recycle"] if not reasons else [],
                "checks": checks, "block_reasons": list(dict.fromkeys(reasons)),
                "planned_action": "recycle" if not reasons else "none",
                "fingerprint": fingerprint}
