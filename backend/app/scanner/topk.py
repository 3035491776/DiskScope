import heapq
from dataclasses import dataclass
from datetime import datetime, timezone

from app.scanner.models import FileMetadata


@dataclass(slots=True)
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

    def accepts(self, size_bytes: int, relative_path: str) -> bool:
        if len(self._heap) < self.limit:
            return True
        worst = self._heap[0].file
        return (size_bytes > worst.size_bytes or
                (size_bytes == worst.size_bytes and relative_path < worst.relative_path))

    def add_observation(
        self, name: str, relative_path: str, parent: str, size_bytes: int,
        mtime_epoch: float, attributes: int | None,
    ) -> None:
        if not self.accepts(size_bytes, relative_path):
            return
        self.add(FileMetadata(
            name, relative_path, parent, size_bytes,
            datetime.fromtimestamp(mtime_epoch, timezone.utc).isoformat(), attributes,
        ))

    def sorted_files(self) -> list[FileMetadata]:
        return [
            item.file
            for item in sorted(
                self._heap,
                key=lambda item: (-item.file.size_bytes, item.file.relative_path),
            )
        ]


@dataclass(slots=True)
class _OldestItem:
    mtime_epoch: float
    file: FileMetadata

    def __lt__(self, other: "_OldestItem") -> bool:
        if self.mtime_epoch != other.mtime_epoch:
            return self.mtime_epoch > other.mtime_epoch
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
        timestamp = datetime.fromisoformat(file.mtime.replace("Z", "+00:00")).timestamp()
        item = _OldestItem(timestamp, file)
        if len(self._oldest) < self.limit:
            heapq.heappush(self._oldest, item)
        elif self._oldest[0] < item:
            heapq.heapreplace(self._oldest, item)

    def add_observation(
        self, name: str, relative_path: str, parent: str, size_bytes: int,
        mtime_epoch: float, attributes: int | None,
    ) -> None:
        size_accepts = self._size.accepts(size_bytes, relative_path)
        oldest_accepts = len(self._oldest) < self.limit
        if not oldest_accepts:
            worst = self._oldest[0]
            oldest_accepts = (mtime_epoch < worst.mtime_epoch or
                              (mtime_epoch == worst.mtime_epoch and
                               relative_path < worst.file.relative_path))
        if not size_accepts and not oldest_accepts:
            return
        file = FileMetadata(
            name, relative_path, parent, size_bytes,
            datetime.fromtimestamp(mtime_epoch, timezone.utc).isoformat(), attributes,
        )
        if size_accepts:
            self._size.add(file)
        if oldest_accepts:
            item = _OldestItem(mtime_epoch, file)
            if len(self._oldest) < self.limit:
                heapq.heappush(self._oldest, item)
            else:
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
