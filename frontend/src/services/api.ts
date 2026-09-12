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

