import test from 'node:test'
import assert from 'node:assert/strict'
import { analyzeSnapshot, getCandidateDetail, getCandidates } from '../src/services/api.ts'
import { actionLabel, categoryLabel, confidenceLabel, coverageMessage, riskLabel, topKMessage } from '../src/utils/recommendations.ts'

test('recommendations always query saved C scope and analyze an existing snapshot ID', async () => {
  const oldFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return { ok: true, json: async () => ({ items: [] }) }
  }
  try {
    await getCandidates({ category: 'crash_dump', risk: 'review', confidence: 'high' })
    await analyzeSnapshot('saved-id')
    await getCandidateDetail('candidate-id')
  } finally {
    globalThis.fetch = oldFetch
  }
  const listed = new URL(calls[0].url, 'http://127.0.0.1:8765')
  assert.equal(listed.pathname, '/api/v1/candidates')
  assert.equal(listed.searchParams.get('scope_key'), 'system_drive_c')
  assert.equal(listed.searchParams.get('category'), 'crash_dump')
  assert.equal(listed.searchParams.get('risk'), 'review')
  assert.equal(listed.searchParams.get('confidence'), 'high')
  assert.equal(calls[1].url, '/api/v1/snapshots/saved-id/analyze')
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[2].url, '/api/v1/candidates/candidate-id?scope_key=system_drive_c')
})

test('recommendation wording keeps risk, confidence, coverage and scope distinct', () => {
  assert.equal(riskLabel('protected'), '系统保护')
  assert.equal(riskLabel('review'), '需确认')
  assert.equal(confidenceLabel('high'), '高')
  assert.equal(categoryLabel('hibernation_file'), '休眠文件')
  assert.equal(categoryLabel('crash_dump'), '崩溃转储')
  assert.match(actionLabel('system_managed'), /不建议手动处理/)
  assert.match(actionLabel('review_for_cleanup'), /人工评估/)
  assert.match(coverageMessage('limited'), /部分内容未能完整读取/)
  assert.equal(coverageMessage('complete'), '')
  assert.match(topKMessage, /不代表所有文件都可处理/)
})
