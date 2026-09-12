import unittest

from app.scanner.aggregator import DirectoryAggregator


MIB = 1024 * 1024


class AggregatorTests(unittest.TestCase):
    def test_direct_and_subtree_bytes_are_distinct(self) -> None:
        aggregator = DirectoryAggregator()
        aggregator.add_directory("", None)
        aggregator.add_directory("A", "")
        aggregator.add_directory("A/B", "A")
        aggregator.add_file("A", 10 * MIB)
        aggregator.add_file("A/B", 20 * MIB)
        directories = aggregator.finish()

        self.assertEqual(directories["A"].direct_bytes, 10 * MIB)
        self.assertEqual(directories["A"].subtree_bytes, 30 * MIB)
        self.assertEqual(directories["A/B"].direct_bytes, 20 * MIB)
        self.assertEqual(directories["A/B"].subtree_bytes, 20 * MIB)
        self.assertEqual(directories[""].subtree_bytes, 30 * MIB)
        self.assertEqual(directories["A"].direct_file_count, 1)
        self.assertEqual(directories["A"].file_count, 2)
        self.assertEqual(directories[""].file_count, 2)
        self.assertEqual(directories["A"].children_count, 1)

    def test_empty_directory_is_zero(self) -> None:
        aggregator = DirectoryAggregator()
        aggregator.add_directory("", None)
        aggregator.add_directory("EmptyDir", "")
        result = aggregator.finish()
        self.assertEqual(result["EmptyDir"].direct_bytes, 0)
        self.assertEqual(result["EmptyDir"].subtree_bytes, 0)
        self.assertEqual(result["EmptyDir"].file_count, 0)


if __name__ == "__main__":
    unittest.main()
