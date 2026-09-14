import { formatBytes } from './format.ts'

export function formatDeltaBytes(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : value < 0 ? '-' : ''}${formatBytes(Math.abs(value))}`
}

export function formatDeltaPercent(ratio: number | null): string {
  if (ratio === null) return '新增'
  if (!Number.isFinite(ratio)) return '—'
  if (ratio === 0) return '无变化'
  return `${ratio > 0 ? '增加' : '减少'} ${(Math.abs(ratio) * 100).toFixed(1)}%`
}

export function historyEmptyMessage(count: number): string {
  if (count === 0) return '还没有历史快照。完成一次固定范围扫描后会自动保存。'
  if (count === 1) return '再完成一次相同范围扫描后即可查看空间变化。'
  return ''
}

export function historyErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : ''
  if (message.includes('400')) return '两个快照的扫描范围不一致，无法比较。'
  if (message.includes('404')) return '快照不存在或已超过历史保留数量。'
  return '历史数据库暂时不可用。当前扫描与空间分析仍可使用。'
}

export function coverageWarning(limited: boolean): string {
  return limited ? '其中一次扫描覆盖受限，变化结果可能不完整。' : ''
}
