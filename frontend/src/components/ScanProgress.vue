<script setup lang="ts">
import type { ScanStatus } from '../services/api'
import { formatBytes, formatNumber, formatSeconds } from '../utils/format'
import { completionLabel, isActive } from '../utils/presentation'

defineProps<{ scan: ScanStatus }>()
</script>

<template>
  <div class="progress-panel">
    <div class="progress-head"><span class="status-pill" :class="scan.state">{{ completionLabel(scan) }}</span><span>{{ isActive(scan) ? '正在枚举文件系统…' : '扫描任务已结束' }}</span></div>
    <div v-if="isActive(scan)" class="indeterminate-track" aria-label="扫描正在进行"><span></span></div>
    <div class="progress-grid">
      <div><small>已发现文件</small><strong>{{ formatNumber(scan.files_seen) }}</strong></div>
      <div><small>已发现目录</small><strong>{{ formatNumber(scan.dirs_seen) }}</strong></div>
      <div><small>逻辑大小</small><strong>{{ formatBytes(scan.logical_bytes) }}</strong></div>
      <div><small>耗时</small><strong>{{ formatSeconds(scan.elapsed_ms) }}</strong></div>
      <div><small>错误</small><strong>{{ formatNumber(scan.errors_count) }}</strong></div>
      <div><small>跳过</small><strong>{{ formatNumber(scan.skipped_count) }}</strong></div>
    </div>
  </div>
</template>
