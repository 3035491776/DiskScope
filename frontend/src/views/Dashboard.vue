<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import LowImpactCard from '../components/LowImpactCard.vue'
import ScanControls from '../components/ScanControls.vue'
import ScanProgress from '../components/ScanProgress.vue'
import ResultSourceBanner from '../components/ResultSourceBanner.vue'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatNumber, formatSeconds } from '../utils/format'
import { isActive, targetName } from '../utils/presentation'

const store = useScanStore()
const scanControls = ref<InstanceType<typeof ScanControls> | null>(null)
const summary = computed(() => store.result?.summary)
const cVolume = computed(() => store.volumes.find(volume => volume.drive === 'C:'))
function usedPercent(total: number, used: number): number | null {
  return total > 0 ? Math.min(100, Math.max(0, used / total * 100)) : null
}
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">DISKSCOPE / OVERVIEW</p><h1>空间总览</h1><p class="page-description">查看当前授权范围的扫描结果，与本机磁盘容量分开呈现。</p></div><span class="read-only-chip">只读诊断</span></div>

  <section class="panel scan-entry">
    <div class="panel-heading"><div><p class="eyebrow">扫描入口</p><h2>选择当前范围</h2></div><span class="subtle-label">固定只读范围</span></div>
    <ScanControls ref="scanControls" />
  </section>

  <ResultSourceBanner />

  <section class="summary-section" aria-label="当前扫描范围统计">
    <div class="section-heading"><div><p class="eyebrow">当前浏览范围</p><h2>{{ targetName(store.resultTarget) }}</h2></div><span v-if="store.result?.source_type !== 'none' && store.result" class="status-pill completed">{{ store.result.coverage === 'limited' ? '扫描完成 · 部分位置未覆盖' : '扫描完成' }}</span></div>
    <div class="metric-grid">
      <div class="metric-card"><span>{{ store.resultTarget === 'c_drive' ? '扫描可见空间' : '已扫描逻辑大小' }}</span><strong>{{ formatBytes(summary?.total_bytes) }}</strong><small>仅当前扫描范围 · 逻辑大小</small></div>
      <div class="metric-card"><span>文件</span><strong>{{ formatNumber(summary?.file_count) }}</strong><small>已发现项目</small></div>
      <div class="metric-card"><span>目录</span><strong>{{ formatNumber(summary?.directory_count) }}</strong><small>包含扫描根</small></div>
      <div class="metric-card"><span>扫描耗时</span><strong>{{ formatSeconds(summary ? summary.duration_seconds * 1000 : null) }}</strong><small>实际任务时间</small></div>
    </div>
    <p v-if="store.resultTarget === 'c_drive' && summary" class="inline-note">磁盘已用空间 {{ formatBytes(cVolume?.used_bytes) }}；扫描可见空间 {{ formatBytes(summary.total_bytes) }}。两者口径不同，权限受限和 NTFS 系统占用可能造成差异。</p>
    <p v-if="store.scan && isActive(store.scan)" class="inline-note">当前运行任务：{{ targetName(store.scan.scope_key === 'system_drive_c' ? 'c_drive' : store.scan.scope_key === 'current_user_temp' ? 'user_temp' : store.scan.scope_key === 'project_workspace' ? 'project' : 'fixture') }}</p>
    <ScanProgress v-if="store.scan && isActive(store.scan)" :scan="store.scan" />
    <div v-if="summary" class="summary-callout">
      <span>{{ store.result?.source_type === 'snapshot' ? '已保存结果' : '最新结果' }} · {{ store.result?.coverage === 'limited' ? `${formatNumber(summary.skipped_count)} 个位置未完全覆盖` : '覆盖完整' }}</span>
      <RouterLink to="/analysis">查看空间分析 →</RouterLink>
    </div>
    <EmptyState v-else title="尚未有扫描结果" description="选择 Windows C: 或当前用户临时文件开始只读扫描；不会自动重扫 C 盘。" />
  </section>

  <section class="volume-section panel" aria-labelledby="volume-title">
    <div class="panel-heading"><div><p class="eyebrow">WINDOWS VOLUMES</p><h2 id="volume-title">本机磁盘容量</h2></div><span class="subtle-label">容量信息不代表扫描结果</span></div>
    <div v-if="store.volumesState === 'ready' && store.volumes.length" class="volume-grid">
      <div v-for="volume in store.volumes" :key="volume.drive" class="volume-card">
        <div class="volume-top"><strong>{{ volume.drive }}</strong><span class="locked-badge">{{ volume.drive === 'C:' ? '只读分析 · Low-Impact' : '整盘扫描尚未开放' }}</span></div>
        <div class="volume-amount">{{ formatBytes(volume.used_bytes) }} <span>/ {{ formatBytes(volume.total_bytes) }}</span></div>
        <div class="capacity-track"><span :style="{ width: `${usedPercent(volume.total_bytes, volume.used_bytes) ?? 0}%` }"></span></div>
        <div class="volume-bottom"><span>磁盘已用空间 {{ formatBytes(volume.used_bytes) }}</span><span>可用 {{ formatBytes(volume.free_bytes) }}</span></div>
        <button v-if="volume.drive === 'C:'" type="button" class="primary-button c-drive-action" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting || isActive(store.scan)" @click="scanControls?.openCDriveDialog()">分析 C 盘</button>
      </div>
    </div>
    <EmptyState v-else-if="store.volumesState === 'ready'" title="没有可显示的本地固定卷" description="容量接口不会列出网络盘，也不会启动扫描。" />
    <p v-else class="inline-note">{{ store.volumesState === 'loading' ? '正在读取本机固定卷容量…' : '磁盘容量暂不可用；不会显示估算值。' }}</p>
  </section>

  <LowImpactCard />
</template>
