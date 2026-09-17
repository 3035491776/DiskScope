# 后续事项

- `BATCH_CLEANUP`：M6.4 未开放。
- `DIRECTORY_CLEANUP`：M6.4 未开放。
- `APPLICATION_CACHE_CLEANUP`：M6.4 未开放。
- `SYSTEM_DUMP_CLEANUP`：M6.4 未开放。
- `RECYCLE_BIN_MANAGEMENT`：M6.4 未开放。
- `UNDO`：M6.4 未开放；DiskScope 不承诺或提供回收站恢复 API。
- `POLICY_TUNING_FROM_DIAGNOSTICS`：可根据诊断统计另行评审；M6.4 不调整现有 30 天、高置信、低风险、Temp 单文件和回收站边界。
- `MFT_OR_USN_SCANNER`：可能带来数量级性能提升，但会改变当前 metadata-only 标准文件系统枚举与 Low-Impact 安全边界；M8 不实现。
- `AGGRESSIVE_PARALLEL_ENUMERATION`：可能提高部分设备吞吐，也可能增加 CPU、RSS、随机 I/O 和系统干扰；M8 保持单 worker，后续只有在独立 A/B 和产品边界评审后才考虑。
- `CODE_SIGNING`：V0.1 portable build 未签名；正式证书、签名流水线与 SmartScreen reputation 属于后续发布基础设施。
- `WINDOWS_10_HARDWARE_VALIDATION`：M9 在 Windows 11 x64 实机通过，Windows 10 x64 为目标平台但尚未在第二台真实系统验证。
- `RELEASE_ICON`：项目尚无正式图标；M9 保留 PyInstaller 默认图标，后续使用经过设计评审的资产替换。
- `INSTALLER_AND_AUTO_UPDATE`：M9 仅交付 one-folder portable ZIP，不写注册表、不安装服务；installer、卸载与更新策略留待后续。
- `ARM64_OR_X86_RELEASES`：V0.1 只构建 x64，其他架构需独立构建、测试和发布支持。
