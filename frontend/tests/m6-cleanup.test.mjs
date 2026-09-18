import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createControlledProbe, executeCleanup, getCleanupExecutions, prepareCleanup, prepareControlledProbe } from '../src/services/api.ts'
import { executionReasonLabel, executionStatus } from '../src/utils/recommendations.ts'

const page = readFileSync(new URL('../src/views/Recommendations.vue', import.meta.url), 'utf8')

test('M6.2 UI exposes single-file guarded recycle and no bulk action', () => {
  assert.match(page, /execution_hint === 'prepare_available'/)
  assert.match(page, /准备处理/)
  assert.match(executionStatus({ execution_hint: 'suggestion_only' }), /暂不符合处理条件/)
  assert.match(page, /再次检查当前文件/)
  assert.match(page, /扫描时：/)
  assert.match(page, /当前：/)
  assert.match(page, /USER_TEMP_STALE_FILE_V1/)
  assert.match(page, /至少 30 天未修改/)
  assert.match(page, /我确认这是我要处理的文件/)
  assert.match(page, /移入 Windows 回收站/)
  assert.match(page, /执行时会再次验证路径、类型、大小、时间、文件身份、父级链接和磁盘卷/)
  assert.match(page, /操作记录/)
  assert.doesNotMatch(page, /全选|一键释放|安全删除|已释放|清理全部/)
})

test('M6.1 controlled probe UI makes the narrow ownership and recycle semantics explicit', () => {
  assert.match(page, /安全执行测试/)
  assert.match(page, /仅测试 DiskScope 本次运行创建并登记的 64 KB 临时文件/)
  assert.match(page, /DiskScope 本次运行创建并登记的 64 KB 临时文件/)
  assert.match(page, /创建测试文件/)
  assert.match(page, /准备移入回收站/)
  assert.match(page, /受控测试文件预检/)
  assert.match(page, /移入 Windows 回收站/)
  assert.match(page, /实际可用空间可能在清空回收站后才增加/)
  assert.doesNotMatch(page, /已释放|成功清理|一键清理|全选/)
})

test('M6.1 API sends no client path and executes only a server token', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return { ok: true, json: async () => ({}) }
  }
  try {
    await createControlledProbe()
    await prepareControlledProbe('probe/id')
    await executeCleanup('opaque-token')
  } finally { globalThis.fetch = original }
  assert.equal(calls[0].url, '/api/v1/cleanup/probes')
  assert.deepEqual(JSON.parse(calls[0].options.body), {})
  assert.equal(calls[1].url, '/api/v1/cleanup/probes/probe%2Fid/prepare')
  assert.deepEqual(JSON.parse(calls[1].options.body), { requested_action: 'recycle' })
  assert.equal(calls[2].url, '/api/v1/cleanup/execute')
  assert.deepEqual(JSON.parse(calls[2].options.body), { execution_token: 'opaque-token' })
  assert.equal(calls.some(call => JSON.stringify(call.options).includes('C:\\')), false)
})

test('protected and directory candidates explain why execution is unavailable', () => {
  const base = { execution_hint: 'suggestion_only', execution_policy: { block_reasons: [] } }
  assert.match(executionStatus({ ...base, execution_policy: { block_reasons: ['EXECUTION_PROTECTED_PATH'] } }), /系统保护位置/)
  assert.match(executionStatus({ ...base, execution_policy: { block_reasons: ['DIRECTORY_EXECUTION_NOT_SUPPORTED'] } }), /文件夹或分组/)
  assert.match(executionStatus({ execution_hint: 'prepare_available' }), /可准备处理/)
  assert.match(executionReasonLabel('TARGET_CHANGED_SINCE_SCAN'), /已发生变化/)
  assert.match(executionReasonLabel('ACCESS_DENIED'), /不会绕过 Windows 权限/)
  assert.match(executionReasonLabel('TARGET_IN_USE'), /不会强制关闭/)
  assert.match(executionReasonLabel('EXECUTION_FILE_TOO_RECENT'), /30 天/)
  assert.match(executionReasonLabel('EXECUTION_EXTENSION_BLOCKED'), /文件类型/)
  assert.match(executionStatus({ execution_hint: 'history_only' }), /已移入回收站/)
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
