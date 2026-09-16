<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { compareSnapshots, getSnapshots } from '../services/api'
import type { SnapshotComparison, SnapshotSummary, DirectoryChange, LargeFileChange } from '../services/api'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber } from '../utils/format'
import { coverageWarning, formatDeltaBytes, formatDeltaPercent, historyEmptyMessage, historyErrorMessage } from '../utils/history'
import { targetName } from '../utils/presentation'

const store = useScanStore()
const snapshots = ref<SnapshotSummary[]>([])
const comparison = ref<SnapshotComparison | null>(null)
const baseId = ref('')
const targetId = ref('')
const loading = ref(false)
const comparing = ref(false)
const error = ref('')
const compareError = ref('')
let loadSequence = 0
let compareSequence = 0
const scopeKey = computed(() => store.selectedTarget === 'c_drive' ? 'system_drive_c' : store.selectedTarget === 'user_temp' ? 'current_user_temp' : store.selectedTarget === 'project' ? 'project_workspace' : 'fixture_sample')

async function loadHistory() {
  const sequence = ++loadSequence
  loading.value = true
  error.value = ''
  comparison.value = null
  try {
    const items = await getSnapshots(scopeKey.value)
    if (sequence !== loadSequence) return
    snapshots.value = items
    targetId.value = items[0]?.snapshot_id || ''
    baseId.value = items[1]?.snapshot_id || ''
    if (items.length >= 2) await loadComparison()
  } catch (cause) {
    if (sequence !== loadSequence) return
    snapshots.value = []
    error.value = historyErrorMessage(cause)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function loadComparison() {
  const sequence = ++compareSequence
  comparison.value = null
  compareError.value = ''
  if (!baseId.value || !targetId.value) return
  comparing.value = true
  try {
    const result = await compareSnapshots(baseId.value, targetId.value)
    if (sequence === compareSequence) comparison.value = result
  } catch (cause) {
    if (sequence === compareSequence) compareError.value = historyErrorMessage(cause)
  } finally {
    if (sequence === compareSequence) comparing.value = false
  }
}

watch(scopeKey, () => void loadHistory())
watch(() => store.scan?.snapshot_id, (id) => { if (id) void loadHistory() })
onMounted(() => void loadHistory())

function changeLabel(change: DirectoryChange): string {
  if (change.change_type === 'added') return '新增'
  if (change.change_type === 'removed') return '移出快照'
  if (change.change_type === 'grown') return '增加'
  if (change.change_type === 'shrunk') return '减少'
  return '无变化'
}

const fileGroups = computed(() => comparison.value ? [
  { title: '新进入 Top 大文件', items: comparison.value.new_large_files },
  { title: '体积增加', items: comparison.value.grown_large_files },
  { title: '体积减少', items: comparison.value.shrunk_large_files },
  { title: '不再出现于 Top 大文件', items: comparison.value.removed_large_files },
] : [])
const hasFileChanges = computed(() => fileGroups.value.some(group => group.items.length > 0))
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">HISTORY / CHANGE</p><h1>历史与变化</h1><p class="page-description">比较同一固定范围的两次扫描，查看空间增长与 Top 大文件变化。</p></div><span class="read-only-chip">只读历史</span></div>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">SCAN SCOPE</p><h2>当前扫描范围 · {{ targetName(store.selectedTarget) }}</h2></div><button type="button" class="text-button" @click="loadHistory">刷新历史</button></div>
    <div class="scan-controls"><label for="history-scope">查看范围</label><select id="history-scope" v-model="store.selectedTarget"><option value="fixture">Fixture Sample</option><option value="project">Project Workspace</option><option value="c_drive">Windows C:</option><option value="user_temp">当前用户临时文件</option></select></div>
    <p class="inline-note">只显示该范围的历史；无法跨范围组合比较。</p>
  </section>
  <p v-if="error" class="panel inline-error history-message" role="alert">{{ error }}</p>
  <p v-else-if="loading && snapshots.length === 0" class="panel inline-note">正在读取历史…</p>
  <EmptyState v-else-if="snapshots.length === 0" title="暂无历史扫描" :description="historyEmptyMessage(0)" />
  <template v-else>
    <section class="panel table-panel"><div class="panel-heading"><div><p class="eyebrow">SNAPSHOTS</p><h2>历史扫描</h2></div><span class="subtle-label">最近 {{ snapshots.length }} 次 · 每范围保留 20 次</span></div>
      <div class="table-scroll"><table><thead><tr><th>完成时间</th><th>逻辑空间</th><th>文件</th><th>目录</th><th>覆盖</th></tr></thead><tbody><tr v-for="snapshot in snapshots" :key="snapshot.snapshot_id"><td class="strong-cell">{{ formatLocalTime(snapshot.completed_at) }}</td><td>{{ formatBytes(snapshot.total_bytes) }}</td><td>{{ formatNumber(snapshot.file_count) }}</td><td>{{ formatNumber(snapshot.directory_count) }}</td><td>{{ snapshot.coverage === 'limited' ? '目录覆盖受限' : snapshot.persisted_file_count < snapshot.observed_file_count ? `文件元数据 ${formatNumber(snapshot.persisted_file_count)} / ${formatNumber(snapshot.observed_file_count)}` : '完整' }}</td></tr></tbody></table></div>
    </section>
    <EmptyState v-if="snapshots.length === 1" title="等待第二次扫描" :description="historyEmptyMessage(1)" />
    <template v-else>
      <section class="panel"><div class="panel-heading"><div><p class="eyebrow">COMPARE</p><h2>选择两次扫描</h2></div><span class="subtle-label">默认：最新一次与上一次</span></div>
        <div class="history-selectors"><label>基准扫描<select v-model="baseId" @change="loadComparison"><option v-for="item in snapshots" :key="item.snapshot_id" :value="item.snapshot_id">{{ formatLocalTime(item.completed_at) }} · {{ formatBytes(item.total_bytes) }}</option></select></label><label>目标扫描<select v-model="targetId" @change="loadComparison"><option v-for="item in snapshots" :key="item.snapshot_id" :value="item.snapshot_id">{{ formatLocalTime(item.completed_at) }} · {{ formatBytes(item.total_bytes) }}</option></select></label></div>
        <p v-if="baseId === targetId" class="inline-note">当前选择的是同一次扫描，变化均为零。</p>
      </section>
      <p v-if="compareError" class="panel inline-error history-message" role="alert">{{ compareError }}</p>
      <p v-else-if="comparing" class="panel inline-note">正在比较…</p>
      <template v-else-if="comparison">
        <p v-if="coverageWarning(comparison.comparison_coverage_limited)" class="coverage-note history-coverage">{{ coverageWarning(comparison.comparison_coverage_limited) }}<span v-if="scopeKey === 'system_drive_c'"> 两次 C 盘扫描也可能因权限或瞬时文件变化而存在自然波动。</span></p>
        <div class="history-summary"><div class="metric-card"><span>空间变化</span><strong>{{ formatDeltaBytes(comparison.total_bytes_delta) }}</strong><small>{{ formatDeltaPercent(comparison.total_bytes_delta_ratio) }}</small></div><div class="metric-card"><span>文件数量变化</span><strong>{{ comparison.file_count_delta > 0 ? '+' : '' }}{{ formatNumber(comparison.file_count_delta) }}</strong><small>{{ comparison.file_count_delta > 0 ? '增加' : comparison.file_count_delta < 0 ? '减少' : '无变化' }}</small></div><div class="metric-card"><span>目录数量变化</span><strong>{{ comparison.directory_count_delta > 0 ? '+' : '' }}{{ formatNumber(comparison.directory_count_delta) }}</strong><small>{{ comparison.directory_count_delta > 0 ? '增加' : comparison.directory_count_delta < 0 ? '减少' : '无变化' }}</small></div></div>
        <div class="two-column">
          <section class="panel table-panel"><div class="panel-heading"><div><p class="eyebrow">BY SPACE</p><h2>增长空间最多</h2></div><span class="subtle-label">按增加字节排序</span></div><p v-if="comparison.growth_by_bytes.length === 0" class="inline-note">没有目录空间增长。</p><div v-else class="table-scroll"><table><thead><tr><th>目录</th><th>变化</th><th>新增空间</th></tr></thead><tbody><tr v-for="item in comparison.growth_by_bytes" :key="item.relative_path"><td class="path-cell" :title="item.relative_path">{{ item.relative_path }}</td><td>{{ changeLabel(item) }}</td><td class="strong-cell">{{ formatDeltaBytes(item.delta_bytes) }}</td></tr></tbody></table></div></section>
          <section class="panel table-panel"><div class="panel-heading"><div><p class="eyebrow">BY RATE</p><h2>增长比例最高</h2></div><span class="subtle-label">基准至少 256 KiB · 目标至少 1 MiB</span></div><p v-if="comparison.growth_by_ratio.length === 0" class="inline-note">没有达到门槛的目录增长。</p><div v-else class="table-scroll"><table><thead><tr><th>目录</th><th>增幅</th><th>新增空间</th></tr></thead><tbody><tr v-for="item in comparison.growth_by_ratio" :key="item.relative_path"><td class="path-cell" :title="item.relative_path">{{ item.relative_path }}</td><td class="strong-cell">{{ formatDeltaPercent(item.delta_ratio) }}</td><td>{{ formatDeltaBytes(item.delta_bytes) }}</td></tr></tbody></table></div></section>
        </div>
        <section class="panel"><div class="panel-heading"><div><p class="eyebrow">FILE METADATA VIEW</p><h2>文件变化</h2></div></div><p class="inline-note">{{ scopeKey === 'current_user_temp' ? '基于有界的最大与最旧文件元数据；覆盖受限时不代表全部文件变化。' : '基于 Top 大文件快照，不代表全量文件变化。' }}“不再出现”可能只是跌出持久化选择，并不表示物理删除。</p>
          <p v-if="!hasFileChanges" class="inline-note">没有 Top 大文件变化。</p><div v-else class="history-file-groups"><div v-for="group in fileGroups" :key="group.title" v-show="group.items.length"><h3>{{ group.title }}</h3><div class="table-scroll"><table><thead><tr><th>文件</th><th>变化</th><th>目标大小</th></tr></thead><tbody><tr v-for="file in group.items" :key="file.relative_path"><td class="path-cell" :title="file.relative_path">{{ file.relative_path }}</td><td>{{ formatDeltaBytes(file.delta_bytes) }}</td><td>{{ formatBytes(file.target_bytes) }}</td></tr></tbody></table></div></div></div>
        </section>
      </template>
    </template>
  </template>
</template>
