# M7 — Product Stabilization & UX Closure

M7 将 DiskScope 已有能力收拢为一致的普通用户流程。产品身份仍是安全、低影响、可解释的 Windows 磁盘空间诊断工具；本阶段没有增加扫描范围、清理规则或执行权限。

## 已处理的审计发现

- 分离当前结果来源、下一次扫描范围和 History 本页范围，消除重启后的 Fixture/C: 状态漂移。
- 删除 C: 扫描的固定耗时承诺，改为基于文件数量、磁盘性能和权限差异的事实说明；存在当前 C: 结果时只显示“上次扫描耗时”。
- 普通扫描入口只突出 Windows C: 与当前用户临时文件；Fixture Sample 与 Project Workspace 保留在默认关闭的开发与测试区域。
- History 同时显示目录扫描覆盖和文件元数据保存覆盖。
- 空间建议默认先展示来源、扫描时间、coverage、候选空间、候选数量与风险；资格诊断、内部版本、原始原因码、受控测试和操作记录进入渐进展开层级。
- 新增轻量共享 Dialog，实现初始焦点、Tab/Shift+Tab 焦点循环、Escape 关闭、关闭后焦点恢复、`role=dialog`、`aria-modal` 和可访问标题。
- 本机会话 bootstrap 成功后再次清除 URL fragment，同时保持当前 route 与 query。
- 扫描状态主区域不再直接展示任务 UUID 或“开发指标”文案；原始标识与错误码保留在技术详情。

## 状态契约

`selectedTarget` 表示用户下一次准备扫描的固定范围。它不描述当前页面显示的结果，也不会因为恢复历史 C: Snapshot 而自动获得 C: 扫描授权。

`resultTarget` 表示当前页面正在浏览的实时结果或已保存 Snapshot。Header、总览、空间分析和大文件页面以它为结果来源。

`historyTarget` 是 History 页面自己的比较范围。第一次进入时跟随 `resultTarget`；用户手动切换后，在页面往返期间保持自己的选择，不会回写 `selectedTarget` 或 `resultTarget`。

无可恢复结果时，Header 明确显示“尚无扫描结果”，Dashboard 引导用户选择 Windows C: 或当前用户临时文件，不伪造 Fixture 来源。

## 用户范围与开发范围

普通入口提供：

- Windows C:：开始前必须再次确认只读边界。
- 当前用户临时文件：固定服务端范围，只读取元数据。

Fixture Sample 与 Project Workspace 后端能力、测试支持和结果浏览能力均保留，但只位于默认关闭的“开发与测试范围/结果”区域。

## C: 扫描预期

C: 确认层不再给出“几十秒至数分钟”的承诺。文案说明完整系统盘扫描受文件数量、磁盘性能和权限情况影响，较大的系统盘可能需要较长时间；扫描期间可以查看状态并随时取消。若当前正在浏览已保存的 C: 结果，只把其真实耗时标为“上次扫描耗时”。

## Coverage 语义

目录扫描覆盖描述枚举过程中是否有位置因权限、安全边界或文件变化而未覆盖。

文件元数据保存覆盖描述已观察文件中有多少条进入有界 Snapshot 元数据。Temp 可以同时出现“部分位置未覆盖”和“10,000 / 26,543，受限”，两者不再互相覆盖。Recommendations 与资格说明继续明确 limited coverage，零 eligible 只表示已分析候选中没有文件同时满足全部条件。

## Recommendations 信息层级

第一层面向普通用户：来源、时间、coverage、值得关注的空间、候选数量、风险和建议项目。每个风险组保留完整总数，默认只预览前 12 项，避免数百张候选卡淹没主流程。

第二层是资格说明：符合或暂不符合处理条件，以及可理解的主要原因。

第三层是高级技术详情：候选规则版本、执行策略版本、原始 reason code、scope/evidence、候选内部标识和原始操作字段。受控 probe 位于“开发与测试工具”，操作审计位于默认关闭的“操作记录”。这些调整只改变前端呈现，不改变候选分析、prepare 或 execute 语义。

## Dialog 可访问性

`BaseDialog.vue` 是本阶段唯一新增的共享 UI 基础组件。Dashboard 的 C: 确认、候选详情、真实候选预检和受控 probe 预检使用同一套焦点与键盘行为。涉及真实执行的按钮、二次确认、单文件约束和回收站语义未改变。

## Bootstrap fragment

启动器 fragment 只用于一次性本机会话交换。前端在发送交换请求前清除 fragment，并在成功响应后使用当前 History state 再次清除，以覆盖 Router 初始导航的竞态；path 与 query 保持不变，刷新继续使用 HttpOnly 会话。

## 明确未改变

- 不修改 Scanner，不优化 C: 性能，不使用 MFT、USN、raw disk 或新增 worker。
- 不修改 SQLite schema；仍为 v6，不做 migration。
- 不修改 Candidate Intelligence 或 `ExecutionPolicyEngine` 语义。
- 不增加批量、目录、永久删除、应用缓存、系统转储、回收站管理或 Undo。
- 不读取目标正文，不 hash 目标文件，不提升权限，不更改 ACL。
- 不执行完整 C: 重扫。
- 不做安装器、代码签名或无 Python runtime 打包。

## M6 freeze

`USER_TEMP_STALE_FILE_V1`、30 天门槛、低风险、高置信、临时文件分类、扩展名 denylist、单文件、candidate-ID-only 和 recycle-only 边界全部冻结。M7 不放开 nested Temp，不新增 cleanup rule，也不根据诊断调整策略。

## 后续边界

M8 才评估扫描性能。M9 才处理 PyInstaller/Nuitka、安装器、签名和发布形态。`POLICY_TUNING_FROM_DIAGNOSTICS` 仍在 backlog，不属于 M7。
