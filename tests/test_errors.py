import errno
import unittest

from app.scanner.errors import ScanErrors, classify_os_error


class ErrorModelTests(unittest.TestCase):
    def test_error_classification(self) -> None:
        self.assertEqual(classify_os_error(PermissionError()), "ACCESS_DENIED")
        self.assertEqual(classify_os_error(FileNotFoundError()), "FILE_NOT_FOUND")
        self.assertEqual(
            classify_os_error(OSError(errno.ENAMETOOLONG, "synthetic")),
            "PATH_TOO_LONG",
        )
        self.assertEqual(classify_os_error(OSError("synthetic")), "IO_ERROR")

    def test_error_samples_are_bounded(self) -> None:
        errors = ScanErrors(samples_per_code=2)
        for index in range(10):
            errors.record("ACCESS_DENIED", f"fixture/file_{index}")
        summary = errors.summary()["ACCESS_DENIED"]
        self.assertEqual(summary["count"], 10)
        self.assertEqual(len(summary["samples"]), 2)


if __name__ == "__main__":
    unittest.main()
