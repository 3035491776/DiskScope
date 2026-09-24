import heapq
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.scanner.models import FileMetadata


class RankedFile(Protocol):
    relative_path: str
    size_bytes: int
    mtime: str


def safe_mtime_iso(mtime_epoch: float) -> str | None:
    """Convert filesystem time without letting invalid metadata abort a scan."""
    try:
        return datetime.fromtimestamp(mtime_epoch, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


@dataclass(slots=True)
class _HeapItem:
    file: RankedFile

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

    def add(self, file: RankedFile) -> None:
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
    ) -> bool:
        if not self.accepts(size_bytes, relative_path):
            return True
        mtime = safe_mtime_iso(mtime_epoch)
        self.add(FileMetadata(
            name, relative_path, parent, size_bytes,
            mtime or "", attributes,
        ))
        return mtime is not None

    def sorted_files(self) -> list[RankedFile]:
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
    file: RankedFile

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
        # Most bounded scopes fit below their cap. Keep their insertion path O(1)
        # and materialize heaps only after the first actual overflow.
        self._all: list[RankedFile] | None = []
        self._all_mtimes: list[float | None] | None = []

    def _promote_to_heaps(self) -> None:
        assert self._all is not None
        assert self._all_mtimes is not None
        for file, timestamp in zip(self._all, self._all_mtimes, strict=True):
            self._size.add(file)
            if timestamp is None:
                continue
            heapq.heappush(self._oldest, _OldestItem(timestamp, file))
            if len(self._oldest) > self.limit:
                heapq.heappop(self._oldest)
        self._all = None
        self._all_mtimes = None

    def add(self, file: RankedFile) -> bool:
        try:
            timestamp = datetime.fromisoformat(file.mtime.replace("Z", "+00:00")).timestamp()
        except (OSError, OverflowError, ValueError):
            timestamp = None
        return self.add_prepared(file, timestamp)

    def add_prepared(self, file: RankedFile, mtime_epoch: float | None) -> bool:
        """Add already validated metadata without repeating time conversion."""
        if self._all is not None:
            assert self._all_mtimes is not None
            self._all.append(file)
            self._all_mtimes.append(mtime_epoch)
            if len(self._all) > self.limit:
                self._promote_to_heaps()
            return mtime_epoch is not None
        self._size.add(file)
        if mtime_epoch is None:
            return False
        item = _OldestItem(mtime_epoch, file)
        if len(self._oldest) < self.limit:
            heapq.heappush(self._oldest, item)
        elif self._oldest[0] < item:
            heapq.heapreplace(self._oldest, item)
        return True

    def add_observation(
        self, name: str, relative_path: str, parent: str, size_bytes: int,
        mtime_epoch: float, attributes: int | None,
    ) -> bool:
        if self._all is not None:
            mtime = safe_mtime_iso(mtime_epoch)
            file = FileMetadata(
                name, relative_path, parent, size_bytes, mtime or "", attributes,
            )
            return self.add_prepared(file, mtime_epoch if mtime is not None else None)
        size_accepts = self._size.accepts(size_bytes, relative_path)
        oldest_accepts = len(self._oldest) < self.limit
        if not oldest_accepts:
            worst = self._oldest[0]
            oldest_accepts = (mtime_epoch < worst.mtime_epoch or
                              (mtime_epoch == worst.mtime_epoch and
                               relative_path < worst.file.relative_path))
        if not size_accepts and not oldest_accepts:
            return True
        mtime = safe_mtime_iso(mtime_epoch)
        file = FileMetadata(
            name, relative_path, parent, size_bytes,
            mtime or "", attributes,
        )
        if size_accepts:
            self._size.add(file)
        # Missing/invalid times remain eligible for size selection but never
        # masquerade as an old file in the age-based half of Temp persistence.
        if oldest_accepts and mtime is not None:
            item = _OldestItem(mtime_epoch, file)
            if len(self._oldest) < self.limit:
                heapq.heappush(self._oldest, item)
            else:
                heapq.heapreplace(self._oldest, item)
        return mtime is not None

    def selected_files(self, observed_count: int, ordered: bool = True) -> list[RankedFile]:
        if self._all is not None:
            files = list(self._all)
            return (sorted(files, key=lambda file: (-file.size_bytes, file.relative_path))
                    if ordered else files)
        by_size = self._size.sorted_files()
        if observed_count <= self.limit:
            return by_size
        by_age = [item.file for item in sorted(
            self._oldest, key=lambda item: (item.mtime_epoch, item.file.relative_path)
        )]
        selected: dict[str, RankedFile] = {}
        for file in by_size[:self.size_quota]:
            selected[file.relative_path] = file
        for file in by_age[:self.limit - self.size_quota]:
            selected.setdefault(file.relative_path, file)
        for file in (*by_size[self.size_quota:], *by_age[self.limit - self.size_quota:]):
            if len(selected) >= self.limit:
                break
            selected.setdefault(file.relative_path, file)
        values = list(selected.values())
        return (sorted(values, key=lambda file: (-file.size_bytes, file.relative_path))
                if ordered else values)
