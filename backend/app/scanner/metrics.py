"""Best-effort process counters for development; no target file is opened."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessSample:
    rss_bytes: int | None = None
    cpu_seconds: float | None = None
    read_bytes: int | None = None
    write_bytes: int | None = None
    read_operations: int | None = None
    write_operations: int | None = None


def _windows_process_sample() -> ProcessSample:
    import ctypes
    from ctypes import wintypes

    class IOCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "read_operations", "write_operations", "other_operations",
            "read_bytes", "write_bytes", "other_bytes",
        )]

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("page_faults", wintypes.DWORD),
            ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
            ("quota_peak_paged", ctypes.c_size_t), ("quota_paged", ctypes.c_size_t),
            ("quota_peak_nonpaged", ctypes.c_size_t), ("quota_nonpaged", ctypes.c_size_t),
            ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t),
        ]

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IOCounters)]
    kernel.GetProcessTimes.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
    ]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD,
    ]
    process = kernel.GetCurrentProcess()
    io = IOCounters()
    memory = MemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    created, exited, kernel_time, user_time = (FileTime() for _ in range(4))

    io_ok = bool(kernel.GetProcessIoCounters(process, ctypes.byref(io)))
    memory_ok = bool(psapi.GetProcessMemoryInfo(process, ctypes.byref(memory), memory.cb))
    cpu_ok = bool(kernel.GetProcessTimes(
        process, ctypes.byref(created), ctypes.byref(exited),
        ctypes.byref(kernel_time), ctypes.byref(user_time),
    ))

    def seconds(value: FileTime) -> float:
        return ((value.high << 32) | value.low) / 10_000_000

    return ProcessSample(
        rss_bytes=memory.working_set if memory_ok else None,
        cpu_seconds=seconds(kernel_time) + seconds(user_time) if cpu_ok else None,
        read_bytes=io.read_bytes if io_ok else None,
        write_bytes=io.write_bytes if io_ok else None,
        read_operations=io.read_operations if io_ok else None,
        write_operations=io.write_operations if io_ok else None,
    )


def read_process_sample() -> ProcessSample:
    if os.name != "nt":
        return ProcessSample()
    try:
        return _windows_process_sample()
    except Exception:  # Metrics must never make an otherwise safe scan fail.
        return ProcessSample()


class ScanResourceMonitor:
    def __init__(self) -> None:
        self.before = read_process_sample()
        self.peak_observed_rss = self.before.rss_bytes

    def sample(self) -> None:
        rss = read_process_sample().rss_bytes
        if rss is not None:
            self.peak_observed_rss = max(self.peak_observed_rss or 0, rss)

    def finish(self, files: int, duration_ms: int) -> dict[str, int | float | None]:
        after = read_process_sample()
        if after.rss_bytes is not None:
            self.peak_observed_rss = max(self.peak_observed_rss or 0, after.rss_bytes)

        def delta(field: str) -> int | float | None:
            first = getattr(self.before, field)
            last = getattr(after, field)
            return last - first if first is not None and last is not None else None

        return {
            "duration_ms": duration_ms,
            "files_per_second": round(files / max(duration_ms / 1000, 0.001), 1),
            "rss_peak_observed_bytes": self.peak_observed_rss,
            "cpu_seconds": delta("cpu_seconds"),
            "process_read_bytes_before": self.before.read_bytes,
            "process_read_bytes_after": after.read_bytes,
            "delta_read_bytes": delta("read_bytes"),
            "process_write_bytes_before": self.before.write_bytes,
            "process_write_bytes_after": after.write_bytes,
            "delta_write_bytes": delta("write_bytes"),
            "delta_read_operations": delta("read_operations"),
            "delta_write_operations": delta("write_operations"),
        }
