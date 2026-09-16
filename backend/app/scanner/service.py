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
    scope_key: str | None = None,
    file_persistence_mode: str = "top_k",
    file_persistence_limit: int | None = None,
) -> ScanResult:
    """Read approved-root metadata without opening or changing scanned files."""
    from app.scanner.topk import BoundedHybridFiles, TopKFiles

    result = ScanResult()
    aggregator = DirectoryAggregator()
    persistence_limit = file_persistence_limit or top_k
    top_files = (BoundedHybridFiles(persistence_limit)
                 if file_persistence_mode == "bounded_scope" else TopKFiles(persistence_limit))
    errors = ScanErrors()

    def mark_limited(relative_path: str) -> None:
        parent = relative_path.rpartition("/")[0]
        while True:
            result.limited_directories.add(parent)
            if not parent:
                break
            parent = parent.rpartition("/")[0]

    for event in enumerate_metadata(root, cancel, scope_key):
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
            mark_limited(event.relative_path)
            result.skipped_count += 1
            result.errors_count = errors.total_count
        elif isinstance(event, ExcludedPath):
            mark_limited(event.relative_path)
            entry = result.exclusions.setdefault(event.rule, {"count": 0, "samples": []})
            entry["count"] += 1
            samples = entry["samples"]
            if len(samples) < 5:
                samples.append(event.relative_path)
            result.skipped_count += 1

    if cancel.is_set():
        errors.record("CANCELLED", "")
        result.cancelled = True
        result.limited_directories.add("")
    result.directories = aggregator.finish()
    result.top_files = (top_files.selected_files(result.files_seen)
                        if isinstance(top_files, BoundedHybridFiles) else top_files.sorted_files())
    result.file_persistence_mode = file_persistence_mode
    result.file_persistence_limit = persistence_limit
    result.persisted_file_count = len(result.top_files)
    result.observed_file_count = result.files_seen
    result.file_metadata_coverage = (
        "complete" if file_persistence_mode == "bounded_scope" and result.files_seen <= persistence_limit
        else "limited"
    )
    result.errors_count = errors.total_count
    result.errors = errors.summary()
    if on_progress:
        on_progress(result)
    return result
