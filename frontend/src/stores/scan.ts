import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  cancelScan, createScan, establishSession, getCurrentScan, getHealth, getLatestResult, getScan, getVolumes,
} from '../services/api'
import type { HealthResponse, ResolvedResult, ScanStatus, ScanTarget, VolumeItem } from '../services/api'
import { isActive } from '../utils/presentation'

type ServiceState = 'checking' | 'online' | 'offline'

export const useScanStore = defineStore('scan', () => {
  const serviceState = ref<ServiceState>('checking')
  const health = ref<HealthResponse | null>(null)
  const sessionReady = ref(false)
  // selectedTarget is only the user's next scan choice. resultTarget is the
  // independently browsed/restored result source.
  const selectedTarget = ref<ScanTarget>('user_temp')
  const resultTarget = ref<ScanTarget>('user_temp')
  const historyTarget = ref<ScanTarget | null>(null)
  const scan = ref<ScanStatus | null>(null)
  const recentCompleted = ref<ScanStatus | null>(null)
  const result = ref<ResolvedResult | null>(null)
  const resultLoading = ref(false)
  const volumes = ref<VolumeItem[]>([])
  const volumesState = ref<'loading' | 'ready' | 'unavailable'>('loading')
  const message = ref('')
  const starting = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let refreshing = false
  let resultRequest = 0

  async function loadResult(target: ScanTarget = resultTarget.value) {
    const request = ++resultRequest
    resultTarget.value = target
    resultLoading.value = true
    result.value = null
    try {
      const resolved = await getLatestResult(target)
      if (request === resultRequest) result.value = resolved
    } catch {
      if (request === resultRequest) result.value = null
    } finally {
      if (request === resultRequest) resultLoading.value = false
    }
  }

  async function restoreResult() {
    const targets: ScanTarget[] = scan.value ? [resultTarget.value] : ['c_drive', 'user_temp', 'project', 'fixture']
    for (const target of targets) {
      await loadResult(target)
      if (!result.value || result.value.source_type !== 'none' || result.value.storage_status === 'unavailable') break
    }
    if (result.value?.source_type === 'none' && resultTarget.value !== 'user_temp') {
      await loadResult('user_temp')
    }
  }

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
        await restoreResult()
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
        : latest.scope_key === 'current_user_temp' ? 'user_temp'
          : latest.scope_key === 'project_workspace' ? 'project' : 'fixture'
      resultTarget.value = target
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
        if (latest.state === 'completed') await loadResult(resultTarget.value)
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
      await loadResult(target)
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
    serviceState, health, sessionReady, selectedTarget, resultTarget, historyTarget, scan,
    recentCompleted, result, resultLoading, volumes, volumesState, message, starting, checkService,
    initialize, reconnect, loadVolumes, loadResult, startScan, requestCancel, refreshScan,
  }
})
