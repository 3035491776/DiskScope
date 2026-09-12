"""Read capacity of local fixed Windows volumes; never enumerate their contents."""

import os


def capacity_record(drive: str, total_bytes: int, free_bytes: int) -> dict[str, int | str | bool]:
    """Keep API capacities as integer bytes; never imply scan permission."""
    return {
        "drive": drive,
        "total_bytes": total_bytes,
        "used_bytes": total_bytes - free_bytes,
        "free_bytes": free_bytes,
        "scan_allowed": False,
    }


def list_fixed_volumes() -> list[dict[str, int | str]]:
    if os.name != "nt":
        return []

    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetLogicalDrives.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    kernel.GetDiskFreeSpaceExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
    ]
    kernel.GetDiskFreeSpaceExW.restype = wintypes.BOOL

    drive_mask = kernel.GetLogicalDrives()
    volumes: list[dict[str, int | str]] = []
    for index in range(26):
        if not drive_mask & (1 << index):
            continue
        root = f"{chr(ord('A') + index)}:\\"
        if kernel.GetDriveTypeW(root) != 3:  # DRIVE_FIXED; excludes network/removable drives.
            continue
        available = ctypes.c_ulonglong()
        total = ctypes.c_ulonglong()
        free = ctypes.c_ulonglong()
        if not kernel.GetDiskFreeSpaceExW(
            root, ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)
        ):
            continue
        volumes.append(capacity_record(root[:2], total.value, free.value))
    return volumes
