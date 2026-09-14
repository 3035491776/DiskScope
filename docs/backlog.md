# 后续事项

- `PERSISTENT_SCAN_RESULT_RESTORE`（M4.1）：重启后 Dashboard、空间分析及大文件与目录目前依赖 ScanManager 内存结果；后续从 latest completed snapshot 恢复浏览。M5 Recommendations 已直接读取 SQLite，不在本轮重构这些页面。
- `REALTIME_PROCESS_METRICS`：运行中的扫描尚未持续展示进程资源指标；单独处理，不纳入 M5。
