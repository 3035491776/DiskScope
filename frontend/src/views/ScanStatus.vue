<script setup lang="ts">
import EmptyState from '../components/EmptyState.vue'
import ScanControls from '../components/ScanControls.vue'
import ScanProgress from '../components/ScanProgress.vue'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber, formatSeconds } from '../utils/format'
import { completionLabel, targetName } from '../utils/presentation'

const store = useScanStore()
const reasonNames: Record<string, string> = {
  ACCESS_DENIED: '权限不足',
  FILE_NOT_FOUND: '扫描时文件已消失',
  REPARSE_POINT_SKIPPED: '链接或挂载点未跟随',
  PATH_TOO_LONG: '路径过长',
  CROSS_VOLUME_SKIPPED: '跨卷路径已跳过',
  IO_ERROR: '读取元数据失败',
  CANCELLED: '用户取消',
}
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">SCAN / STATUS</p><h1>扫描状态</h1><p class="page-description">查看当前或最近一次任务的进度、覆盖情况和资源指标。</p></div></div>
  <section class="panel scan-entry"><div class="panel-heading"><div><p class="eyebrow">CONTROL</p><h2>固定范围扫描</h2></div></div><ScanControls /></section>
  <EmptyState v-if="!store.scan" title="还没有扫描任务" description="选择 Fixture Sample 或 Project Workspace 并开始扫描；不会自动扫描磁盘。" />
  <template v-else>
    <section class="panel status-detail"><div class="panel-heading"><div><p class="eyebrow">CURRENT TASK</p><h2>{{ targetName(store.resultTarget) }}</h2></div><span class="status-pill" :class="store.scan.state">{{ completionLabel(store.scan) }}</span></div><p v-if="store.resultTarget === 'c_drive'" class="inline-note">Low-Impact Scan · Metadata Only · 单扫描任务。只读分析可随时取消，不显示未知总量的百分比进度。</p><ScanProgress :scan="store.scan" />
      <div class="detail-grid"><div><span>创建时间</span><strong>{{ formatLocalTime(store.scan.created_at) }}</strong></div><div><span>开始时间</span><strong>{{ formatLocalTime(store.scan.started_at) }}</strong></div><div><span>结束时间</span><strong>{{ formatLocalTime(store.scan.finished_at) }}</strong></div><div><span>任务编号</span><strong class="mono">{{ store.scan.scan_id }}</strong></div></div>
      <p v-if="store.scan.state === 'failed'" class="inline-error" role="alert">扫描失败：{{ store.scan.error_message || store.scan.error_code || '原因未知' }}</p>
      <p v-else-if="store.scan.state === 'cancelled'" class="inline-note">任务已取消；以下统计可能不完整。</p>
      <p v-else-if="store.scan.state === 'completed' && (store.scan.errors_count || store.scan.skipped_count)" class="coverage-note">扫描完成，覆盖受限。部分目录按安全策略跳过，或发生了可解释的读取错误。</p>
      <p v-if="store.scan.state === 'completed' && store.scan.snapshot_status === 'pending'" class="inline-note">正在保存历史快照…</p>
      <p v-if="store.scan.state === 'completed' && store.scan.snapshot_status === 'failed'" class="inline-error" role="alert">扫描已完成，但历史快照保存失败（{{ store.scan.snapshot_error_code }}）。当前扫描结果仍可查看。</p>
    </section>
    <div class="two-column">
      <section class="panel"><div class="panel-heading"><div><p class="eyebrow">COVERAGE</p><h2>错误与跳过</h2></div><span class="subtle-label">错误 {{ formatNumber(store.scan.errors_count) }} · 跳过 {{ formatNumber(store.scan.skipped_count) }}</span></div>
        <div v-if="Object.keys(store.scan.errors).length" class="reason-list"><div v-for="(item, code) in store.scan.errors" :key="code"><strong>{{ reasonNames[code] || code }}</strong><span>{{ code }} · {{ item.count }}</span></div></div>
        <p v-else class="inline-note">{{ store.scan.errors_count === 0 ? '未记录读取错误。' : '正在收集错误摘要…' }}</p>
        <div v-if="store.resultTarget === 'c_drive'" class="detail-grid"><div><span>访问受限</span><strong>{{ store.scan.coverage_summary.access_denied_count }}</strong></div><div><span>链接/挂载点跳过</span><strong>{{ store.scan.coverage_summary.reparse_skipped_count }}</strong></div><div><span>扫描中消失</span><strong>{{ store.scan.coverage_summary.file_not_found_count }}</strong></div><div><span>路径过长</span><strong>{{ store.scan.coverage_summary.path_too_long_count }}</strong></div><div><span>其他 I/O 错误</span><strong>{{ store.scan.coverage_summary.other_io_error_count }}</strong></div></div>
        <p v-if="store.resultTarget === 'c_drive'" class="fine-print">ACCESS_DENIED 表示 Windows 权限保护，DiskScope 不尝试绕过。REPARSE_POINT_SKIPPED 表示为避免重复或跨卷访问，链接与挂载点未跟随。</p>
        <div v-if="Object.keys(store.scan.exclusions).length" class="exclusion-list"><strong>安全排除</strong><span v-for="(item, rule) in store.scan.exclusions" :key="rule">{{ rule }} · {{ item.count }}</span></div>
      </section>
      <section class="panel"><div class="panel-heading"><div><p class="eyebrow">PROCESS METRICS</p><h2>扫描资源</h2></div><span class="subtle-label">进程范围 · 开发指标</span></div>
        <div class="detail-grid metrics-detail"><div><span>耗时</span><strong>{{ formatSeconds(store.scan.metrics?.duration_ms) }}</strong></div><div><span>文件速率</span><strong>{{ store.scan.metrics ? store.scan.metrics.files_per_second.toLocaleString() + ' 文件/秒' : '—' }}</strong></div><div><span>读取量</span><strong>{{ formatBytes(store.scan.metrics?.delta_read_bytes) }}</strong></div><div><span>写入量</span><strong>{{ formatBytes(store.scan.metrics?.delta_write_bytes) }}</strong></div><div><span>RSS 观测峰值</span><strong>{{ formatBytes(store.scan.metrics?.rss_peak_observed_bytes) }}</strong></div><div><span>CPU 时间</span><strong>{{ store.scan.metrics?.cpu_seconds == null ? '—' : `${store.scan.metrics.cpu_seconds.toFixed(2)} s` }}</strong></div></div>
        <p class="fine-print">指标包含本地服务自身活动，不能当作目标目录读写量；不可取得时显示 —。</p>
      </section>
    </div>
  </template>
</template>
