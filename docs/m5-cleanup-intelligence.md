# M5：空间建议与候选识别

M5 只解释已保存扫描结果中的空间占用，不执行删除、移动、回收、卸载、权限修改或任何目标文件操作。Scanner 仍负责元数据发现、目录聚合和最多 1000 个 Top 文件；独立的 Candidate Engine 只读取 SQLite 快照行，**不再遍历 C:\**，不打开文件正文，也不计算文件 hash。

## 数据与规则

`CleanupCandidate` 分开保存 `category`（对象是什么）、`risk_level`（人工处理风险：`protected/high/review/low`）和 `confidence`（识别确定性：`high/medium/low`）。风险“低”不等于保证安全或删除授权。每项包含稳定 `reason_code`、规则 ID 与 `rules-v1.0.0`、标题、说明、至少两条针对需确认项的 evidence、建议动作及需人工复核标记；不存在 `safe_to_delete`。候选 ID 对同一快照与规则版本确定，重新分析结果一致。规则按 priority 降序、rule ID 升序选择唯一最终命中；系统文件和明确的服务临时目录 dump 优先于通用大文件规则。路径按 Windows 分隔符拆成组件并不区分大小写，不用字符串前缀判断边界。

V1 保守识别 crash dump、临时文件与目录、应用或浏览器缓存、安装文件、日志、下载、桌面和文档、hiberfil/pagefile/swapfile、系统与应用管理项目及 unknown。`Windows/ServiceProfiles/*/AppData/Local/Temp/*.dmp` 为需确认的诊断转储；`hiberfil.sys` 等系统管理文件为受保护，不计入“值得关注的空间”。普通 AppData、ProgramData、Program Files、Windows 和用户文档不会因为扩展名、大小或年龄被判成可清理。Temp 的年龄只使用快照记录的 mtime，以扫描完成时间为参照，分为不足一天、1–7 天、7–30 天、30–90 天、超过 90 天；近期文件更保守。默认文件门槛 1 MiB，大型未知文件门槛 1 GiB。规则不读取文件锁状态，不调用 AI。

同一服务临时目录中的多个 dump 按 `reason_code + parent + category` 组成 group。UI 可展开成员。汇总的“值得关注的空间”仅求和 `review/low` 的**文件级** Top-K 候选，组与目录不重复计入，也绝不称为“可释放空间”。候选来自 Top-K 与完整目录聚合，不代表发现了 C 盘全部文件级可处理项目。覆盖受限的快照会在页面提示，扫描错误和跳过的 reparse point 不成为候选。

## 持久化与重启

SQLite `PRAGMA user_version` 从 v1 通过显式事务原位升级到 v2，保留原有三张快照表和数据；新表 `candidate_runs`、`cleanup_candidates` 以外键关联快照。`snapshot_id + rule_version` 唯一，重复分析返回同一成功 run；未来规则版本可重新分析旧快照，无需重新扫描。查询按扫描完成时间选择指定 scope 的最新已完成快照及最新成功 run。Recommendations 直接用这些 SQLite 记录，不依赖 ScanManager 的 current/last task；页面打开后可分析最新快照并展示扫描时间、规则版本、`analysis_coverage=top_k_and_directories`、覆盖及 Top-K 限制。快照保留策略删除旧快照时，关联候选随外键级联清理。

分析按游标流式读取目录快照，文件最多 1000 项，保留的只是命中项；不复制完整目录树。快照的逻辑大小不等于真实物理占用，硬链接、稀疏/压缩文件与权限限制仍影响结果。数据库不可用时返回明确错误，不触发扫描。候选分析时长记录于 run。

真实验收只分析已有 `system_drive_c` 已完成快照，检查服务临时目录 dump 的分组、hiberfil 受保护、证据详情、覆盖提示与 Top-K 提示；不得删除 dump，不得为了验收重扫 C 盘。M5 之外的 `PERSISTENT_SCAN_RESULT_RESTORE` 与 `REALTIME_PROCESS_METRICS` 见 [backlog.md](backlog.md)。
