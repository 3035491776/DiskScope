# M8 — Scan Performance & Resource Efficiency

M8 优化 DiskScope 的单 worker、metadata-only 扫描路径。目标是消除 Python 与文件系统元数据调用中的重复工作，而不是扩大扫描范围、增加激进并发或降低安全检查。

## 原始真实基线

M7 已保存的 Windows C: Snapshot：1,204,833 文件、379,480 目录、456,789,491,601 字节，耗时 2,623.141 秒（约 459 files/s），CPU 2,421.73 秒，RSS peak 约 323 MB，Process Write 0 B，coverage limited。

M7 已保存的 current user Temp Snapshot：26,543 文件、11,557 目录、14,212,985,291 字节，耗时 48.234 秒（约 550.3 files/s），CPU 39.56 秒，RSS peak 63.3 MB，Process Write 0 B，coverage limited。

## Profiling 方法与瓶颈

在相同机器、相同 fixture、单 worker 下，对 M7 提交 `12d4258` 的隔离副本和 M8 工作树分别运行一次 warmup，再运行三次计时并取中位数。指标来自 `perf_counter`、`process_time` 与现有 Windows 进程计数器；扫描正确性同时核对文件数、目录数、逻辑字节、根目录聚合、Top-K 数量、错误和跳过计数。`tests/benchmark_m8.py` 还单独记录隔离 SQLite Snapshot 保存时间与 cooperative cancel latency。

M7 Medium cProfile（10,000 文件、1,001 目录）产生约 231 万次函数调用，总计 6.331 秒。`assert_safe_directory` 累计 5.128 秒；其中每个目录重复授权 root，累计 3,004 次 `Path.resolve`、6,005 次 `lstat`。每个 entry 还会为了卷检查构造 `Path`，所有文件都会创建完整 `FileMetadata` 与 ISO mtime，即使最终不会进入 Top-K。C: 的目录比例很高，这些固定 Python/metadata 成本会被放大。

M8 相同 cProfile 降至约 102 万次函数调用、2.008 秒。队列目录校验累计 1.325 秒，路径解析降至约 1,003 次；仍保留每个目录一次 canonical boundary/reparse 检查和每个 entry 一次不跟随链接的 `DirEntry.stat`。

## 实施的优化

1. 扫描 root 只授权并 canonicalize 一次。由安全枚举产生的队列目录继续逐目录检查 canonical path、approved-root boundary 和 reparse；不再重复验证 root 或逐层重复 `lstat`。跨卷检查缓存 root drive，并直接解析 entry path 的卷标，避免为每个文件构造 `Path`。
2. `FileSeen` 流式传递原始 metadata。Top-K/Temp hybrid heap 先按大小、路径或时间判断是否可能入选，只为有机会保留的文件创建 `FileMetadata` 和 ISO mtime。Top-K 仍是有界 heap；Temp 仍以 10,000 硬上限执行“最大 + 最旧”的确定性选择。
3. `DirectoryStats`、`FileMetadata` 和短生命周期扫描事件使用 slotted dataclass。浅对象大小由 344 bytes 分别降至 88/80 bytes。进度回调在最初 32 个 item 保持密集，以支持小 fixture 和快速取消，随后按 256 个 item 批量发布；cancel flag 本身仍逐 entry 检查。资源计数器仍最多每秒读取一次。

## Before / After benchmark

| Workload | Files / dirs | M7 median | M8 median | Duration | Throughput |
| --- | ---: | ---: | ---: | ---: | ---: |
| Small | 10 / 17 | 0.131927 s | 0.034913 s | -73.5% | 75.8 → 286.4 files/s |
| Medium | 10,000 / 1,001 | 7.530601 s | 1.810796 s | -76.0% | 1,327.9 → 5,522.4 files/s |
| Large synthetic | 50,000 / 5,001 | 39.058750 s | 9.133195 s | -76.6% | 1,280.1 → 5,474.5 files/s |

Medium CPU 中位数由 7.468750 秒降至 1.796875 秒（-75.9%），观测 RSS peak 由 27,627,520 降至 25,853,952 bytes（-6.4%）。Large CPU 由 37.906250 秒降至 8.937500 秒（-76.4%），RSS peak 由 34,283,520 降至 30,199,808 bytes（-11.9%）。所有 fixture 扫描的进程 read/write bytes 都是 0；这是 Windows 进程 I/O 计数器的实际结果，不代表未读取目录元数据。

Snapshot 保存已经使用单事务和 `executemany`。新建隔离 DB 的一次保存观测范围为约 0.05–0.20 秒（Large 5,001 目录 + 1,000 Top-K）；该阶段不是主要瓶颈且 M8 未重写。Cancel latency 从 0.002235 秒变为 0.001681 秒，没有退化。

## 真实 Temp 验证

测试时真实 Temp 已变化为 37,641 文件、12,825 目录、14,845,855,423 字节，因此不能把总时长直接与旧 Snapshot 当作同一 workload 比较。M8 两次实测结果完全一致，中位 33.497625 秒、1,123.7 files/s、CPU 32.585938 秒、RSS peak 56,807,424 bytes、Process Write 0 B、10,000 条持久化选择。与 M7 的 550.3 files/s 相比吞吐约提升 104%；CPU/file 由约 1.49 ms 降至 0.87 ms。

## 正确性与 Low-Impact 验证

- Small、Medium、Large 的文件数、目录数、逻辑字节、根聚合、Top-K、错误和跳过计数 before/after 一致。
- 继续使用单枚举 worker；没有 thread pool、并行递归或额外随机 I/O。
- 不读取普通文件正文，不 hash，不使用 MFT、USN、raw disk 或 device API。
- `DirEntry.stat(follow_symlinks=False)`、逐目录 canonical guard、cross-volume boundary 和普通权限保持。
- cancel flag 逐 entry 检查；single-active-scan、错误样本上限、Snapshot schema v6 与 M6 cleanup policy 不变。
- 未重新完整扫描 C:。三档可重复 fixture 与增长后的真实 Temp 已显示一致、材料性的改善；为再次运行约 43 分钟的全 C: 扫描增加系统负载没有必要。原 C: 与 Temp Snapshot 未修改。

## 未采用或回退的方向

- 未删除逐目录 canonical guard；这样虽会更快，但会削弱 reparse/边界证明。
- 未加入 bounded concurrency。现有 C: 基线 CPU/wall 比较高，本轮已通过消除重复 CPU 工作获得显著改善；增加 worker 会提高随机 I/O 和系统影响。
- 未改 SQLite schema、durability 或事务语义；持久化不是主要瓶颈。
- 未采用 MFT、USN、raw disk、原生扩展或大量 ctypes metadata 代码。

## 已知剩余瓶颈

每个目录仍需一次 Windows canonical path 查询，这是 reparse 与 approved-root 安全边界的主要剩余成本。目录聚合必须保留每个可浏览目录的一条记录；slots 已降低单对象成本，但 C: 规模仍会占用可观内存。若未来需要数量级提升，MFT/USN 或激进并行会改变 Low-Impact 产品边界，只记录在 backlog，不在 M8 实施。
