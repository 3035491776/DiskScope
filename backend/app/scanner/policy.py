from dataclasses import dataclass


@dataclass(frozen=True)
class ScanPolicy:
    """One-worker metadata-only invariants shared by approved scope modes."""

    mode: str = "standard"
    max_active_scans: int = 1
    concurrency: int = 1
    follow_reparse_points: bool = False
    allow_cross_volume: bool = False
    read_file_contents: bool = False
    hash_files: bool = False

    def __post_init__(self) -> None:
        if (
            self.mode not in {"standard", "c_drive_safe_readonly"}
            or self.max_active_scans != 1
            or self.concurrency != 1
            or self.follow_reparse_points
            or self.allow_cross_volume
            or self.read_file_contents
            or self.hash_files
        ):
            raise ValueError("Only single-worker metadata-only scan policies are supported")


SCAN_POLICY = ScanPolicy()
C_DRIVE_SAFE_READONLY = ScanPolicy(mode="c_drive_safe_readonly")
