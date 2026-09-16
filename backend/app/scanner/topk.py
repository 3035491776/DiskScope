import heapq
from dataclasses import dataclass

from app.scanner.models import FileMetadata


@dataclass
class _HeapItem:
    file: FileMetadata

    def __lt__(self, other: "_HeapItem") -> bool:
        if self.file.size_bytes != other.file.size_bytes:
            return self.file.size_bytes < other.file.size_bytes
        # Among equal sizes, a larger path is the worse candidate.
        return self.file.relative_path > other.file.relative_path


class TopKFiles:
    def __init__(self, limit: int = 1000) -> None:
        if limit < 1:
            raise ValueError("Top-K limit must be positive")
        self.limit = limit
        self._heap: list[_HeapItem] = []

    def add(self, file: FileMetadata) -> None:
        item = _HeapItem(file)
        if len(self._heap) < self.limit:
            heapq.heappush(self._heap, item)
        elif self._heap[0] < item:
            heapq.heapreplace(self._heap, item)

    def sorted_files(self) -> list[FileMetadata]:
        return [
            item.file
            for item in sorted(
                self._heap,
                key=lambda item: (-item.file.size_bytes, item.file.relative_path),
            )
        ]


@dataclass
class _OldestItem:
    file: FileMetadata

    def __lt__(self, other: "_OldestItem") -> bool:
        if self.file.mtime != other.file.mtime:
            return self.file.mtime > other.file.mtime
        return self.file.relative_path > other.file.relative_path


class BoundedHybridFiles:
    """Bounded deterministic size/age selection for the fixed user Temp scope."""

    def __init__(self, limit: int = 10_000) -> None:
        if limit < 2:
            raise ValueError("Hybrid persistence limit must be at least two")
        self.limit = limit
        self.size_quota = limit // 2
        self._size = TopKFiles(limit)
        self._oldest: list[_OldestItem] = []

    def add(self, file: FileMetadata) -> None:
        self._size.add(file)
        item = _OldestItem(file)
        if len(self._oldest) < self.limit:
            heapq.heappush(self._oldest, item)
        elif self._oldest[0] < item:
            heapq.heapreplace(self._oldest, item)

    def selected_files(self, observed_count: int) -> list[FileMetadata]:
        by_size = self._size.sorted_files()
        if observed_count <= self.limit:
            return by_size
        by_age = [item.file for item in sorted(
            self._oldest, key=lambda item: (item.file.mtime, item.file.relative_path)
        )]
        selected: dict[str, FileMetadata] = {}
        for file in by_size[:self.size_quota]:
            selected[file.relative_path] = file
        for file in by_age[:self.limit - self.size_quota]:
            selected.setdefault(file.relative_path, file)
        for file in (*by_size[self.size_quota:], *by_age[self.limit - self.size_quota:]):
            if len(selected) >= self.limit:
                break
            selected.setdefault(file.relative_path, file)
        return sorted(selected.values(), key=lambda file: (-file.size_bytes, file.relative_path))
