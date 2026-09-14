<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import LowImpactCard from '../components/LowImpactCard.vue'
import ScanControls from '../components/ScanControls.vue'
import ScanProgress from '../components/ScanProgress.vue'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatNumber, formatSeconds } from '../utils/format'
import { completionLabel, isActive, targetName } from '../utils/presentation'

const store = useScanStore()
const router = useRouter()
const confirmCDrive = ref(false)
const summary = computed(() => store.scan)
const cVolume = computed(() => store.volumes.find(volume => volume.drive === 'C:'))
async function beginCDriveAnalysis() {
  if (store.starting || isActive(store.scan)) return
  const started = await store.startScan('c_drive')
  if (started) {
    confirmCDrive.value = false
    await router.push('/status')
  }
}
function usedPercent(total: number, used: number): number | null {
  return total > 0 ? Math.min(100, Math.max(0, used / total * 100)) : null
}
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">DISKSCOPE / OVERVIEW</p><h1>空间总览</h1><p class="page-description">查看当前授权范围的扫描结果，与本机磁盘容量分开呈现。</p></div><span class="read-only-chip">只读诊断</span></div>

  <section class="panel scan-entry">
    <div class="panel-heading"><div><p class="eyebrow">扫描入口</p><h2>选择当前范围</h2></div><span class="subtle-label">固定开发测试范围</span></div>
    <ScanControls />
  </section>

  <section class="summary-section" aria-label="当前扫描范围统计">
    <div class="section-heading"><div><p class="eyebrow">当前扫描范围</p><h2>{{ targetName(store.scan ? store.resultTarget : store.selectedTarget) }}</h2></div><span v-if="summary" class="status-pill" :class="summary.state">{{ completionLabel(summary) }}</span></div>
    <div class="metric-grid">
      <div class="metric-card"><span>{{ store.resultTarget === 'c_drive' ? '扫描可见空间' : '已扫描逻辑大小' }}</span><strong>{{ formatBytes(summary?.logical_bytes) }}</strong><small>仅当前扫描范围 · 逻辑大小</small></div>
      <div class="metric-card"><span>文件</span><strong>{{ formatNumber(summary?.files_seen) }}</strong><small>已发现项目</small></div>
      <div class="metric-card"><span>目录</span><strong>{{ formatNumber(summary?.dirs_seen) }}</strong><small>包含扫描根</small></div>
      <div class="metric-card"><span>扫描耗时</span><strong>{{ formatSeconds(summary?.elapsed_ms) }}</strong><small>实际任务时间</small></div>
    </div>
    <p v-if="store.resultTarget === 'c_drive' && summary" class="inline-note">磁盘已用空间 {{ formatBytes(cVolume?.used_bytes) }}；扫描可见空间 {{ formatBytes(summary.logical_bytes) }}。两者口径不同，权限受限和 NTFS 系统占用可能造成差异。</p>
    <ScanProgress v-if="summary && isActive(summary)" :scan="summary" />
    <div v-else-if="summary?.state === 'completed'" class="summary-callout">
      <span>{{ completionLabel(summary) }} · 错误 {{ summary.errors_count }} · 跳过 {{ summary.skipped_count }}</span>
      <RouterLink to="/analysis">查看空间分析 →</RouterLink>
    </div>
    <EmptyState v-else-if="!summary" title="尚无扫描结果" description="选择一个固定范围并开始只读扫描，统计数字将从实际扫描 API 显示。" />
    <p v-else-if="summary.state === 'cancelled' || summary.state === 'failed'" class="inline-note">{{ completionLabel(summary) }}。可在扫描状态页查看详情或重新开始。</p>
  </section>

  <section class="volume-section panel" aria-labelledby="volume-title">
    <div class="panel-heading"><div><p class="eyebrow">WINDOWS VOLUMES</p><h2 id="volume-title">本机磁盘容量</h2></div><span class="subtle-label">容量信息不代表扫描结果</span></div>
    <div v-if="store.volumesState === 'ready' && store.volumes.length" class="volume-grid">
      <div v-for="volume in store.volumes" :key="volume.drive" class="volume-card">
        <div class="volume-top"><strong>{{ volume.drive }}</strong><span class="locked-badge">{{ volume.drive === 'C:' ? '只读分析 · Low-Impact' : '整盘扫描尚未开放' }}</span></div>
        <div class="volume-amount">{{ formatBytes(volume.used_bytes) }} <span>/ {{ formatBytes(volume.total_bytes) }}</span></div>
        <div class="capacity-track"><span :style="{ width: `${usedPercent(volume.total_bytes, volume.used_bytes) ?? 0}%` }"></span></div>
        <div class="volume-bottom"><span>磁盘已用空间 {{ formatBytes(volume.used_bytes) }}</span><span>可用 {{ formatBytes(volume.free_bytes) }}</span></div>
        <button v-if="volume.drive === 'C:'" type="button" class="primary-button c-drive-action" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting || isActive(store.scan)" @click="confirmCDrive = true">分析 C 盘</button>
      </div>
    </div>
    <EmptyState v-else-if="store.volumesState === 'ready'" title="没有可显示的本地固定卷" description="容量接口不会列出网络盘，也不会启动扫描。" />
    <p v-else class="inline-note">{{ store.volumesState === 'loading' ? '正在读取本机固定卷容量…' : '磁盘容量暂不可用；不会显示估算值。' }}</p>
  </section>

  <LowImpactCard />
  <div v-if="confirmCDrive" class="modal-backdrop"><section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="c-drive-confirm-title" aria-describedby="c-drive-confirm-description"><p class="eyebrow">C DRIVE / READ ONLY</p><h2 id="c-drive-confirm-title">分析 Windows C盘</h2><p id="c-drive-confirm-description">DiskScope 将只读取文件系统元数据，统计目录和文件的逻辑大小。不会读取文件正文、删除或修改文件、修改权限、跨磁盘扫描，也不会跟随 junction 或 symlink。</p><p>扫描可能需要几十秒至数分钟，受保护目录可能无法完整读取；扫描过程中可以随时取消。</p><div class="confirm-actions"><button type="button" class="text-button" :disabled="store.starting" @click="confirmCDrive = false">取消</button><button type="button" class="primary-button" :disabled="store.starting || isActive(store.scan)" @click="beginCDriveAnalysis">{{ store.starting ? '正在启动…' : '开始只读分析' }}</button></div><p v-if="store.message" class="inline-error" role="alert">{{ store.message }}</p></section></div>
</template>
