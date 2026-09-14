"""Fixed C volume identity and read-only display categories."""

import os
from pathlib import Path

from app.scanner.path_guard import is_reparse_point
from app.scanner.policy import C_DRIVE_SAFE_READONLY
from app.scanner.whole_volume_gate import reject_whole_volume_root


C_ROOT = Path("C:\\")
SYSTEM_DRIVE_SCOPE_KEY = "system_drive_c"
SYSTEM_DRIVE_LABEL = "Windows C:"


class SystemDriveNotFixed(ValueError):
    code = "SYSTEM_DRIVE_NOT_FIXED"


class SystemDriveUnavailable(ValueError):
    code = "SYSTEM_DRIVE_UNAVAILABLE"


def drive_type(root: Path) -> int:
    """GetDriveTypeW only; never open a volume or physical device."""
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    return int(kernel.GetDriveTypeW(str(root)))


def validate_system_drive_c() -> Path:
    reject_whole_volume_root(C_ROOT, C_DRIVE_SAFE_READONLY)
    if drive_type(C_ROOT) != 3:  # DRIVE_FIXED
        raise SystemDriveNotFixed("SYSTEM_DRIVE_NOT_FIXED")
    try:
        if is_reparse_point(os.lstat(C_ROOT)) or C_ROOT.resolve(strict=True) != C_ROOT:
            raise SystemDriveUnavailable("SYSTEM_DRIVE_UNAVAILABLE")
        if not C_ROOT.is_dir():
            raise SystemDriveUnavailable("SYSTEM_DRIVE_UNAVAILABLE")
    except OSError as exc:
        raise SystemDriveUnavailable("SYSTEM_DRIVE_UNAVAILABLE") from exc
    return C_ROOT


_CATEGORIES = {
    "windows": ("windows", "system_managed", "系统管理"),
    "program files": ("program_files", "application_managed", "应用管理"),
    "program files (x86)": ("program_files_x86", "application_managed", "应用管理"),
    "programdata": ("program_data", "application_managed", "应用管理"),
    "users": ("users", "user_data", "用户数据"),
    "recovery": ("recovery", "protected_system", "受保护系统目录"),
    "system volume information": ("system_protected", "protected_system", "受保护系统目录"),
    "$recycle.bin": ("recycle_bin", "system_managed", "回收站（只读分析）"),
    "perflogs": ("perflogs", "system_managed", "系统管理"),
}
_SYSTEM_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys"}


def classify_system_item(relative_path: str) -> dict[str, str]:
    first = relative_path.replace("\\", "/").split("/", 1)[0].casefold()
    if first in _SYSTEM_FILES:
        category, risk, label = "system_file", "system_managed", "系统管理文件"
    else:
        category, risk, label = _CATEGORIES.get(first, ("other", "unknown", "其他目录"))
    return {"system_category": category, "risk_class": risk, "category_label": label}
