# DiskScope v0.1.0 快速开始

DiskScope 是面向 Windows 的安全、低影响磁盘空间诊断工具。

## 系统要求

- Windows 10 或 Windows 11，64 位 x64。
- 普通用户权限；不需要管理员权限。
- 系统默认浏览器。

## 启动

1. 下载 `DiskScope-v0.1.0-windows-x64.zip`。
2. 将完整发布包解压到当前用户可写目录，例如“下载”或“文档”；不要直接在 ZIP 内运行 `DiskScope.exe`。
3. 双击 `DiskScope.exe`。
4. 保持启动窗口打开。默认浏览器会自动打开 `http://127.0.0.1:8765/`。
5. 选择 Windows C: 或当前用户临时文件。
6. 点击“开始扫描”进行只读分析。

不需要安装 Python、Node.js、npm 或其他开发工具。如果浏览器未自动打开，请按启动窗口提示手动打开本地地址。

## 安全说明

- 扫描仅读取文件系统元数据，不读取普通文件正文，不计算文件内容哈希。
- DiskScope 不请求管理员权限，不跟随 reparse point，不跨卷扫描。
- 真实处理仅限严格策略允许的单个 Temp 文件，并且只移入 Windows 回收站；没有永久删除回退。

## 数据与日志

- 数据库：`data\diskscope.db`
- 日志：`logs\launcher.log`、`logs\backend.log`

升级时请保留 `data` 目录。不要把新版本直接覆盖到不可写的系统目录。

## 退出与故障

关闭启动窗口或按 Ctrl+C 会停止本地服务。端口 8765 已被占用时，DiskScope 会安全退出，不会终止其他进程。

此 v0.1.0 构建未进行代码签名。Windows SmartScreen 或安全软件可能显示未知发布者/声誉提示；请通过项目发布页核对 ZIP 的 SHA-256，不要关闭或绕过系统安全功能。
