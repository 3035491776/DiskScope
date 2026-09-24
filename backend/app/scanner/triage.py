"""Bounded personal-file metadata selection performed inside the scan stream."""

from __future__ import annotations

import ntpath
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.cleanup.categories import (
    EXTENSION_CATEGORY, REVIEW_ROOTS, TRIAGE_INDEX_LIMIT, extension_for_filename,
)
from app.cleanup.policy import BLOCKED_EXTENSIONS
from app.scanner.topk import BoundedHybridFiles, safe_mtime_iso


@dataclass(frozen=True, slots=True)
class TriageFile:
    relative_path: str
    name: str
    extension: str
    size_bytes: int
    mtime: str
    category: str
    location_group: str
    safety_classification: str
    attributes: int | None


def _root_map(scan_root: Path, user_profile: str | None) -> dict[str, str]:
    profile = user_profile if user_profile is not None else os.environ.get("USERPROFILE", "")
    if not profile:
        return {}
    root = ntpath.normcase(ntpath.normpath(str(scan_root)))
    profile_norm = ntpath.normcase(ntpath.normpath(profile))
    try:
        if ntpath.commonpath((root, profile_norm)) != root:
            return {}
        base = ntpath.relpath(profile_norm, root).replace("\\", "/").strip("/")
    except ValueError:
        return {}
    if base in {"", "."}:
        return {name: name.casefold() for name in REVIEW_ROOTS}
    return {name: f"{base}/{name}".casefold() for name in REVIEW_ROOTS}


class TriageCollector:
    def __init__(self, scan_root: Path, enabled: bool, limit: int = TRIAGE_INDEX_LIMIT,
                 user_profile: str | None = None, root_map: dict[str, str] | None = None):
        self.limit = limit
        self.roots = ({key.casefold(): value.replace("\\", "/").strip("/").casefold()
                       for key, value in root_map.items()} if root_map is not None
                      else _root_map(scan_root, user_profile)) if enabled else {}
        self._selector = BoundedHybridFiles(limit)
        self.observed_count = 0
        self._current_parent: str | None = None
        self._current_location: str | None = None

    def _location(self, normalized_path: str) -> str | None:
        return next((key for key, prefix in self.roots.items()
                     if not prefix or normalized_path == prefix or
                     normalized_path.startswith(prefix + "/")), None)

    def enter_directory(self, relative_path: str) -> bool:
        """Cache review-root context once for the directory's following file events."""
        self._current_parent = relative_path
        self._current_location = self._location(relative_path.casefold())
        return self._current_location is not None

    def add_observation(self, name: str, relative_path: str, parent: str, size_bytes: int,
                        mtime_epoch: float, attributes: int | None) -> bool:
        if parent != self._current_parent:
            self.enter_directory(parent)
        return self.add_current(name, relative_path, size_bytes, mtime_epoch, attributes)

    def add_current(self, name: str, relative_path: str, size_bytes: int,
                    mtime_epoch: float, attributes: int | None) -> bool:
        """Add a file after enter_directory established its inherited context."""
        location = self._current_location
        if location is None:
            return True
        self.observed_count += 1
        mtime = safe_mtime_iso(mtime_epoch)
        valid_epoch = mtime_epoch if mtime is not None else None
        extension = extension_for_filename(name)
        file = TriageFile(
            relative_path, name, extension, size_bytes, mtime or "",
            EXTENSION_CATEGORY.get(extension, "other"), location,
            "DO_NOT_TOUCH" if extension in BLOCKED_EXTENSIONS else "REVIEW_REQUIRED",
            attributes,
        )
        return self._selector.add_prepared(file, valid_epoch)

    def selected(self) -> list[TriageFile]:
        return cast(list[TriageFile], self._selector.selected_files(
            self.observed_count, ordered=False))
