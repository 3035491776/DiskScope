import type { CleanupCandidate } from '../services/api'

export function riskLabel(value: CleanupCandidate['risk_level']): string {
  return { protected: '系统保护', high: '高风险', review: '需确认', low: '低风险' }[value]
}

export function confidenceLabel(value: CleanupCandidate['confidence']): string {
  return { high: '高', medium: '中', low: '低' }[value]
}

export function categoryLabel(value: string): string {
  return {
    crash_dump: '崩溃转储', temporary_file: '临时文件', temporary_directory: '临时目录',
    application_cache: '应用缓存', browser_cache: '浏览器缓存',
    installer_artifact: '安装文件', log_file: '日志文件', user_download: '下载文件',
    user_desktop: '桌面数据', user_document: '用户文档', user_data: '用户数据',
    hibernation_file: '休眠文件', pagefile: '页面文件', swapfile: '交换文件',
    system_managed: '系统管理', application_managed: '应用管理', unknown: '未知',
  }[value] ?? value
}

export function actionLabel(value: string): string {
  return {
    system_managed: '由系统管理，不建议手动处理。',
    review_application: '请通过应用或系统管理方式了解占用。',
    review_for_cleanup: '如相关诊断已完成，可人工评估后续处理。',
    manual_review: '请人工确认用途与影响。',
  }[value] ?? '请人工确认用途与影响。'
}

export function coverageMessage(coverage: string | undefined): string {
  return coverage === 'limited' ? '本次扫描覆盖受限，建议结果可能不完整。' : ''
}

export const topKMessage = '候选基于已保存扫描结果中的大文件 Top-K 与目录聚合，不代表完整文件级清理扫描。'

export function executionStatus(candidate: CleanupCandidate): string {
  if (candidate.execution_hint === 'history_only') return '已移入回收站 · 历史候选'
  if (candidate.execution_hint === 'prepare_available') return '可准备处理 · 执行前将重新验证当前文件'
  const reasons = candidate.execution_policy?.block_reasons ?? []
  if (reasons.includes('EXECUTION_PROTECTED_PATH')) return '当前执行策略不支持处理 Windows 或系统保护路径中的文件'
  if (reasons.includes('DIRECTORY_EXECUTION_NOT_SUPPORTED')) return '当前版本不支持处理目录或分组'
  if (reasons.includes('EXECUTION_CURRENT_USER_TEMP_ONLY')) return '当前版本仅建议；只开放当前用户临时目录中的严格合格文件'
  if (reasons.includes('EXECUTION_FILE_TOO_RECENT')) return '当前版本仅建议；文件不足 30 天'
  if (reasons.includes('EXECUTION_EXTENSION_BLOCKED')) return '当前版本仅建议；文件类型不在首批处理范围'
  return '当前版本仅建议'
}

export function executionReasonLabel(code: string): string {
  return {
    TARGET_CHANGED_SINCE_SCAN: '该文件自扫描后已发生变化，请重新扫描或重新评估。',
    TARGET_CHANGED_SINCE_PREPARE: '该文件在预检后又发生变化，处理已阻止。',
    TARGET_CHANGED_SINCE_CREATE: '测试文件与创建时登记的信息不一致，处理已阻止。',
    TARGET_NO_LONGER_EXISTS: '该文件已不存在，历史记录仍会保留。',
    EXECUTION_REPARSE_POINT_BLOCKED: '路径中出现链接或系统重定向，处理已阻止。',
    ACCESS_DENIED: '当前权限不足，DiskScope 不会绕过 Windows 权限。',
    TARGET_IN_USE: '文件正在使用，未处理。DiskScope 不会强制关闭应用或解锁文件。',
    OPERATION_CONFLICT: '扫描或另一项处理正在进行，请稍后再试。',
    EXECUTION_FILE_TOO_RECENT: '该文件最后修改时间不足 30 天，处理已阻止。',
    EXECUTION_TIMESTAMP_INVALID: '文件时间异常、位于未来或无法验证，处理已阻止。',
    EXECUTION_EXTENSION_BLOCKED: '该文件类型不在首批处理范围，处理已阻止。',
    EXECUTION_CATEGORY_BLOCKED: '仅高置信临时文件可以进入处理预检。',
    EXECUTION_CONFIDENCE_BLOCKED: '识别置信度不足，处理已阻止。',
    EXECUTION_RISK_BLOCKED: '该候选的风险等级不符合首批处理策略。',
    EXECUTION_POLICY_BLOCKED: '该候选未命中 USER_TEMP_STALE_FILE_V1，处理已阻止。',
    EXECUTION_SIZE_BELOW_THRESHOLD: '文件小于 1 MiB，不进入首批处理范围。',
    EXECUTION_PATH_BLOCKED: '文件路径无法通过规范化边界检查。',
    EXECUTION_SCOPE_BLOCKED: '该候选不属于 Windows C: 已保存扫描范围。',
    EXECUTION_PROTECTED_PATH: 'Windows 或系统保护路径禁止处理。',
    DIRECTORY_EXECUTION_NOT_SUPPORTED: '当前版本不处理目录、目录树或分组。',
    EXECUTION_CURRENT_USER_TEMP_ONLY: '只允许当前登录用户的 LocalAppData\\Temp。',
    EXECUTION_PARENT_CHANGED: '路径中的父级对象已变化，处理已阻止。',
    TARGET_METADATA_ERROR: '无法可靠读取当前文件元数据，未处理。',
    ALREADY_EXECUTED: '该历史候选已经成功移入回收站，不能再次执行。',
    EXECUTION_POLICY_CHANGED: '预检后执行策略或候选绑定发生变化，处理已阻止。',
    SNAPSHOT_RECORD_MISMATCH: '候选与已保存快照记录不一致，处理已阻止。',
    EXECUTION_TOKEN_EXPIRED: '确认时间已过期，文件未处理。',
    EXECUTION_TOKEN_INVALID: '执行凭据无效，文件未处理。',
    CONTROLLED_PROBE_BOUNDARY_BLOCKED: '该对象不属于本次运行登记的受控测试目录。',
    CONTROLLED_PROBE_STATE_BLOCKED: '该测试文件当前状态不允许再次处理。',
    CONTROLLED_PROBE_NOT_FOUND: '没有找到本次运行登记的测试文件。',
    EXECUTION_CROSS_VOLUME_BLOCKED: '路径在验证过程中跨越了磁盘卷，处理已阻止。',
    RECYCLE_OPERATION_ABORTED: 'Windows 中止了回收站操作，DiskScope 未使用永久删除。',
    RECYCLE_OPERATION_FAILED: 'Windows 回收站操作失败，DiskScope 未使用永久删除。',
    RECYCLE_ORIGINAL_PATH_REMAINS: '原始路径仍然存在，回收站操作未被判定为成功。',
  }[code] ?? code
}
