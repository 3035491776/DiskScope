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
  return coverage === 'limited' ? '本次扫描有部分内容未能完整读取，因此建议可能不完整。' : ''
}

export const topKMessage = '这些建议来自已保存的大文件和文件夹信息，不代表所有文件都可处理。'

export function executionStatus(candidate: CleanupCandidate): string {
  if (candidate.execution_hint === 'history_only') return '已移入回收站 · 历史候选'
  if (candidate.execution_hint === 'prepare_available') return '可准备处理 · 执行前将重新验证当前文件'
  const reasons = candidate.execution_policy?.block_reasons ?? []
  if (reasons.includes('EXECUTION_PROTECTED_PATH')) return '暂不符合处理条件：位于 Windows 或系统保护位置'
  if (reasons.includes('DIRECTORY_EXECUTION_NOT_SUPPORTED')) return '暂不符合处理条件：当前版本不处理文件夹或分组'
  if (reasons.includes('EXECUTION_CURRENT_USER_TEMP_ONLY')) return '暂不符合处理条件：只允许严格合格的当前用户临时文件'
  if (reasons.includes('EXECUTION_FILE_TOO_RECENT')) return '暂不符合处理条件：文件还比较新'
  if (reasons.includes('EXECUTION_EXTENSION_BLOCKED')) return '暂不符合处理条件：这种文件类型不会自动处理'
  return '暂不符合处理条件'
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
    EXECUTION_POLICY_BLOCKED: '该候选不符合当前受保护处理规则，处理已阻止。',
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

export function policyReasonTitle(code: string): string {
  return {
    ELIGIBLE_USER_TEMP_STALE_FILE: '满足当前处理条件',
    EXECUTION_PROTECTED_PATH: '系统保护路径',
    EXECUTION_SCOPE_BLOCKED: '不在诊断范围内',
    EXECUTION_CURRENT_USER_TEMP_ONLY: '不在当前用户临时目录内',
    EXECUTION_PATH_BLOCKED: '路径边界未通过',
    DIRECTORY_EXECUTION_NOT_SUPPORTED: '当前版本不处理目录',
    EXECUTION_REPARSE_POINT_BLOCKED: '链接或系统重定向被阻止',
    EXECUTION_PARENT_CHANGED: '父级路径状态不符合要求',
    EXECUTION_CROSS_VOLUME_BLOCKED: '路径跨越磁盘卷',
    UNKNOWN_CATEGORY: '文件分类未知',
    EXECUTION_CATEGORY_BLOCKED: '文件分类不符合要求',
    UNKNOWN_RISK: '风险等级未知',
    EXECUTION_RISK_BLOCKED: '当前位置风险较高',
    UNKNOWN_CONFIDENCE: '识别置信度未知',
    EXECUTION_CONFIDENCE_BLOCKED: '识别置信度不足',
    EXECUTION_POLICY_BLOCKED: '候选规则不匹配',
    EXECUTION_EXTENSION_BLOCKED: '这种文件类型不会自动处理',
    EXECUTION_SIZE_BELOW_THRESHOLD: '文件小于当前处理下限',
    UNKNOWN_MTIME: '修改时间未知',
    EXECUTION_TIMESTAMP_INVALID: '修改时间无法可靠判断',
    EXECUTION_FILE_TOO_RECENT: '文件还比较新',
    TARGET_CHANGED_SINCE_SCAN: '文件在扫描后发生变化',
    TARGET_NO_LONGER_EXISTS: '文件已不存在',
    TARGET_METADATA_ERROR: '无法读取当前元数据',
    POLICY_EVALUATION_ERROR: '策略评估失败',
  }[code] ?? code
}

export function policyReasonExplanation(code: string): string {
  return {
    ELIGIBLE_USER_TEMP_STALE_FILE: '保存的元数据显示：这是当前用户 Temp 根目录中的普通临时文件，至少 30 天未修改，识别置信度高、风险低，且文件类型未被排除。进入处理前仍需重新核对文件当前状态。',
    EXECUTION_RISK_BLOCKED: '此文件位于临时目录的子目录中。当前版本将这类文件视为较高风险，因为它可能属于程序运行状态、更新程序或缓存，因此不会提供处理操作。',
    EXECUTION_FILE_TOO_RECENT: '文件距离上次修改不足 30 天，当前策略不会处理较新的临时文件。',
    EXECUTION_EXTENSION_BLOCKED: '该文件类型在当前安全策略中被明确排除。转储、程序、脚本和系统文件不会进入处理预检。',
    EXECUTION_POLICY_BLOCKED: '候选的识别依据没有命中当前执行策略要求的临时文件规则。',
    EXECUTION_CATEGORY_BLOCKED: '该候选没有被识别为当前策略支持的普通临时文件。',
    EXECUTION_CONFIDENCE_BLOCKED: '识别结果没有达到当前策略要求的高置信度。',
    EXECUTION_SIZE_BELOW_THRESHOLD: '文件小于当前首批处理策略的 1 MiB 下限。',
    DIRECTORY_EXECUTION_NOT_SUPPORTED: '当前版本只评估单个普通文件，不支持目录、目录树或分组处理。',
    EXECUTION_PROTECTED_PATH: 'Windows 或系统保护路径始终禁止由此执行策略处理。',
    EXECUTION_CURRENT_USER_TEMP_ONLY: '当前执行策略只覆盖当前登录用户的 LocalAppData\\Temp。',
    EXECUTION_SCOPE_BLOCKED: '该候选不属于当前执行策略允许的固定范围。',
    EXECUTION_PATH_BLOCKED: '保存的路径无法通过严格的规范化和目录边界检查。',
    UNKNOWN_CATEGORY: '保存的候选缺少可靠分类。未知值按不符合处理条件处理。',
    UNKNOWN_RISK: '保存的候选缺少可靠风险等级。未知值按不符合处理条件处理。',
    UNKNOWN_CONFIDENCE: '保存的候选缺少可靠置信度。未知值按不符合处理条件处理。',
    UNKNOWN_MTIME: '保存的候选缺少修改时间，无法确认是否达到 30 天。',
    EXECUTION_TIMESTAMP_INVALID: '保存的修改时间异常或位于未来，无法可靠判断文件年龄。',
    POLICY_EVALUATION_ERROR: '本次策略评估没有得到可靠结果，因此按不符合处理条件处理。',
  }[code] ?? executionReasonLabel(code)
}

export function eligibilityDecisionLabel(value: string): string {
  return value === 'eligible_for_recycle' ? '可以准备处理' : '暂不符合处理条件'
}
