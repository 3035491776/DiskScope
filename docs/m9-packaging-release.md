# M9 — Packaging & Release Readiness

M9 将 DiskScope v0.1.0 交付为 Windows x64 one-folder portable release。普通用户解压后双击 `DiskScope.exe`，不需要安装 Python、Node.js、pip、npm 或使用 PowerShell，也不需要管理员权限。源码工作流 `setup.bat` / `start.bat` 保持不变。

## 方案选择

快速比较了 PyInstaller、Nuitka 与 Python embeddable distribution。Nuitka 会增加编译器工具链、构建时间和维护成本；embeddable distribution 需要自行维护解释器、依赖、入口和资源布局。PyInstaller 6.22.3 已能稳定收集 FastAPI、Uvicorn、Pydantic、stdlib SQLite、ctypes/IFileOperation 路径和静态前端，因此选择维护成本最低的 PyInstaller。

发布形态采用 one-folder，而不是 one-file。它避免每次启动临时解压，便于诊断和升级数据保留，也通常比新生成的单文件可执行程序更少触发额外声誉风险。V0.1 保留简洁 console launcher：启动失败会直接显示原因，并把正常启动信息写入日志；没有引入 Electron、WebView2、安装器或后台服务。

## 构建

构建机需要 Windows x64、64 位 Python 3.11–3.14、Node.js/npm、现有 `.venv` 与网络可用的初次依赖安装。运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1
```

脚本使用锁定的 `frontend/package-lock.json` 执行 `npm ci` 和 production build，再使用 `packaging/build-requirements.txt` 中固定的 `pyinstaller==6.22.3` 构建。它只删除仓库内明确的 `build\m9-release` 和同版本 release 输出，重新整理目录、创建空 `data\`/`logs\`、生成 ZIP 和 `.sha256` 文件。

构建输出：

```text
release\
  DiskScope-v0.1.0-windows-x64\
    DiskScope.exe
    _internal\
    data\
    logs\
    LICENSE
    QUICKSTART.md
    THIRD-PARTY-NOTICES.txt
    VERSION.txt
  DiskScope-v0.1.0-windows-x64.zip
  DiskScope-v0.1.0-windows-x64.zip.sha256
```

`build\` 与 `release\` 被 Git 忽略。连续 clean build 会清除旧产物；空 data/logs、文件数和顶层结构保持一致，不要求 PyInstaller 二进制 bit-for-bit 相同。

## Runtime path model

- Bundled resources：PyInstaller `_MEIPASS` 下的 `frontend/dist`，只读。
- Writable runtime root：`DiskScope.exe` 所在目录。
- SQLite：`data\diskscope.db`。
- 日志：`logs\launcher.log` 与 `logs\backend.log`。

构建不会复制源码仓库的 `data/diskscope.db`、WAL/journal、日志、Fixture、候选、probe 或审计记录。首次启动从空目录创建 schema v6。升级时应解压到用户可写目录并保留原有 `data\`；构建脚本自身从不把开发 DB 放进发行包。

## Launcher 与本机安全

`DiskScope.exe` 复用 `launcher/bootstrap.py`：检查资源与端口，创建 data/logs，启动同一打包程序的内部 `--serve` 模式，等待 `/health`，再用系统默认浏览器打开一次性 bootstrap fragment。服务固定绑定 `127.0.0.1:8765`，不开放 LAN、CORS 或公开 API docs。

bootstrap token 只通过子进程环境和浏览器 fragment 传递，不写日志；交换成功后前端立即清除 fragment，并使用 HttpOnly、SameSite=Strict cookie。第二实例遇到已占用的 8765 时以退出码 1 安全失败，显示明确错误，不终止现有进程。默认浏览器打不开时，console 会给出可手动打开的一次性本机地址。

启动器通过私有 stdin pipe 绑定子进程生命周期：正常 Ctrl+C、窗口关闭或父进程异常结束都会关闭 pipe，后端收到 EOF 后退出。实测强制终止 launcher 后，本机 health endpoint 在 10 秒内停止，无残留后端。内部 `--serve` 仅用于打包进程和自动化验收，不是普通用户入口。

缺少前端资源时提示重新完整解压；data/logs 路径不可用时提示把完整发行目录移动到当前用户可写位置。固定端口冲突同样返回可理解错误，所有路径均不尝试修改 ACL 或提升权限。

## Release / development isolation

`sys.frozen` 明确标识 packaged release。打包模式强制 developer mode OFF，即使环境中存在 `DISKSCOPE_DEV_MODE`；前端只显示 Windows C: 和当前用户 Temp，后端同时拒绝任意 caller root、`fixture_sample` 与 `project_workspace`。源码模式仍可通过已有 dev-mode contract 使用 Fixture 和 Project Workspace。

版本在 `/health`、release folder、VERSION、build script 与 EXE metadata 中统一为 `0.1.0`。EXE metadata 包含 Product Name `DiskScope`、Description `Windows disk space diagnostic tool`，manifest 不请求管理员权限。项目没有正式 icon，因此使用默认图标。

## Clean-machine-like acceptance

最终发行目录被复制到全新的 `%TEMP%\DiskScope-M9-Smoke-<id>`，从该目录直接运行；工作目录不是仓库，未激活 venv，程序不调用 PATH 中的 Python 或 Node。验证结果：

- 从最终 ZIP 解压后的独立目录启动，health ready 3.971 秒，`200`、version `0.1.0`、`guarded_cleanup`、developer mode false；
- `/` 与 hashed frontend assets 返回 200；bootstrap session 成功，fragment 清除；
- 任意 root 与 Fixture scope 均返回 403；
- Temp 实扫 26,234 文件、11,628 目录、14,719,894,294 bytes，15.281 秒、1,716.8 files/s、CPU 15.109 秒、RSS peak 74,702,848 bytes、Process Write 0 B；
- Snapshot 保存成功，10,000 项 bounded persistence 保持；新 DB schema v6，`integrity_check=ok`，`foreign_key_check=[]`；
- controlled probe 完成 create → prepare → single-use token → IFileOperation recycle → audit，目标只进入回收站；
- 第二实例退出码 1，并明确报告端口占用；日志未出现 bootstrap token。

浏览器 E2E 验证了 Dashboard、Scan Status、Space Analysis、大文件与目录、History、Recommendations、Settings；刷新和重启后从 Snapshot 恢复。C: volume card 与 Temp scope 可见，Fixture/Project 不可见，所有主路由正确，浏览器 console 0 warning/error。没有重新完整扫描 C:。

现有 260,919,296-byte schema v6 DB 先复制到另一隔离发行目录，再启动 packaged app；C: 与 Temp 最新 Snapshot、History source 和 1,586 条 Temp candidates 均可读取，原 DB 未修改。

## Packaged performance smoke

在 D: 隔离目录运行 packaged executable，真实 Temp 扫描先 warmup，再运行三次；相同源码 Python/相同 `ScanTaskManager` 也先 warmup 后运行三次。测量期间 Temp 稳定在约 25,554 文件、11,523 目录、14,561,518,460 bytes。

| Runtime | Median duration | Median throughput | Max observed RSS | Process write |
| --- | ---: | ---: | ---: | ---: |
| Packaged executable | 18.016 s | 1,418.4 files/s | 99,004,416 bytes | 0 B |
| Source Python | 23.531 s | 1,086.0 files/s | 60,329,984 bytes | 0 B |

两组均保持相同扫描语义和 0 B process write。短时真实 Temp 结果会受系统缓存、后台负载和同进程保留最近结果影响，因此这里只用于发现严重 packaging regression；本次没有出现 >20–30% 退化。打包 runtime 基础 RSS 较高，记录为 one-folder Python runtime 的资源代价。M8 scanner 的 slots、single worker、metadata reuse、bounded callbacks、volume cache、reparse/cross-volume/cancel 保护均未修改。

## Windows、签名与依赖

目标平台为 Windows 10 x64 与 Windows 11 x64；本次只在 Windows 11 x64（10.0.26200）实机验证，不能宣称 Windows 10 已实机通过。V0.1 未签名，SmartScreen/Defender 可能显示未知发布者或声誉提示；文档不会要求绕过或关闭安全软件，code signing 留待后续。

项目与发布 LICENSE 为 MIT。运行依赖的基础摘要在 `THIRD-PARTY-NOTICES.txt`：FastAPI/Pydantic 为 MIT，Starlette/Uvicorn/AnyIO/h11/idna 等为 BSD/MIT/PSF 兼容许可证，PyInstaller bootloader 使用带 bootloader exception 的 GPL。该清单是基本再分发核对，不构成完整法律审计。

## Artifact audit 与限制

发行目录搜索 `.git`、`.env`、credentials、tests、node_modules、源码目录、`__pycache__`、开发 DB/logs、Fixture、真实 Snapshot/candidate/probe/audit 均无命中。二进制文本搜索 `D:\Artilius`、`Artilius`、`Windows-C-clear`、`Codex` 无命中；runtime 不依赖构建机绝对路径。服务保持 metadata-only、no hash、no MFT/USN/raw disk、normal privilege、no ACL change、no permanent-delete fallback。

最终 ZIP 为 16,922,868 bytes，解压后的 101 个文件合计 37,076,951 bytes。SHA-256 为 `6d7f497d8f93c650d973f4b6beb282d4610ef0e8a29eb11cc01a26a91c7d53b7`，同时写入同名 `.zip.sha256`。已知限制：固定端口安全失败而不复用现有实例页面；portable 目录必须可写；无 installer、自动更新、签名、正式 icon、Windows 10 实机或 ARM64/x86 构建。这些事项只进入 backlog，不在 M9 扩大范围。
