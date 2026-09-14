# M4：Windows C: 安全只读分析

M4 首次为固定 `system_drive_c` 范围开放 Windows C:\ 的**只读空间分析**。它现在开放，是因为 M1–M3 已建立元数据扫描、Low-Impact 约束、固定范围、错误统计、取消、空间分析和快照。M4 仍无任何清理、删除、移动、卸载或权限修改能力；D:\ 和其他整卷根继续拒绝。

扫描 API 只接受固定 `scope_key=system_drive_c` 加 `confirmed_readonly=true`，不接受同时传入 `root`。普通 `root: "C:\\"` 请求仍走旧 whole-volume gate 并被拒绝。前端只在 C: 容量卡片的“分析 C 盘”按钮显示确认层，确认后才发送请求；不会随启动、打开页面或定时器自动扫描。固定 registry 将该 scope 映射到 `C:\`、`Windows C:` 和 `c_drive_safe_readonly`；用户无法自由输入 C 盘子目录或其他路径。

扫描前通过 Windows `GetDriveTypeW` 核实 C:\ 为 `DRIVE_FIXED`，并拒绝不可用或根本身为 reparse point 的情况。UNC、设备命名空间、GLOBALROOT 和 Volume GUID 路径不进入固定 scope；普通路径入口继续拒绝这些形式。扫描器对每个目录重查路径边界，使用不跟随链接的元数据 stat；junction、symlink、mount point 等 reparse point 记录 `REPARSE_POINT_SKIPPED` 并跳过，跨卷条目不遍历。无需 `CreateFileW`、`DeviceIoControl`、PhysicalDrive、Raw Disk 或特权 API。

`c_drive_safe_readonly` 与原 `standard` 共用一个 Scanner：单活动任务、单枚举 worker、metadata-only、不读文件正文、不 hash、不写目标、不修改 ACL、不提权、不执行 shell 扫描。普通用户权限是默认模式；`ACCESS_DENIED`、`FILE_NOT_FOUND`、`PATH_TOO_LONG` 等单路径问题记录后继续，覆盖标记为 `limited`，绝不通过 takeown、icacls、UAC 或管理员启动绕过。日志只保留任务级或关键错误摘要，不逐文件写日志。

Windows 顶层目录标记 `system_category` 与 `risk_class`：Windows、Program Files、Program Files (x86)、ProgramData、Users、Recovery、System Volume Information、$Recycle.Bin、PerfLogs 和其他。pagefile.sys、hiberfil.sys、swapfile.sys 标记为系统管理文件。分类仅用于展示，绝不产生 `safe_to_delete`、清理评分或操作按钮。空间分析按当前层级请求目录，Top 文件默认显示 100 条，Scanner heap 最多保存 1000 条；目录聚合每目录一条记录，回卷时不复制整张目录值列表。低影响指标展示耗时、速度、RSS、CPU 和进程 I/O；进程写入可能来自应用 SQLite/日志，不代表目标文件被修改。

**磁盘已用空间**来自 Windows 卷容量 API；**扫描可见空间**来自文件条目的逻辑大小之和，两者不相等，也不保证完整覆盖。权限保护、NTFS 元数据、保留空间、pagefile、hard link、sparse/compressed 文件、去重与瞬时变化都会造成差异。M4 不做硬链接物理去重或稀疏文件实际簇计算，不声称“物理占用完全精确”。扫描前未知文件总数，界面只显示已发现数量、空间和耗时，不显示虚构百分比。取消后 worker 退出，可重新启动固定范围扫描。

完成的 C: 扫描以 `system_drive_c` 保存快照；取消/失败不保存，覆盖受限仍可保存。仍是完整目录聚合与 Top-K 文件元数据，每 scope 保留 20 次。比较只允许 C: 对 C:，不同范围拒绝。C 盘缓存、日志、更新与权限会自然波动；比较覆盖受限时页面提示结果可能不完整，不能把所有变化归因于用户行为。

真实验收应以普通权限运行 `start.bat`，先点“分析 C 盘”，阅读确认后观察扫描状态与资源指标，至少取消一次并确认后续 Project Workspace 扫描可启动；随后只完成一次 C: 扫描，核对空间分析、Top-K 和历史。若环境阻止真实 C: 扫描，应报告阻断并由用户本机补验，不修改安全策略或提权。
