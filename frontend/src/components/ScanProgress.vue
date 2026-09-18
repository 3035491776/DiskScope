<script setup lang="ts">
import type { ScanStatus } from '../services/api'
import { formatBytes, formatNumber, formatSeconds } from '../utils/format'
import { completionLabel, isActive } from '../utils/presentation'
import { coverageIssueCount } from '../utils/coverage'

defineProps<{ scan: ScanStatus }>()
</script>

<template>
  <div class="progress-panel">
    <div class="progress-head"><span class="status-pill" :class="scan.state">{{ completionLabel(scan) }}</span><span>{{ isActive(scan) ? '正在查找文件和文件夹…' : '扫描已结束' }}</span></div>
    <div v-if="isActive(scan)" class="indeterminate-track" aria-label="扫描正在进行"><span></span></div>
    <div class="progress-grid">
      <div><small>已发现文件</small><strong>{{ formatNumber(scan.files_seen) }}</strong></div>
      <div><small>已扫描文件夹</small><strong>{{ formatNumber(scan.dirs_seen) }}</strong></div>
      <div><small>已发现空间</small><strong>{{ formatBytes(scan.logical_bytes) }}</strong></div>
      <div><small>已运行</small><strong>{{ formatSeconds(scan.elapsed_ms) }}</strong></div>
      <div><small>扫描速度</small><strong>{{ scan.metrics ? formatNumber(scan.metrics.files_per_second) + ' 文件/秒' : '—' }}</strong></div>
      <div><small>内存占用</small><strong>{{ formatBytes(scan.metrics?.rss_current_bytes) }}</strong></div>
      <div><small>未能扫描的位置</small><strong>{{ formatNumber(coverageIssueCount(scan)) }}</strong></div>
    </div>
  </div>
</template>
