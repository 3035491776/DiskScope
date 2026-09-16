<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { analyzeSnapshot, createControlledProbe, executeCleanup, getCandidateDetail, getCandidates, getCleanupExecutions, prepareCleanup, prepareControlledProbe } from '../services/api'
import type { CandidateRun, CandidateSummary, CleanupCandidate, CleanupExecution, CleanupExecutionResult, ControlledProbe, EligibilitySummary, PreparedCleanup, SnapshotSummary } from '../services/api'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber, formatSeconds } from '../utils/format'
import { actionLabel, categoryLabel, confidenceLabel, coverageMessage, executionReasonLabel, executionStatus, riskLabel, topKMessage } from '../utils/recommendations'

const store = useScanStore()
const latestSnapshot = ref<SnapshotSummary | null>(null)
const run = ref<CandidateRun | null>(null)
const summary = ref<CandidateSummary | null>(null)
const eligibility = ref<EligibilitySummary | null>(null)
const scopeKey = ref<'system_drive_c' | 'current_user_temp'>('current_user_temp')
const sections = ref<{ risk: CleanupCandidate['risk_level']; items: CleanupCandidate[]; total: number }[]>([])
const selected = ref<CleanupCandidate | null>(null)
const members = ref<CleanupCandidate[]>([])
const category = ref('')
const confidence = ref('')
const loading = ref(false)
const analyzing = ref(false)
const detailLoading = ref(false)
const error = ref('')
const detailError = ref('')
const prepared = ref<PreparedCleanup | null>(null)
const prepareLoading = ref(false)
const candidateConfirmed = ref(false)
const candidateExecutionLoading = ref(false)
const candidateExecutionError = ref('')
const candidateResult = ref<CleanupExecutionResult | null>(null)
const executionHistory = ref<CleanupExecution[]>([])
const controlledProbe = ref<ControlledProbe | null>(null)
const probePlan = ref<PreparedCleanup | null>(null)
const probeDialogOpen = ref(false)
const probeResult = ref<CleanupExecutionResult | null>(null)
const probeLoading = ref(false)
const probeError = ref('')
let requestNumber = 0

const categories = computed(() => Object.keys(summary.value?.by_category ?? {}).sort())
const currentRun = computed(() => run.value && latestSnapshot.value?.snapshot_id === run.value.snapshot_id)
const sectionTitles: Record<CleanupCandidate['risk_level'], string> = {
  review: '值得关注 · 需确认', low: '值得关注 · 低风险',
  high: '需要谨慎', protected: '系统管理 / 不建议手动处理',
}

async function loadRecommendations(autoAnalyze = true) {
  if (!store.sessionReady) return
  const request = ++requestNumber
  loading.value = true
  error.value = ''
  try {
    let initial = await getCandidates({ scopeKey: scopeKey.value, risk: 'review', category: category.value, confidence: confidence.value })
    if (request !== requestNumber) return
    latestSnapshot.value = initial.latest_snapshot
    if (autoAnalyze && initial.latest_snapshot && initial.run?.snapshot_id !== initial.latest_snapshot.snapshot_id) {
      analyzing.value = true
      await analyzeSnapshot(initial.latest_snapshot.snapshot_id)
      initial = await getCandidates({ scopeKey: scopeKey.value, risk: 'review', category: category.value, confidence: confidence.value })
      analyzing.value = false
    }
    if (request !== requestNumber) return
    run.value = initial.run
    summary.value = initial.summary
    eligibility.value = initial.eligibility_summary
    if (!initial.run || initial.run.snapshot_id !== initial.latest_snapshot?.snapshot_id) {
      sections.value = []
      return
    }
    const risks = ['low', 'high', 'protected'] as const
    const others = await Promise.all(risks.map(risk => getCandidates({ scopeKey: scopeKey.value, risk, category: category.value, confidence: confidence.value })))
    if (request !== requestNumber) return
    sections.value = [
      { risk: 'review', items: initial.items, total: initial.total },
      ...risks.map((risk, index) => ({ risk, items: others[index]!.items, total: others[index]!.total })),
    ]
  } catch (cause) {
    if (request === requestNumber) error.value = cause instanceof Error ? cause.message : '无法分析已保存快照'
  } finally {
    if (request === requestNumber) { loading.value = false; analyzing.value = false }
  }
}

async function openDetail(item: CleanupCandidate) {
  selected.value = null
  prepared.value = null
  candidateResult.value = null
  candidateExecutionError.value = ''
  members.value = []
  detailError.value = ''
  detailLoading.value = true
  try {
    const result = await getCandidateDetail(item.candidate_id, scopeKey.value)
    selected.value = result.candidate
    members.value = result.members
  } catch (cause) {
    detailError.value = cause instanceof Error ? cause.message : '无法读取识别依据'
  } finally {
    detailLoading.value = false
  }
}

async function copyPath(path: string) {
  try { await navigator.clipboard.writeText(path) }
  catch { detailError.value = '无法复制路径，请检查浏览器剪贴板权限。' }
}

async function prepareSelected() {
  if (!selected.value || selected.value.execution_hint !== 'prepare_available') return
  prepareLoading.value = true
  detailError.value = ''
  try {
    prepared.value = await prepareCleanup(selected.value.candidate_id)
    candidateConfirmed.value = false
    candidateExecutionError.value = ''
    selected.value = null
    await loadExecutionHistory()
  }
  catch (cause) { detailError.value = cause instanceof Error ? cause.message : '当前状态检查失败' }
  finally { prepareLoading.value = false }
}

async function recycleSelected() {
  const token = prepared.value?.execution_token
  if (!token || !prepared.value?.real_execution_enabled || !candidateConfirmed.value) return
  candidateExecutionLoading.value = true
  candidateExecutionError.value = ''
  try {
    candidateResult.value = await executeCleanup(token)
    prepared.value = null
    candidateConfirmed.value = false
    await Promise.all([loadExecutionHistory(), loadRecommendations(false)])
  } catch (cause) {
    candidateExecutionError.value = executionReasonLabel(
      cause instanceof Error ? cause.message : 'RECYCLE_OPERATION_FAILED',
    )
    await loadExecutionHistory()
  } finally { candidateExecutionLoading.value = false }
}

function fileName(path: string): string {
  return path.split('\\').pop() || path
}

function auditStatus(record: CleanupExecution): string {
  if (record.status === 'completed' && record.target_mutation === 'recycle_bin') return '已移入回收站'
  if (record.status === 'prepared') return '等待确认'
  if (record.status === 'expired') return '确认已过期，未处理'
  if (record.status === 'blocked' || record.status === 'failed') return '未处理'
  return record.status
}

async function loadExecutionHistory() {
  try { executionHistory.value = await getCleanupExecutions() }
  catch { executionHistory.value = [] }
}

async function createProbeTest() {
  probeLoading.value = true
  probeError.value = ''
  probePlan.value = null
  probeDialogOpen.value = false
  probeResult.value = null
  try { controlledProbe.value = await createControlledProbe() }
  catch (cause) { probeError.value = cause instanceof Error ? cause.message : '无法创建受控测试文件' }
  finally { probeLoading.value = false }
}

async function prepareProbeTest() {
  if (!controlledProbe.value) return
  probeLoading.value = true
  probeError.value = ''
  try {
    probePlan.value = await prepareControlledProbe(controlledProbe.value.probe_id)
    probeDialogOpen.value = true
    if (probePlan.value.execution_token) controlledProbe.value = { ...controlledProbe.value, state: 'prepared' }
  }
  catch (cause) { probeError.value = cause instanceof Error ? cause.message : '测试文件预检失败' }
  finally { probeLoading.value = false }
}

async function recycleProbeTest() {
  const token = probePlan.value?.execution_token
  if (!token || !probePlan.value?.real_execution_enabled) return
  probeLoading.value = true
  probeError.value = ''
  try {
    probeResult.value = await executeCleanup(token)
    if (controlledProbe.value) controlledProbe.value = { ...controlledProbe.value, state: 'recycled' }
    probePlan.value = null
    probeDialogOpen.value = false
    await loadExecutionHistory()
  }
  catch (cause) {
    probeError.value = cause instanceof Error ? cause.message : '移入回收站失败；测试文件未被永久删除'
    if (controlledProbe.value) controlledProbe.value = { ...controlledProbe.value, state: 'invalidated' }
    await loadExecutionHistory()
  }
  finally { probeLoading.value = false }
}

watch(() => store.sessionReady, ready => { if (ready) void loadRecommendations() }, { immediate: true })
watch(() => store.sessionReady, ready => { if (ready) void loadExecutionHistory() }, { immediate: true })
watch([category, confidence], () => { if (store.sessionReady) void loadRecommendations(false) })
watch(scopeKey, () => {
  category.value = ''
  confidence.value = ''
  selected.value = null
  prepared.value = null
  void loadRecommendations()
})
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">RECOMMENDATIONS / SAVED SNAPSHOT</p><h1>空间建议</h1><p class="page-description">解释哪些项目值得关注，以及识别依据与处理风险。</p></div><span class="read-only-chip">严格门禁 · 单文件回收站</span></div>
  <p class="coverage-note">历史快照不是处理授权。只有当前用户 LocalAppData\Temp 中至少 30 天未修改、达到 1 MiB 的高置信低风险临时普通文件，才能逐个重新验证并由您确认移入回收站。</p>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">SOURCE</p><h2>{{ scopeKey === 'current_user_temp' ? '当前用户临时文件' : 'Windows C:' }} · 基于已保存扫描结果</h2></div><button type="button" class="text-button" :disabled="loading || !latestSnapshot" @click="loadRecommendations(true)">重新分析已保存快照</button></div>
    <div class="scan-controls"><label>分析范围<select v-model="scopeKey"><option value="current_user_temp">当前用户临时文件</option><option value="system_drive_c">Windows C:</option></select></label></div>
    <p v-if="!store.sessionReady" class="inline-note">请从 start.bat 打开本地页面，以查看已保存的扫描结果。</p>
    <template v-else><div class="recommendation-meta"><span>扫描时间：{{ formatLocalTime(latestSnapshot?.completed_at) }}</span><span>规则版本：{{ run?.rule_version ?? 'rules-v1.0.0' }}</span><span>分析范围：大文件 Top-K + 目录聚合</span><span v-if="run">分析耗时：{{ formatSeconds(run.duration_ms) }}</span></div>
      <p v-if="coverageMessage(latestSnapshot?.coverage)" class="coverage-note">{{ coverageMessage(latestSnapshot?.coverage) }}</p>
      <p class="inline-note">{{ scopeKey === 'current_user_temp' ? `文件元数据 ${latestSnapshot?.persisted_file_count ?? 0} / ${latestSnapshot?.observed_file_count ?? 0}；${(latestSnapshot?.persisted_file_count ?? 0) === (latestSnapshot?.observed_file_count ?? 0) ? '覆盖完整。' : '已达到有界持久化上限，结果覆盖受限。'}` : topKMessage }}</p>
    </template>
  </section>
  <p v-if="error" class="panel inline-error" role="alert">{{ error }}</p>
  <p v-if="analyzing" class="panel inline-note" role="status">正在分析已保存的快照元数据；不会重新扫描磁盘，也不会执行处理…</p>
  <p v-else-if="loading" class="panel inline-note" role="status">正在读取已保存的建议…</p>
  <EmptyState v-else-if="store.sessionReady && !latestSnapshot" :title="scopeKey === 'current_user_temp' ? '尚无当前用户 Temp 快照' : '尚无 C 盘快照'" description="完成对应范围的只读扫描后，这里会分析已保存结果；本页不会启动扫描。" />
  <EmptyState v-else-if="store.sessionReady && !currentRun" title="等待快照分析" description="最新 C 盘快照已保存，但候选尚未生成。可重新分析已保存快照，无需扫描磁盘。" />
  <template v-else-if="currentRun && summary">
    <div class="metric-grid"><div class="metric-card"><span>值得关注的空间</span><strong>{{ formatBytes(summary.candidate_bytes) }}</strong><small>候选元数据统计，不是可释放空间</small></div><div class="metric-card"><span>候选项目</span><strong>{{ formatNumber(summary.candidate_count) }}</strong><small>分组不重复计数成员</small></div><div class="metric-card"><span>符合 M6.2 门禁</span><strong>{{ formatNumber(eligibility?.eligible_count) }}</strong><small>{{ formatBytes(eligibility?.eligible_bytes) }} · 仅只读评估</small></div><div class="metric-card"><span>需要人工确认</span><strong>{{ formatNumber(summary.review_count) }}</strong><small>规则建议复核</small></div><div class="metric-card"><span>受保护项目</span><strong>{{ formatNumber(summary.protected_count) }}</strong><small>不计入值得关注空间</small></div></div>
    <p v-if="eligibility?.eligible_count" class="coverage-note">发现符合 USER_TEMP_STALE_FILE_V1 静态与历史元数据条件的真实候选。DiskScope 不会自动准备或执行，请先人工检查。</p>
    <section class="panel recommendation-filters"><div class="panel-heading"><div><p class="eyebrow">FILTER</p><h2>筛选识别结果</h2></div></div><div class="scan-controls"><label>类型<select v-model="category"><option value="">全部类型</option><option v-for="item in categories" :key="item" :value="item">{{ categoryLabel(item) }}</option></select></label><label>识别置信度<select v-model="confidence"><option value="">全部置信度</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label></div></section>
    <section v-for="section in sections" :key="section.risk" class="panel recommendation-section"><div class="panel-heading"><div><p class="eyebrow">{{ section.risk.toUpperCase() }}</p><h2>{{ sectionTitles[section.risk] }}</h2></div><span class="subtle-label">{{ section.total }} 项<span v-if="section.total > section.items.length"> · 显示前 {{ section.items.length }} 项</span></span></div>
      <p v-if="!section.items.length" class="inline-note">此范围暂无匹配项目。</p>
    <div v-else class="recommendation-list"><article v-for="item in section.items" :key="item.candidate_id" class="recommendation-item"><div class="recommendation-item-head"><div><strong>{{ item.title }}</strong><p class="path-cell" :title="item.display_path">{{ item.display_path }}</p></div><strong class="size-cell">{{ formatBytes(item.logical_bytes) }}</strong></div><p>{{ item.summary }}</p><div class="recommendation-tags"><span>{{ categoryLabel(item.category) }}</span><span>{{ riskLabel(item.risk_level) }}</span><span>置信度 {{ confidenceLabel(item.confidence) }}</span><span>{{ item.object_type === 'group' ? '分组' : item.object_type === 'directory' ? '目录' : '文件' }}</span></div><p class="execution-status">{{ executionStatus(item) }}</p><button type="button" class="text-button" @click="openDetail(item)">为什么被识别 →</button></article></div>
    </section>
  </template>
  <p v-if="detailLoading" class="inline-note" role="status">正在读取识别依据…</p>
  <p v-if="detailError" class="inline-error" role="alert">{{ executionReasonLabel(detailError) }}</p>
  <p v-if="candidateResult" class="coverage-note" role="status"><strong>已移入 Windows 回收站。</strong> 文件原始大小记录已保留；磁盘可用空间未必立即增加。</p>
  <div v-if="selected" class="modal-backdrop" @click.self="selected = null"><section class="confirm-dialog recommendation-detail" role="dialog" aria-modal="true" aria-labelledby="recommendation-title"><p class="eyebrow">EVIDENCE / SAVED SNAPSHOT</p><h2 id="recommendation-title">{{ selected.title }}</h2><p>{{ selected.summary }}</p><div class="recommendation-tags"><span>{{ riskLabel(selected.risk_level) }}</span><span>置信度 {{ confidenceLabel(selected.confidence) }}</span><span>{{ categoryLabel(selected.category) }}</span></div><p class="path-cell" :title="selected.display_path">{{ selected.display_path }}</p><strong>{{ formatBytes(selected.logical_bytes) }}</strong><h3>识别依据</h3><ul><li v-for="evidence in selected.evidence" :key="evidence">{{ evidence }}</li></ul><p>{{ selected.explanation }}</p><p><strong>建议：</strong>{{ actionLabel(selected.recommended_action) }} <span v-if="selected.execution_hint !== 'prepare_available'">当前策略不允许处理该项目。</span></p><p class="fine-print">识别规则：{{ selected.source_rule_id }} · {{ selected.rule_version }} · {{ selected.reason_code }}</p><div v-if="members.length"><h3>分组成员（{{ members.length }}）</h3><div class="member-list"><div v-for="member in members" :key="member.candidate_id"><span class="path-cell" :title="member.display_path">{{ member.display_path }}</span><strong class="size-cell">{{ formatBytes(member.logical_bytes) }}</strong></div></div></div><p class="execution-status">{{ selected.execution_hint === 'prepare_available' ? '可准备处理 · 需重新核对当前文件' : executionStatus(selected) }}</p><ul v-if="selected.execution_policy?.block_reasons.length"><li v-for="reason in selected.execution_policy.block_reasons" :key="reason">{{ executionReasonLabel(reason) }}</li></ul><div class="confirm-actions"><button v-if="selected.execution_hint === 'prepare_available'" type="button" class="primary-button" :disabled="prepareLoading" @click="prepareSelected">{{ prepareLoading ? '正在检查…' : '准备处理' }}</button><button type="button" class="text-button" @click="copyPath(selected.display_path)">复制路径</button><button type="button" class="primary-button" @click="selected = null">关闭</button></div></section></div>
  <div v-if="prepared" class="modal-backdrop" @click.self="prepared = null">
    <section class="confirm-dialog recommendation-detail" role="dialog" aria-modal="true" aria-labelledby="preflight-title">
      <p class="eyebrow">CURRENT FILE / PREFLIGHT</p><h2 id="preflight-title">当前状态预检</h2>
      <h3>{{ fileName(prepared.preflight.current_path) }}</h3>
      <p class="path-cell" :title="prepared.preflight.current_path">{{ prepared.preflight.current_path }}</p>
      <p>扫描时：{{ formatBytes(prepared.preflight.snapshot_size) }} · {{ formatLocalTime(prepared.preflight.snapshot_mtime) }}</p>
      <p>当前：{{ prepared.preflight.current_size === null ? '无法读取' : formatBytes(prepared.preflight.current_size) }} · {{ formatLocalTime(prepared.preflight.current_mtime) }}</p>
      <p>文件年龄：{{ prepared.preflight.age_days == null ? '无法验证' : `${prepared.preflight.age_days.toFixed(1)} 天` }}</p>
      <div class="recommendation-tags"><span>{{ categoryLabel(prepared.preflight.category ?? '') }}</span><span>{{ riskLabel((prepared.preflight.risk_level ?? 'review') as CleanupCandidate['risk_level']) }}</span><span>置信度 {{ confidenceLabel((prepared.preflight.confidence ?? 'low') as CleanupCandidate['confidence']) }}</span></div>
      <p><strong>执行策略：</strong>{{ prepared.preflight.policy_rule_id }}</p>
      <p><strong>状态：</strong>{{ prepared.preflight.block_reasons.length ? '该文件已变化或不符合策略，处理已阻止' : '预检通过，等待您的明确确认' }}</p>
      <p><strong>计划动作：</strong>{{ prepared.preflight.planned_action === 'recycle' ? '移入 Windows 回收站' : '无' }}</p>
      <ul v-if="prepared.preflight.block_reasons.length"><li v-for="reason in prepared.preflight.block_reasons" :key="reason">{{ executionReasonLabel(reason) }}</li></ul>
      <template v-if="prepared.real_execution_enabled && prepared.execution_token">
        <p class="coverage-note">仅处理这一个文件。执行时会再次验证路径、类型、大小、时间、文件身份、父级链接和磁盘卷。</p>
        <label><input v-model="candidateConfirmed" type="checkbox"> 我确认这是我要处理的文件</label>
      </template>
      <p v-if="candidateExecutionError" class="inline-error" role="alert">{{ candidateExecutionError }}</p>
      <p class="fine-print">预检本身不会修改文件。令牌 {{ prepared.expires_at ? `于 ${formatLocalTime(prepared.expires_at)} 过期` : '未签发' }}。移入回收站后磁盘可用空间未必立即增加。</p>
      <div class="confirm-actions"><button v-if="prepared.real_execution_enabled && prepared.execution_token" type="button" class="primary-button" :disabled="!candidateConfirmed || candidateExecutionLoading" @click="recycleSelected">{{ candidateExecutionLoading ? '正在移入…' : '移入 Windows 回收站' }}</button><button type="button" class="text-button" @click="prepared = null">取消</button></div>
    </section>
  </div>
  <section class="panel controlled-probe-panel">
    <div class="panel-heading"><div><p class="eyebrow">CONTROLLED PROBE TEST</p><h2>安全执行测试</h2></div><span class="read-only-chip">仅限 DiskScope 自建文件</span></div>
    <p class="inline-note">仅测试 DiskScope 本次运行创建并登记的 64 KB 临时文件。真实候选使用独立的 USER_TEMP_STALE_FILE_V1 门禁与人工确认。</p>
    <div v-if="controlledProbe" class="probe-summary">
      <div><strong>{{ controlledProbe.absolute_path.split('\\').pop() }}</strong><p class="path-cell" :title="controlledProbe.absolute_path">{{ controlledProbe.absolute_path }}</p></div>
      <div class="recommendation-tags"><span>{{ formatBytes(controlledProbe.expected_size) }}</span><span>{{ formatLocalTime(controlledProbe.created_at) }}</span><span>{{ controlledProbe.state }}</span></div>
    </div>
    <p v-if="probeResult" class="coverage-note"><strong>已移入回收站。</strong> 项目已从原位置移入 Windows 回收站；实际可用空间可能在清空回收站后才增加。</p>
    <p v-if="probeError" class="inline-error" role="alert">{{ probeError }}</p>
    <div class="confirm-actions">
      <button type="button" class="primary-button" :disabled="probeLoading || !!controlledProbe" @click="createProbeTest">{{ probeLoading && !controlledProbe ? '正在创建…' : '创建测试文件' }}</button>
      <button v-if="controlledProbe && controlledProbe.state === 'created' && !probeResult" type="button" class="primary-button" :disabled="probeLoading" @click="prepareProbeTest">{{ probeLoading ? '正在检查…' : '准备移入回收站' }}</button>
      <button v-if="controlledProbe?.state === 'prepared' && probePlan && !probeDialogOpen" type="button" class="primary-button" @click="probeDialogOpen = true">查看执行计划</button>
    </div>
  </section>
  <div v-if="probePlan && probeDialogOpen" class="modal-backdrop" @click.self="probeDialogOpen = false">
    <section class="confirm-dialog recommendation-detail" role="dialog" aria-modal="true" aria-labelledby="probe-preflight-title">
      <p class="eyebrow">CONTROLLED PROBE / CURRENT FILE</p><h2 id="probe-preflight-title">受控测试文件预检</h2>
      <p class="coverage-note">此功能当前仅处理 DiskScope 为安全测试创建的文件。</p>
      <p class="path-cell" :title="probePlan.preflight.current_path">{{ probePlan.preflight.current_path }}</p>
      <p>创建时间：{{ formatLocalTime(probePlan.preflight.created_at) }}</p>
      <p>登记信息：{{ formatBytes(probePlan.preflight.snapshot_size) }} · {{ formatLocalTime(probePlan.preflight.snapshot_mtime) }}</p>
      <p>当前信息：{{ probePlan.preflight.current_size === null ? '无法读取' : formatBytes(probePlan.preflight.current_size) }} · {{ formatLocalTime(probePlan.preflight.current_mtime) }}</p>
      <p><strong>动作：</strong>移入 Windows 回收站</p>
      <p><strong>状态：</strong>{{ probePlan.preflight.block_reasons.length ? '该测试文件已变化，处理已阻止' : '当前 metadata 与登记信息一致' }}</p>
      <ul v-if="probePlan.preflight.block_reasons.length"><li v-for="reason in probePlan.preflight.block_reasons" :key="reason">{{ executionReasonLabel(reason) }}</li></ul>
      <p class="fine-print">Token 将于 {{ formatLocalTime(probePlan.expires_at) }} 过期。移入回收站不代表可用空间立即增加。</p>
      <div class="confirm-actions"><button v-if="probePlan.real_execution_enabled && probePlan.execution_token" type="button" class="primary-button" :disabled="probeLoading" @click="recycleProbeTest">{{ probeLoading ? '正在移入…' : '移入 Windows 回收站' }}</button><button type="button" class="text-button" @click="probeDialogOpen = false">返回</button></div>
    </section>
  </div>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">AUDIT</p><h2>操作记录</h2></div><button type="button" class="text-button" @click="loadExecutionHistory">刷新</button></div>
    <p class="inline-note">记录预检与执行门禁结果；只有状态明确为“已移入回收站”才表示原路径已消失。这里不计算磁盘可用空间变化。</p>
    <p v-if="!executionHistory.length" class="inline-note">暂无操作记录。</p>
    <div v-else class="recommendation-list"><div v-for="record in executionHistory" :key="record.id" class="recommendation-item"><div class="recommendation-item-head"><div><strong>{{ formatLocalTime(record.execute_time ?? record.prepare_time) }} · {{ auditStatus(record) }}</strong><p>{{ fileName(record.original_path) }}</p><p class="path-cell" :title="record.original_path">{{ record.original_path }}</p></div><strong class="size-cell">{{ formatBytes(record.execute_size ?? record.preflight_size ?? record.snapshot_size) }}</strong></div><div class="recommendation-tags"><span>动作：移入回收站</span><span>策略：{{ record.policy_rule_id }}</span><span v-if="record.candidate_category">{{ categoryLabel(record.candidate_category) }}</span></div><p v-if="record.failure_code">原因：{{ executionReasonLabel(record.failure_code) }}</p><p>结果：{{ record.final_result === 'recycled' ? '已移入回收站' : '未处理' }} · target_mutation={{ record.target_mutation }}</p></div></div>
  </section>
</template>
