from pathlib import Path


WHOLE_VOLUME_SCAN_NOT_APPROVED = "WHOLE_VOLUME_SCAN_NOT_APPROVED"


class WholeVolumeScanDenied(ValueError):
    code = WHOLE_VOLUME_SCAN_NOT_APPROVED

    def __init__(self) -> None:
        super().__init__(WHOLE_VOLUME_SCAN_NOT_APPROVED)


def can_scan_whole_volume(_root: Path) -> bool:
    """Independent M1.6 gate: no whole-volume scan is approved."""
    return False


def reject_whole_volume_root(path: Path) -> None:
    if path.drive and path == Path(path.anchor) and not can_scan_whole_volume(path):
        raise WholeVolumeScanDenied()
