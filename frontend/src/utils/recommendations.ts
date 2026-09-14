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
