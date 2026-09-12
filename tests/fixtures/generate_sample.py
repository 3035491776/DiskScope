"""Create deterministic synthetic files inside this project's fixture folder only."""

import argparse
import os
import stat
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent
SAMPLE_ROOT = FIXTURES / "sample_disk"
MEDIUM_ROOT = FIXTURES / "medium_disk"
FIXED_MTIME = 1_704_067_200  # 2024-01-01 00:00:00 UTC

SAMPLE_FILES = {
    "Users/TestUser/Desktop/empty.bin": 0,
    "Users/TestUser/Documents/note.bin": 1024,
    "Users/TestUser/Downloads/archive.bin": 5 * 1024 * 1024,
    "Users/TestUser/AppData/Local/Temp/cache.bin": 100 * 1024,
    "Windows/system.bin": 2 * 1024 * 1024,
    "Program Files/app.bin": 1 * 1024 * 1024,
    "Nested/A/nest.bin": 10 * 1024,
    "Nested/A/B/deep.bin": 4 * 1024,
    "Nested/C/one.bin": 1024,
    "Mixed/mix.bin": 2 * 1024 * 1024,
}
SAMPLE_DIRS = {
    "Users",
    "Users/TestUser",
    "Users/TestUser/Desktop",
    "Users/TestUser/Documents",
    "Users/TestUser/Downloads",
    "Users/TestUser/AppData",
    "Users/TestUser/AppData/Local",
    "Users/TestUser/AppData/Local/Temp",
    "Windows",
    "Program Files",
    "EmptyDir",
    "Nested",
    "Nested/A",
    "Nested/A/B",
    "Nested/C",
    "Mixed",
}
EXPECTED_SAMPLE_FILES = len(SAMPLE_FILES)
EXPECTED_SAMPLE_DIRS = len(SAMPLE_DIRS) + 1  # Include sample_disk itself.
EXPECTED_SAMPLE_BYTES = sum(SAMPLE_FILES.values())
EXPECTED_MEDIUM_FILES = 10_000
EXPECTED_MEDIUM_DIRS = 1_001
EXPECTED_MEDIUM_BYTES = EXPECTED_MEDIUM_FILES * 128


def _check_no_unexpected_entries(
    root: Path, expected_dirs: set[str], expected_files: set[str]
) -> None:
    if not root.exists():
        return
    if _is_reparse(root):
        raise RuntimeError("Fixture root must not be a reparse point")
    for item in root.rglob("*"):
        if _is_reparse(item):
            raise RuntimeError(f"Reparse point in fixture: {item.relative_to(root).as_posix()}")
        relative = item.relative_to(root).as_posix()
        allowed = expected_dirs if item.is_dir() else expected_files
        if relative not in allowed:
            raise RuntimeError(f"Unexpected fixture entry: {relative}")


def _is_reparse(path: Path) -> bool:
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _write_synthetic_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"D" * size)
    os.utime(path, (FIXED_MTIME, FIXED_MTIME))


def generate_sample() -> tuple[int, int, int]:
    _check_no_unexpected_entries(SAMPLE_ROOT, SAMPLE_DIRS, set(SAMPLE_FILES))
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    for relative in sorted(SAMPLE_DIRS):
        (SAMPLE_ROOT / relative).mkdir(parents=True, exist_ok=True)
    for relative, size in sorted(SAMPLE_FILES.items()):
        _write_synthetic_file(SAMPLE_ROOT / relative, size)
    return EXPECTED_SAMPLE_FILES, EXPECTED_SAMPLE_DIRS, EXPECTED_SAMPLE_BYTES


def generate_medium() -> tuple[int, int, int]:
    expected_dirs = {f"dir_{index:04d}" for index in range(1_000)}
    expected_files = {
        f"dir_{directory_index:04d}/file_{file_index:02d}.bin"
        for directory_index in range(1_000)
        for file_index in range(10)
    }
    _check_no_unexpected_entries(MEDIUM_ROOT, expected_dirs, expected_files)
    MEDIUM_ROOT.mkdir(parents=True, exist_ok=True)
    for directory_index in range(1_000):
        directory = MEDIUM_ROOT / f"dir_{directory_index:04d}"
        directory.mkdir(exist_ok=True)
        for file_index in range(10):
            _write_synthetic_file(directory / f"file_{file_index:02d}.bin", 128)
    return EXPECTED_MEDIUM_FILES, EXPECTED_MEDIUM_DIRS, EXPECTED_MEDIUM_BYTES


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--medium", action="store_true", help="Also create the performance fixture")
    args = parser.parse_args()
    print("sample files, dirs, bytes:", generate_sample())
    if args.medium:
        print("medium files, dirs, bytes:", generate_medium())
