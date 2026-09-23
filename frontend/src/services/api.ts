export interface HealthResponse {
  status: 'ok'
  app: 'DiskScope'
  version: string
  mode: 'guarded_cleanup'
  developer_mode: boolean
  capabilities: {
    scan: 'read_only'
    cleanup: 'guarded_recycle'
    cleanup_scope: 'bounded_candidate_batch_and_manual_review'
    cleanup_batch_limit: number
  }
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
    !('mode' in payload) || payload.mode !== 'guarded_cleanup' ||
    !('developer_mode' in payload) || typeof payload.developer_mode !== 'boolean' ||
    !('capabilities' in payload) || typeof payload.capabilities !== 'object' || payload.capabilities === null ||
    !('scan' in payload.capabilities) || payload.capabilities.scan !== 'read_only' ||
    !('cleanup' in payload.capabilities) || payload.capabilities.cleanup !== 'guarded_recycle' ||
    !('cleanup_scope' in payload.capabilities) ||
      payload.capabilities.cleanup_scope !== 'bounded_candidate_batch_and_manual_review' ||
    !('cleanup_batch_limit' in payload.capabilities) || payload.capabilities.cleanup_batch_limit !== 200
  ) {
    throw new Error('服务响应格式不正确')
  }

  return payload as HealthResponse
}

export interface ScanStatus {
  scan_id: string
  root: string
  scope_key: string
  scope_label: string
  policy_mode: 'standard' | 'c_drive_safe_readonly'
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
  metadata_warning_count: number
  coverage: 'complete' | 'limited'
  coverage_summary: {
    access_denied_count: number
    reparse_skipped_count: number
    file_not_found_count: number
    path_too_long_count: number
    other_io_error_count: number
    invalid_file_metadata_count: number
  }
  errors: Record<string, { count: number; samples: string[] }>
  exclusions: Record<string, { count: number; samples: string[] }>
  metrics: ScanMetrics | null
  cancel_requested: boolean
  error_code: string | null
  error_message: string | null
  snapshot_status: 'not_applicable' | 'pending' | 'saved' | 'failed'
  snapshot_id: string | null
  snapshot_error_code: string | null
  file_persistence_mode: 'top_k' | 'bounded_scope' | null
  file_persistence_limit: number | null
  persisted_file_count: number
  observed_file_count: number
  file_metadata_coverage: 'complete' | 'limited' | null
}

export interface SnapshotSummary {
  snapshot_id: string
  scope_key: string
  scope_label: string
  completed_at: string
  total_bytes: number
  file_count: number
  directory_count: number
  error_count: number
  skipped_count: number
  coverage: 'complete' | 'limited'
  file_persistence_mode: 'top_k' | 'bounded_scope'
  file_persistence_limit: number
  persisted_file_count: number
  observed_file_count: number
}

export interface DirectoryChange {
  relative_path: string
  name: string
  base_bytes: number
  target_bytes: number
  delta_bytes: number
  delta_ratio: number | null
  change_type: 'added' | 'removed' | 'grown' | 'shrunk' | 'unchanged'
}

export interface LargeFileChange {
  relative_path: string
  name: string
  base_bytes: number
  target_bytes: number
  delta_bytes: number
  change_type: string
}

export interface SnapshotComparison {
  base_snapshot: SnapshotSummary
  target_snapshot: SnapshotSummary
  total_bytes_delta: number
  total_bytes_delta_ratio: number | null
  file_count_delta: number
  directory_count_delta: number
  comparison_coverage_limited: boolean
  growth_by_bytes: DirectoryChange[]
  growth_by_ratio: DirectoryChange[]
  directory_changes: DirectoryChange[]
  directory_change_counts: Record<string, number>
  new_large_files: LargeFileChange[]
  removed_large_files: LargeFileChange[]
  grown_large_files: LargeFileChange[]
  shrunk_large_files: LargeFileChange[]
}

export interface ScanMetrics {
  duration_ms: number
  files_per_second: number
  rss_current_bytes: number | null
  rss_peak_observed_bytes: number | null
  cpu_seconds: number | null
  process_read_bytes_before: number | null
  process_read_bytes_after: number | null
  delta_read_bytes: number | null
  process_write_bytes_before: number | null
  process_write_bytes_after: number | null
  delta_write_bytes: number | null
  delta_read_operations: number | null
  delta_write_operations: number | null
}

export interface FileItem {
  name: string
  relative_path: string
  parent: string
  size_bytes: number
  mtime: string
  attributes: number | null
  system_category?: string
  risk_class?: string
  category_label?: string
}

export interface DirectoryItem {
  node_id: string
  name: string
  relative_path: string
  parent: string | null
  direct_bytes: number
  subtree_bytes: number
  direct_file_count: number | null
  file_count: number
  children_count: number
  coverage: 'complete' | 'limited'
  system_category?: string
  risk_class?: string
  category_label?: string
}

export interface VolumeItem {
  drive: string
  total_bytes: number
  used_bytes: number
  free_bytes: number
  scan_allowed: boolean
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...init,
  })
  if (!response.ok) {
    let detail = `服务返回 ${response.status}`
    try {
      const payload = await response.json() as { detail?: unknown }
      if (typeof payload.detail === 'string') detail = payload.detail
    } catch { /* Keep the HTTP status when the body is not JSON. */ }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export async function establishSession(): Promise<boolean> {
  const fragment = new URLSearchParams(window.location.hash.slice(1))
  const launchToken = fragment.get('bootstrap')
  if (launchToken) {
    const cleanUrl = window.location.pathname + window.location.search
    window.history.replaceState(window.history.state, '', cleanUrl)
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
    // Vue Router may finish its initial navigation while the exchange is in
    // flight. Clean the fragment again after success without changing route.
    window.history.replaceState(window.history.state, '', cleanUrl)
    return true
  }
  const state = await apiJson<{ ready: boolean }>('/api/v1/session')
  return state.ready
}

export type ScanTarget = 'fixture' | 'project' | 'c_drive' | 'user_temp'
export function createScan(target: ScanTarget = 'fixture'): Promise<{ scan_id: string; state: string }> {
  return apiJson('/api/v1/scans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(target === 'c_drive' || target === 'user_temp'
      ? { scope_key: target === 'c_drive' ? 'system_drive_c' : 'current_user_temp', confirmed_readonly: target === 'c_drive' }
      : { scope_key: target === 'project' ? 'project_workspace' : 'fixture_sample' }),
  })
}

export function getScan(scanId: string): Promise<ScanStatus> {
  return apiJson(`/api/v1/scans/${encodeURIComponent(scanId)}`)
}

export async function getCurrentScan(): Promise<ScanStatus | null> {
  const result = await apiJson<{ scan: ScanStatus | null }>('/api/v1/scans/current')
  return result.scan
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

export async function getDirectories(scanId: string, parentId = ''): Promise<DirectoryItem[]> {
  const result = await apiJson<{ items: DirectoryItem[] }>(
    `/api/v1/scans/${encodeURIComponent(scanId)}/directories?parent_id=${encodeURIComponent(parentId)}`,
  )
  return result.items
}

export async function getTopDirectories(scanId: string, limit = 100): Promise<DirectoryItem[]> {
  const result = await apiJson<{ items: DirectoryItem[] }>(
    `/api/v1/scans/${encodeURIComponent(scanId)}/top?kind=directory&limit=${limit}`,
  )
  return result.items
}

export type ResultSourceType = 'live' | 'snapshot' | 'none'

export interface ResolvedResult {
  scope_key: string
  source_type: ResultSourceType
  result_id: string | null
  snapshot_id: string | null
  completed_at: string | null
  coverage: 'complete' | 'limited' | null
  storage_status: 'ready' | 'unavailable'
  summary: {
    total_bytes: number
    file_count: number
    directory_count: number
    duration_seconds: number
    error_count: number
    skipped_count: number
    metadata_warning_count: number | null
    file_persistence_mode: 'top_k' | 'bounded_scope'
    file_persistence_limit: number
    persisted_file_count: number
    observed_file_count: number
    file_metadata_coverage: 'complete' | 'limited'
  } | null
}

export const scopeForTarget: Record<ScanTarget, string> = {
  fixture: 'fixture_sample', project: 'project_workspace', c_drive: 'system_drive_c', user_temp: 'current_user_temp',
}

export function getLatestResult(target: ScanTarget): Promise<ResolvedResult> {
  return apiJson(`/api/v1/results/latest?scope_key=${scopeForTarget[target]}`)
}

function resultUrl(result: ResolvedResult, suffix: string): string {
  if (!result.result_id || result.source_type === 'none') throw new Error('暂无已保存扫描结果')
  return `/api/v1/results/${result.source_type}/${encodeURIComponent(result.result_id)}/${suffix}`
}

export async function getResultDirectories(result: ResolvedResult, parentId = ''): Promise<DirectoryItem[]> {
  const query = new URLSearchParams({ scope_key: result.scope_key, parent_id: parentId })
  const payload = await apiJson<{ items: DirectoryItem[] }>(resultUrl(result, `directories?${query}`))
  return payload.items
}

export async function getResultTop(result: ResolvedResult, kind: 'file', limit?: number): Promise<FileItem[]>
export async function getResultTop(result: ResolvedResult, kind: 'directory', limit?: number): Promise<DirectoryItem[]>
export async function getResultTop(result: ResolvedResult, kind: 'file' | 'directory', limit = 100): Promise<FileItem[] | DirectoryItem[]> {
  const query = new URLSearchParams({ scope_key: result.scope_key, kind, limit: String(limit) })
  const payload = await apiJson<{ items: FileItem[] | DirectoryItem[] }>(resultUrl(result, `top?${query}`))
  return payload.items
}

export async function getVolumes(): Promise<VolumeItem[]> {
  const result = await apiJson<{ items: VolumeItem[] }>('/api/v1/volumes')
  return result.items
}

export async function getSnapshots(scopeKey: string): Promise<SnapshotSummary[]> {
  const response = await apiJson<{ items: SnapshotSummary[] }>(
    `/api/v1/snapshots?scope_key=${encodeURIComponent(scopeKey)}&limit=20`,
  )
  return response.items
}

export function compareSnapshots(base: string, target: string): Promise<SnapshotComparison> {
  return apiJson(`/api/v1/compare?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`)
}

export interface CleanupCandidate {
  candidate_id: string
  relative_path: string
  display_path: string
  object_type: 'file' | 'directory' | 'group'
  logical_bytes: number
  category: string
  risk_level: 'protected' | 'high' | 'review' | 'low'
  confidence: 'high' | 'medium' | 'low'
  reason_code: string
  title: string
  summary: string
  explanation: string
  evidence: string[]
  recommended_action: string
  requires_manual_review: boolean
  source_rule_id: string
  rule_version: string
  group_id: string | null
  snapshot_mtime?: string | null
  execution_state?: 'available' | 'recycled'
  execution_hint?: 'prepare_available' | 'suggestion_only' | 'history_only'
  execution_policy?: {
    eligibility: 'ineligible' | 'eligible_for_recycle'
    allowed_actions: string[]
    block_reasons: string[]
    policy_rule_id: 'USER_TEMP_STALE_FILE_V1'
    required_checks: string[]
    real_execution_enabled: boolean
  }
}

export type CleanupClassification = 'SAFE_ACTIONABLE' | 'REVIEW_REQUIRED' | 'DO_NOT_TOUCH'

export interface CleanupCenterItem {
  candidate_id: string
  display_path: string
  relative_path: string
  object_type: 'file' | 'directory' | 'group'
  logical_bytes: number
  snapshot_mtime: string | null
  title: string
  category: string
  risk_level: string
  confidence: string
  reason_code: string
  source_rule_id: string
  execution_state: 'available' | 'recycled'
  classification: CleanupClassification
  reason: string
  reason_codes: string[]
  authorization_policy: string | null
}

export interface CleanupCenterListing {
  scope_key: 'system_drive_c' | 'current_user_temp'
  run: {
    id: string
    snapshot_id: string
    created_at: string
    scan_completed_at: string
    coverage: 'complete' | 'limited'
  }
  summary: Record<CleanupClassification, { count: number; bytes: number }>
  items: Record<CleanupClassification, CleanupCenterItem[]>
  per_class_limit: number
  truncated: Record<CleanupClassification, boolean>
}

export interface TriageFilters {
  locations?: string[]
  categories?: string[]
  extensions?: string[]
  minSize?: number
  maxSize?: number
  olderThanDays?: number
  classifications?: CleanupClassification[]
  search?: string
  sort?: 'size_desc' | 'mtime_asc' | 'name_asc' | 'path_asc'
  limit?: 25 | 50 | 100
  offset?: number
}

export interface TriageItem {
  item_id: string
  candidate_id: string
  relative_path: string
  display_path: string
  name: string
  extension: string
  size_bytes: number
  logical_bytes: number
  mtime: string | null
  snapshot_mtime: string | null
  age_days: number | null
  category: string
  category_label: string
  location_group: string
  classification: CleanupClassification
  execution_state: 'available' | 'recycled'
}

export interface TriageListing {
  scope_key: 'system_drive_c' | 'current_user_temp'
  snapshot_id: string
  index_available: boolean
  message?: string
  coverage: { observed_count: number; persisted_count: number; limit: number; status: 'complete' | 'limited' } | null
  summary: Record<CleanupClassification, { count: number; bytes: number }>
  matched_count: number
  matched_bytes: number
  items: TriageItem[]
  facets: Record<string, Array<{ value: string; count: number; bytes: number }>>
  smart_views: Array<{ key: string; label: string; count: number; bytes: number; filters: Record<string, string[] | number> }>
  limit: number
  offset: number
  explicit_filter: boolean
}

function triageParams(
  scopeKey: 'system_drive_c' | 'current_user_temp', filters: TriageFilters,
): URLSearchParams {
  const query = new URLSearchParams({ scope: scopeKey })
  for (const value of filters.locations ?? []) query.append('location', value)
  for (const value of filters.categories ?? []) query.append('category', value)
  for (const value of filters.extensions ?? []) query.append('extension', value)
  for (const value of filters.classifications ?? []) query.append('classification', value)
  if (filters.minSize !== undefined) query.set('min_size', String(filters.minSize))
  if (filters.maxSize !== undefined) query.set('max_size', String(filters.maxSize))
  if (filters.olderThanDays !== undefined) query.set('older_than_days', String(filters.olderThanDays))
  if (filters.search) query.set('search', filters.search)
  if (filters.sort) query.set('sort', filters.sort)
  if (filters.limit) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  return query
}

export function getTriageFiles(
  scopeKey: 'system_drive_c' | 'current_user_temp', filters: TriageFilters = {},
): Promise<TriageListing> {
  return apiJson(`/api/v1/cleanup/triage?${triageParams(scopeKey, filters)}`)
}

export function selectFilteredTriage(
  scopeKey: 'system_drive_c' | 'current_user_temp', filters: TriageFilters,
): Promise<{ item_ids: string[]; matched_count: number; matched_bytes: number }> {
  return apiJson(`/api/v1/cleanup/triage/selection?${triageParams(scopeKey, filters)}`)
}

export interface PreparedCleanupBatch {
  batch_id: string
  execution_token: string | null
  expires_at: string | null
  mode: 'safe' | 'review' | 'controlled_probe'
  scope_key: string
  requested_count: number
  approved_count: number
  skipped_count: number
  requested_bytes: number
  approved_bytes: number
  real_execution_enabled: boolean
  items: Array<{
    item_id: string
    candidate_id: string | null
    probe_id: string | null
    classification: string
    decision: 'approved' | 'skipped'
    reason: string | null
  }>
}

export interface CleanupBatchResult {
  batch_id: string
  status: 'completed' | 'completed_with_partial_result'
  mode: 'safe' | 'review' | 'controlled_probe'
  requested_count: number
  success_count: number
  skipped_count: number
  failed_count: number
  requested_bytes: number
  recycled_bytes: number
  target_mutation: 'recycle_bin' | 'none'
  items: Array<{
    item_id: string
    candidate_id: string | null
    probe_id: string | null
    result: 'recycled' | 'skipped' | 'failed'
    reason: string | null
    recycled_bytes: number
  }>
}

export interface CleanupBatchAudit {
  batch: Record<string, string | number | null>
  items: Array<Record<string, string | number | null>>
}

export function getCleanupClassifications(
  scopeKey: 'system_drive_c' | 'current_user_temp',
): Promise<CleanupCenterListing> {
  return apiJson(`/api/v1/cleanup/classifications?scope=${encodeURIComponent(scopeKey)}`)
}

export function prepareCleanupBatch(
  itemIds: string[], mode: 'safe' | 'review', scopeKey: 'system_drive_c' | 'current_user_temp',
): Promise<PreparedCleanupBatch> {
  return apiJson('/api/v1/cleanup/batches/prepare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_ids: itemIds, mode, scope_key: scopeKey }),
  })
}

export function executeCleanupBatch(executionToken: string): Promise<CleanupBatchResult> {
  return apiJson('/api/v1/cleanup/batches/execute', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ execution_token: executionToken }),
  })
}

export function getCleanupBatch(batchId: string): Promise<CleanupBatchAudit> {
  return apiJson(`/api/v1/cleanup/batches/${encodeURIComponent(batchId)}`)
}

export interface CleanupPreflight {
  candidate_id: string | null
  probe_id?: string
  current_path: string
  created_at?: string
  snapshot_size: number
  snapshot_mtime: string | null
  current_size: number | null
  current_mtime: string | null
  age_days?: number | null
  category?: string | null
  risk_level?: string | null
  confidence?: string | null
  policy_rule_id?: string
  execution_rule_id?: string
  eligibility: 'ineligible' | 'eligible_for_review' | 'eligible_for_recycle'
  allowed_actions?: string[]
  checks: { check: string; passed: boolean }[]
  block_reasons: string[]
  planned_action: 'none' | 'dry_run_only' | 'recycle'
}

export interface PreparedCleanup {
  execution_id: string
  execution_token: string | null
  expires_at: string | null
  preflight: CleanupPreflight
  real_execution_enabled: boolean
}

export interface CleanupExecution {
  id: string
  candidate_id: string | null
  probe_id: string | null
  prepare_time: string
  execute_time: string | null
  original_path: string
  requested_action: string
  actual_action: string | null
  planned_action: string
  snapshot_id: string | null
  snapshot_size: number
  snapshot_mtime: string | null
  preflight_size: number | null
  preflight_mtime: string | null
  execute_size: number | null
  execute_mtime: string | null
  policy_rule_id: string
  candidate_category: string | null
  candidate_risk: string | null
  candidate_confidence: string | null
  status: string
  failure_code: string | null
  final_result: string | null
  target_mutation: 'none' | 'recycle_bin' | 'unknown'
  recycle_api_outcome: string | null
}

export interface ControlledProbe {
  probe_id: string
  session_id: string
  absolute_path: string
  created_at: string
  expected_size: number
  expected_mtime_ns: number
  state: 'created' | 'prepared' | 'recycled' | 'invalidated' | 'failed'
  failure_code: string | null
}

export interface CleanupExecutionResult {
  execution_id: string
  probe_id: string | null
  candidate_id: string | null
  status: 'completed'
  final_result: 'recycled'
  target_mutation: 'recycle_bin'
  original_path_absent: true
  message: string
}

export function prepareCleanup(candidateId: string): Promise<PreparedCleanup> {
  return apiJson('/api/v1/cleanup/prepare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId, requested_action: 'recycle' }),
  })
}

export function createControlledProbe(): Promise<ControlledProbe> {
  return apiJson('/api/v1/cleanup/probes', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })
}

export async function getControlledProbes(): Promise<ControlledProbe[]> {
  const result = await apiJson<{ items: ControlledProbe[] }>('/api/v1/cleanup/probes')
  return result.items
}

export function prepareControlledProbe(probeId: string): Promise<PreparedCleanup> {
  return apiJson(`/api/v1/cleanup/probes/${encodeURIComponent(probeId)}/prepare`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ requested_action: 'recycle' }),
  })
}

export function executeCleanup(executionToken: string): Promise<CleanupExecutionResult> {
  return apiJson('/api/v1/cleanup/execute', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ execution_token: executionToken }),
  })
}

export async function getCleanupExecutions(): Promise<CleanupExecution[]> {
  const result = await apiJson<{ items: CleanupExecution[] }>('/api/v1/cleanup/executions?limit=10')
  return result.items
}

export interface CandidateRun {
  run_id: string
  snapshot_id: string
  rule_version: string
  created_at: string
  status: 'completed'
  duration_ms: number
  analysis_coverage: 'top_k_and_directories' | 'bounded_scope_files'
  scope_key: string
  scope_label: string
  scan_completed_at: string
  snapshot_coverage: 'complete' | 'limited'
  error_count: number
  skipped_count: number
  file_persistence_mode: 'top_k' | 'bounded_scope'
  file_persistence_limit: number
  persisted_file_count: number
  observed_file_count: number
}

export interface CandidateSummary {
  candidate_count: number
  candidate_bytes: number
  by_category: Record<string, number>
  by_risk: Record<string, number>
  by_confidence: Record<string, number>
  protected_count: number
  review_count: number
  low_count: number
  unknown_count: number
}

export interface CandidateListing {
  latest_snapshot: SnapshotSummary | null
  run: CandidateRun | null
  summary: CandidateSummary | null
  items: CleanupCandidate[]
  total: number
  eligibility_summary: EligibilitySummary
}

export interface EligibilitySummary {
  eligible_count: number
  eligible_bytes: number
  policy_rule_id: 'USER_TEMP_STALE_FILE_V1'
  items: Array<Pick<CleanupCandidate, 'candidate_id' | 'relative_path' | 'display_path' | 'logical_bytes' | 'category' | 'risk_level' | 'confidence'> & { snapshot_mtime: string | null }>
}

export interface PolicyDecision {
  policy_rule_id: 'USER_TEMP_STALE_FILE_V1'
  execution_policy_version: string
  eligibility: 'ineligible' | 'eligible_for_review' | 'eligible_for_recycle' | 'eligible_for_delete'
  allowed_actions: string[]
  primary_reason: string
  reason_codes: string[]
  evidence: {
    path_scope?: string
    file_type?: string
    logical_bytes?: number
    minimum_bytes?: number
    snapshot_mtime?: string | null
    age_days?: number | null
    required_age_days?: number
    category?: string | null
    required_category?: string
    risk?: string | null
    required_risk?: string
    confidence?: string | null
    required_confidence?: string
    candidate_reason_code?: string | null
    required_candidate_reason_code?: string
    extension?: string
    extension_blocked?: boolean
  }
  evaluated_at: string
  evaluation_basis: 'snapshot_only' | 'snapshot_plus_current_metadata'
  execution_authority: false
}

export interface EligibilityReasonDistribution {
  reason_code: string
  candidate_count: number
  total_bytes: number
}

export interface EligibilityCoverage {
  snapshot_coverage: 'complete' | 'limited'
  file_persistence_mode: 'top_k' | 'bounded_scope'
  file_persistence_limit: number
  persisted_file_count: number
  observed_file_count: number
  file_metadata_coverage?: 'complete' | 'limited'
}

export interface EligibilityDiagnosticsSummary {
  scope: string
  snapshot_id: string
  candidate_analysis_run_id: string
  candidate_rule_version: string
  policy_rule_id: 'USER_TEMP_STALE_FILE_V1'
  execution_policy_version: string
  evaluation_basis: 'snapshot_only' | 'snapshot_plus_current_metadata'
  execution_authority: false
  evaluated_at: string
  duration_ms: number
  evaluated_candidate_count: number
  eligible_count: number
  blocked_count: number
  eligible_bytes: number
  blocked_bytes: number
  evaluation_error_count: number
  primary_reason_distribution: EligibilityReasonDistribution[]
  all_reason_distribution: EligibilityReasonDistribution[]
  age_distribution: Array<{ bucket: string; candidate_count: number; total_bytes: number }>
  coverage: EligibilityCoverage
  semantics: {
    primary_reason_counts_sum_to_evaluated: true
    all_reason_counts_may_overlap: true
    zero_eligible_means: string
  }
}

export interface EligibilityDiagnosticCandidate {
  candidate_id: string
  file_name: string
  relative_path: string
  display_path: string
  logical_bytes: number
  snapshot_time: string
  snapshot_mtime: string | null
  age_days: number | null
  object_type: 'file' | 'directory' | 'group'
  category: string
  risk_level: CleanupCandidate['risk_level']
  confidence: CleanupCandidate['confidence']
  candidate_reason_code: string
  candidate_rule_id: string
  candidate_rule_version: string
  candidate_evidence: string[]
  decision: PolicyDecision
  limitations: string[]
}

export interface EligibilityDiagnosticsListing {
  scope: string
  snapshot_id: string
  candidate_analysis_run_id: string
  policy_rule_id: 'USER_TEMP_STALE_FILE_V1'
  execution_policy_version: string
  evaluation_basis: 'snapshot_only' | 'snapshot_plus_current_metadata'
  execution_authority: false
  evaluated_at: string
  filter: string
  sort: string
  total: number
  limit: number
  offset: number
  items: EligibilityDiagnosticCandidate[]
}

export interface EligibilityDiagnosticDetail {
  scope: string
  snapshot_id: string
  candidate_analysis_run_id: string
  coverage: EligibilityCoverage
  candidate: EligibilityDiagnosticCandidate
}

export function getEligibilityDiagnosticsSummary(scopeKey = 'current_user_temp'): Promise<EligibilityDiagnosticsSummary> {
  return apiJson(`/api/v1/cleanup/eligibility/summary?scope=${encodeURIComponent(scopeKey)}`)
}

export function getEligibilityDiagnosticCandidates(filters: {
  scopeKey?: string
  limit?: number
  offset?: number
  filter?: 'all' | 'eligible' | 'blocked' | 'high_risk' | 'recent' | 'extension_blocked'
  sort?: 'size_desc' | 'age_desc'
} = {}): Promise<EligibilityDiagnosticsListing> {
  const query = new URLSearchParams({
    scope: filters.scopeKey ?? 'current_user_temp',
    limit: String(filters.limit ?? 50),
    offset: String(filters.offset ?? 0),
    filter: filters.filter ?? 'all',
    sort: filters.sort ?? 'size_desc',
  })
  return apiJson(`/api/v1/cleanup/eligibility/candidates?${query}`)
}

export function getEligibilityDiagnosticDetail(
  candidateId: string, scopeKey = 'current_user_temp',
): Promise<EligibilityDiagnosticDetail> {
  return apiJson(
    `/api/v1/cleanup/eligibility/candidates/${encodeURIComponent(candidateId)}?scope=${encodeURIComponent(scopeKey)}`,
  )
}

export function getCandidates(filters: { scopeKey?: string; category?: string; risk?: string; confidence?: string; limit?: number } = {}): Promise<CandidateListing> {
  const query = new URLSearchParams({ scope_key: filters.scopeKey ?? 'system_drive_c', limit: String(filters.limit ?? 100) })
  if (filters.category) query.set('category', filters.category)
  if (filters.risk) query.set('risk', filters.risk)
  if (filters.confidence) query.set('confidence', filters.confidence)
  return apiJson(`/api/v1/candidates?${query}`)
}

export function analyzeSnapshot(snapshotId: string): Promise<{ run: CandidateRun; summary: CandidateSummary }> {
  return apiJson(`/api/v1/snapshots/${encodeURIComponent(snapshotId)}/analyze`, { method: 'POST' })
}

export function getCandidateDetail(candidateId: string, scopeKey = 'system_drive_c'): Promise<{ candidate: CleanupCandidate; members: CleanupCandidate[] }> {
  return apiJson(`/api/v1/candidates/${encodeURIComponent(candidateId)}?scope_key=${encodeURIComponent(scopeKey)}`)
}
