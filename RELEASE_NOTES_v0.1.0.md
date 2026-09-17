# DiskScope v0.1.0

DiskScope 是安全、低影响、可解释的 Windows 磁盘空间诊断工具。本版本以 Windows x64 portable ZIP 交付，解压完整目录后双击 `DiskScope.exe` 即可运行。

## Highlights

- 分析 Windows C: 与当前用户 Temp 的扫描可见逻辑空间。
- 查看目录空间分布、逐层下钻、大文件与大目录。
- 保存同一固定范围的历史 Snapshot，并比较两次扫描的变化。
- 根据已保存元数据生成保守的空间建议和 cleanup eligibility diagnostics。
- 对极少数严格符合策略的当前用户 Temp 单文件，在用户逐项确认后移入 Windows 回收站。
- 无需安装 Python、Node.js、pip、npm、PowerShell 或管理员权限。

## Safety model

扫描只读取普通文件系统元数据，不读取普通文件正文、不计算文件内容哈希、不使用 MFT、USN Journal、raw disk 或设备 API。扫描器不跟随 symlink、junction 或其他 reparse point，不跨卷，保持单枚举 worker、普通用户权限和协作取消。

Cleanup 有意保持很窄：只支持满足 `USER_TEMP_STALE_FILE_V1` 的单个普通文件，要求位于当前用户 Temp 根目录、至少 30 天未修改、至少 1 MiB、高置信且低风险。Prepare 和 Execute 都会重新验证；唯一真实动作是移入 Windows 回收站。没有批量、目录、应用缓存、系统转储、自动或永久删除。

## Performance

M8 在不改变扫描范围和 Low-Impact 边界的前提下，减少了重复路径校验、无效对象构建和高频进度回调，并压缩了高基数目录元数据对象。可重复 large synthetic fixture 从 39.059 秒降至 9.133 秒。

一份在 M8 提交之后完成并保存的真实完整 C: Snapshot 被确认为 v0.1.0 的现场基线：1,173,146 个文件、377,234 个目录、423,183,874,865 个可见逻辑字节，耗时 1,243.484 秒，约 943.4 files/s，coverage limited。旧基线为约 459 files/s；由于两次扫描之间磁盘内容和系统状态发生变化，不能把全部差异归因于代码优化。

## Packaging

- Windows x64 one-folder portable release。
- 本地服务仅绑定 `127.0.0.1:8765`。
- 前端和 Python runtime 已包含在发布包内。
- 数据库和日志分别写入程序旁的 `data\` 与 `logs\`。
- 发布 ZIP 中的 `data\` 和 `logs\` 为空，不包含开发数据库、Snapshot 或日志。

## System requirements and compatibility

- Target: Windows 10/11 x64。
- Tested on: Windows 11 x64。
- Windows 10 physical validation: not completed。
- 需要系统默认浏览器和当前用户可写的解压目录。
- 不需要管理员权限。

## Signing and SmartScreen

v0.1.0 未进行代码签名。Windows SmartScreen 或安全软件可能显示未知发布者或声誉提示。请只从可信的项目 Release 页面下载，核对随 Release 提供的 SHA-256；不要关闭 Defender，也不要绕过系统安全功能。

## Known limitations

- 完整 C: 扫描可能需要较长时间。
- 扫描为 metadata-only，不能回答文件内容问题。
- 普通用户权限、reparse 和跨卷保护可能导致 coverage limited。
- Temp 文件元数据持久化硬上限为 10,000 项，采用确定性的最大与最旧选择。
- 历史 Snapshot 是扫描时的元数据，不代表目标文件当前状态。
- Cleanup 有意仅限严格合格的当前用户 Temp 单文件；没有 batch、directory、app-cache 或 permanent-delete 功能。
- 移入回收站的文件仍可能占用磁盘空间，直至用户通过 Windows 管理回收站。
- Windows 10 x64 尚未在真实主机验证。
- 可执行文件未签名。
- 本版本没有 installer、自动更新、ARM64 或 x86 构建。
