"""Conservative, ordered Windows metadata rules. Patterns match path components."""

from dataclasses import dataclass


RULE_VERSION = "rules-v1.0.0"
MIB = 1024 * 1024
GIB = 1024 * MIB


@dataclass(frozen=True)
class CandidateRule:
    rule_id: str
    priority: int
    object_type: str
    pattern: tuple[str, ...]
    category: str
    risk_level: str
    confidence: str
    reason_code: str
    title: str
    summary: str
    explanation: str
    recommended_action: str
    min_bytes: int = MIB
    extensions: tuple[str, ...] = ()
    min_age_days: int | None = None

    def matches(self, parts: tuple[str, ...], object_type: str, size: int,
                age_days: float | None) -> bool:
        if self.object_type != object_type or size < self.min_bytes:
            return False
        if self.extensions and (not parts or not parts[-1].endswith(self.extensions)):
            return False
        if self.min_age_days is not None and (age_days is None or age_days < self.min_age_days):
            return False
        pattern = self.pattern
        tail = bool(pattern and pattern[-1] == "...")
        fixed = pattern[:-1] if tail else pattern
        if len(parts) < len(fixed) or (not tail and len(parts) != len(fixed)):
            return False
        return all(want == "*" or want == found for want, found in zip(fixed, parts))


RULES: tuple[CandidateRule, ...] = (
    CandidateRule("win-hibernation", 100, "file", ("hiberfil.sys",), "hibernation_file", "protected", "high", "HIBERNATION_SYSTEM_FILE", "Windows 休眠文件", "Windows 管理的休眠与快速启动文件。", "不建议手动处理；当前版本不会修改它。", "system_managed", 0),
    CandidateRule("win-pagefile", 100, "file", ("pagefile.sys",), "pagefile", "protected", "high", "PAGEFILE_SYSTEM_FILE", "Windows 页面文件", "Windows 管理的虚拟内存文件。", "不建议手动处理；当前版本不会修改它。", "system_managed", 0),
    CandidateRule("win-swapfile", 100, "file", ("swapfile.sys",), "swapfile", "protected", "high", "SWAPFILE_SYSTEM_FILE", "Windows 交换文件", "Windows 管理的交换文件。", "不建议手动处理；当前版本不会修改它。", "system_managed", 0),
    CandidateRule("service-temp-dump", 95, "file", ("windows", "serviceprofiles", "*", "appdata", "local", "temp", "..."), "crash_dump", "review", "high", "CRASH_DUMP_IN_SERVICE_TEMP", "大型崩溃转储", "系统服务临时目录中的诊断转储。", "如果相关故障已经排查，可人工评估后续处理；当前版本不会删除。", "review_for_cleanup", MIB, (".dmp",)),
    CandidateRule("browser-cache-chrome", 90, "file", ("users", "*", "appdata", "local", "google", "chrome", "user data", "*", "cache", "..."), "browser_cache", "review", "medium", "KNOWN_BROWSER_CACHE", "浏览器缓存文件", "位于明确的浏览器缓存目录。", "需确认浏览器状态及用途；当前版本不会处理。", "manual_review"),
    CandidateRule("browser-cache-edge", 90, "file", ("users", "*", "appdata", "local", "microsoft", "edge", "user data", "*", "cache", "..."), "browser_cache", "review", "medium", "KNOWN_BROWSER_CACHE", "浏览器缓存文件", "位于明确的浏览器缓存目录。", "需确认浏览器状态及用途；当前版本不会处理。", "manual_review"),
    CandidateRule("app-cache", 85, "file", ("users", "*", "appdata", "local", "*", "cache", "..."), "application_cache", "review", "medium", "APPLICATION_CACHE_FILE", "应用缓存文件", "位于应用专属 Cache 目录，但可能仍被应用使用。", "需要人工确认；当前版本不会处理。", "manual_review"),
    CandidateRule("user-temp-stale", 84, "file", ("users", "*", "appdata", "local", "temp", "..."), "temporary_file", "review", "medium", "STALE_USER_TEMP_FILE", "较久未更新的临时文件", "位于用户临时目录且最后修改时间超过七天。", "先确认应用不再需要；当前版本不会处理。", "manual_review", MIB, (), 7),
    CandidateRule("user-temp-recent", 72, "file", ("users", "*", "appdata", "local", "temp", "..."), "temporary_file", "high", "low", "RECENT_USER_TEMP_FILE", "近期临时文件", "临时目录中的文件可能正在使用。", "暂不作为优先关注项；当前版本不会处理。", "manual_review"),
    CandidateRule("program-data-log", 80, "file", ("programdata", "*", "logs", "..."), "log_file", "review", "medium", "STALE_APPLICATION_LOG", "应用日志文件", "位于应用日志目录且较久未更新。", "请先确认诊断需求；当前版本不会处理。", "manual_review", MIB, (".log",), 30),
    CandidateRule("download-installer", 78, "file", ("users", "*", "downloads", "..."), "installer_artifact", "review", "medium", "DOWNLOAD_INSTALLER_ARTIFACT", "下载的安装文件", "下载目录中的安装文件仍可能需要保留。", "请人工核对用途；当前版本不会处理。", "manual_review", 100 * MIB, (".msi", ".msix", ".exe")),
    CandidateRule("large-download", 75, "file", ("users", "*", "downloads", "..."), "user_download", "review", "high", "LARGE_USER_DOWNLOAD", "大型下载文件", "下载目录中的大文件可能由用户有意保留。", "请人工核对用途；当前版本不会处理。", "manual_review", 100 * MIB),
    CandidateRule("user-desktop", 70, "file", ("users", "*", "desktop", "..."), "user_desktop", "high", "high", "USER_DESKTOP_FILE", "桌面用户文件", "桌面文件属于用户数据。", "仅供了解占用；不要据此手动删除。", "manual_review"),
    CandidateRule("user-documents", 70, "file", ("users", "*", "documents", "..."), "user_document", "high", "high", "USER_DOCUMENT_FILE", "用户文档", "文档目录中的文件属于用户数据。", "仅供了解占用；不要据此手动删除。", "manual_review"),
    CandidateRule("appdata-generic", 62, "file", ("users", "*", "appdata", "..."), "application_managed", "high", "medium", "APPDATA_MANAGED_FILE", "应用数据文件", "AppData 可能包含配置、缓存及其他应用数据，不能整体视为缓存。", "仅供了解占用；当前版本不会处理。", "manual_review"),
    CandidateRule("generic-user", 60, "file", ("users", "..."), "user_data", "high", "medium", "USER_DATA_FILE", "用户数据文件", "位于用户资料区域。", "仅供人工了解占用；当前版本不会处理。", "manual_review"),
    CandidateRule("program-files", 65, "file", ("program files", "..."), "application_managed", "high", "high", "APPLICATION_MANAGED_FILE", "应用管理文件", "位于 Program Files，手动处理可能损坏应用。", "如需改变应用占用，应使用应用自身或系统管理机制；当前版本不会操作。", "review_application"),
    CandidateRule("program-files-x86", 65, "file", ("program files (x86)", "..."), "application_managed", "high", "high", "APPLICATION_MANAGED_FILE", "应用管理文件", "位于 Program Files (x86)，手动处理可能损坏应用。", "如需改变应用占用，应使用应用自身或系统管理机制；当前版本不会操作。", "review_application"),
    CandidateRule("program-data", 60, "file", ("programdata", "..."), "application_managed", "high", "medium", "PROGRAMDATA_MANAGED_FILE", "应用或系统管理文件", "ProgramData 不等同于可清理缓存。", "仅供了解占用；当前版本不会处理。", "manual_review"),
    CandidateRule("windows-generic", 55, "file", ("windows", "..."), "system_managed", "protected", "high", "WINDOWS_MANAGED_FILE", "Windows 系统文件", "位于 Windows 系统目录。", "不建议手动处理；当前版本不会修改它。", "system_managed"),
    CandidateRule("large-unknown", 10, "file", ("...",), "unknown", "high", "low", "UNKNOWN_LARGE_FILE", "大型未知文件", "仅凭大小无法判断用途。", "请人工识别来源；当前版本不会处理。", "manual_review", GIB),
    CandidateRule("known-app-cache-dir", 85, "directory", ("users", "*", "appdata", "local", "*", "cache"), "application_cache", "review", "medium", "APPLICATION_CACHE_DIRECTORY", "应用缓存目录", "目录名与所属路径符合应用缓存模式，无法确认文件是否仍在使用。", "需人工查看应用状态；当前版本不会处理。", "manual_review", 100 * MIB),
    CandidateRule("user-temp-dir", 70, "directory", ("users", "*", "appdata", "local", "temp"), "temporary_directory", "high", "medium", "USER_TEMP_DIRECTORY", "用户临时目录", "目录聚合不包含各文件的最后修改时间，不能据此判断可处理性。", "仅供了解占用；当前版本不会处理。", "manual_review", 100 * MIB),
    CandidateRule("windows-root", 60, "directory", ("windows",), "system_managed", "protected", "high", "WINDOWS_MANAGED_DIRECTORY", "Windows 系统目录", "由 Windows 管理的目录。", "不建议手动处理；当前版本不会修改它。", "system_managed", 0),
    CandidateRule("program-files-root", 60, "directory", ("program files",), "application_managed", "high", "high", "APPLICATION_MANAGED_DIRECTORY", "应用安装目录", "由已安装应用管理。", "仅供了解占用；当前版本不会处理。", "review_application", 0),
    CandidateRule("program-files-x86-root", 60, "directory", ("program files (x86)",), "application_managed", "high", "high", "APPLICATION_MANAGED_DIRECTORY", "应用安装目录", "由已安装应用管理。", "仅供了解占用；当前版本不会处理。", "review_application", 0),
    CandidateRule("program-data-root", 60, "directory", ("programdata",), "application_managed", "high", "high", "PROGRAMDATA_MANAGED_DIRECTORY", "ProgramData", "可能包含配置、系统数据和应用数据。", "不要把整个目录视作缓存；当前版本不会处理。", "manual_review", 0),
    CandidateRule("desktop-dir", 60, "directory", ("users", "*", "desktop"), "user_desktop", "high", "high", "USER_DESKTOP_DIRECTORY", "桌面占用", "桌面目录属于用户数据。", "仅供了解占用；当前版本不会处理。", "manual_review", 100 * MIB),
    CandidateRule("downloads-dir", 60, "directory", ("users", "*", "downloads"), "user_download", "review", "high", "USER_DOWNLOAD_DIRECTORY", "下载目录占用", "下载目录可能含用户有意保留的文件。", "请人工核对用途；当前版本不会处理。", "manual_review", 100 * MIB),
)


RULES = tuple(sorted(RULES, key=lambda rule: (-rule.priority, rule.rule_id)))
