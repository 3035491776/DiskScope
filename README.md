# DiskScope

DiskScope 是安全、低影响、易理解的 Windows 磁盘空间诊断工具。当前朋友测试版本为 **v0.2.0**。它先帮助用户看懂 C 盘与临时文件的空间占用，再通过“可处理 / 建议手动检查 / 不建议处理”给出明确下一步；扫描只读取文件基本信息，所有处理都只会移入 Windows 回收站。

Cleanup Center 的安全模型和第二轮测试计划见 [docs/v0.2-cleanup-center.md](docs/v0.2-cleanup-center.md) 与 [docs/friend-test-checklist.md](docs/friend-test-checklist.md)。v0.1.0 仍保留为正式技术基线，v0.1.1 作为第一轮普通用户测试基线。

## 当前实现

- FastAPI 后端：`GET /health` 返回 `guarded_cleanup` 模式，并分别声明只读扫描与受保护回收站能力。
- Vue 3 + TypeScript + Vite 页面：总览、空间分析、大文件与目录、扫描状态、历史与变化、空间建议、设置与说明；实际请求 `/health` 显示后端状态。
- 只读扫描器：流式读取元数据、目录聚合、Top-K、错误摘要和协作取消；完成结果保存为 SQLite 快照，重启后仍可浏览。
- 固定扫描入口：普通用户优先选择 Windows C: 或服务端解析的当前用户 `%LOCALAPPDATA%\Temp`；C: 必须经确认层启动专用只读扫描。Fixture 与项目工作区保留在默认关闭的开发与测试区域。Temp 入口不接受前端路径，且扫描不会删除文件。
- 本机固定卷容量卡片：`GET /api/v1/volumes` 读取容量，不启动扫描，也不列出网络盘。图表只绘制获准范围的扫描结果。
- M2 页面和 API 口径见 [docs/m2-space-analysis.md](docs/m2-space-analysis.md)。
- M3 在 `data/diskscope.db` 保存完成扫描的目录聚合与 Top-K 文件元数据；“历史与变化”页面比较相同固定范围的两次扫描。数据模型、增长口径、保留策略和故障隔离见 [docs/m3-snapshots-growth.md](docs/m3-snapshots-growth.md)。
- M4 固定 C: 范围、普通权限、安全校验、分类和容量口径见 [docs/m4-safe-c-drive-analysis.md](docs/m4-safe-c-drive-analysis.md)。D: 整卷仍锁定。
- M5 “空间建议”仅分析已保存快照的 Top-K 文件与目录聚合，提供保守分类、风险、置信度和识别依据；SQLite v1 数据原位迁移至 v2。规则与限制见 [docs/m5-cleanup-intelligence.md](docs/m5-cleanup-intelligence.md)。不执行清理。
- M5.1 总览、空间分析和大文件与目录可从最新已完成快照恢复；运行中展示进程资源指标，长路径与覆盖情况有明确展示。来源与历史安全边界见 [docs/m5.1-persistence-ux-stabilization.md](docs/m5.1-persistence-ux-stabilization.md)。
- M6 新增独立执行策略、实时元数据预检、90 秒单次 token 和 SQLite v3 审计。现有候选的 `/api/v1/cleanup/prepare` 仅做 dry-run，execute 仍返回 `EXECUTION_NOT_ENABLED_YET`。安全边界见 [docs/m6-cleanup-execution-safety.md](docs/m6-cleanup-execution-safety.md)。
- M6.1 只允许 DiskScope 本次进程在 `%LOCALAPPDATA%\Temp\DiskScope\probes` 下创建并登记的 64 KiB 测试文件经过完整门禁后移入 Windows 回收站。SQLite 原位升级至 v4；现有用户文件和 M5 候选没有获得真实处理能力。详见 [docs/m6.1-controlled-recycle-execution.md](docs/m6.1-controlled-recycle-execution.md)。
- M6.2 只允许已持久化候选中命中 `USER_TEMP_STALE_FILE_V1` 的单个普通文件：当前用户 `%LOCALAPPDATA%\Temp`、至少 30 天、高置信临时文件、低风险且达到 1 MiB。Prepare 和 Execute 都重新验证，只能移入 Windows 回收站，无永久删除回退。详见 [docs/m6.2-limited-user-temp-cleanup.md](docs/m6.2-limited-user-temp-cleanup.md)。
- M6.3 增加固定 `current_user_temp` metadata-only 扫描，以 10,000 项硬上限保存最大与最旧文件的确定性混合元数据，并明确报告完整或受限覆盖。结果进入独立 Snapshot、M5 候选分析和 M6.2 只读资格评估；不自动 prepare、签发 token 或执行。详见 [docs/m6.3-user-temp-candidate-discovery.md](docs/m6.3-user-temp-candidate-discovery.md)。
- M6.4 由 `ExecutionPolicyEngine` 返回结构化、确定性的 `PolicyDecision`，通过只读 API 和空间建议页解释候选为什么符合或不符合 guarded cleanup policy，并分别统计主要原因与全部原因及对应字节数。诊断基于历史快照元数据，不是执行授权，不会自动 prepare、签发 token 或执行。详见 [docs/m6.4-eligibility-diagnostics.md](docs/m6.4-eligibility-diagnostics.md)。
- M7 分离当前结果、下一次扫描范围和 History 比较范围，收拢 Recommendations 信息层级，完善覆盖语义、Dialog 键盘可访问性和启动 fragment 清理；不改变 M6 策略与执行边界。详见 [docs/m7-product-stabilization.md](docs/m7-product-stabilization.md)。
- M8 基于 cProfile 与可重复 fixture 消除重复 root/path 校验、无效 Top-K 对象构建和高频进度回调，并用 slotted metadata 模型降低目录聚合内存；保持单 worker、逐 entry 取消、reparse/跨卷保护与 schema v6。详见 [docs/m8-scan-performance.md](docs/m8-scan-performance.md)。
- M9 提供 Windows x64 one-folder portable release：预构建前端、内置 Python runtime，以 `DiskScope.exe` 启动本机服务和默认浏览器；开发数据、日志、Fixture 和源码不会进入发行包。构建与验收见 [docs/m9-packaging-release.md](docs/m9-packaging-release.md)。
- v0.2 新增“清理空间”、三层分类、独立人工复核授权、每批最多 200 个服务器 item ID、90 秒单次 batch token、逐项 live revalidation、顺序回收和部分成功审计；SQLite 原位升级至 v7。详见 [docs/v0.2-cleanup-center.md](docs/v0.2-cleanup-center.md)。
- Low-Impact `standard` 策略：单枚举 worker、禁止跨卷和 reparse 跟随；扫描状态展示必要的进程资源概览，内部标识留在技术详情。设计与口径见 [docs/low-impact-scan.md](docs/low-impact-scan.md)。
- `setup.bat`：检查本机 Python 和 Node.js，创建项目 `.venv`，安装依赖并构建前端。
- `start.bat`：调用 `launcher/bootstrap.py` 启动后端，等待真实健康检查成功，再打开默认浏览器。

## 尚未实现

本阶段可显式分析固定 C:\ 和当前用户 Temp 范围，也保留 fixture 与项目工作区；D:\ 整卷、任意路径和网络路径仍拒绝。批量处理仅编排逐文件安全检查；目录、应用缓存自动清理、系统转储、Windows/Program Files、回收站自动清空和永久删除均未开放。扫描器与执行策略都不打开文件正文，安全边界由后端执行。

## Portable Release

普通 Windows 10/11 x64 测试者完整解压 `DiskScope-v0.2.0-test-windows-x64.zip` 后，双击 `DiskScope.exe` 即可；无需 Python、Node.js、pip、npm、PowerShell 或管理员权限。测试包把数据库和日志分别写到自身的 `data\` 与 `logs\`，因此应解压到当前用户可写目录。完整说明见包内 `QUICKSTART.md`。

v0.2.0 朋友测试版未签名，可能出现 SmartScreen 或安全软件声誉提示。不要关闭或绕过系统安全功能；请向提供测试包的人核对 SHA-256。

## 源码首次准备与日常启动

在 Windows 10/11 x64 上安装 64 位 Python 3.11–3.14 和 Node.js，然后在项目根目录运行 `setup.bat`。脚本只在本项目的 `.venv` 中安装 Python 依赖，在 `frontend/node_modules` 中安装 npm 依赖，并生成 `frontend/dist`。首次准备可能需要网络，不修改系统 PATH、注册表或全局包环境。

准备完成后运行 `tests/fixtures/generate_sample.py` 生成受控样本，再双击 `start.bat`。启动器只在 `127.0.0.1:8765` 监听；端口被占用时会明确报错。后端通过 `/health` 验证后才打开本地页面，并通过一次性 URL fragment 建立 HttpOnly 本机会话。关闭启动窗口或按 Ctrl+C 可结束服务。运行日志保存在 `logs/`。

源码首次准备需要 Node.js 来构建页面；日常源码运行使用已构建的页面，无需启动 Node.js。Portable Release 已内置前端与 Python runtime，不使用源码开发依赖。

## 开发启动

先运行 `setup.bat` 并生成样本。完整启动流程优先使用 `start.bat`。若单独运行 Vite，需要在后端启用仅供开发的来源白名单，并给前后端使用同一临时启动凭据；不要把凭据提交到仓库。

开发时在后端终端运行：

```powershell
$env:DISKSCOPE_DEV_MODE='1'
$env:DISKSCOPE_BOOTSTRAP_TOKEN=[guid]::NewGuid().ToString('N')
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765 --workers 1
```

在另一个终端运行：

```powershell
npm.cmd --prefix frontend run dev
```

浏览器打开 `http://127.0.0.1:5173/#bootstrap=<同一临时凭据>`。Vite 将 `/health` 和 `/api` 转发到 `127.0.0.1:8765`。正式入口由后端直接提供 `frontend/dist`，页面和 API 同源。后端不启用公开 API 文档或宽泛 CORS。

## 受控样本与测试

`tests/fixtures/generate_sample.py` 可重复生成 `sample_disk`：10 个文件、17 个目录（含根目录）、10,604,544 字节。`--medium` 还会生成 10,000 文件、1,001 目录的性能样本。生成的文件均不进入 Git。

`tests/benchmark_m8.py` 使用相同 fixture 做 warmup 后重复计时，并可生成 50,000 个零内容文件的临时 metadata workload；它还记录 CPU、RSS、进程 I/O、Snapshot 保存和取消延迟，运行后自动移除大型临时样本。

```powershell
.venv\Scripts\python.exe tests\fixtures\generate_sample.py
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1
```

扫描 API 位于 `/api/v1/scans`，提供创建、状态、取消、Top 文件/大目录和当前层级目录结果；容量接口位于 `/api/v1/volumes`，历史与比较接口位于 `/api/v1/snapshots` 和 `/api/v1/compare`；快照候选分析与查询位于 `/api/v1/snapshots/{id}/analyze` 和 `/api/v1/candidates`。除 `/health` 外，这些 API 需要本机会话；修改请求还校验 Origin。C: 只能由固定 `system_drive_c` scope 与显式确认进入专用只读策略；Temp 只能使用 `current_user_temp`，路径由后端从当前会话环境解析。任意 root、其他整卷、UNC、设备路径及重解析点仍被拒绝。

## 安全边界

本地服务仅绑定回环地址；健康检查不返回敏感信息。启动时不扫描磁盘，只有显式发起任务才枚举获准目录的元数据。扫描器不读取文件内容、不修改扫描目标；生成器只写自己的受控样本。开发对齐基线见根目录 `DiskScope_开发对齐基线_v0.1.docx`。
