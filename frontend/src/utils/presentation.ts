import type { ScanStatus, ScanTarget } from '../services/api'

export function targetName(target: ScanTarget): string {
  return target === 'c_drive' ? 'Windows C 盘'
    : target === 'user_temp' ? '临时文件'
      : target === 'project' ? 'Project Workspace' : 'Fixture Sample'
}

export function scanHeading(scan: Pick<ScanStatus, 'scope_key' | 'state'>): string {
  const name = scan.scope_key === 'system_drive_c' ? 'C 盘'
    : scan.scope_key === 'current_user_temp' ? '临时文件'
      : scan.scope_key === 'project_workspace' ? '项目工作区' : '测试样本'
  return ['queued', 'running', 'cancelling'].includes(scan.state)
    ? `正在扫描${name === 'C 盘' ? ' ' : ''}${name}`
    : `${name}扫描结果`
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
    if (scan.skipped_count > 0) return '扫描完成，但部分位置未能扫描'
    if (scan.metadata_warning_count > 0) return '扫描完成，但部分文件的信息不完整'
    return '扫描完成，但部分内容的信息不完整'
  }
  return stateLabel(scan.state)
}

export function isActive(scan: ScanStatus | null): boolean {
  return !!scan && ['queued', 'running', 'cancelling'].includes(scan.state)
}
