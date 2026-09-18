<script setup lang="ts">
import EmptyState from '../components/EmptyState.vue'
import ScanControls from '../components/ScanControls.vue'
import ScanProgress from '../components/ScanProgress.vue'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber, formatSeconds } from '../utils/format'
import { completionLabel, scanHeading } from '../utils/presentation'
import { coverageHeading, coverageIssueCount, coverageReasons, scanErrorMessage } from '../utils/coverage'

const store = useScanStore()
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">扫描进度</p><h1>扫描状态</h1><p class="page-description">查看正在做什么、已发现多少文件，以及是否有位置未能扫描。</p></div></div>
  <section class="panel scan-entry"><div class="panel-heading"><div><p class="eyebrow">扫描控制</p><h2>选择扫描位置</h2></div></div><ScanControls /></section>
  <EmptyState v-if="!store.scan" title="还没有扫描任务" description="选择固定范围并主动开始扫描；不会自动扫描磁盘。" />
  <template v-else>
    <section class="panel status-detail"><div class="panel-heading"><div><p class="eyebrow">当前任务</p><h2>{{ scanHeading(store.scan) }}</h2></div><span class="status-pill" :class="store.scan.state">{{ completionLabel(store.scan) }}</span></div><p v-if="['system_drive_c', 'current_user_temp'].includes(store.scan.scope_key)" class="inline-note">扫描过程中不会修改你的文件。你可以随时取消。</p><ScanProgress :scan="store.scan" />
      <div class="detail-grid"><div><span>创建时间</span><strong>{{ formatLocalTime(store.scan.created_at) }}</strong></div><div><span>开始时间</span><strong>{{ formatLocalTime(store.scan.started_at) }}</strong></div><div><span>结束时间</span><strong>{{ formatLocalTime(store.scan.finished_at) }}</strong></div></div>
      <p v-if="store.scan.state === 'failed'" class="inline-error" role="alert">{{ scanErrorMessage(store.scan.error_code) }}</p>
      <p v-else-if="store.scan.state === 'cancelled'" class="inline-note">任务已取消；以下统计可能不完整。</p>
      <p v-else-if="store.scan.state === 'completed' && coverageIssueCount(store.scan)" class="coverage-note">{{ coverageHeading(store.scan) }}。DiskScope 已安全跳过这些位置，其余结果仍可查看。</p>
      <p v-if="store.scan.state === 'completed' && store.scan.snapshot_status === 'pending'" class="inline-note">正在保存这次扫描记录…</p>
      <p v-if="store.scan.state === 'completed' && store.scan.snapshot_status === 'failed'" class="inline-error" role="alert">扫描已完成，但扫描记录保存失败。当前结果仍可查看。</p>
      <p v-if="store.scan.state === 'completed' && store.scan.scope_key === 'current_user_temp'" class="inline-note">这次发现了 {{ formatNumber(store.scan.observed_file_count) }} 个文件。{{ store.scan.file_metadata_coverage === 'complete' ? '已保存全部文件的详细信息。' : `为了控制资源占用，保存了其中 ${formatNumber(store.scan.persisted_file_count)} 个文件的详细信息。` }}</p>
      <details class="coverage-technical"><summary>技术详情</summary><p>任务编号 <span class="mono">{{ store.scan.scan_id }}</span></p><p v-if="store.scan.error_code">错误代码 <span class="mono">{{ store.scan.error_code }}</span></p><p v-if="store.scan.error_message">原始错误信息 <span class="mono">{{ store.scan.error_message }}</span></p><p v-if="store.scan.snapshot_error_code">扫描记录错误代码 <span class="mono">{{ store.scan.snapshot_error_code }}</span></p></details>
    </section>
    <div class="two-column">
      <section class="panel"><div class="panel-heading"><div><p class="eyebrow">结果完整度</p><h2>未能扫描的位置</h2></div><span class="subtle-label">{{ coverageHeading(store.scan) }}</span></div>
        <p class="inline-note">{{ formatNumber(coverageIssueCount(store.scan)) }} 个位置未能扫描。其余扫描结果仍可浏览，这通常不代表程序故障。</p>
        <div v-if="Object.keys(store.scan.errors).length" class="coverage-reasons"><div v-for="(item, code) in store.scan.errors" :key="code" class="coverage-reason"><div><strong>{{ coverageReasons[code]?.label || code }}</strong><span>{{ formatNumber(item.count) }} 项</span></div><p>{{ coverageReasons[code]?.explanation || '可在技术详情中查看原始错误代码。' }}</p><details><summary>技术详情</summary><code>{{ code }}</code><ul v-if="item.samples.length"><li v-for="sample in item.samples" :key="sample" :title="sample">{{ sample }}</li></ul></details></div></div>
        <p v-else class="inline-note">{{ store.scan.errors_count === 0 ? '未记录覆盖问题。' : '正在收集覆盖摘要…' }}</p>
        <details class="coverage-technical"><summary>查看原始统计</summary><p>errors_count {{ store.scan.errors_count }} · skipped_count {{ store.scan.skipped_count }}</p></details>
        <details v-if="Object.keys(store.scan.exclusions).length" class="coverage-technical"><summary>查看安全排除技术详情</summary><div class="exclusion-list"><strong>安全排除</strong><span v-for="(item, rule) in store.scan.exclusions" :key="rule">{{ rule }} · {{ item.count }}</span></div></details>
      </section>
      <details class="panel advanced-details"><summary class="advanced-summary"><span><small>技术详情</small><strong>资源使用情况</strong></span><span>展开查看</span></summary><section class="nested-panel">
        <div class="detail-grid metrics-detail"><div><span>耗时</span><strong>{{ formatSeconds(store.scan.metrics?.duration_ms) }}</strong></div><div><span>扫描速度</span><strong>{{ store.scan.metrics ? store.scan.metrics.files_per_second.toLocaleString() + ' 文件/秒' : '—' }}</strong></div><div><span>进程读取量</span><strong>{{ formatBytes(store.scan.metrics?.delta_read_bytes) }}</strong></div><div><span>进程写入量</span><strong>{{ formatBytes(store.scan.metrics?.delta_write_bytes) }}</strong></div><div><span>内存占用</span><strong>{{ formatBytes(store.scan.metrics?.rss_current_bytes) }}</strong></div><div><span>扫描峰值内存</span><strong>{{ formatBytes(store.scan.metrics?.rss_peak_observed_bytes) }}</strong></div><div><span>CPU 用时</span><strong>{{ store.scan.metrics?.cpu_seconds == null ? '—' : `${store.scan.metrics.cpu_seconds.toFixed(2)} s` }}</strong></div></div>
        <p class="fine-print">指标包含 DiskScope 本地服务本身；无法取得时显示 —。</p></section>
      </details>
    </div>
  </template>
</template>
