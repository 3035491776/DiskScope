import assert from 'node:assert/strict'
import test from 'node:test'
import { formatBytes } from '../src/utils/format.ts'
import { completionLabel, stateLabel } from '../src/utils/presentation.ts'

test('byte formatter distinguishes zero, units and unavailable', () => {
  assert.equal(formatBytes(0), '0 B')
  assert.equal(formatBytes(512), '512 B')
  assert.equal(formatBytes(1228.8), '1.2 KB')
  assert.equal(formatBytes(35.4 * 1024 * 1024), '35.4 MB')
  assert.equal(formatBytes(2.1 * 1024 ** 3), '2.1 GB')
  assert.equal(formatBytes(null), '—')
})

test('terminal states distinguish limited coverage, failure and cancellation', () => {
  const base = { state: 'completed', errors_count: 0, skipped_count: 0 }
  assert.equal(completionLabel(base), '扫描完成')
  assert.equal(completionLabel({ ...base, errors_count: 2 }), '扫描完成，但部分位置未能扫描')
  assert.equal(completionLabel({ ...base, skipped_count: 1 }), '扫描完成，但部分位置未能扫描')
  assert.equal(completionLabel({ ...base, state: 'failed' }), '扫描失败')
  assert.equal(completionLabel({ ...base, state: 'cancelled' }), '已取消')
  assert.equal(stateLabel('cancelling'), '正在取消')
})
