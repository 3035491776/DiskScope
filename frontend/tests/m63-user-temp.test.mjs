import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createScan, getCandidateDetail, getCandidates } from '../src/services/api.ts'
import { targetName } from '../src/utils/presentation.ts'

test('current user Temp uses a fixed server-side scope without a submitted path', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    return { ok: true, json: async () => ({ scan_id: 'temp', state: 'queued', items: [] }) }
  }
  try {
    await createScan('user_temp')
    await getCandidates({ scopeKey: 'current_user_temp', risk: 'low' })
    await getCandidateDetail('temp-candidate', 'current_user_temp')
  } finally { globalThis.fetch = original }
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    scope_key: 'current_user_temp', confirmed_readonly: false,
  })
  assert.equal(JSON.stringify(JSON.parse(calls[0].options.body)).includes('AppData'), false)
  assert.match(calls[1].url, /scope_key=current_user_temp/)
  assert.equal(calls[2].url, '/api/v1/candidates/temp-candidate?scope_key=current_user_temp')
  assert.equal(targetName('user_temp'), '临时文件')
})

test('Temp discovery UI states metadata-only coverage and never auto-executes', () => {
  const controls = readFileSync(new URL('../src/components/ScanControls.vue', import.meta.url), 'utf8')
  const status = readFileSync(new URL('../src/views/ScanStatus.vue', import.meta.url), 'utf8')
  const history = readFileSync(new URL('../src/views/History.vue', import.meta.url), 'utf8')
  const recommendations = readFileSync(new URL('../src/views/Recommendations.vue', import.meta.url), 'utf8')
  assert.match(controls, /扫描当前 Windows 用户的临时文件夹/)
  assert.match(controls, /不会删除文件/)
  assert.match(status, /file_metadata_coverage/)
  assert.match(history, /current_user_temp/)
  assert.match(recommendations, /可以准备处理/)
  assert.match(recommendations, /仍需逐个确认/)
  assert.doesNotMatch(recommendations, /watch\([^)]*scopeKey[^]*executeCleanup/)
  assert.match(recommendations, /不会自动处理/)
  assert.doesNotMatch(recommendations, /批量处理|全部处理/)
})
