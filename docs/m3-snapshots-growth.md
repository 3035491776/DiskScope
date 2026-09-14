# M3：扫描快照与增长比较

M3 在 M2 的只读扫描结果上增加本地历史。只有扫描状态为 `completed` 时，任务管理器才把**已经生成的内存结果**交给 Snapshot Store；写入器不重新访问扫描目录。`cancelled` 与 `failed` 不创建正式快照。完成但存在错误、跳过或受限目录时仍保存，`coverage=limited`、错误数和跳过数随快照保留。数据库写入失败独立标记 `snapshot_status=failed`，扫描维持 `completed`，当前结果仍可查看。

数据库位于 `data/diskscope.db`，由 `.gitignore` 排除。使用 Python 标准库 `sqlite3`、参数化 SQL、显式事务和每连接 `PRAGMA foreign_keys=ON`；不启用 WAL。`PRAGMA user_version=1`。版本 0 只初始化新库，版本 1 正常使用，更高版本返回 `SNAPSHOT_DATABASE_VERSION_UNSUPPORTED`。无法打开、锁定、损坏或缺表返回 `SNAPSHOT_DATABASE_UNAVAILABLE`；不会删除或重建异常数据库。历史故障不阻断健康检查、页面或扫描。

Schema 有 `scan_snapshots`、`directory_snapshots`、`file_snapshots`。扫描表存稳定 `scope_key`、时间、整数 byte 总量、文件/目录数、错误/跳过和覆盖情况；目录表存完整目录聚合及父子关系；文件表只存 Scanner 已有的 Top-K（当前 capacity 1000）元数据，不存所有文件，也不存内容或 hash。完整目录聚合可以按相对路径比较空间变化，有限 Top-K 则控制未来大目录的数据库规模。索引支持按 scope/时间列历史、按父目录取当前层级；目录和文件的 `(snapshot_id, relative_path)` 唯一约束同时提供路径索引。

固定范围映射为 `fixture_sample`、`project_workspace`；其他获准 fixture 子目录使用 `fixture_path:<相对路径>`，不能与前两者混淆。比较只允许同一 `scope_key`，否则 HTTP 400 `SNAPSHOT_SCOPE_MISMATCH`。历史列表 API 只返回摘要；单快照 API 也只返回摘要；历史目录 API 每次只返回一个父目录的直接子目录。所有历史 API 都要求现有本机会话。

比较定义 `delta_bytes=target-base`、`delta_ratio=(target-base)/base`。基准为 0 且目标为 0 时比例为 0；基准为 0 且目标大于 0 时返回 `null`，前端显示“新增”。目录以 `relative_path` 匹配并标注 `added`、`removed`、`grown`、`shrunk`、`unchanged`。增长空间榜按正向新增字节降序，排除根目录；增长比例榜只收录正向增长且**基准至少 256 KiB、目标至少 1 MiB**的目录，避免 1 B 到 1 MiB 这类极小基数长期霸榜。两榜各最多 20 条，目录变化摘要最多 100 条。

文件同样按相对路径匹配，但只在历史 Top-K 视野内比较：`new_large_files`、`removed_large_files`、`grown_large_files`、`shrunk_large_files`。不再出现在 Top-K 可能是跌出榜单，不能解读为物理文件被删除。任一快照覆盖受限、出现错误或跳过时，比较设置 `comparison_coverage_limited=true`，页面提示结果可能不完整。

每个 scope 保留最近 20 次完成快照。新快照、完整子记录和 retention 在**同一事务**内提交；任何失败均回滚，不会先删除旧历史。Retention 的 SQL `DELETE` 只作用于 `scan_snapshots`，外键 `ON DELETE CASCADE` 自动清理该快照的目录和 Top-K 元数据。数据库的 `removed` 只是比较状态，不触发文件系统操作。

安全边界沿用 M0–M2：仅 Fixture Sample 与显式白名单 Project Workspace，metadata-only、单活动任务、单 worker、协作取消、不跟随 reparse point、不跨卷、不读文件内容、不修改扫描目标。C:\、D:\ 及任意整卷根继续由 `WHOLE_VOLUME_SCAN_NOT_APPROVED` 拒绝；容量信息卡片不提供扫描授权。M3 不提供删除历史按钮或清理能力。
