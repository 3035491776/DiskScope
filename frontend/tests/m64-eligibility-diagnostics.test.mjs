import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  getEligibilityDiagnosticCandidates,
  getEligibilityDiagnosticDetail,
  getEligibilityDiagnosticsSummary,
} from '../src/services/api.ts'
import {
  eligibilityDecisionLabel,
  policyReasonExplanation,
  policyReasonTitle,
} from '../src/utils/recommendations.ts'

const page = readFileSync(new URL('../src/views/Recommendations.vue', import.meta.url), 'utf8')

test('diagnostics API is GET-only, scoped, bounded, filtered, and sorted by enums', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    return { ok: true, json: async () => ({}) }
  }
  try {
    await getEligibilityDiagnosticsSummary('current_user_temp')
    await getEligibilityDiagnosticCandidates({
      scopeKey: 'current_user_temp', limit: 50, offset: 100,
      filter: 'extension_blocked', sort: 'age_desc',
    })
    await getEligibilityDiagnosticDetail('candidate/id', 'current_user_temp')
  } finally { globalThis.fetch = original }

  assert.equal(calls[0].url, '/api/v1/cleanup/eligibility/summary?scope=current_user_temp')
  assert.match(calls[1].url, /^\/api\/v1\/cleanup\/eligibility\/candidates\?/)
  assert.match(calls[1].url, /limit=50/)
  assert.match(calls[1].url, /offset=100/)
  assert.match(calls[1].url, /filter=extension_blocked/)
  assert.match(calls[1].url, /sort=age_desc/)
  assert.equal(calls[2].url, '/api/v1/cleanup/eligibility/candidates/candidate%2Fid?scope=current_user_temp')
  assert.equal(calls.every(call => (call.options.method ?? 'GET') === 'GET'), true)
})

test('summary explains zero eligibility, reason semantics, coverage, and both rule versions', () => {
  assert.match(page, /为什么有些文件不能处理？/)
  assert.match(page, /当前已分析的建议项中，没有文件同时满足所有处理条件/)
  assert.match(page, /为了控制资源占用，只保存了其中/)
  assert.match(page, /不是对所有临时文件的完整结论/)
  assert.match(page, /主要阻止原因/)
  assert.match(page, /全部原因/)
  assert.match(page, /候选识别规则版本/)
  assert.match(page, /执行策略版本/)
  assert.match(page, /重新核对当前文件/)
  assert.match(page, /不等于可以直接释放的空间/)
  assert.doesNotMatch(page, /没有垃圾文件|垃圾文件|已释放空间|已释放/)
})

test('candidate explanations cover nested, recent, extension, and eligible future states', () => {
  assert.match(policyReasonTitle('EXECUTION_RISK_BLOCKED'), /风险较高/)
  assert.match(policyReasonExplanation('EXECUTION_RISK_BLOCKED'), /临时目录的子目录/)
  assert.match(policyReasonExplanation('EXECUTION_RISK_BLOCKED'), /程序运行状态、更新程序或缓存/)
  assert.match(policyReasonExplanation('EXECUTION_FILE_TOO_RECENT'), /不足 30 天/)
  assert.match(policyReasonExplanation('EXECUTION_EXTENSION_BLOCKED'), /明确排除/)
  assert.match(policyReasonExplanation('ELIGIBLE_USER_TEMP_STALE_FILE'), /至少 30 天/)
  assert.match(policyReasonExplanation('ELIGIBLE_USER_TEMP_STALE_FILE'), /重新核对文件当前状态/)
  assert.equal(eligibilityDecisionLabel('eligible_for_recycle'), '可以准备处理')
  assert.equal(eligibilityDecisionLabel('ineligible'), '暂不符合处理条件')
  assert.match(page, /为什么不能处理？/)
  assert.match(page, /为什么可以进入准备处理？/)
  assert.match(page, /candidate_evidence/)
})

test('blocked candidates remain explanatory and cannot expose an execution action', () => {
  assert.match(page, /v-if="selected\.execution_hint === 'prepare_available'"/)
  assert.doesNotMatch(page, /v-if="diagnosticDetail[^>]+prepareSelected/)
  assert.doesNotMatch(page, /批量处理|全部处理/)
  assert.match(page, /不会自动处理/)
  assert.match(page, /准备处理时重新核对当前文件/)
})
