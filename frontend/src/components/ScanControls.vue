<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import BaseDialog from './BaseDialog.vue'
import { useScanStore } from '../stores/scan'
import { formatSeconds } from '../utils/format'
import { isActive, targetName } from '../utils/presentation'

const store = useScanStore()
const router = useRouter()
const confirmCDrive = ref(false)
const devTarget = ref<'fixture' | 'project'>('fixture')
const isDevTarget = computed(() => store.selectedTarget === 'fixture' || store.selectedTarget === 'project')
const lastCDuration = computed(() => (
  store.resultTarget === 'c_drive' && store.result?.summary
    ? formatSeconds(store.result.summary.duration_seconds * 1000)
    : ''
))

function openCDriveDialog() {
  store.selectedTarget = 'c_drive'
  confirmCDrive.value = true
}

async function startSelected() {
  if (store.selectedTarget === 'c_drive') {
    openCDriveDialog()
    return
  }
  await store.startScan()
}

async function startDeveloperScan() {
  store.selectedTarget = devTarget.value
  await store.startScan(devTarget.value)
}

async function beginCDriveAnalysis() {
  if (store.starting || isActive(store.scan)) return
  const started = await store.startScan('c_drive')
  if (started) {
    confirmCDrive.value = false
    await router.push('/status')
  }
}

defineExpose({ openCDriveDialog })
</script>

<template>
  <div class="scan-controls">
    <label for="scan-target">扫描位置</label>
    <select id="scan-target" v-model="store.selectedTarget" :disabled="isActive(store.scan)">
      <option value="user_temp">临时文件</option>
      <option value="c_drive">Windows C 盘</option>
      <option v-if="isDevTarget" :value="store.selectedTarget">{{ targetName(store.selectedTarget) }}</option>
    </select>
    <button v-if="!isActive(store.scan)" class="primary-button" type="button" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting" @click="startSelected">
      {{ store.selectedTarget === 'c_drive' ? '扫描 C 盘' : '扫描临时文件' }}
    </button>
    <button v-else class="danger-button" type="button" :disabled="store.scan?.state === 'cancelling'" @click="store.requestCancel">取消扫描</button>
    <span class="control-hint">{{ store.selectedTarget === 'c_drive' ? '完整扫描可能需要较长时间，你可以随时取消' : store.selectedTarget === 'user_temp' ? '扫描当前 Windows 用户的临时文件夹；不会删除文件' : '已选择开发与测试范围' }}</span>
  </div>

  <details v-if="store.developerMode" class="developer-scan-tools">
    <summary>开发与测试范围</summary>
    <div class="scan-controls">
      <label for="developer-scan-target">测试范围</label>
      <select id="developer-scan-target" v-model="devTarget" :disabled="isActive(store.scan)">
        <option value="fixture">Fixture Sample</option>
        <option value="project">Project Workspace</option>
      </select>
      <button type="button" class="text-button" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting || isActive(store.scan)" @click="startDeveloperScan">开始测试扫描</button>
    </div>
  </details>
  <p v-if="store.message" class="inline-error" role="alert">{{ store.message }}</p>

  <BaseDialog :open="confirmCDrive" title-id="c-drive-confirm-title" description-id="c-drive-confirm-description" @close="confirmCDrive = false">
    <p class="eyebrow">安全扫描</p>
    <h2 id="c-drive-confirm-title">扫描 C 盘</h2>
    <p id="c-drive-confirm-description">DiskScope 只读取文件和文件夹的基本信息，不会修改或删除文件。</p>
    <p>完整扫描可能需要较长时间，具体取决于文件数量和磁盘状态。你可以随时取消。</p>
    <details class="technical-details"><summary>技术详情</summary><p>扫描不会读取文件正文、修改权限或跨磁盘，也不会跟随系统链接或重定向位置。</p></details>
    <p v-if="lastCDuration" class="inline-note">上次扫描耗时：{{ lastCDuration }}</p>
    <div class="confirm-actions">
      <button type="button" class="text-button" :disabled="store.starting" @click="confirmCDrive = false">取消</button>
      <button type="button" class="primary-button" data-dialog-initial :disabled="store.starting || isActive(store.scan)" @click="beginCDriveAnalysis">{{ store.starting ? '正在启动…' : '开始扫描' }}</button>
    </div>
    <p v-if="store.message" class="inline-error" role="alert">{{ store.message }}</p>
  </BaseDialog>
</template>
