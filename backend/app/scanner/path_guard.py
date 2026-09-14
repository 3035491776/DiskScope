import os
import stat
from pathlib import Path, PureWindowsPath

from app.core.config import PROJECT_ROOT
from app.scanner.whole_volume_gate import reject_whole_volume_root


FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures"
# Temporary M1.5 developer allowlist. Only this exact root may be requested via API.
ALLOWED_REAL_ROOTS = (Path(r"D:\Artilius\Codex\Windows-C-clear"),)
PROJECT_ROOT_LABEL = "project_workspace"


class InvalidScanRoot(ValueError):
    pass


def is_reparse_point(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _normalized_path(raw_path: str) -> Path:
    if not raw_path or "\x00" in raw_path:
        raise InvalidScanRoot("A scan directory is required.")
    windows_path = PureWindowsPath(raw_path)
    if raw_path.startswith("\\\\") or windows_path.drive.startswith("\\\\"):
        raise InvalidScanRoot("UNC and device paths are not allowed.")
    if windows_path.drive and not windows_path.is_absolute():
        raise InvalidScanRoot("Drive-relative paths are not allowed.")
    supplied = Path(raw_path)
    return Path(os.path.abspath(supplied if supplied.is_absolute() else PROJECT_ROOT / supplied))


def _assert_no_reparse(start: Path, relative_parts: tuple[str, ...]) -> None:
    current = start
    try:
        if is_reparse_point(os.lstat(current)):
            raise InvalidScanRoot("Reparse points are not allowed in a scan path.")
        for component in relative_parts:
            current /= component
            if is_reparse_point(os.lstat(current)):
                raise InvalidScanRoot("Reparse points are not allowed in a scan path.")
    except OSError as exc:
        raise InvalidScanRoot("The scan path is unavailable.") from exc


def validate_scan_root(raw_root: str) -> tuple[Path, str]:
    lexical = _normalized_path(raw_root)
    reject_whole_volume_root(lexical)
    try:
        resolved = lexical.resolve(strict=True)
        if not resolved.is_dir():
            raise InvalidScanRoot("The scan root must be a directory.")

        if lexical == PROJECT_ROOT:
            if not any(
                lexical == allowed and resolved == allowed.resolve(strict=True)
                for allowed in ALLOWED_REAL_ROOTS
            ):
                raise InvalidScanRoot("The project workspace is not allowlisted.")
            _assert_no_reparse(lexical, ())
            return resolved, PROJECT_ROOT_LABEL

        relative_project_path = lexical.relative_to(PROJECT_ROOT)
        fixture_base = FIXTURE_ROOT.resolve(strict=True)
        resolved.relative_to(fixture_base)
        _assert_no_reparse(PROJECT_ROOT, relative_project_path.parts)
        return resolved, relative_project_path.as_posix()
    except (OSError, ValueError) as exc:
        if isinstance(exc, InvalidScanRoot):
            raise
        raise InvalidScanRoot(
            "Only tests/fixtures or the exact allowlisted project workspace may be scanned."
        ) from exc


def assert_safe_directory(root: Path, path: Path, scope_key: str | None = None) -> None:
    """Recheck each queued directory without broadening API root authorization."""
    if scope_key == "system_drive_c":
        if root != Path("C:\\"):
            raise InvalidScanRoot("The system drive scope is fixed to C:\\.")
        approved_root = root
    else:
        approved_root, _ = validate_scan_root(str(root))
    lexical = _normalized_path(str(path))
    try:
        relative = lexical.relative_to(approved_root)
        lexical.resolve(strict=True).relative_to(approved_root)
        _assert_no_reparse(approved_root, relative.parts)
    except (OSError, ValueError) as exc:
        if isinstance(exc, InvalidScanRoot):
            raise
        raise InvalidScanRoot("A queued directory left the approved scan root.") from exc
