<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import BaseDialog from '../components/BaseDialog.vue'
import EmptyState from '../components/EmptyState.vue'
import {
  analyzeSnapshot, executeCleanupBatch, getCandidates, getCleanupBatch,
  getCleanupClassifications, prepareCleanupBatch,
} from '../services/api'
import type {
  CleanupBatchResult, CleanupCenterItem, CleanupCenterListing, CleanupClassification,
} from '../services/api'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber } from '../utils/format'

type UserTab = 'safe' | 'review' | 'protected'
type UserMode = 'safe' | 'review'

const store = useScanStore()
const scopeKey = ref<'system_drive_c' | 'current_user_temp'>(
  store.resultTarget === 'c_drive' ? 'system_drive_c' : 'current_user_temp',
)
const activeTab = ref<UserTab>('safe')
const listing = ref<CleanupCenterListing | null>(null)
const loading = ref(false)
const error = ref('')
const selectedSafe = ref(new Set<string>())
const selectedReview = ref(new Set<string>())
const confirmMode = ref<UserMode | null>(null)
const reviewAcknowledged = ref(false)
const processing = ref<{ batchId: string; completed: number; total: number } | null>(null)
const result = ref<CleanupBatchResult | null>(null)
let loadRequest = 0
let progressTimer: ReturnType<typeof setInterval> | null = null

const tabClass: Record<UserTab, CleanupClassification> = {
  safe: 'SAFE_ACTIONABLE', review: 'REVIEW_REQUIRED', protected: 'DO_NOT_TOUCH',
}
const tabLabel: Record<UserTab, string> = {
  safe: '可处理', review: '建议手动检查', protected: '不建议处理',
}
const currentItems = computed(() => listing.value?.items[tabClass[activeTab.value]] ?? [])
const safeItems = computed(() => listing.value?.items.SAFE_ACTIONABLE ?? [])
const reviewItems = computed(() => listing.value?.items.REVIEW_REQUIRED ?? [])
const selectedIds = computed(() => Array.from(
  confirmMode.value === 'safe' ? selectedSafe.value : selectedReview.value,
))
const selectedRows = computed(() => {
  const items = confirmMode.value === 'safe' ? safeItems.value : reviewItems.value
  const ids = new Set(selectedIds.value)
  return items.filter(item => ids.has(item.candidate_id))
})
const selectedBytes = computed(() => selectedRows.value.reduce((total, item) => total + item.logical_bytes, 0))
const allSafeSelected = computed(() => safeItems.value.length > 0 && safeItems.value.every(
  item => selectedSafe.value.has(item.candidate_id),
))
const summary = computed(() => listing.value?.summary)

function fileName(path: string): string {
  return path.split('\\').pop() || path
}

function toggleSelection(mode: UserMode, id: string, checked: boolean) {
  const source = mode === 'safe' ? selectedSafe.value : selectedReview.value
  const next = new Set(source)
  if (checked) next.add(id)
  else next.delete(id)
  if (mode === 'safe') selectedSafe.value = next
  else selectedReview.value = next
}

function toggleAllSafe() {
  selectedSafe.value = allSafeSelected.value
    ? new Set()
    : new Set(safeItems.value.map(item => item.candidate_id))
}

function openConfirmation(mode: UserMode) {
  const ids = mode === 'safe' ? selectedSafe.value : selectedReview.value
  if (!ids.size) return
  confirmMode.value = mode
  reviewAcknowledged.value = false
  result.value = null
}

function closeConfirmation() {
  if (processing.value) return
  confirmMode.value = null
  reviewAcknowledged.value = false
}

async function load() {
  if (!store.sessionReady) return
  const request = ++loadRequest
  loading.value = true
  error.value = ''
  try {
    const candidates = await getCandidates({ scopeKey: scopeKey.value, limit: 1 })
    if (!candidates.latest_snapshot) {
      if (request === loadRequest) listing.value = null
      return
    }
    if (candidates.run?.snapshot_id !== candidates.latest_snapshot.snapshot_id) {
      await analyzeSnapshot(candidates.latest_snapshot.snapshot_id)
    }
    const next = await getCleanupClassifications(scopeKey.value)
    if (request !== loadRequest) return
    listing.value = next
    selectedSafe.value = new Set()
    selectedReview.value = new Set()
    if (!next.summary.SAFE_ACTIONABLE.count && next.summary.REVIEW_REQUIRED.count) activeTab.value = 'review'
    else if (!next.summary.SAFE_ACTIONABLE.count && !next.summary.REVIEW_REQUIRED.count) activeTab.value = 'protected'
  } catch {
    if (request === loadRequest) {
      listing.value = null
      error.value = '暂时无法读取清理建议，请稍后重试或先完成一次扫描。'
    }
  } finally {
    if (request === loadRequest) loading.value = false
  }
}

function reasonMessage(code: string | null): string {
  return ({
    TARGET_CHANGED_SINCE_SCAN: '文件已经发生变化',
    TARGET_CHANGED_SINCE_PREPARE: '文件在确认后发生了变化',
    TARGET_NO_LONGER_EXISTS: '文件已经不存在',
    ACCESS_DENIED: '当前没有权限',
    TARGET_IN_USE: '文件正在使用中',
    EXECUTION_REPARSE_POINT_BLOCKED: '文件位置变成了系统链接',
    EXECUTION_CROSS_VOLUME_BLOCKED: '文件位置跨越了其他磁盘',
    BATCH_CLASSIFICATION_CHANGED: '当前安全分类已经变化',
    BATCH_ITEM_NO_LONGER_AVAILABLE: '扫描记录中的项目已经不可用',
    RECYCLE_ORIGINAL_PATH_REMAINS: '无法确认文件已进入回收站',
  } as Record<string, string>)[code ?? ''] ?? '当前安全规则不允许处理'
}

async function updateProgress(batchId: string) {
  try {
    const audit = await getCleanupBatch(batchId)
    const completed = audit.items.filter(item => item.execute_result !== null).length
    if (processing.value?.batchId === batchId) processing.value = { ...processing.value, completed }
  } catch { /* Execution result remains authoritative. */ }
}

async function confirmBatch() {
  const mode = confirmMode.value
  if (!mode || !selectedIds.value.length || (mode === 'review' && !reviewAcknowledged.value)) return
  error.value = ''
  try {
    const prepared = await prepareCleanupBatch(selectedIds.value, mode, scopeKey.value)
    if (!prepared.execution_token || !prepared.approved_count) {
      result.value = {
        batch_id: prepared.batch_id, status: 'completed_with_partial_result', mode,
        requested_count: prepared.requested_count, success_count: 0,
        skipped_count: prepared.skipped_count, failed_count: 0,
        requested_bytes: prepared.requested_bytes, recycled_bytes: 0, target_mutation: 'none',
        items: prepared.items.map(item => ({
          item_id: item.item_id, candidate_id: item.candidate_id, probe_id: item.probe_id,
          result: 'skipped', reason: item.reason, recycled_bytes: 0,
        })),
      }
      confirmMode.value = null
      return
    }
    processing.value = { batchId: prepared.batch_id, completed: 0, total: prepared.approved_count }
    progressTimer = setInterval(() => void updateProgress(prepared.batch_id), 250)
    result.value = await executeCleanupBatch(prepared.execution_token)
    if (mode === 'safe') selectedSafe.value = new Set()
    else selectedReview.value = new Set()
    confirmMode.value = null
    await load()
  } catch {
    error.value = '处理没有完成；DiskScope 未使用永久删除。请查看未处理原因后重试。'
  } finally {
    if (progressTimer) clearInterval(progressTimer)
    progressTimer = null
    processing.value = null
  }
}

async function copyPath(path: string) {
  try { await navigator.clipboard.writeText(path) }
  catch { error.value = '无法复制路径，请检查浏览器剪贴板权限。' }
}

watch(() => store.sessionReady, ready => { if (ready) void load() }, { immediate: true })
watch(scopeKey, () => {
  activeTab.value = 'safe'
  result.value = null
  void load()
})
onBeforeUnmount(() => { if (progressTimer) clearInterval(progressTimer) })
</script>

<template>
  <div class="page-heading">
    <div><p class="eyebrow">扫描后的下一步</p><h1>清理空间</h1><p class="page-description">根据安全等级查看已分析文件，再决定是否移入 Windows 回收站。</p></div>
    <span class="read-only-chip">不会永久删除</span>
  </div>

  <section class="panel cleanup-source">
    <div><strong>查看哪次扫描的建议？</strong><p>清理中心使用已保存的扫描记录；真正处理前仍会重新检查每个文件。</p></div>
    <label>扫描位置
      <select v-model="scopeKey" :disabled="loading || !!processing">
        <option value="system_drive_c">Windows C 盘</option>
        <option value="current_user_temp">临时文件</option>
      </select>
    </label>
  </section>

  <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
  <p v-if="loading" class="inline-note" aria-live="polite">正在整理清理建议…</p>

  <template v-if="listing && summary">
    <section class="cleanup-summary" aria-label="清理建议分类摘要">
      <button type="button" :class="{ active: activeTab === 'safe' }" @click="activeTab = 'safe'">
        <span>可处理</span><strong>{{ formatBytes(summary.SAFE_ACTIONABLE.bytes) }}</strong><small>{{ formatNumber(summary.SAFE_ACTIONABLE.count) }} 个文件</small>
      </button>
      <button type="button" :class="{ active: activeTab === 'review' }" @click="activeTab = 'review'">
        <span>建议手动检查</span><strong>{{ formatBytes(summary.REVIEW_REQUIRED.bytes) }}</strong><small>{{ formatNumber(summary.REVIEW_REQUIRED.count) }} 个文件</small>
      </button>
      <button type="button" :class="{ active: activeTab === 'protected' }" @click="activeTab = 'protected'">
        <span>不建议处理</span><strong>{{ formatBytes(summary.DO_NOT_TOUCH.bytes) }}</strong><small>{{ formatNumber(summary.DO_NOT_TOUCH.count) }} 个项目</small>
      </button>
    </section>

    <p class="fine-print">以上容量来自扫描记录，不代表一定能立即增加相同的磁盘可用空间。</p>

    <section class="panel cleanup-panel">
      <div class="panel-heading cleanup-heading">
        <div>
          <p class="eyebrow">{{ tabLabel[activeTab] }}</p>
          <h2 v-if="activeTab === 'safe'">这些文件已通过当前安全检查</h2>
          <h2 v-else-if="activeTab === 'review'">请逐个判断是否仍然需要</h2>
          <h2 v-else>这些项目不会提供处理入口</h2>
        </div>
        <button v-if="activeTab === 'safe' && safeItems.length" type="button" class="text-button" @click="toggleAllSafe">
          {{ allSafeSelected ? '取消全选' : '全选当前列表' }}
        </button>
      </div>

      <p v-if="activeTab === 'review'" class="coverage-note">DiskScope 无法判断这些个人文件是否仍然有用，因此不会默认选择，也不提供一键全选。</p>
      <p v-if="activeTab === 'protected'" class="coverage-note">系统位置、程序文件、危险类型、文件夹或安全信息不足的项目都会留在这里，不能强制处理。</p>

      <div v-if="currentItems.length" class="cleanup-list">
        <article v-for="item in currentItems" :key="item.candidate_id" class="cleanup-item">
          <label v-if="activeTab !== 'protected'" class="cleanup-check">
            <input
              type="checkbox"
              :checked="activeTab === 'safe' ? selectedSafe.has(item.candidate_id) : selectedReview.has(item.candidate_id)"
              :aria-label="`选择 ${fileName(item.display_path)}`"
              @change="toggleSelection(activeTab === 'safe' ? 'safe' : 'review', item.candidate_id, ($event.target as HTMLInputElement).checked)"
            >
          </label>
          <div class="cleanup-item-main">
            <div class="cleanup-item-title"><strong>{{ fileName(item.display_path) }}</strong><span>{{ formatBytes(item.logical_bytes) }}</span></div>
            <p class="cleanup-path" :title="item.display_path">{{ item.display_path }}</p>
            <p>{{ item.reason }}</p>
            <div class="cleanup-item-actions">
              <span>最后修改：{{ formatLocalTime(item.snapshot_mtime) }}</span>
              <button type="button" class="table-action" @click="copyPath(item.display_path)">复制路径</button>
            </div>
            <details class="technical-details">
              <summary>技术详情</summary>
              <p>分类：{{ item.classification }} · 项目 ID：<span class="mono">{{ item.candidate_id }}</span></p>
              <p>判断依据：<span class="mono">{{ item.reason_codes.join(', ') }}</span></p>
            </details>
          </div>
        </article>
      </div>

      <div v-else-if="activeTab === 'safe' && reviewItems.length" class="zero-safe-state">
        <EmptyState title="暂时没有可以直接处理的文件" description="你可以查看需要自己判断的个人文件。" />
        <button type="button" class="primary-button" @click="activeTab = 'review'">查看建议检查的文件</button>
      </div>
      <EmptyState v-else title="这一类暂时没有项目" description="可以切换上方分类，或完成新的扫描后再查看。" />

      <div v-if="activeTab === 'safe' && selectedSafe.size" class="selection-toolbar">
        <span>已选择 {{ selectedSafe.size }} 个文件 · {{ formatBytes(safeItems.filter(item => selectedSafe.has(item.candidate_id)).reduce((sum, item) => sum + item.logical_bytes, 0)) }}</span>
        <button type="button" class="primary-button" @click="openConfirmation('safe')">移入 Windows 回收站</button>
      </div>
      <div v-if="activeTab === 'review' && selectedReview.size" class="selection-toolbar">
        <span>已逐项选择 {{ selectedReview.size }} 个文件 · {{ formatBytes(reviewItems.filter(item => selectedReview.has(item.candidate_id)).reduce((sum, item) => sum + item.logical_bytes, 0)) }}</span>
        <button type="button" class="primary-button" @click="openConfirmation('review')">继续确认</button>
      </div>
    </section>

    <section v-if="!summary.SAFE_ACTIONABLE.count && !summary.REVIEW_REQUIRED.count" class="panel no-action-state">
      <h2>当前没有适合通过 DiskScope 处理的文件</h2>
      <p>你仍可以继续了解空间占用，或在文件发生变化后重新扫描。</p>
      <div><RouterLink to="/analysis">查看空间分析</RouterLink><RouterLink to="/large-items">查看大文件</RouterLink></div>
    </section>
  </template>

  <EmptyState v-else-if="!loading" title="还没有可用的扫描记录" description="请先扫描 C 盘或临时文件，再回到这里查看能做什么。" />

  <section v-if="processing" class="panel processing-panel" aria-live="polite">
    <strong>正在移入 Windows 回收站</strong>
    <p>正在处理 {{ processing.completed }} / {{ processing.total }}；请保持 DiskScope 打开。</p>
  </section>

  <section v-if="result" class="panel batch-result" aria-live="polite">
    <div class="panel-heading"><div><p class="eyebrow">处理结果</p><h2>处理完成</h2></div><span class="status-pill completed">{{ result.success_count }} 个成功</span></div>
    <div class="result-counts"><span>成功：{{ result.success_count }}</span><span>跳过：{{ result.skipped_count }}</span><span>失败：{{ result.failed_count }}</span></div>
    <p>已将 {{ formatBytes(result.recycled_bytes) }} 的文件移入 Windows 回收站。</p>
    <p class="coverage-note">这些文件仍可能占用磁盘空间。如需真正释放空间，请通过 Windows 回收站自行确认并清空；DiskScope 不会自动清空回收站。</p>
    <details v-if="result.items.some(item => item.result !== 'recycled')" class="technical-details">
      <summary>查看未处理原因</summary>
      <ul><li v-for="item in result.items.filter(entry => entry.result !== 'recycled')" :key="item.item_id">{{ reasonMessage(item.reason) }} <span class="mono">({{ item.reason }})</span></li></ul>
    </details>
  </section>

  <BaseDialog
    :open="confirmMode !== null"
    title-id="batch-confirm-title"
    description-id="batch-confirm-description"
    :close-on-backdrop="!processing"
    @close="closeConfirmation"
  >
    <h2 id="batch-confirm-title">{{ confirmMode === 'safe' ? '移入 Windows 回收站？' : '确认处理这些文件？' }}</h2>
    <div id="batch-confirm-description">
      <p>已选择 {{ selectedIds.length }} 个文件，总大小约 {{ formatBytes(selectedBytes) }}。</p>
      <p v-if="confirmMode === 'safe'">这些文件已经通过 DiskScope 当前的安全检查。处理后会进入 Windows 回收站，不会永久删除。</p>
      <template v-else>
        <p>这些文件需要你自己判断是否仍然有用。DiskScope 无法替你确认文件内容是否重要。</p>
        <label class="acknowledgement"><input v-model="reviewAcknowledged" type="checkbox"> 我已经检查过所选文件，并确认不再需要</label>
      </template>
    </div>
    <div class="confirm-actions">
      <button type="button" class="text-button" :disabled="!!processing" @click="closeConfirmation">取消</button>
      <button type="button" class="primary-button" data-dialog-initial :disabled="!!processing || (confirmMode === 'review' && !reviewAcknowledged)" @click="confirmBatch">移入回收站</button>
    </div>
  </BaseDialog>
</template>
