import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { getCleanupExecutions, prepareCleanup } from '../src/services/api.ts'
import { executionReasonLabel, executionStatus } from '../src/utils/recommendations.ts'

const page = readFileSync(new URL('../src/views/Recommendations.vue', import.meta.url), 'utf8')

test('M6 UI exposes dry-run only for policy-approved items and no bulk action', () => {
  assert.match(page, /execution_hint === 'prepare_available'/)
  assert.match(page, /准备处理/)
  assert.match(executionStatus({ execution_hint: 'suggestion_only' }), /当前版本仅建议/)
  assert.match(page, /当前状态预检/)
  assert.match(page, /扫描时：/)
  assert.match(page, /当前：/)
  assert.match(page, /真实处理尚未开放/)
  assert.match(page, /操作记录/)
  assert.doesNotMatch(page, /全选|一键释放|安全删除|已释放/)
  assert.doesNotMatch(page, /executeCleanup|移入回收站.*@click/)
})

test('protected and directory candidates explain why execution is unavailable', () => {
  const base = { execution_hint: 'suggestion_only', execution_policy: { block_reasons: [] } }
  assert.match(executionStatus({ ...base, execution_policy: { block_reasons: ['EXECUTION_PROTECTED_PATH'] } }), /系统保护路径/)
  assert.match(executionStatus({ ...base, execution_policy: { block_reasons: ['DIRECTORY_EXECUTION_NOT_SUPPORTED'] } }), /目录或分组/)
  assert.match(executionStatus({ execution_hint: 'prepare_available' }), /可准备处理/)
  assert.match(executionReasonLabel('TARGET_CHANGED_SINCE_SCAN'), /已发生变化/)
  assert.match(executionReasonLabel('ACCESS_DENIED'), /不会绕过 Windows 权限/)
  assert.match(executionReasonLabel('TARGET_IN_USE'), /不会强制关闭/)
})

test('M6 preparation sends candidate ID without a filesystem path', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return { ok: true, json: async () => ({ items: [] }) }
  }
  try {
    await prepareCleanup('candidate-id')
    await getCleanupExecutions()
  } finally { globalThis.fetch = original }
  assert.equal(calls[0].url, '/api/v1/cleanup/prepare')
  assert.deepEqual(JSON.parse(calls[0].options.body), { candidate_id: 'candidate-id', requested_action: 'recycle' })
  assert.equal(calls[1].url, '/api/v1/cleanup/executions?limit=10')
})
