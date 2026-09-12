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
