import errno
from collections import Counter


ERROR_CODES = {
    "ACCESS_DENIED",
    "FILE_NOT_FOUND",
    "PATH_TOO_LONG",
    "REPARSE_POINT_SKIPPED",
    "INVALID_PATH",
    "IO_ERROR",
    "CANCELLED",
}


def classify_os_error(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return "ACCESS_DENIED"
    if isinstance(error, FileNotFoundError):
        return "FILE_NOT_FOUND"
    if error.errno == errno.ENAMETOOLONG or getattr(error, "winerror", None) == 206:
        return "PATH_TOO_LONG"
    return "IO_ERROR"


class ScanErrors:
    def __init__(self, samples_per_code: int = 5) -> None:
        self.counts: Counter[str] = Counter()
        self.samples: dict[str, list[str]] = {}
        self.samples_per_code = samples_per_code

    def record(self, code: str, relative_path: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown scan error code: {code}")
        self.counts[code] += 1
        samples = self.samples.setdefault(code, [])
        if len(samples) < self.samples_per_code:
            samples.append(relative_path)

    def summary(self) -> dict[str, dict[str, object]]:
        return {
            code: {"count": count, "samples": list(self.samples.get(code, []))}
            for code, count in sorted(self.counts.items())
        }

    @property
    def total_count(self) -> int:
        return sum(self.counts.values())
