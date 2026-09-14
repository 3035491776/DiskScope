import test from 'node:test'
import assert from 'node:assert/strict'
import { coverageWarning, formatDeltaBytes, formatDeltaPercent, historyEmptyMessage, historyErrorMessage } from '../src/utils/history.ts'

test('signed byte and percentage changes avoid non-finite output', () => {
  assert.equal(formatDeltaBytes(1048576), '+1.0 MB')
  assert.equal(formatDeltaBytes(-1024), '-1.0 KB')
  assert.equal(formatDeltaBytes(0), '0 B')
  assert.equal(formatDeltaPercent(0.125), '增加 12.5%')
  assert.equal(formatDeltaPercent(-0.25), '减少 25.0%')
  assert.equal(formatDeltaPercent(0), '无变化')
  assert.equal(formatDeltaPercent(null), '新增')
  assert.equal(formatDeltaPercent(Infinity), '—')
})

test('coverage, empty and error messages remain explicit', () => {
  assert.equal(coverageWarning(true), '其中一次扫描覆盖受限，变化结果可能不完整。')
  assert.equal(coverageWarning(false), '')
  assert.match(historyEmptyMessage(0), /还没有历史快照/)
  assert.match(historyEmptyMessage(1), /再完成一次相同范围扫描/)
  assert.match(historyErrorMessage(new Error('服务返回 400')), /扫描范围不一致/)
  assert.match(historyErrorMessage(new Error('服务返回 404')), /快照不存在/)
  assert.match(historyErrorMessage(new Error('服务返回 503')), /数据库暂时不可用/)
})
