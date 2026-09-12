export interface HealthResponse {
  status: 'ok'
  app: 'DiskScope'
  version: string
  mode: 'read_only'
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch('/health', {
    method: 'GET',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw new Error(`服务返回 ${response.status}`)
  }

  const payload: unknown = await response.json()
  if (
    typeof payload !== 'object' || payload === null ||
    !('status' in payload) || payload.status !== 'ok' ||
    !('app' in payload) || payload.app !== 'DiskScope' ||
    !('version' in payload) || typeof payload.version !== 'string' ||
    !('mode' in payload) || payload.mode !== 'read_only'
  ) {
    throw new Error('服务响应格式不正确')
  }

  return payload as HealthResponse
}

export interface ScanStatus {
  scan_id: string
  root: string
  state: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed'
  phase: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number
  files_seen: number
  dirs_seen: number
  logical_bytes: number
  skipped_count: number
  errors_count: number
  errors: Record<string, { count: number; samples: string[] }>
  exclusions: Record<string, { count: number; samples: string[] }>
  cancel_requested: boolean
  error_code: string | null
  error_message: string | null
}

export interface FileItem {
  name: string
  relative_path: string
  parent: string
  size_bytes: number
  mtime: string
  attributes: number | null
}

export interface DirectoryItem {
  relative_path: string
  parent: string | null
  direct_bytes: number
  subtree_bytes: number
  direct_file_count: number
  file_count: number
  children_count: number
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...init,
  })
  if (!response.ok) {
    throw new Error(`服务返回 ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function establishSession(): Promise<boolean> {
  const fragment = new URLSearchParams(window.location.hash.slice(1))
  const launchToken = fragment.get('bootstrap')
  if (launchToken) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    const response = await fetch('/api/v1/session/bootstrap', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: launchToken }),
    })
    if (!response.ok) {
      throw new Error(`会话初始化失败：${response.status}`)
    }
    return true
  }
  const state = await apiJson<{ ready: boolean }>('/api/v1/session')
  return state.ready
}

export type ScanTarget = 'fixture' | 'project'
export const PROJECT_WORKSPACE_PATH = 'D:\\Artilius\\Codex\\Windows-C-clear'

export function createScan(target: ScanTarget = 'fixture'): Promise<{ scan_id: string; state: string }> {
  return apiJson('/api/v1/scans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      root: target === 'project' ? PROJECT_WORKSPACE_PATH : 'tests/fixtures/sample_disk',
    }),
  })
}

export function getScan(scanId: string): Promise<ScanStatus> {
  return apiJson(`/api/v1/scans/${encodeURIComponent(scanId)}`)
}

export function cancelScan(scanId: string): Promise<ScanStatus> {
  return apiJson(`/api/v1/scans/${encodeURIComponent(scanId)}/cancel`, { method: 'POST' })
}

export async function getTopFiles(scanId: string, limit = 10): Promise<FileItem[]> {
  const result = await apiJson<{ items: FileItem[] }>(
    `/api/v1/scans/${encodeURIComponent(scanId)}/top?kind=file&limit=${limit}`,
  )
  return result.items
}

export async function getRootDirectories(scanId: string): Promise<DirectoryItem[]> {
  const result = await apiJson<{ items: DirectoryItem[] }>(
    `/api/v1/scans/${encodeURIComponent(scanId)}/directories`,
  )
  return result.items
}
