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
    <label for="scan-target">扫描范围</label>
    <select id="scan-target" v-model="store.selectedTarget" :disabled="isActive(store.scan)">
      <option value="user_temp">当前用户临时文件</option>
      <option value="c_drive">Windows C:</option>
      <option v-if="isDevTarget" :value="store.selectedTarget">{{ targetName(store.selectedTarget) }}</option>
    </select>
    <button v-if="!isActive(store.scan)" class="primary-button" type="button" :disabled="!store.sessionReady || store.serviceState !== 'online' || store.starting" @click="startSelected">
      {{ store.selectedTarget === 'c_drive' ? '确认只读分析' : '开始扫描' }}
    </button>
    <button v-else class="danger-button" type="button" :disabled="store.scan?.state === 'cancelling'" @click="store.requestCancel">取消扫描</button>
    <span class="control-hint">{{ store.selectedTarget === 'c_drive' ? '完整系统盘扫描可能需要较长时间，开始前会再次确认' : store.selectedTarget === 'user_temp' ? '只读取当前用户 Temp 的文件元数据；扫描不会删除文件' : '已选择开发与测试范围' }}</span>
  </div>

  <details class="developer-scan-tools">
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
    <p class="eyebrow">C DRIVE / READ ONLY</p>
    <h2 id="c-drive-confirm-title">分析 Windows C盘</h2>
    <p id="c-drive-confirm-description">DiskScope 将只读取文件系统元数据，统计目录和文件的逻辑大小。不会读取文件正文、删除或修改文件、修改权限、跨磁盘扫描，也不会跟随 junction 或 symlink。</p>
    <p>完整系统盘扫描耗时取决于文件数量、磁盘性能和权限情况，较大的系统盘可能需要较长时间。扫描期间可以继续查看状态，也可以随时取消。</p>
    <p v-if="lastCDuration" class="inline-note">上次扫描耗时：{{ lastCDuration }}</p>
    <div class="confirm-actions">
      <button type="button" class="text-button" :disabled="store.starting" @click="confirmCDrive = false">取消</button>
      <button type="button" class="primary-button" data-dialog-initial :disabled="store.starting || isActive(store.scan)" @click="beginCDriveAnalysis">{{ store.starting ? '正在启动…' : '开始只读分析' }}</button>
    </div>
    <p v-if="store.message" class="inline-error" role="alert">{{ store.message }}</p>
  </BaseDialog>
</template>
