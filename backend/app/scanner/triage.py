"""Bounded personal-file metadata selection performed inside the scan stream."""

from __future__ import annotations

import ntpath
import os
from dataclasses import dataclass
from pathlib import Path

from app.cleanup.categories import EXTENSION_CATEGORY, REVIEW_ROOTS, TRIAGE_INDEX_LIMIT, normalize_extension
from app.cleanup.policy import BLOCKED_EXTENSIONS
from app.scanner.models import FileMetadata
from app.scanner.topk import BoundedHybridFiles


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
        self._parent_locations: dict[str, str | None] = {}
        self._parent_cache_limit = 4096

    def _location(self, normalized_path: str) -> str | None:
        return next((key for key, prefix in self.roots.items()
                     if not prefix or normalized_path == prefix or
                     normalized_path.startswith(prefix + "/")), None)

    def add_observation(self, name: str, relative_path: str, parent: str, size_bytes: int,
                        mtime_epoch: float, attributes: int | None) -> bool:
        location = self._parent_locations.get(parent)
        if parent not in self._parent_locations:
            location = self._location(parent.casefold())
            if len(self._parent_locations) >= self._parent_cache_limit:
                self._parent_locations.clear()
            self._parent_locations[parent] = location
        if location is None:
            return True
        self.observed_count += 1
        return self._selector.add_observation(
            name, relative_path, parent, size_bytes, mtime_epoch, attributes)

    def selected(self) -> list[TriageFile]:
        selected: list[TriageFile] = []
        for file in self._selector.selected_files(self.observed_count, ordered=False):
            location = self._location(file.parent.casefold())
            assert location is not None
            extension = normalize_extension(file.name)
            selected.append(TriageFile(
                file.relative_path, file.name, extension, file.size_bytes, file.mtime,
                EXTENSION_CATEGORY.get(extension, "other"), location,
                "DO_NOT_TOUCH" if extension in BLOCKED_EXTENSIONS else "REVIEW_REQUIRED",
                file.attributes,
            ))
        return selected
