# M10 — v0.1.0 Release Candidate & Final Release

M10 冻结 M6 cleanup semantics、M7 product hierarchy、M8 scanner architecture 和 M9 one-folder packaging architecture，只处理正式发布所需的 blocker、文档与验证。基线为 M9 commit `a99ac1de6e4d266c25b7dc6df4cff49919ed7b42`，发布分支为 `release/v0.1.0-rc`。

## Release blocker

最终 E2E 发现侧栏仍显示缩写版本 `V0.1`。这是版本冻结 blocker，已仅将用户可见文案修正为 `v0.1.0`，并增加前端契约测试。未修改扫描器、Snapshot schema、cleanup policy、执行门或 packaging runtime architecture。

## Final artifact

- Directory: `DiskScope-v0.1.0-windows-x64\`
- ZIP: `DiskScope-v0.1.0-windows-x64.zip`
- ZIP size: 16,922,394 bytes
- Unpacked files: 101 files / 37,077,070 bytes
- SHA-256: `a5afcbb080ffe44d03e0b64966a20d65b2c1c8a4bd2ba35db92e2d7deb6f68c0`
- Checksum source: `DiskScope-v0.1.0-windows-x64.zip.sha256`

Build script started from clean project-local `build\m9-release` and same-version release outputs, rebuilt the Vue production bundle, ran PyInstaller 6.22.3 with `--clean`, and recreated the release directory, ZIP and checksum. The release directory contains `DiskScope.exe`, `_internal`, empty `data` and `logs`, `LICENSE`, `QUICKSTART.md`, `THIRD-PARTY-NOTICES.txt` and `VERSION.txt`. PowerShell `Compress-Archive` omits empty directories; a fresh extracted app creates `data` and `logs` beside the executable before use.

## Packaged acceptance

The final ZIP was extracted under a new `%TEMP%` directory outside the repository. It ran without an active venv and without invoking Python or Node from PATH. Final smoke results:

- startup to health: 4,768 ms;
- `/health`: 200, version `0.1.0`, developer mode false;
- Temp scan: 13,365 files, 11,753 directories, 8,674,042,596 bytes;
- duration 17.000 s, 786.2 files/s, CPU 16.875 s, RSS peak 73,269,248 bytes;
- process read 8,192 bytes, process write 0 bytes;
- Snapshot saved;
- controlled probe create → prepare → single-use token → Recycle Bin → audit completed;
- second instance failed safely with exit code 1 while the first process remained intact.

Fresh first-use session initialization created schema v6 with `integrity_check=ok`, an empty `foreign_key_check`, and zero snapshots. An isolated copy of the existing v6 database also returned `integrity_check=ok`, two C snapshots, one Temp snapshot and 2,530 persisted candidates before the E2E run; the original database was not modified.

Browser E2E covered Dashboard, C and Temp result restore, scan controls, Temp cancel and completed states, Space Analysis, directory drill-down, Large Files and directories, History, same-scope Compare, Recommendations, eligibility explanations, Scan Status, Settings, refresh and restart restore. Bootstrap fragment removal was verified with a fresh per-launch token. Browser console result: zero errors and zero warnings. Release mode showed only C and Temp scopes and no developer scan controls.

## Final C benchmark

Per the M10 execution rule, DiskScope did not repeat a full C scan. The newest saved C Snapshot was verified as a valid post-M8 full C benchmark:

- M8 scanner commit: `ad5df4901f0e88067998be6b0936752d8b7828d7`, committed 2026-09-16 16:11:10 +08:00;
- scan id: `32df75d0-3180-4dc1-a62e-cc71fbd26590`;
- snapshot id: `9d7818f4-ee0e-491e-ad45-c14d2c702ebd`;
- scope/root: `system_drive_c` / `C:\`;
- started: 2026-09-17 09:56:03 +08:00;
- completed and saved: 2026-09-17 10:16:47 +08:00;
- status: `completed`;
- files: 1,173,146;
- directories: 377,234;
- visible logical bytes: 423,183,874,865;
- duration: 1,243.484 s (20m43.484s);
- throughput: 943.435 files/s;
- errors: 168;
- skips: 168;
- coverage: `limited`;
- Top-K persistence: 1,000 / 1,173,146 observed files.

The schema does not persist terminal CPU time, RSS, process I/O, error-reason counters or Snapshot persistence duration. Those fields are therefore `unavailable / not recorded`; the benchmark was not repeated merely to reconstruct auxiliary metrics.

The older C baseline had 1,204,833 files, 379,480 directories, 456,789,491,601 bytes, 2,623.141 seconds and about 459 files/s. The post-M8 Snapshot has 2.63% fewer files, 0.59% fewer directories and 7.36% fewer logical bytes; duration is 52.60% lower and throughput 105.40% higher. Disk contents, cache state and background activity changed, so the entire difference cannot be attributed to M8.

The scan-time power state, background load and exact capacity snapshot were not recorded. A same-host check after the scan reported Windows 11 Home x64 `10.0.26200`, Intel Core i7-12700 with 20 logical processors, 34,013,499,392 bytes RAM, and no battery device; C: then reported 510,737,248,256 total, 404,870,713,344 used and 105,866,534,912 free bytes. These are contextual host facts, not reconstructed scan-time measurements.

## Regression and security

Source verification completed with 132 Python tests, 34 frontend tests, a 649-module production frontend build and `pip check` reporting no broken requirements. Scanner tests cover metadata-only behavior, no content hashing, cooperative cancel, single active scan, reparse rejection, cross-volume rejection, bounded errors and Snapshot persistence. Cleanup tests cover fixed candidate identity, 30-day threshold, nested Temp denial, prepare/execute revalidation, single-use token, recycle-only behavior, blocked candidates, concurrent-operation exclusion and no permanent-delete fallback.

The final artifact contains no `.git`, tests, fixtures, source tree, `node_modules`, development database, Snapshot/candidate/probe/audit history, runtime logs, `.env`, credential file or build cache. Scans for `D:\Artilius`, `Artilius`, `Windows-C-clear`, `Codex` and the real user profile path returned no artifact matches. Focused scans returned no GitHub token, cloud key, private key or embedded bootstrap-token value. A broad scan matched only dependency API signatures containing `password=None`; these are code symbols, not secrets.

The EXE metadata, `VERSION.txt`, `/health`, folder and ZIP names all report `0.1.0`. The manifest requests `asInvoker`, the app binds only `127.0.0.1`, and no UAC, `takeown`, `icacls` or ACL modification is used. `LICENSE` and `THIRD-PARTY-NOTICES.txt` are present. The executable is intentionally unsigned.

## Compatibility and limitations

Windows 11 x64 `10.0.26200` is physically validated. Windows 10/11 x64 is the target; Windows 10 physical validation is not completed and does not block v0.1.0. The final user-facing limitations and SmartScreen guidance are maintained in `RELEASE_NOTES_v0.1.0.md` and the packaged `QUICKSTART.md`.
