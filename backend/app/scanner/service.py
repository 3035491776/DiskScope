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
    triage_index_limit: int = 100_000,
    triage_user_profile: str | None = None,
    triage_root_map: dict[str, str] | None = None,
) -> ScanResult:
    """Read approved-root metadata without opening or changing scanned files."""
    from app.scanner.topk import BoundedHybridFiles, TopKFiles
    from app.scanner.triage import TriageCollector

    result = ScanResult()
    aggregator = DirectoryAggregator()
    persistence_limit = file_persistence_limit or top_k
    top_files = (BoundedHybridFiles(persistence_limit)
                 if file_persistence_mode == "bounded_scope" else TopKFiles(persistence_limit))
    triage = TriageCollector(
        root, scope_key == "system_drive_c" or triage_root_map is not None, triage_index_limit,
        triage_user_profile, triage_root_map,
    )
    errors = ScanErrors()
    last_progress_items = 0

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
            items_seen = result.files_seen + result.dirs_seen
            if on_progress and (items_seen <= 32 or items_seen - last_progress_items >= 256):
                on_progress(result)
                last_progress_items = items_seen
        elif isinstance(event, FileSeen):
            aggregator.add_file(event.parent, event.size_bytes)
            top_metadata_complete = top_files.add_observation(
                event.name, event.relative_path, event.parent, event.size_bytes,
                event.mtime_epoch, event.attributes,
            )
            triage_metadata_complete = triage.add_observation(
                event.name, event.relative_path, event.parent, event.size_bytes,
                event.mtime_epoch, event.attributes,
            )
            result.files_seen += 1
            result.logical_bytes += event.size_bytes
            if not top_metadata_complete or not triage_metadata_complete:
                errors.record("INVALID_FILE_METADATA", event.relative_path)
                result.metadata_warning_count += 1
                result.errors_count = errors.total_count
            items_seen = result.files_seen + result.dirs_seen
            if on_progress and items_seen - last_progress_items >= 256:
                on_progress(result)
                last_progress_items = items_seen
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
    result.triage_files = triage.selected()
    result.triage_observed_count = triage.observed_count
    result.triage_persisted_count = len(result.triage_files)
    result.triage_index_limit = triage.limit if triage.roots else 0
    result.triage_coverage = (
        "complete" if triage.roots and triage.observed_count <= triage.limit
        else "limited" if triage.roots else None
    )
    result.errors_count = errors.total_count
    result.errors = errors.summary()
    if on_progress:
        on_progress(result)
    return result
