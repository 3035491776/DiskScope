from pathlib import Path
from app.scanner.policy import SCAN_POLICY, ScanPolicy


WHOLE_VOLUME_SCAN_NOT_APPROVED = "WHOLE_VOLUME_SCAN_NOT_APPROVED"


class WholeVolumeScanDenied(ValueError):
    code = WHOLE_VOLUME_SCAN_NOT_APPROVED

    def __init__(self) -> None:
        super().__init__(WHOLE_VOLUME_SCAN_NOT_APPROVED)


def can_scan_whole_volume(root: Path, policy: ScanPolicy = SCAN_POLICY) -> bool:
    """Only the dedicated C policy can authorize the exact local C volume root."""
    return policy.mode == "c_drive_safe_readonly" and str(root).casefold() == "c:\\"


def reject_whole_volume_root(path: Path, policy: ScanPolicy = SCAN_POLICY) -> None:
    if path.drive and path == Path(path.anchor) and not can_scan_whole_volume(path, policy):
        raise WholeVolumeScanDenied()
