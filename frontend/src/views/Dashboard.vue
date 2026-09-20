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
function resultCoverageLabel(): string {
  if (store.result?.coverage !== 'limited') return '扫描完成'
  if (summary.value?.skipped_count === 0 && (summary.value.metadata_warning_count || summary.value.error_count)) {
    return '扫描完成，但部分文件的信息不完整'
  }
  return '扫描完成，但部分内容未能完整读取'
}
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">磁盘空间诊断</p><h1>我的 C 盘空间</h1><p class="page-description">先看磁盘用了多少，再扫描并找到空间主要被哪些文件夹占用。</p></div><span class="read-only-chip">不会修改文件</span></div>

  <section class="panel scan-entry">
    <div class="panel-heading"><div><p class="eyebrow">开始扫描</p><h2>你想查看哪里？</h2></div><span class="subtle-label">安全只读</span></div>
    <ScanControls ref="scanControls" />
  </section>

  <ResultSourceBanner />

  <section class="summary-section" aria-label="当前扫描范围统计">
    <div class="section-heading"><div><p class="eyebrow">上次扫描结果</p><h2>{{ targetName(store.resultTarget) }}</h2></div><span v-if="store.result?.source_type !== 'none' && store.result" class="status-pill completed">{{ resultCoverageLabel() }}</span></div>
    <div class="metric-grid">
      <div class="metric-card"><span>{{ store.resultTarget === 'c_drive' ? '扫描发现的文件大小' : '已发现的文件大小' }}</span><strong>{{ formatBytes(summary?.total_bytes) }}</strong><small>只计算能读取到的文件</small></div>
      <div class="metric-card"><span>文件</span><strong>{{ formatNumber(summary?.file_count) }}</strong><small>已发现项目</small></div>
      <div class="metric-card"><span>文件夹</span><strong>{{ formatNumber(summary?.directory_count) }}</strong><small>包括最上层文件夹</small></div>
      <div class="metric-card"><span>扫描耗时</span><strong>{{ formatSeconds(summary ? summary.duration_seconds * 1000 : null) }}</strong><small>实际任务时间</small></div>
    </div>
    <p v-if="store.resultTarget === 'c_drive' && summary" class="inline-note">Windows 显示 C 盘已用 {{ formatBytes(cVolume?.used_bytes) }}；DiskScope 在可访问位置发现了 {{ formatBytes(summary.total_bytes) }}。系统保留空间、文件分配方式和访问权限会让两个数字不同。</p>
    <p v-if="store.scan && isActive(store.scan)" class="inline-note">当前运行任务：{{ targetName(store.scan.scope_key === 'system_drive_c' ? 'c_drive' : store.scan.scope_key === 'current_user_temp' ? 'user_temp' : store.scan.scope_key === 'project_workspace' ? 'project' : 'fixture') }}</p>
    <ScanProgress v-if="store.scan && isActive(store.scan)" :scan="store.scan" />
    <div v-if="summary" class="summary-callout">
      <span>{{ store.result?.source_type === 'snapshot' ? '已保存的扫描记录' : '最新结果' }} · {{ store.result?.coverage === 'limited' ? (summary.skipped_count ? `${formatNumber(summary.skipped_count)} 个位置未能扫描` : '部分文件的信息不完整') : '可访问位置已扫描' }}</span>
      <RouterLink to="/analysis">查看空间分析 →</RouterLink>
    </div>
    <div v-if="summary" class="next-actions" aria-label="扫描后的操作">
      <RouterLink to="/analysis"><strong>查看空间占用</strong><span>逐层了解文件夹大小</span></RouterLink>
      <RouterLink to="/large-items"><strong>查看大文件</strong><span>找到最占空间的项目</span></RouterLink>
      <RouterLink to="/cleanup" class="primary-next"><strong>清理空间</strong><span>按安全等级选择处理</span></RouterLink>
      <RouterLink to="/history"><strong>扫描历史</strong><span>比较之前的变化</span></RouterLink>
    </div>
    <EmptyState v-else title="尚未有扫描结果" description="选择 Windows C: 或当前用户临时文件开始只读扫描；不会自动重扫 C 盘。" />
  </section>

  <section class="volume-section panel" aria-labelledby="volume-title">
    <div class="panel-heading"><div><p class="eyebrow">Windows 磁盘</p><h2 id="volume-title">本机磁盘容量</h2></div><span class="subtle-label">Windows 报告的容量</span></div>
    <div v-if="store.volumesState === 'ready' && store.volumes.length" class="volume-grid">
      <div v-for="volume in store.volumes" :key="volume.drive" class="volume-card">
        <div class="volume-top"><strong>{{ volume.drive }}</strong><span class="locked-badge">{{ volume.drive === 'C:' ? '可安全扫描' : '暂不支持整盘扫描' }}</span></div>
        <div class="volume-amount">{{ formatBytes(volume.used_bytes) }} <span>/ {{ formatBytes(volume.total_bytes) }}</span></div>
        <div class="capacity-track"><span :style="{ width: `${usedPercent(volume.total_bytes, volume.used_bytes) ?? 0}%` }"></span></div>
        <div class="volume-bottom"><span>磁盘已用空间 {{ formatBytes(volume.used_bytes) }}</span><span>可用 {{ formatBytes(volume.free_bytes) }}</span></div>
        <button v-if="volume.drive === 'C:'" type="button" class="primary-button c-drive-action" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting || isActive(store.scan)" @click="scanControls?.openCDriveDialog()">扫描 C 盘</button>
      </div>
    </div>
    <EmptyState v-else-if="store.volumesState === 'ready'" title="没有可显示的本地固定卷" description="容量接口不会列出网络盘，也不会启动扫描。" />
    <p v-else class="inline-note">{{ store.volumesState === 'loading' ? '正在读取本机固定卷容量…' : '磁盘容量暂不可用；不会显示估算值。' }}</p>
  </section>

  <LowImpactCard />
</template>
