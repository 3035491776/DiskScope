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
MIN_AGE_DAYS = 7
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
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.user_profile = user_profile if user_profile is not None else os.environ.get("USERPROFILE", "")
        self.lstat = lstat
        self.now = now

    def static_reasons(self, candidate: Mapping[str, object], scope_key: str) -> list[str]:
        path = str(candidate.get("display_path", ""))
        parts = _parts(path)
        relative = str(candidate.get("relative_path", ""))
        reasons: list[str] = []
        if scope_key != "system_drive_c":
            reasons.append("EXECUTION_SCOPE_BLOCKED")
        if parts is None or not relative or ntpath.join("C:\\", relative.replace("/", "\\")).casefold() != path.casefold():
            reasons.append("EXECUTION_PATH_BLOCKED")
        if parts and (parts[0] in PROTECTED_ROOTS or parts[-1] in PROTECTED_NAMES):
            reasons.append("EXECUTION_PROTECTED_PATH")
        if candidate.get("object_type") != "file":
            reasons.append("DIRECTORY_EXECUTION_NOT_SUPPORTED")
        profile_parts = _parts(self.user_profile)
        if (not parts or not profile_parts or
                parts[:len(profile_parts) + 3] != (*profile_parts, "appdata", "local", "temp") or
                len(parts) <= len(profile_parts) + 3):
            reasons.append("EXECUTION_CURRENT_USER_TEMP_ONLY")
        if (candidate.get("category") != "temporary_file" or
                candidate.get("confidence") not in {"medium", "high"} or
                candidate.get("risk_level") not in {"low", "review"} or
                candidate.get("reason_code") != "STALE_USER_TEMP_FILE"):
            reasons.append("EXECUTION_POLICY_BLOCKED")
        if int(candidate.get("logical_bytes", 0)) < MIN_BYTES:
            reasons.append("EXECUTION_SIZE_BELOW_THRESHOLD")
        return reasons

    def preflight(self, candidate: Mapping[str, object], scope_key: str,
                  snapshot_mtime: str | None) -> dict[str, object]:
        reasons = self.static_reasons(candidate, scope_key)
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
            if (self.now() - datetime.fromtimestamp(fingerprint["mtime_ns"] / 1e9, timezone.utc)).total_seconds() < MIN_AGE_DAYS * 86400:
                reasons.append("EXECUTION_FILE_TOO_RECENT")
        checks.append({"check": "current_filesystem_metadata", "passed": fingerprint is not None})
        checks.append({"check": "snapshot_fingerprint", "passed": fingerprint is not None and "TARGET_CHANGED_SINCE_SCAN" not in reasons})
        return {"candidate_id": candidate.get("candidate_id"), "current_path": path,
                "execution_rule_id": "USER_TEMP_STALE_FILE_PREFLIGHT_V1",
                "snapshot_size": candidate.get("logical_bytes"), "snapshot_mtime": snapshot_mtime,
                "current_size": current_size, "current_mtime": current_mtime,
                "eligibility": "eligible_for_review" if not reasons else "ineligible",
                "checks": checks, "block_reasons": list(dict.fromkeys(reasons)),
                "planned_action": "dry_run_only" if not reasons else "none",
                "fingerprint": fingerprint}
