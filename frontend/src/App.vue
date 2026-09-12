<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getHealth } from './services/api'
import type { HealthResponse } from './services/api'
import packageInfo from '../package.json'

type ServiceState = 'checking' | 'online' | 'offline'

const serviceState = ref<ServiceState>('checking')
const health = ref<HealthResponse | null>(null)
const frontendVersion = packageInfo.version

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

onMounted(checkService)
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
        <div class="detail-row"><span>当前阶段</span><strong>M0 可运行骨架</strong></div>
      </div>
    </section>
  </main>
</template>

