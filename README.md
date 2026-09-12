# DiskScope

DiskScope 是 Windows 磁盘空间诊断工具。当前状态为 **V0.1 / M1 只读扫描器开发阶段**。M1 仅允许扫描仓库内的受控测试目录。

## 当前实现

- FastAPI 后端：`GET /health` 返回服务状态、应用名、版本和只读模式。
- Vue 3 + TypeScript + Vite 页面：实际请求 `/health` 显示后端状态，支持手动重新检查。
- fixture-only 扫描器：流式读取元数据、目录聚合、Top-K、错误摘要和协作取消；扫描结果暂存在内存。
- 开发扫描测试区：固定使用 `tests/fixtures/sample_disk`，通过 HTTP 轮询展示真实任务状态与结果。
- `setup.bat`：检查本机 Python 和 Node.js，创建项目 `.venv`，安装依赖并构建前端。
- `start.bat`：调用 `launcher/bootstrap.py` 启动后端，等待真实健康检查成功，再打开默认浏览器。

## 尚未实现

本阶段不扫描真实磁盘或用户目录，不提供清理、删除、移动、文件修改、缓存清理、SQLite 快照、增长比较或图表。扫描器不打开文件内容。M1 的路径限制由后端执行，页面上的固定选项不是安全边界。

## 首次准备与日常启动

在 Windows 10/11 x64 上安装 64 位 Python 3.11–3.14 和 Node.js，然后在项目根目录运行 `setup.bat`。脚本只在本项目的 `.venv` 中安装 Python 依赖，在 `frontend/node_modules` 中安装 npm 依赖，并生成 `frontend/dist`。首次准备可能需要网络，不修改系统 PATH、注册表或全局包环境。

准备完成后运行 `tests/fixtures/generate_sample.py` 生成受控样本，再双击 `start.bat`。启动器只在 `127.0.0.1:8765` 监听；端口被占用时会明确报错。后端通过 `/health` 验证后才打开本地页面，并通过一次性 URL fragment 建立 HttpOnly 本机会话。关闭启动窗口或按 Ctrl+C 可结束服务。运行日志保存在 `logs/`。

当前源码首次准备需要 Node.js 来构建页面；日常运行使用已构建的页面，无需启动 Node.js。后续发布流程会进一步处理无 Node 的首次安装体验。

## 开发启动

先运行 `setup.bat` 并生成样本。完整 M1 流程优先使用 `start.bat`。若单独运行 Vite，需要在后端启用仅供开发的来源白名单，并给前后端使用同一临时启动凭据；不要把凭据提交到仓库。

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
```

扫描 API 位于 `/api/v1/scans`，提供创建、状态、取消、Top 文件和目录结果。除 `/health` 外，M1 API 需要本机会话；修改请求还校验 Origin。扫描根必须是 `tests/fixtures` 或其子目录，拒绝真实盘符根、UNC、设备路径和重解析点。

## 安全边界

本地服务仅绑定回环地址；健康检查不返回敏感信息。启动时不扫描磁盘，只有显式发起的 fixture 任务才枚举测试目录元数据。扫描器不读取文件内容、不修改扫描目标；生成器只写自己的受控样本。开发对齐基线见根目录 `DiskScope_开发对齐基线_v0.1.docx`。
