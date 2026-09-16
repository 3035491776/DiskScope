"""Resolve the current user's fixed Temp scope without accepting caller paths."""

from __future__ import annotations

import ntpath
import os
import stat
from pathlib import Path, PureWindowsPath

from app.scanner.path_guard import InvalidScanRoot, is_reparse_point


CURRENT_USER_TEMP_SCOPE_KEY = "current_user_temp"
CURRENT_USER_TEMP_LABEL = "当前用户临时文件"
CURRENT_USER_TEMP_PERSISTENCE_LIMIT = 10_000


def _safe_absolute_windows_path(value: str) -> PureWindowsPath:
    path = PureWindowsPath(value)
    if (not value or "\x00" in value or value.startswith("\\\\") or
            path.drive.startswith("\\\\") or not path.is_absolute() or
            path.drive.casefold() in {"\\\\?\\", "\\\\.\\"}):
        raise InvalidScanRoot("CURRENT_USER_TEMP_UNAVAILABLE")
    return path


def resolve_current_user_temp() -> Path:
    """Return the server-resolved LocalAppData Temp after fixed-boundary checks."""
    profile_raw = os.environ.get("USERPROFILE", "")
    local_raw = os.environ.get("LOCALAPPDATA", "")
    system_drive = os.environ.get("SystemDrive", "C:")
    profile = _safe_absolute_windows_path(profile_raw)
    local = _safe_absolute_windows_path(local_raw)
    if (profile.drive.casefold() != system_drive.casefold() or
            local.drive.casefold() != system_drive.casefold()):
        raise InvalidScanRoot("CURRENT_USER_TEMP_OUTSIDE_SYSTEM_DRIVE")
    profile_norm = ntpath.normcase(ntpath.normpath(str(profile)))
    local_norm = ntpath.normcase(ntpath.normpath(str(local)))
    try:
        if ntpath.commonpath((profile_norm, local_norm)) != profile_norm:
            raise InvalidScanRoot("CURRENT_USER_TEMP_OUTSIDE_PROFILE")
    except ValueError as exc:
        raise InvalidScanRoot("CURRENT_USER_TEMP_OUTSIDE_PROFILE") from exc
    temp = Path(str(local / "Temp"))
    try:
        current = Path(profile.anchor)
        info = os.lstat(current)
        for component in Path(str(temp)).parts[1:]:
            current /= component
            info = os.lstat(current)
            if is_reparse_point(info):
                raise InvalidScanRoot("CURRENT_USER_TEMP_REPARSE_BLOCKED")
        if not stat.S_ISDIR(info.st_mode):
            raise InvalidScanRoot("CURRENT_USER_TEMP_UNAVAILABLE")
        return Path(os.path.abspath(temp))
    except InvalidScanRoot:
        raise
    except (OSError, ValueError) as exc:
        raise InvalidScanRoot("CURRENT_USER_TEMP_UNAVAILABLE") from exc
