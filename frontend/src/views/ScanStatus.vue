<script setup lang="ts">
import EmptyState from '../components/EmptyState.vue'
import ScanControls from '../components/ScanControls.vue'
import ScanProgress from '../components/ScanProgress.vue'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber, formatSeconds } from '../utils/format'
import { completionLabel, targetName } from '../utils/presentation'
import { coverageHeading, coverageIssueCount, coverageReasons } from '../utils/coverage'

const store = useScanStore()
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">SCAN / STATUS</p><h1>扫描状态</h1><p class="page-description">查看当前或最近一次任务的进度、覆盖情况和资源指标。</p></div></div>
  <section class="panel scan-entry"><div class="panel-heading"><div><p class="eyebrow">CONTROL</p><h2>固定范围扫描</h2></div></div><ScanControls /></section>
  <EmptyState v-if="!store.scan" title="还没有扫描任务" description="选择固定范围并主动开始扫描；不会自动扫描磁盘。" />
  <template v-else>
    <section class="panel status-detail"><div class="panel-heading"><div><p class="eyebrow">CURRENT TASK</p><h2>{{ targetName(store.scan.scope_key === 'system_drive_c' ? 'c_drive' : store.scan.scope_key === 'current_user_temp' ? 'user_temp' : store.scan.scope_key === 'project_workspace' ? 'project' : 'fixture') }}</h2></div><span class="status-pill" :class="store.scan.state">{{ completionLabel(store.scan) }}</span></div><p v-if="['system_drive_c', 'current_user_temp'].includes(store.scan.scope_key)" class="inline-note">Low-Impact Scan · Metadata Only · 单扫描任务。只读分析可随时取消，不读取正文，也不会删除文件。</p><ScanProgress :scan="store.scan" />
      <div class="detail-grid"><div><span>创建时间</span><strong>{{ formatLocalTime(store.scan.created_at) }}</strong></div><div><span>开始时间</span><strong>{{ formatLocalTime(store.scan.started_at) }}</strong></div><div><span>结束时间</span><strong>{{ formatLocalTime(store.scan.finished_at) }}</strong></div><div><span>任务编号</span><strong class="mono">{{ store.scan.scan_id }}</strong></div></div>
      <p v-if="store.scan.state === 'failed'" class="inline-error" role="alert">扫描失败：{{ store.scan.error_message || store.scan.error_code || '原因未知' }}</p>
      <p v-else-if="store.scan.state === 'cancelled'" class="inline-note">任务已取消；以下统计可能不完整。</p>
      <p v-else-if="store.scan.state === 'completed' && coverageIssueCount(store.scan)" class="coverage-note">{{ coverageHeading(store.scan) }}。部分位置按只读安全策略跳过，或元数据读取受限。</p>
      <p v-if="store.scan.state === 'completed' && store.scan.snapshot_status === 'pending'" class="inline-note">正在保存历史快照…</p>
      <p v-if="store.scan.state === 'completed' && store.scan.snapshot_status === 'failed'" class="inline-error" role="alert">扫描已完成，但历史快照保存失败（{{ store.scan.snapshot_error_code }}）。当前扫描结果仍可查看。</p>
      <p v-if="store.scan.state === 'completed' && store.scan.scope_key === 'current_user_temp'" class="inline-note">文件元数据持久化：{{ formatNumber(store.scan.persisted_file_count) }} / {{ formatNumber(store.scan.observed_file_count) }} · {{ store.scan.file_metadata_coverage === 'complete' ? '完整覆盖' : `达到 ${formatNumber(store.scan.file_persistence_limit)} 项硬上限，覆盖受限` }}</p>
    </section>
    <div class="two-column">
      <section class="panel"><div class="panel-heading"><div><p class="eyebrow">COVERAGE</p><h2>覆盖情况</h2></div><span class="subtle-label">{{ coverageHeading(store.scan) }}</span></div>
        <p class="inline-note">{{ formatNumber(coverageIssueCount(store.scan)) }} 个位置未完全覆盖。已完成的扫描结果仍可浏览；该数字不代表程序故障。</p>
        <div v-if="Object.keys(store.scan.errors).length" class="coverage-reasons"><div v-for="(item, code) in store.scan.errors" :key="code" class="coverage-reason"><div><strong>{{ coverageReasons[code]?.label || code }}</strong><span>{{ formatNumber(item.count) }} 项</span></div><p>{{ coverageReasons[code]?.explanation || '可在技术详情中查看原始错误代码。' }}</p><details><summary>技术详情</summary><code>{{ code }}</code><ul v-if="item.samples.length"><li v-for="sample in item.samples" :key="sample" :title="sample">{{ sample }}</li></ul></details></div></div>
        <p v-else class="inline-note">{{ store.scan.errors_count === 0 ? '未记录覆盖问题。' : '正在收集覆盖摘要…' }}</p>
        <details class="coverage-technical"><summary>查看原始统计</summary><p>errors_count {{ store.scan.errors_count }} · skipped_count {{ store.scan.skipped_count }}</p></details>
        <div v-if="Object.keys(store.scan.exclusions).length" class="exclusion-list"><strong>安全排除</strong><span v-for="(item, rule) in store.scan.exclusions" :key="rule">{{ rule }} · {{ item.count }}</span></div>
      </section>
      <section class="panel"><div class="panel-heading"><div><p class="eyebrow">PROCESS METRICS</p><h2>扫描资源</h2></div><span class="subtle-label">进程范围 · 开发指标</span></div>
        <div class="detail-grid metrics-detail"><div><span>耗时</span><strong>{{ formatSeconds(store.scan.metrics?.duration_ms) }}</strong></div><div><span>文件速率</span><strong>{{ store.scan.metrics ? store.scan.metrics.files_per_second.toLocaleString() + ' 文件/秒' : '—' }}</strong></div><div><span>进程读取量</span><strong>{{ formatBytes(store.scan.metrics?.delta_read_bytes) }}</strong></div><div><span>进程写入量</span><strong>{{ formatBytes(store.scan.metrics?.delta_write_bytes) }}</strong></div><div><span>当前内存</span><strong>{{ formatBytes(store.scan.metrics?.rss_current_bytes) }}</strong></div><div><span>扫描峰值内存</span><strong>{{ formatBytes(store.scan.metrics?.rss_peak_observed_bytes) }}</strong></div><div><span>累计 CPU 时间</span><strong>{{ store.scan.metrics?.cpu_seconds == null ? '—' : `${store.scan.metrics.cpu_seconds.toFixed(2)} s` }}</strong></div></div>
        <p class="fine-print">指标包含本地服务自身活动，不能当作目标目录读写量；不可取得时显示 —。</p>
      </section>
    </div>
  </template>
</template>
