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
      <option value="user_temp">当前用户临时文件</option>
      <option v-if="store.selectedTarget === 'c_drive'" value="c_drive" disabled>Windows C:（从总览卡片启动）</option>
    </select>
    <button v-if="!isActive(store.scan) && store.selectedTarget !== 'c_drive'" class="primary-button" type="button" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting" @click="store.startScan()">开始扫描</button>
    <button v-if="isActive(store.scan)" class="danger-button" type="button" :disabled="store.scan?.state === 'cancelling'" @click="store.requestCancel">取消扫描</button>
    <span class="control-hint">{{ store.selectedTarget === 'c_drive' ? 'C 盘需从总览卡片显式确认' : store.selectedTarget === 'user_temp' ? '只读取当前用户 Temp 的文件元数据；扫描不会删除文件' : '固定范围只读测试模式' }}</span>
  </div>
  <p v-if="store.message" class="inline-error" role="alert">{{ store.message }}</p>
</template>
