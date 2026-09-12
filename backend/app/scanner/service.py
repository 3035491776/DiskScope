from pathlib import Path
from threading import Event
from typing import Callable

from app.scanner.aggregator import DirectoryAggregator
from app.scanner.enumerator import (
    DirectorySeen, ExcludedPath, FileSeen, ScanProblem, enumerate_metadata,
)
from app.scanner.errors import ScanErrors
from app.scanner.models import ScanResult


ProgressCallback = Callable[[ScanResult], None]


def scan_fixture(
    root: Path,
    cancel: Event,
    on_progress: ProgressCallback | None = None,
    top_k: int = 1000,
) -> ScanResult:
    """Read approved-root metadata without opening or changing scanned files."""
    from app.scanner.topk import TopKFiles

    result = ScanResult()
    aggregator = DirectoryAggregator()
    top_files = TopKFiles(top_k)
    errors = ScanErrors()

    for event in enumerate_metadata(root, cancel):
        if isinstance(event, DirectorySeen):
            aggregator.add_directory(event.relative_path, event.parent)
            result.dirs_seen += 1
            if on_progress:
                on_progress(result)
        elif isinstance(event, FileSeen):
            aggregator.add_file(event.file.parent, event.file.size_bytes)
            top_files.add(event.file)
            result.files_seen += 1
            result.logical_bytes += event.file.size_bytes
            if on_progress and result.files_seen % 256 == 0:
                on_progress(result)
        elif isinstance(event, ScanProblem):
            errors.record(event.code, event.relative_path)
            result.skipped_count += 1
            result.errors_count = errors.total_count
        elif isinstance(event, ExcludedPath):
            entry = result.exclusions.setdefault(event.rule, {"count": 0, "samples": []})
            entry["count"] += 1
            samples = entry["samples"]
            if len(samples) < 5:
                samples.append(event.relative_path)
            result.skipped_count += 1

    if cancel.is_set():
        errors.record("CANCELLED", "")
        result.cancelled = True
    result.directories = aggregator.finish()
    result.top_files = top_files.sorted_files()
    result.errors_count = errors.total_count
    result.errors = errors.summary()
    if on_progress:
        on_progress(result)
    return result
