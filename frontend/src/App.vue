<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import {
  PROJECT_WORKSPACE_PATH,
  cancelScan,
  createScan,
  establishSession,
  getHealth,
  getRootDirectories,
  getScan,
  getTopFiles,
} from './services/api'
import type { DirectoryItem, FileItem, HealthResponse, ScanStatus, ScanTarget } from './services/api'
import packageInfo from '../package.json'

type ServiceState = 'checking' | 'online' | 'offline'

const serviceState = ref<ServiceState>('checking')
const health = ref<HealthResponse | null>(null)
const frontendVersion = packageInfo.version
const sessionReady = ref(false)
const sessionMessage = ref('')
const scan = ref<ScanStatus | null>(null)
const scanMessage = ref('')
const selectedTarget = ref<ScanTarget>('fixture')
const resultTarget = ref<ScanTarget>('fixture')
const topFiles = ref<FileItem[]>([])
const rootDirectories = ref<DirectoryItem[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null
let pollBusy = false

async function checkService() {
  serviceState.value = 'checking'
  health.value = null
  try {
    health.value = await getHealth()
    serviceState.value = 'online'
  } catch {
    serviceState.value = 'offline'
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function refreshScan() {
  if (!scan.value || pollBusy) return
  pollBusy = true
  try {
    const latest = await getScan(scan.value.scan_id)
    scan.value = latest
    if (['completed', 'cancelled', 'failed'].includes(latest.state)) {
      stopPolling()
      if (latest.state === 'completed' || latest.state === 'cancelled') {
        ;[topFiles.value, rootDirectories.value] = await Promise.all([
          getTopFiles(latest.scan_id, resultTarget.value === 'project' ? 20 : 10),
          getRootDirectories(latest.scan_id),
        ])
      }
    }
  } catch (error) {
    scanMessage.value = error instanceof Error ? error.message : '无法获取扫描状态'
    stopPolling()
  } finally {
    pollBusy = false
  }
}

async function startTestScan() {
  scanMessage.value = ''
  topFiles.value = []
  rootDirectories.value = []
  try {
    resultTarget.value = selectedTarget.value
    const created = await createScan(resultTarget.value)
    scan.value = await getScan(created.scan_id)
    stopPolling()
    pollTimer = setInterval(() => void refreshScan(), 500)
    await refreshScan()
  } catch (error) {
    scanMessage.value = error instanceof Error ? error.message : '无法创建扫描任务'
  }
}

async function requestCancel() {
  if (!scan.value) return
  try {
    scan.value = await cancelScan(scan.value.scan_id)
  } catch (error) {
    scanMessage.value = error instanceof Error ? error.message : '无法取消扫描'
  }
}

function formatBytes(value: number): string {
  return `${value.toLocaleString()} B`
}

function metricBytes(value: number | null | undefined): string {
  return value == null ? 'unavailable' : formatBytes(value)
}

function metricRate(value: number | null | undefined): string {
  return value == null ? 'unavailable' : `${value.toLocaleString()} files/sec`
}

onMounted(async () => {
  await checkService()
  try {
    sessionReady.value = await establishSession()
  } catch {
    sessionMessage.value = '开发扫描需要从 start.bat 打开本地页面。'
  }
})
onUnmounted(stopPolling)
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div class="brand-mark" aria-hidden="true">D</div>
      <div class="brand-name">DiskScope</div>
      <span class="topbar-version">V0.1</span>
    </header>

    <section class="workspace" aria-labelledby="page-title">
      <div class="intro">
        <p class="eyebrow">本地诊断工具</p>
        <h1 id="page-title">DiskScope</h1>
        <p class="subtitle">Windows 磁盘空间诊断工具</p>
      </div>

      <div class="status-panel">
        <div>
          <p class="panel-label">服务状态</p>
          <p class="status-line" role="status" aria-live="polite">
            <span class="status-dot" :class="serviceState" aria-hidden="true"></span>
            <span v-if="serviceState === 'online'">后端服务运行正常</span>
            <span v-else-if="serviceState === 'checking'">正在检查服务…</span>
            <span v-else>服务不可用</span>
          </p>
          <p v-if="serviceState === 'offline'" class="status-help">请确认本地服务已启动，然后重新检查。</p>
        </div>
        <button type="button" :disabled="serviceState === 'checking'" @click="checkService">
          重新检查服务
        </button>
      </div>

      <div class="details">
        <div class="detail-row"><span>Backend Version</span><strong>{{ health?.version ?? '—' }}</strong></div>
        <div class="detail-row"><span>Frontend Version</span><strong>{{ frontendVersion }}</strong></div>
        <div class="detail-row"><span>运行模式</span><strong>V0.1 · 只读诊断模式</strong></div>
        <div class="detail-row"><span>当前阶段</span><strong>M1.6 Low-Impact Scan 安全门</strong></div>
      </div>

      <section class="scan-panel" aria-labelledby="scan-title">
        <div class="scan-heading">
          <div>
            <p class="eyebrow">仅限固定白名单目录</p>
            <h2 id="scan-title">开发扫描测试</h2>
          </div>
          <span class="fixture-badge">{{ selectedTarget === 'project' ? 'Project Workspace' : 'Fixture Sample' }}</span>
        </div>
        <p class="scan-explanation">只读取文件系统元数据；后端仅接受 fixture 或固定项目根目录。</p>
        <div class="low-impact-note">
          <strong>Low-Impact Scan</strong>
          <span>Metadata only · Concurrency: 1 · Reparse points: not followed · Cross-volume: disabled · Whole-volume scan: blocked</span>
        </div>
        <p v-if="selectedTarget === 'project'" class="scan-warning">真实目录只读测试模式<br><strong>{{ PROJECT_WORKSPACE_PATH }}</strong></p>
        <div class="scan-controls">
          <label for="fixture-select">扫描目标</label>
          <select id="fixture-select" v-model="selectedTarget" :disabled="!!scan && ['queued', 'running', 'cancelling'].includes(scan.state)">
            <option value="fixture">Fixture Sample</option>
            <option value="project">Project Workspace</option>
          </select>
          <button
            type="button"
            :disabled="!sessionReady || serviceState !== 'online' || !!scan && ['queued', 'running', 'cancelling'].includes(scan.state)"
            @click="startTestScan"
          >开始测试扫描</button>
          <button
            v-if="scan && ['queued', 'running', 'cancelling'].includes(scan.state)"
            type="button"
            :disabled="scan.state === 'cancelling'"
            @click="requestCancel"
          >取消扫描</button>
        </div>
        <p v-if="sessionMessage" class="scan-note">{{ sessionMessage }}</p>
        <p v-if="scanMessage" class="scan-error" role="alert">{{ scanMessage }}</p>

        <div v-if="scan" class="scan-progress" aria-live="polite">
          <div><span>状态</span><strong>{{ scan.state }}</strong></div>
          <div><span>文件数</span><strong>{{ scan.files_seen.toLocaleString() }}</strong></div>
          <div><span>目录数</span><strong>{{ scan.dirs_seen.toLocaleString() }}</strong></div>
          <div><span>逻辑大小</span><strong>{{ formatBytes(scan.logical_bytes) }}</strong></div>
          <div><span>错误数</span><strong>{{ scan.errors_count }}</strong></div>
          <div><span>跳过数</span><strong>{{ scan.skipped_count }}</strong></div>
        </div>
        <div v-if="scan && Object.keys(scan.errors).length" class="scan-summary">
          <strong>错误摘要</strong>
          <span v-for="(entry, code) in scan.errors" :key="code">{{ code }}: {{ entry.count }}</span>
        </div>
        <div v-if="scan && Object.keys(scan.exclusions).length" class="scan-summary">
          <strong>实际排除</strong>
          <span v-for="(entry, rule) in scan.exclusions" :key="rule">{{ rule }}: {{ entry.count }}</span>
        </div>

        <template v-if="scan && ['completed', 'cancelled'].includes(scan.state)">
          <p class="scan-note">耗时 {{ (scan.elapsed_ms / 1000).toFixed(2) }} 秒 · 文件 {{ scan.files_seen }} · 目录 {{ scan.dirs_seen }} · 总逻辑大小 {{ formatBytes(scan.logical_bytes) }}</p>
          <div class="scan-metrics">
            <strong>开发资源指标（进程范围）</strong>
            <span>Duration: {{ scan.metrics ? (scan.metrics.duration_ms / 1000).toFixed(2) + ' s' : 'unavailable' }}</span>
            <span>Rate: {{ metricRate(scan.metrics?.files_per_second) }}</span>
            <span>Read bytes: {{ metricBytes(scan.metrics?.delta_read_bytes) }}</span>
            <span>Write bytes: {{ metricBytes(scan.metrics?.delta_write_bytes) }}</span>
            <span>RSS observed peak: {{ metricBytes(scan.metrics?.rss_peak_observed_bytes) }}</span>
          </div>
          <div class="result-grid">
            <div>
              <h3>Top {{ resultTarget === 'project' ? 20 : 10 }} 文件</h3>
              <ol class="result-list">
                <li v-for="file in topFiles" :key="file.relative_path">
                  <span>{{ file.relative_path }}</span><strong>{{ formatBytes(file.size_bytes) }}</strong>
                </li>
              </ol>
            </div>
            <div>
              <h3>根目录一级子目录</h3>
              <ul class="result-list">
                <li v-for="directory in rootDirectories" :key="directory.relative_path">
                  <span>{{ directory.relative_path }}</span><strong>{{ formatBytes(directory.subtree_bytes) }}</strong>
                </li>
              </ul>
            </div>
          </div>
        </template>
        <p v-if="scan?.state === 'failed'" class="scan-error">{{ scan.error_message }}</p>
      </section>
    </section>
  </main>
</template>
