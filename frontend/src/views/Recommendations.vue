<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { analyzeSnapshot, getCandidateDetail, getCandidates } from '../services/api'
import type { CandidateRun, CandidateSummary, CleanupCandidate, SnapshotSummary } from '../services/api'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber, formatSeconds } from '../utils/format'
import { actionLabel, categoryLabel, confidenceLabel, coverageMessage, riskLabel, topKMessage } from '../utils/recommendations'

const store = useScanStore()
const latestSnapshot = ref<SnapshotSummary | null>(null)
const run = ref<CandidateRun | null>(null)
const summary = ref<CandidateSummary | null>(null)
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
    let initial = await getCandidates({ risk: 'review', category: category.value, confidence: confidence.value })
    if (request !== requestNumber) return
    latestSnapshot.value = initial.latest_snapshot
    if (autoAnalyze && initial.latest_snapshot && initial.run?.snapshot_id !== initial.latest_snapshot.snapshot_id) {
      analyzing.value = true
      await analyzeSnapshot(initial.latest_snapshot.snapshot_id)
      initial = await getCandidates({ risk: 'review', category: category.value, confidence: confidence.value })
      analyzing.value = false
    }
    if (request !== requestNumber) return
    run.value = initial.run
    summary.value = initial.summary
    if (!initial.run || initial.run.snapshot_id !== initial.latest_snapshot?.snapshot_id) {
      sections.value = []
      return
    }
    const risks = ['low', 'high', 'protected'] as const
    const others = await Promise.all(risks.map(risk => getCandidates({ risk, category: category.value, confidence: confidence.value })))
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
  members.value = []
  detailError.value = ''
  detailLoading.value = true
  try {
    const result = await getCandidateDetail(item.candidate_id)
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

watch(() => store.sessionReady, ready => { if (ready) void loadRecommendations() }, { immediate: true })
watch([category, confidence], () => { if (store.sessionReady) void loadRecommendations(false) })
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">RECOMMENDATIONS / SAVED SNAPSHOT</p><h1>空间建议</h1><p class="page-description">解释哪些项目值得关注，以及识别依据与处理风险。</p></div><span class="read-only-chip">仅分析 · 不执行清理</span></div>
  <p class="coverage-note">当前仅提供分析与建议，不会自动删除文件。低风险也不等于保证安全。</p>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">SOURCE</p><h2>Windows C: · 基于已保存扫描结果</h2></div><button type="button" class="text-button" :disabled="loading || !latestSnapshot" @click="loadRecommendations(true)">重新分析已保存快照</button></div>
    <p v-if="!store.sessionReady" class="inline-note">请从 start.bat 打开本地页面，以查看已保存的扫描结果。</p>
    <template v-else><div class="recommendation-meta"><span>扫描时间：{{ formatLocalTime(latestSnapshot?.completed_at) }}</span><span>规则版本：{{ run?.rule_version ?? 'rules-v1.0.0' }}</span><span>分析范围：大文件 Top-K + 目录聚合</span><span v-if="run">分析耗时：{{ formatSeconds(run.duration_ms) }}</span></div>
      <p v-if="coverageMessage(latestSnapshot?.coverage)" class="coverage-note">{{ coverageMessage(latestSnapshot?.coverage) }}</p>
      <p class="inline-note">{{ topKMessage }}</p>
    </template>
  </section>
  <p v-if="error" class="panel inline-error" role="alert">{{ error }}</p>
  <p v-if="analyzing" class="panel inline-note" role="status">正在分析已保存的快照元数据；不会重新扫描 C 盘…</p>
  <p v-else-if="loading" class="panel inline-note" role="status">正在读取已保存的建议…</p>
  <EmptyState v-else-if="store.sessionReady && !latestSnapshot" title="尚无 C 盘快照" description="完成一次 C 盘只读扫描后，这里会分析已保存结果；本页不会启动扫描。" />
  <EmptyState v-else-if="store.sessionReady && !currentRun" title="等待快照分析" description="最新 C 盘快照已保存，但候选尚未生成。可重新分析已保存快照，无需扫描磁盘。" />
  <template v-else-if="currentRun && summary">
    <div class="metric-grid"><div class="metric-card"><span>值得关注的空间</span><strong>{{ formatBytes(summary.candidate_bytes) }}</strong><small>仅计入需确认/低风险的 Top-K 文件；不是可释放空间</small></div><div class="metric-card"><span>候选项目</span><strong>{{ formatNumber(summary.candidate_count) }}</strong><small>分组不重复计数成员</small></div><div class="metric-card"><span>需要人工确认</span><strong>{{ formatNumber(summary.review_count) }}</strong><small>规则建议复核</small></div><div class="metric-card"><span>受保护项目</span><strong>{{ formatNumber(summary.protected_count) }}</strong><small>不计入值得关注空间</small></div></div>
    <section class="panel recommendation-filters"><div class="panel-heading"><div><p class="eyebrow">FILTER</p><h2>筛选识别结果</h2></div></div><div class="scan-controls"><label>类型<select v-model="category"><option value="">全部类型</option><option v-for="item in categories" :key="item" :value="item">{{ categoryLabel(item) }}</option></select></label><label>识别置信度<select v-model="confidence"><option value="">全部置信度</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label></div></section>
    <section v-for="section in sections" :key="section.risk" class="panel recommendation-section"><div class="panel-heading"><div><p class="eyebrow">{{ section.risk.toUpperCase() }}</p><h2>{{ sectionTitles[section.risk] }}</h2></div><span class="subtle-label">{{ section.total }} 项<span v-if="section.total > section.items.length"> · 显示前 {{ section.items.length }} 项</span></span></div>
      <p v-if="!section.items.length" class="inline-note">此范围暂无匹配项目。</p>
    <div v-else class="recommendation-list"><article v-for="item in section.items" :key="item.candidate_id" class="recommendation-item"><div class="recommendation-item-head"><div><strong>{{ item.title }}</strong><p class="path-cell" :title="item.display_path">{{ item.display_path }}</p></div><strong class="size-cell">{{ formatBytes(item.logical_bytes) }}</strong></div><p>{{ item.summary }}</p><div class="recommendation-tags"><span>{{ categoryLabel(item.category) }}</span><span>{{ riskLabel(item.risk_level) }}</span><span>置信度 {{ confidenceLabel(item.confidence) }}</span><span>{{ item.object_type === 'group' ? '分组' : item.object_type === 'directory' ? '目录' : '文件' }}</span></div><button type="button" class="text-button" @click="openDetail(item)">为什么被识别 →</button></article></div>
    </section>
  </template>
  <p v-if="detailLoading" class="inline-note" role="status">正在读取识别依据…</p>
  <p v-if="detailError" class="inline-error" role="alert">{{ detailError }}</p>
  <div v-if="selected" class="modal-backdrop" @click.self="selected = null"><section class="confirm-dialog recommendation-detail" role="dialog" aria-modal="true" aria-labelledby="recommendation-title"><p class="eyebrow">EVIDENCE / READ ONLY</p><h2 id="recommendation-title">{{ selected.title }}</h2><p>{{ selected.summary }}</p><div class="recommendation-tags"><span>{{ riskLabel(selected.risk_level) }}</span><span>置信度 {{ confidenceLabel(selected.confidence) }}</span><span>{{ categoryLabel(selected.category) }}</span></div><p class="path-cell" :title="selected.display_path">{{ selected.display_path }}</p><strong>{{ formatBytes(selected.logical_bytes) }}</strong><h3>识别依据</h3><ul><li v-for="evidence in selected.evidence" :key="evidence">{{ evidence }}</li></ul><p>{{ selected.explanation }}</p><p><strong>建议：</strong>{{ actionLabel(selected.recommended_action) }} 当前版本不会删除或修改该项目。</p><p class="fine-print">规则：{{ selected.source_rule_id }} · {{ selected.rule_version }} · {{ selected.reason_code }}</p><div v-if="members.length"><h3>分组成员（{{ members.length }}）</h3><div class="member-list"><div v-for="member in members" :key="member.candidate_id"><span class="path-cell" :title="member.display_path">{{ member.display_path }}</span><strong class="size-cell">{{ formatBytes(member.logical_bytes) }}</strong></div></div></div><div class="confirm-actions"><button type="button" class="text-button" @click="copyPath(selected.display_path)">复制路径</button><button type="button" class="primary-button" @click="selected = null">关闭</button></div></section></div>
</template>
