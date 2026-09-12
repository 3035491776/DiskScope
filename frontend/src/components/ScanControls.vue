<script setup lang="ts">
import { useScanStore } from '../stores/scan'
import { isActive } from '../utils/presentation'

const store = useScanStore()
</script>

<template>
  <div class="scan-controls">
    <label for="scan-target">扫描范围</label>
    <select id="scan-target" v-model="store.selectedTarget" :disabled="isActive(store.scan)">
      <option value="fixture">Fixture Sample</option>
      <option value="project">Project Workspace</option>
    </select>
    <button v-if="!isActive(store.scan)" class="primary-button" type="button" :disabled="!store.sessionReady || store.serviceState !== 'online'" @click="store.startScan">开始扫描</button>
    <button v-else class="danger-button" type="button" :disabled="store.scan?.state === 'cancelling'" @click="store.requestCancel">取消扫描</button>
    <span class="control-hint">真实目录只读测试模式 · 整卷扫描未开放</span>
  </div>
  <p v-if="store.message" class="inline-error" role="alert">{{ store.message }}</p>
</template>
