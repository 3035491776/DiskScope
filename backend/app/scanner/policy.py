from dataclasses import dataclass


@dataclass(frozen=True)
class ScanPolicy:
    """M1.6 invariants. Only standard mode is implemented."""

    mode: str = "standard"
    max_active_scans: int = 1
    concurrency: int = 1
    follow_reparse_points: bool = False
    allow_cross_volume: bool = False
    read_file_contents: bool = False
    hash_files: bool = False

    def __post_init__(self) -> None:
        if (
            self.mode != "standard"
            or self.max_active_scans != 1
            or self.concurrency != 1
            or self.follow_reparse_points
            or self.allow_cross_volume
            or self.read_file_contents
            or self.hash_files
        ):
            raise ValueError("M1.6 supports only the single-worker metadata-only standard policy")


SCAN_POLICY = ScanPolicy()
