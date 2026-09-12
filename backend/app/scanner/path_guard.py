import os
import stat
from pathlib import Path, PureWindowsPath

from app.core.config import PROJECT_ROOT


FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures"


class InvalidScanRoot(ValueError):
    pass


def is_reparse_point(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def validate_scan_root(raw_root: str) -> tuple[Path, str]:
    if not raw_root or "\x00" in raw_root:
        raise InvalidScanRoot("A fixture directory is required.")
    windows_path = PureWindowsPath(raw_root)
    if raw_root.startswith("\\\\") or windows_path.drive.startswith("\\\\"):
        raise InvalidScanRoot("UNC and device paths are not allowed.")

    supplied = Path(raw_root)
    lexical = Path(os.path.abspath(supplied if supplied.is_absolute() else PROJECT_ROOT / supplied))
    try:
        relative_project_path = lexical.relative_to(PROJECT_ROOT)
        fixture_base = FIXTURE_ROOT.resolve(strict=True)
        fixture_base.relative_to(PROJECT_ROOT)
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(fixture_base)
    except (OSError, ValueError) as exc:
        raise InvalidScanRoot("Only tests/fixtures and its subdirectories may be scanned.") from exc

    current = PROJECT_ROOT
    try:
        for component in relative_project_path.parts:
            current /= component
            if is_reparse_point(os.lstat(current)):
                raise InvalidScanRoot("Reparse points are not allowed in a scan root.")
    except OSError as exc:
        raise InvalidScanRoot("The fixture path is unavailable.") from exc
    if not resolved.is_dir():
        raise InvalidScanRoot("The scan root must be a directory.")
    return resolved, relative_project_path.as_posix()


def assert_safe_directory(path: Path) -> None:
    """Recheck a queued directory immediately before enumerating it."""
    validate_scan_root(str(path))
