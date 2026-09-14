import type { ScanStatus } from '../services/api'

export const coverageReasons: Record<string, { label: string; explanation: string }> = {
  ACCESS_DENIED: { label: '权限受限', explanation: '部分 Windows 保护位置无法读取。DiskScope 不会尝试提权或绕过系统权限。' },
  REPARSE_POINT_SKIPPED: { label: '链接/系统重定向未跟随', explanation: '为避免重复扫描、循环路径或跨卷访问，DiskScope 默认不跟随重解析点。' },
  FILE_NOT_FOUND: { label: '扫描期间发生变化', explanation: '某些临时文件在扫描过程中创建、移动或消失，这在运行中的 Windows 系统上可能发生。' },
  PATH_TOO_LONG: { label: '路径限制', explanation: '少量路径因系统或 API 路径限制未能读取元数据。' },
  IO_ERROR: { label: '读取元数据失败', explanation: '部分位置的文件系统元数据读取失败，可在技术详情中查看原始错误代码。' },
  CROSS_VOLUME_SKIPPED: { label: '跨卷位置未访问', explanation: '只读扫描不会越过已授权的磁盘范围。' },
  INVALID_PATH: { label: '路径不可用', explanation: '扫描过程中有路径不可访问。' },
  CANCELLED: { label: '扫描已取消', explanation: '用户取消后，结果未作为已完成快照保存。' },
}

export function coverageIssueCount(scan: Pick<ScanStatus, 'errors_count' | 'skipped_count'>): number {
  return Math.max(scan.errors_count, scan.skipped_count)
}

export function coverageHeading(scan: Pick<ScanStatus, 'state' | 'errors_count' | 'skipped_count'>): string {
  if (scan.state === 'failed') return '扫描失败'
  if (scan.state === 'cancelled') return '扫描已取消'
  if (scan.state === 'completed') return coverageIssueCount(scan) ? '扫描完成 · 部分位置未覆盖' : '扫描完成 · 覆盖完整'
  return '扫描进行中 · 覆盖情况持续更新'
}
