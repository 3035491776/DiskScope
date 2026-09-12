from app.scanner.models import DirectoryStats


class DirectoryAggregator:
    """Keep one record per directory; roll child totals into parents once."""

    def __init__(self) -> None:
        self.directories: dict[str, DirectoryStats] = {}

    def add_directory(self, relative_path: str, parent: str | None) -> None:
        if relative_path in self.directories:
            raise ValueError(f"Duplicate directory: {relative_path}")
        self.directories[relative_path] = DirectoryStats(relative_path, parent)

    def add_file(self, parent: str, size_bytes: int) -> None:
        directory = self.directories[parent]
        directory.direct_bytes += size_bytes
        directory.subtree_bytes += size_bytes
        directory.direct_file_count += 1
        directory.file_count += 1

    def finish(self) -> dict[str, DirectoryStats]:
        # Discovery inserts each parent before its children.
        for directory in reversed(list(self.directories.values())):
            if directory.parent is not None:
                parent = self.directories[directory.parent]
                parent.subtree_bytes += directory.subtree_bytes
                parent.file_count += directory.file_count
                parent.children_count += 1
        return self.directories
