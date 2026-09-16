import ntpath
from pathlib import Path


def volume_identity(path: Path) -> str:
    """Return the cached lexical volume identity used by one scan."""
    return path.drive.casefold()


def path_matches_volume(root_drive: str, candidate: str) -> bool:
    """Reject another drive or UNC share without constructing a Path per entry."""
    candidate_drive, _ = ntpath.splitdrive(candidate)
    return bool(root_drive) and root_drive == candidate_drive.casefold()


def same_scan_volume(root: Path, candidate: Path) -> bool:
    """Reject a different Windows drive before considering an entry for traversal."""
    return path_matches_volume(volume_identity(root), str(candidate))
