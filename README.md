# DiskScope

DiskScope 是 Windows 磁盘空间诊断工具。当前状态为 **V0.1 / M5.1 结果恢复与体验稳定化**。C: 仅可经固定范围和显式确认进行元数据分析；**NO CLEANUP EXECUTION YET**。

## 当前实现

- FastAPI 后端：`GET /health` 返回服务状态、应用名、版本和只读模式。
- Vue 3 + TypeScript + Vite 页面：总览、空间分析、大文件与目录、扫描状态、历史与变化、空间建议、设置与说明；实际请求 `/health` 显示后端状态。
- 只读扫描器：流式读取元数据、目录聚合、Top-K、错误摘要和协作取消；完成结果保存为 SQLite 快照，重启后仍可浏览。
- 固定扫描入口：选择 fixture 或 `D:\Artilius\Codex\Windows-C-clear`；C: 只可从容量卡片确认后启动专用只读扫描。状态通过 HTTP 轮询，空间分析只按当前层级查询目录。
- 本机固定卷容量卡片：`GET /api/v1/volumes` 读取容量，不启动扫描，也不列出网络盘。图表只绘制获准范围的扫描结果。
- M2 页面和 API 口径见 [docs/m2-space-analysis.md](docs/m2-space-analysis.md)。
- M3 在 `data/diskscope.db` 保存完成扫描的目录聚合与 Top-K 文件元数据；“历史与变化”页面比较相同固定范围的两次扫描。数据模型、增长口径、保留策略和故障隔离见 [docs/m3-snapshots-growth.md](docs/m3-snapshots-growth.md)。
- M4 固定 C: 范围、普通权限、安全校验、分类和容量口径见 [docs/m4-safe-c-drive-analysis.md](docs/m4-safe-c-drive-analysis.md)。D: 整卷仍锁定。
- M5 “空间建议”仅分析已保存快照的 Top-K 文件与目录聚合，提供保守分类、风险、置信度和识别依据；SQLite v1 数据原位迁移至 v2。规则与限制见 [docs/m5-cleanup-intelligence.md](docs/m5-cleanup-intelligence.md)。不执行清理。
- M5.1 总览、空间分析和大文件与目录可从最新已完成快照恢复；运行中展示进程资源指标，长路径与覆盖情况有明确展示。来源与历史安全边界见 [docs/m5.1-persistence-ux-stabilization.md](docs/m5.1-persistence-ux-stabilization.md)。
- Low-Impact `standard` 策略：单枚举 worker、禁止跨卷和 reparse 跟随；开发区展示进程范围资源指标。设计与口径见 [docs/low-impact-scan.md](docs/low-impact-scan.md)。
- `setup.bat`：检查本机 Python 和 Node.js，创建项目 `.venv`，安装依赖并构建前端。
- `start.bat`：调用 `launcher/bootstrap.py` 启动后端，等待真实健康检查成功，再打开默认浏览器。

## 尚未实现

本阶段可显式分析固定 C:\ 范围，也保留 fixture 与项目工作区；D:\ 整卷、任意路径和网络路径仍拒绝。总览、空间分析、大文件与目录和空间建议可在重启后使用 SQLite 最新已完成快照。没有清理、删除、移动、文件修改或缓存清理。扫描器不打开文件内容。安全边界由后端执行。

## 首次准备与日常启动

在 Windows 10/11 x64 上安装 64 位 Python 3.11–3.14 和 Node.js，然后在项目根目录运行 `setup.bat`。脚本只在本项目的 `.venv` 中安装 Python 依赖，在 `frontend/node_modules` 中安装 npm 依赖，并生成 `frontend/dist`。首次准备可能需要网络，不修改系统 PATH、注册表或全局包环境。

准备完成后运行 `tests/fixtures/generate_sample.py` 生成受控样本，再双击 `start.bat`。启动器只在 `127.0.0.1:8765` 监听；端口被占用时会明确报错。后端通过 `/health` 验证后才打开本地页面，并通过一次性 URL fragment 建立 HttpOnly 本机会话。关闭启动窗口或按 Ctrl+C 可结束服务。运行日志保存在 `logs/`。

当前源码首次准备需要 Node.js 来构建页面；日常运行使用已构建的页面，无需启动 Node.js。后续发布流程会进一步处理无 Node 的首次安装体验。

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

```powershell
.venv\Scripts\python.exe tests\fixtures\generate_sample.py
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
```

扫描 API 位于 `/api/v1/scans`，提供创建、状态、取消、Top 文件/大目录和当前层级目录结果；容量接口位于 `/api/v1/volumes`，历史与比较接口位于 `/api/v1/snapshots` 和 `/api/v1/compare`；快照候选分析与查询位于 `/api/v1/snapshots/{id}/analyze` 和 `/api/v1/candidates`。除 `/health` 外，这些 API 需要本机会话；修改请求还校验 Origin。C: 只能由固定 `system_drive_c` scope 与显式确认进入专用只读策略；直接提交 `root: "C:\\"` 仍拒绝。项目扫描按路径组件排除 `.git/`、`.venv/`、`frontend/node_modules/`、`frontend/dist/`、`logs/`、`data/`。D: 和其他整卷、UNC、设备路径及重解析点仍被拒绝。

## 安全边界

本地服务仅绑定回环地址；健康检查不返回敏感信息。启动时不扫描磁盘，只有显式发起任务才枚举获准目录的元数据。扫描器不读取文件内容、不修改扫描目标；生成器只写自己的受控样本。开发对齐基线见根目录 `DiskScope_开发对齐基线_v0.1.docx`。
