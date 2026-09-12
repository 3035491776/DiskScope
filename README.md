# DiskScope

DiskScope 是 Windows 磁盘空间诊断工具。当前状态为 **V0.1 / M0 可运行骨架**，只提供本地 Web UI 与服务健康检查。

## 当前实现

- FastAPI 后端：`GET /health` 返回服务状态、应用名、版本和只读模式。
- Vue 3 + TypeScript + Vite 页面：实际请求 `/health` 显示后端状态，支持手动重新检查。
- `setup.bat`：检查本机 Python 和 Node.js，创建项目 `.venv`，安装依赖并构建前端。
- `start.bat`：调用 `launcher/bootstrap.py` 启动后端，等待真实健康检查成功，再打开默认浏览器。

## 尚未实现

本阶段没有磁盘扫描、清理、删除、文件修改、缓存删除、快照、统计或图表，也没有面向文件操作的 API。页面上的“只读诊断模式”表示产品边界，不表示 M0 已提供诊断结果。

## 首次准备与日常启动

在 Windows 10/11 x64 上安装 64 位 Python 3.11–3.14 和 Node.js，然后在项目根目录运行 `setup.bat`。脚本只在本项目的 `.venv` 中安装 Python 依赖，在 `frontend/node_modules` 中安装 npm 依赖，并生成 `frontend/dist`。首次准备可能需要网络，不修改系统 PATH、注册表或全局包环境。

准备完成后双击 `start.bat`。启动器只在 `127.0.0.1:8765` 监听；端口被占用时会明确报错。后端通过 `/health` 验证后才打开 `http://127.0.0.1:8765/`。关闭启动窗口或按 Ctrl+C 可结束服务。运行日志保存在 `logs/`。

当前 M0 的首次准备需要 Node.js 来构建页面；日常运行使用已构建的页面，无需启动 Node.js。后续发布流程会进一步处理无 Node 的首次安装体验。

## 开发启动

先运行 `setup.bat`。开发时在两个终端分别运行：

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765 --workers 1
npm.cmd --prefix frontend run dev
```

浏览器打开 `http://127.0.0.1:5173/`。Vite 将 `/health` 转发到 `127.0.0.1:8765`。正式入口由后端直接提供 `frontend/dist`，页面和健康检查同源。后端不启用公开 API 文档或宽泛 CORS。

## 安全边界

本地服务仅绑定回环地址；当前唯一 API 是无敏感信息的健康检查。启动时不枚举磁盘，不读取扫描目标目录或文件内容，不修改扫描目标。程序只写自己的依赖环境、前端构建产物和 `logs/`。开发对齐基线见根目录 `DiskScope_开发对齐基线_v0.1.docx`；本轮严格限于 M0。

