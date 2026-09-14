import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createScan } from '../src/services/api.ts'
import { targetName } from '../src/utils/presentation.ts'

test('C scan request uses only the fixed scope and explicit acknowledgement', async () => {
  const oldFetch = globalThis.fetch
  let called
  globalThis.fetch = async (url, options) => {
    called = { url, options }
    return { ok: true, json: async () => ({ scan_id: 'test', state: 'queued' }) }
  }
  try {
    await createScan('c_drive')
    assert.equal(called.url, '/api/v1/scans')
    assert.deepEqual(JSON.parse(called.options.body), {
      scope_key: 'system_drive_c', confirmed_readonly: true,
    })
    assert.equal(targetName('c_drive'), 'Windows C:')
  } finally {
    globalThis.fetch = oldFetch
  }
})

test('C entry requires confirmation while D remains locked in the dashboard', () => {
  const dashboard = readFileSync(new URL('../src/views/Dashboard.vue', import.meta.url), 'utf8')
  assert.match(dashboard, /分析 C 盘/)
  assert.match(dashboard, /分析 Windows C盘/)
  assert.match(dashboard, /开始只读分析/)
  assert.match(dashboard, /确认层|confirmCDrive/)
  assert.match(dashboard, /整盘扫描尚未开放/)
  assert.match(dashboard, /磁盘已用空间/)
  assert.match(dashboard, /扫描可见空间/)
  const status = readFileSync(new URL('../src/views/ScanStatus.vue', import.meta.url), 'utf8')
  assert.match(status, /取消扫描|ScanProgress/)
  assert.match(status, /coverageReasons/)
  const coverage = readFileSync(new URL('../src/utils/coverage.ts', import.meta.url), 'utf8')
  assert.match(coverage, /权限受限/)
  const history = readFileSync(new URL('../src/views/History.vue', import.meta.url), 'utf8')
  assert.match(history, /system_drive_c/)
})
