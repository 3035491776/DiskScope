import unittest

from app.scanner.models import FileMetadata
from app.scanner.topk import BoundedHybridFiles, TopKFiles


def file(path: str, size: int) -> FileMetadata:
    return FileMetadata(path, path, "", size, "2024-01-01T00:00:00+00:00")


class TopKTests(unittest.TestCase):
    def test_fewer_than_k(self) -> None:
        top = TopKFiles(3)
        top.add(file("a", 1))
        top.add(file("b", 2))
        self.assertEqual([item.relative_path for item in top.sorted_files()], ["b", "a"])

    def test_equal_to_k(self) -> None:
        top = TopKFiles(2)
        top.add(file("a", 1))
        top.add(file("b", 2))
        self.assertEqual(len(top.sorted_files()), 2)

    def test_greater_than_k(self) -> None:
        top = TopKFiles(2)
        for path, size in (("a", 1), ("b", 3), ("c", 2)):
            top.add(file(path, size))
        self.assertEqual([item.relative_path for item in top.sorted_files()], ["b", "c"])

    def test_ties_prefer_lexicographically_smaller_paths(self) -> None:
        top = TopKFiles(2)
        for path in ("z", "b", "a"):
            top.add(file(path, 5))
        self.assertEqual([item.relative_path for item in top.sorted_files()], ["a", "b"])

    def test_zero_byte_file(self) -> None:
        top = TopKFiles(1)
        top.add(file("zero", 0))
        self.assertEqual(top.sorted_files()[0].size_bytes, 0)

    def test_observations_keep_top_k_without_materializing_every_file(self) -> None:
        top = TopKFiles(2)
        for path, size in (("z", 5), ("b", 5), ("a", 5), ("tiny", 1)):
            top.add_observation(path, path, "", size, 1_704_067_200, None)
        self.assertEqual([item.relative_path for item in top.sorted_files()], ["a", "b"])

    def test_hybrid_observations_preserve_size_and_oldest_selection(self) -> None:
        hybrid = BoundedHybridFiles(4)
        values = ((9, 50), (8, 40), (1, 10), (2, 20), (7, 30))
        for index, (size, mtime) in enumerate(values):
            path = f"f{index}"
            hybrid.add_observation(path, path, "", size, mtime, None)
        selected = hybrid.selected_files(5)
        self.assertEqual(
            {item.relative_path for item in selected}, {"f0", "f1", "f2", "f3"}
        )


if __name__ == "__main__":
    unittest.main()
