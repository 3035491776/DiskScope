from pathlib import Path


def same_scan_volume(root: Path, candidate: Path) -> bool:
    """Reject a different Windows drive before considering an entry for traversal."""
    return bool(root.drive) and root.drive.casefold() == candidate.drive.casefold()
