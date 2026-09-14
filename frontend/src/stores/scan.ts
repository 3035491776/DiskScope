import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  cancelScan, createScan, establishSession, getCurrentScan, getHealth, getScan, getVolumes,
} from '../services/api'
import type { HealthResponse, ScanStatus, ScanTarget, VolumeItem } from '../services/api'
import { isActive } from '../utils/presentation'

type ServiceState = 'checking' | 'online' | 'offline'

export const useScanStore = defineStore('scan', () => {
  const serviceState = ref<ServiceState>('checking')
  const health = ref<HealthResponse | null>(null)
  const sessionReady = ref(false)
  const selectedTarget = ref<ScanTarget>('fixture')
  const resultTarget = ref<ScanTarget>('fixture')
  const scan = ref<ScanStatus | null>(null)
  const recentCompleted = ref<ScanStatus | null>(null)
  const volumes = ref<VolumeItem[]>([])
  const volumesState = ref<'loading' | 'ready' | 'unavailable'>('loading')
  const message = ref('')
  const starting = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let refreshing = false

  function stopPolling() {
    if (timer) clearInterval(timer)
    timer = null
  }

  async function checkService() {
    serviceState.value = 'checking'
    try {
      health.value = await getHealth()
      serviceState.value = 'online'
    } catch {
      health.value = null
      serviceState.value = 'offline'
      volumesState.value = 'unavailable'
    }
  }

  async function loadVolumes() {
    volumesState.value = 'loading'
    try {
      volumes.value = await getVolumes()
      volumesState.value = 'ready'
    } catch {
      volumes.value = []
      volumesState.value = 'unavailable'
    }
  }

  async function reconnect() {
    await checkService()
    if (serviceState.value !== 'online') {
      sessionReady.value = false
      return
    }
    try {
      sessionReady.value = await establishSession()
      if (sessionReady.value) {
        await loadVolumes()
        await restoreCurrentScan()
      }
      else message.value = '请从 start.bat 打开本地页面，以启用扫描。'
    } catch {
      sessionReady.value = false
      message.value = '本地会话不可用，请从 start.bat 重新打开页面。'
    }
  }

  async function initialize() {
    await reconnect()
  }

  async function restoreCurrentScan() {
    try {
      const latest = await getCurrentScan()
      if (!latest) return
      scan.value = latest
      const target: ScanTarget = latest.scope_key === 'system_drive_c' ? 'c_drive'
        : latest.scope_key === 'project_workspace' ? 'project' : 'fixture'
      resultTarget.value = target
      selectedTarget.value = target
      if (isActive(latest) || latest.snapshot_status === 'pending') {
        stopPolling()
        timer = setInterval(() => void refreshScan(), 400)
      } else if (latest.state === 'completed') {
        recentCompleted.value = latest
      }
    } catch {
      // Older local service or transient status failure leaves existing pages usable.
    }
  }

  async function refreshScan() {
    if (!scan.value || refreshing) return
    refreshing = true
    try {
      const latest = await getScan(scan.value.scan_id)
      scan.value = latest
      if (!isActive(latest) && !(latest.state === 'completed' && latest.snapshot_status === 'pending')) {
        stopPolling()
        if (latest.state === 'completed') recentCompleted.value = latest
      }
    } catch (error) {
      message.value = error instanceof Error ? error.message : '无法获取扫描状态'
      stopPolling()
      await checkService()
    } finally {
      refreshing = false
    }
  }

  async function startScan(targetOverride?: ScanTarget) {
    if (!sessionReady.value || serviceState.value !== 'online' || isActive(scan.value) || starting.value) return false
    starting.value = true
    message.value = ''
    try {
      const target = targetOverride ?? selectedTarget.value
      const created = await createScan(target)
      selectedTarget.value = target
      resultTarget.value = target
      scan.value = await getScan(created.scan_id)
      stopPolling()
      timer = setInterval(() => void refreshScan(), 400)
      await refreshScan()
      return true
    } catch (error) {
      message.value = error instanceof Error ? error.message : '无法开始扫描'
      return false
    } finally {
      starting.value = false
    }
  }

  async function requestCancel() {
    if (!scan.value || !isActive(scan.value)) return
    try {
      scan.value = await cancelScan(scan.value.scan_id)
    } catch (error) {
      message.value = error instanceof Error ? error.message : '无法取消扫描'
    }
  }

  return {
    serviceState, health, sessionReady, selectedTarget, resultTarget, scan,
    recentCompleted, volumes, volumesState, message, starting, checkService,
    initialize, reconnect, loadVolumes, startScan, requestCancel, refreshScan,
  }
})
