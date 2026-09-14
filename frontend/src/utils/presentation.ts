import type { ScanStatus, ScanTarget } from '../services/api'

export function targetName(target: ScanTarget): string {
  return target === 'c_drive' ? 'Windows C:' : target === 'project' ? 'Project Workspace' : 'Fixture Sample'
}

export function stateLabel(state: ScanStatus['state']): string {
  return {
    queued: '等待扫描',
    running: '扫描中',
    cancelling: '正在取消',
    cancelled: '已取消',
    completed: '扫描完成',
    failed: '扫描失败',
  }[state]
}

export function completionLabel(scan: ScanStatus): string {
  if (scan.state === 'failed') return '扫描失败'
  if (scan.state === 'cancelled') return '已取消'
  if (scan.state === 'completed' && (scan.errors_count > 0 || scan.skipped_count > 0)) {
    return '扫描完成 · 部分位置未覆盖'
  }
  return stateLabel(scan.state)
}

export function isActive(scan: ScanStatus | null): boolean {
  return !!scan && ['queued', 'running', 'cancelling'].includes(scan.state)
}
