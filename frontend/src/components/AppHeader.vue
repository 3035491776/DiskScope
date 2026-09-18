<script setup lang="ts">
import { computed } from 'vue'
import { useScanStore } from '../stores/scan'
import { targetName } from '../utils/presentation'

const store = useScanStore()
const scope = computed(() => {
  if (store.resultLoading) return '正在恢复…'
  if (!store.result || store.result.source_type === 'none') return '尚无扫描结果'
  return targetName(store.resultTarget)
})
</script>

<template>
  <header class="app-header">
    <div class="header-scope"><span class="header-label">正在查看</span><strong>{{ scope }}</strong><span class="header-separator">/</span><span>DiskScope 只会扫描你主动选择的位置</span></div>
    <div class="header-state" role="status" aria-live="polite">
      <span class="state-dot" :class="store.serviceState"></span>
      <span v-if="store.serviceState === 'online'">服务运行正常</span>
      <span v-else-if="store.serviceState === 'checking'">正在连接服务</span>
      <span v-else>服务不可用</span>
      <button class="text-button" type="button" :disabled="store.serviceState === 'checking'" @click="store.reconnect">重新检查</button>
    </div>
  </header>
</template>
