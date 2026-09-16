"""Independent, deny-by-default execution policy and metadata-only preflight."""

from __future__ import annotations

import ntpath
import os
import stat
from datetime import datetime, timezone
from typing import Callable, Mapping

PROTECTED_ROOTS = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "recovery", "system volume information", "$recycle.bin",
})
PROTECTED_NAMES = frozenset({"hiberfil.sys", "pagefile.sys", "swapfile.sys"})
MIN_BYTES = 1024 * 1024
MIN_AGE_DAYS = 30
EXECUTION_RULE_ID = "USER_TEMP_STALE_FILE_V1"
BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".msi", ".msp", ".cab",
    ".ps1", ".bat", ".cmd", ".com", ".scr", ".dmp",
})
REPARSE_FLAG = 0x400
RESERVED_DOS_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})


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
        if candidate.get("category") != "temporary_file":
            reasons.append("EXECUTION_CATEGORY_BLOCKED")
        if candidate.get("confidence") != "high":
            reasons.append("EXECUTION_CONFIDENCE_BLOCKED")
        if candidate.get("risk_level") != "low":
            reasons.append("EXECUTION_RISK_BLOCKED")
        if candidate.get("reason_code") != "STALE_USER_TEMP_FILE":
            reasons.append("EXECUTION_POLICY_BLOCKED")
        if parts and ntpath.splitext(parts[-1])[1].casefold() in BLOCKED_EXTENSIONS:
            reasons.append("EXECUTION_EXTENSION_BLOCKED")
        if int(candidate.get("logical_bytes", 0)) < MIN_BYTES:
            reasons.append("EXECUTION_SIZE_BELOW_THRESHOLD")
        return list(dict.fromkeys(reasons))

    def _timestamp_reasons(self, value: str | None) -> tuple[list[str], float | None]:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError
            age_seconds = (self.now() - timestamp.astimezone(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError, OSError):
            return ["EXECUTION_TIMESTAMP_INVALID"], None
        if age_seconds < 0:
            return ["EXECUTION_TIMESTAMP_INVALID"], age_seconds / 86400
        if age_seconds < MIN_AGE_DAYS * 86400:
            return ["EXECUTION_FILE_TOO_RECENT"], age_seconds / 86400
        return [], age_seconds / 86400

    def discovery_reasons(self, candidate: Mapping[str, object], scope_key: str,
                          snapshot_mtime: str | None) -> list[str]:
        reasons = self.static_reasons(candidate, scope_key)
        timestamp_reasons, _ = self._timestamp_reasons(snapshot_mtime)
        return list(dict.fromkeys([*reasons, *timestamp_reasons]))

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
