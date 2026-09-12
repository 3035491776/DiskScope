from dataclasses import dataclass, field


@dataclass(frozen=True)
class FileMetadata:
    name: str
    relative_path: str
    parent: str
    size_bytes: int
    mtime: str
    attributes: int | None = None


@dataclass
class DirectoryStats:
    relative_path: str
    parent: str | None
    direct_bytes: int = 0
    subtree_bytes: int = 0
    direct_file_count: int = 0
    file_count: int = 0
    children_count: int = 0


@dataclass
class ScanResult:
    directories: dict[str, DirectoryStats] = field(default_factory=dict)
    top_files: list[FileMetadata] = field(default_factory=list)
    files_seen: int = 0
    dirs_seen: int = 0
    logical_bytes: int = 0
    skipped_count: int = 0
    errors_count: int = 0
    errors: dict[str, dict[str, object]] = field(default_factory=dict)
    exclusions: dict[str, dict[str, object]] = field(default_factory=dict)
    cancelled: bool = False
