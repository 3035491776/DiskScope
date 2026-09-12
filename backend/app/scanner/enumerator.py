import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Iterator

from app.scanner.errors import classify_os_error
from app.scanner.exclusions import project_exclusion
from app.scanner.models import FileMetadata
from app.scanner.path_guard import InvalidScanRoot, assert_safe_directory, is_reparse_point
from app.core.config import PROJECT_ROOT


@dataclass(frozen=True)
class DirectorySeen:
    relative_path: str
    parent: str | None


@dataclass(frozen=True)
class FileSeen:
    file: FileMetadata


@dataclass(frozen=True)
class ScanProblem:
    code: str
    relative_path: str


@dataclass(frozen=True)
class ExcludedPath:
    rule: str
    relative_path: str


ScanEvent = DirectorySeen | FileSeen | ScanProblem | ExcludedPath


class RootUnavailable(OSError):
    pass


def enumerate_metadata(root: Path, cancel: Event) -> Iterator[ScanEvent]:
    """Stream metadata events; retain only pending directory paths."""
    pending: list[tuple[Path, str, str | None]] = [(root, "", None)]
    while pending:
        if cancel.is_set():
            return
        path, relative_path, parent = pending.pop()
        try:
            assert_safe_directory(root, path)
        except InvalidScanRoot as exc:
            if not relative_path:
                raise RootUnavailable("The scan root became unavailable.") from exc
            yield ScanProblem("INVALID_PATH", relative_path)
            continue

        yield DirectorySeen(relative_path, parent)
        children: list[tuple[Path, str, str]] = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if cancel.is_set():
                        return
                    child_relative = (
                        f"{relative_path}/{entry.name}" if relative_path else entry.name
                    )
                    if root == PROJECT_ROOT:
                        rule = project_exclusion(child_relative)
                        if rule is not None:
                            yield ExcludedPath(rule, child_relative)
                            continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if is_reparse_point(info):
                            yield ScanProblem("REPARSE_POINT_SKIPPED", child_relative)
                        elif stat.S_ISDIR(info.st_mode):
                            children.append((Path(entry.path), child_relative, relative_path))
                        elif stat.S_ISREG(info.st_mode):
                            yield FileSeen(
                                FileMetadata(
                                    name=entry.name,
                                    relative_path=child_relative,
                                    parent=relative_path,
                                    size_bytes=max(0, info.st_size),
                                    mtime=datetime.fromtimestamp(
                                        info.st_mtime, timezone.utc
                                    ).isoformat(),
                                    attributes=getattr(info, "st_file_attributes", None),
                                )
                            )
                        else:
                            yield ScanProblem("INVALID_PATH", child_relative)
                    except OSError as exc:
                        yield ScanProblem(classify_os_error(exc), child_relative)
        except OSError as exc:
            if not relative_path:
                raise RootUnavailable("The scan root cannot be enumerated.") from exc
            yield ScanProblem(classify_os_error(exc), relative_path)
        pending.extend(reversed(children))
