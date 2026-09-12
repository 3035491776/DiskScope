<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import {
  cancelScan,
  createScan,
  establishSession,
  getHealth,
  getRootDirectories,
  getScan,
  getTopFiles,
} from './services/api'
import type { DirectoryItem, FileItem, HealthResponse, ScanStatus } from './services/api'
import packageInfo from '../package.json'

type ServiceState = 'checking' | 'online' | 'offline'

const serviceState = ref<ServiceState>('checking')
const health = ref<HealthResponse | null>(null)
const frontendVersion = packageInfo.version
const sessionReady = ref(false)
const sessionMessage = ref('')
const scan = ref<ScanStatus | null>(null)
const scanMessage = ref('')
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
          getTopFiles(latest.scan_id),
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
    const created = await createScan()
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
        <div class="detail-row"><span>当前阶段</span><strong>M1 只读扫描器测试</strong></div>
      </div>

      <section class="scan-panel" aria-labelledby="scan-title">
        <div class="scan-heading">
          <div>
            <p class="eyebrow">仅限受控测试目录</p>
            <h2 id="scan-title">开发扫描测试</h2>
          </div>
          <span class="fixture-badge">sample_disk</span>
        </div>
        <p class="scan-explanation">本页只扫描项目内的 tests/fixtures/sample_disk，读取文件系统元数据。</p>
        <div class="scan-controls">
          <label for="fixture-select">测试样本</label>
          <select id="fixture-select" value="sample_disk" disabled>
            <option value="sample_disk">sample_disk</option>
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
        </div>

        <template v-if="scan && ['completed', 'cancelled'].includes(scan.state)">
          <p class="scan-note">耗时 {{ (scan.elapsed_ms / 1000).toFixed(2) }} 秒 · 文件 {{ scan.files_seen }} · 目录 {{ scan.dirs_seen }} · 总逻辑大小 {{ formatBytes(scan.logical_bytes) }}</p>
          <div class="result-grid">
            <div>
              <h3>Top 10 文件</h3>
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
