import type { ScanStatus } from '../services/api'

export const coverageReasons: Record<string, { label: string; explanation: string }> = {
  ACCESS_DENIED: { label: '有些位置没有访问权限', explanation: 'DiskScope 已跳过这些 Windows 保护位置，不会尝试提升权限或绕过系统限制。' },
  REPARSE_POINT_SKIPPED: { label: '已跳过系统链接或重定向位置', explanation: '这样可以避免重复扫描、循环路径或访问另一块磁盘。' },
  FILE_NOT_FOUND: { label: '文件在扫描过程中发生了变化', explanation: '这个文件可能已经被创建、移动或删除；这在运行中的 Windows 系统上很常见。' },
  PATH_TOO_LONG: { label: '有些路径过长', explanation: '少量路径因 Windows 路径限制未能读取文件基本信息。' },
  IO_ERROR: { label: '无法读取文件基本信息', explanation: '部分位置的文件基本信息读取失败，可在技术详情中查看原始错误代码。' },
  CROSS_VOLUME_SKIPPED: { label: '跨卷位置未访问', explanation: '只读扫描不会越过已授权的磁盘范围。' },
  INVALID_PATH: { label: '路径不可用', explanation: '扫描过程中有路径不可访问。' },
  CANCELLED: { label: '扫描已取消', explanation: '取消后的不完整结果不会保存为扫描记录。' },
}

export function coverageIssueCount(scan: Pick<ScanStatus, 'errors_count' | 'skipped_count'>): number {
  return Math.max(scan.errors_count, scan.skipped_count)
}

export function coverageHeading(scan: Pick<ScanStatus, 'state' | 'errors_count' | 'skipped_count'>): string {
  if (scan.state === 'failed') return '扫描失败'
  if (scan.state === 'cancelled') return '扫描已取消'
  if (scan.state === 'completed') return coverageIssueCount(scan) ? '扫描完成，但部分位置未能扫描' : '扫描完成'
  return '正在扫描，结果完整度会持续更新'
}

export function scanErrorMessage(code: string | null | undefined): string {
  return {
    ACCESS_DENIED: '有些位置没有访问权限，DiskScope 已跳过这些位置。',
    FILE_NOT_FOUND: '扫描过程中有文件发生变化或已经不存在。',
    REPARSE_POINT_SKIPPED: '已跳过系统链接或重定向位置。',
    PATH_TOO_LONG: '有些文件路径过长，DiskScope 无法读取。',
    IO_ERROR: '读取文件基本信息时遇到问题，请稍后重试。',
    SCAN_ALREADY_ACTIVE: '已有扫描正在进行，请先等待或取消当前扫描。',
  }[code ?? ''] ?? '扫描没有完成。你可以稍后重试，并在技术详情中查看错误信息。'
}
