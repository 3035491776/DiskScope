"""Shared file categories for cleanup triage; never an execution authority."""

from __future__ import annotations

from app.cleanup.policy import BLOCKED_EXTENSIONS


REVIEW_ROOTS = frozenset({"downloads", "desktop", "documents", "videos", "pictures", "music"})
TRIAGE_INDEX_LIMIT = 100_000

CATEGORY_LABELS = {
    "video": "视频", "image": "图片", "audio": "音频", "document": "文档",
    "archive": "压缩包", "disk_image": "磁盘镜像 / 虚拟机", "backup": "备份文件",
    "data": "数据文件", "diagnostic": "日志与诊断", "temporary": "临时类文件",
    "installer": "安装与程序", "development": "开发与项目", "creative": "设计与创作",
    "other": "其他文件",
}

_GROUPS = {
    "video": "mp4 mkv avi mov wmv flv webm m4v ts mts m2ts 3gp mpg mpeg vob",
    "image": "jpg jpeg png gif bmp webp tif tiff heic heif svg ico raw cr2 cr3 nef arw dng orf rw2",
    "audio": "mp3 flac wav aac m4a ogg opus wma aiff ape",
    "document": "pdf doc docx xls xlsx ppt pptx txt rtf odt ods odp md epub mobi",
    "archive": "zip 7z rar tar gz tgz bz2 xz zst",
    "disk_image": "iso img vhd vhdx vmdk vdi qcow2",
    "backup": "bak backup old",
    "data": "db sqlite sqlite3 csv tsv json jsonl ndjson xml parquet feather avro",
    "diagnostic": "log trace etl dump dmp",
    "temporary": "tmp temp cache",
    "installer": "exe msi msp msix appx appxbundle dll sys drv com scr cmd bat ps1",
    "development": "py pyc js ts tsx jsx java class jar c cpp h cs go rs swift kt ipynb",
    "creative": "psd psb ai aep prproj blend c4d max fbx obj dwg dxf",
}

EXTENSION_CATEGORY = {
    f".{extension}": category
    for category, extensions in _GROUPS.items()
    for extension in extensions.split()
}


def normalize_extension(name_or_extension: str) -> str:
    value = name_or_extension.strip().casefold()
    if not value:
        return ""
    if value.startswith(".") and "/" not in value and "\\" not in value:
        extension = value
    else:
        separator = max(value.rfind("/"), value.rfind("\\"))
        dot = value.rfind(".")
        extension = value[dot:] if dot > separator else ""
    if extension == ".":
        return ""
    return extension


def category_for_name(name: str) -> str:
    return EXTENSION_CATEGORY.get(normalize_extension(name), "other")


def is_blocked_extension(extension: str) -> bool:
    return normalize_extension(extension) in BLOCKED_EXTENSIONS
