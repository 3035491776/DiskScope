import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { establishSession } from '../src/services/api.ts'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('result scope, next scan target, and History scope are separate', () => {
  const store = read('../src/stores/scan.ts')
  const header = read('../src/components/AppHeader.vue')
  const history = read('../src/views/History.vue')
  assert.match(store, /selectedTarget = ref<ScanTarget>\('user_temp'\)/)
  assert.match(store, /resultTarget = ref<ScanTarget>\('user_temp'\)/)
  assert.match(header, /当前结果来源/)
  assert.match(header, /尚无扫描结果/)
  assert.match(history, /historyTarget/)
  assert.doesNotMatch(history, /v-model="store\.selectedTarget"/)
})

test('primary scan entry contains C and Temp while dev targets are collapsed', () => {
  const controls = read('../src/components/ScanControls.vue')
  assert.match(controls, /<option value="user_temp">当前用户临时文件<\/option>/)
  assert.match(controls, /<option value="c_drive">Windows C:<\/option>/)
  assert.match(controls, /<details v-if="store\.developerMode" class="developer-scan-tools">/)
  assert.match(controls, /Fixture Sample/)
  assert.match(controls, /Project Workspace/)
  assert.doesNotMatch(controls, /几十秒至数分钟/)
  assert.match(controls, /较大的系统盘可能需要较长时间/)
})

test('History presents directory and persisted file coverage independently', () => {
  const history = read('../src/views/History.vue')
  assert.match(history, /目录扫描覆盖：/)
  assert.match(history, /文件元数据保存：/)
  assert.match(history, /persisted_file_count/)
  assert.match(history, /observed_file_count/)
})

test('shared dialog traps focus, closes on Escape, and restores focus', () => {
  const dialog = read('../src/components/BaseDialog.vue')
  const dashboardControls = read('../src/components/ScanControls.vue')
  const recommendations = read('../src/views/Recommendations.vue')
  assert.match(dialog, /event\.key === 'Escape'/)
  assert.match(dialog, /event\.shiftKey/)
  assert.match(dialog, /returnFocus\?\.focus\(\)/)
  assert.match(dialog, /aria-modal="true"/)
  assert.match(dashboardControls, /<BaseDialog/)
  assert.equal((recommendations.match(/<BaseDialog/g) ?? []).length, 3)
})

test('Recommendations defaults to user guidance and folds technical tools', () => {
  const page = read('../src/views/Recommendations.vue')
  assert.match(page, /值得关注的空间/)
  assert.match(page, /符合处理条件/)
  assert.match(page, /高级技术详情/)
  assert.match(page, /开发与测试工具/)
  assert.match(page, /<details class="panel advanced-details">/)
  assert.match(page, /recommendationPreviewLimit = 12/)
  assert.match(page, /当前已分析候选中，没有文件同时满足所有处理条件/)
})

test('Scan Status keeps identifiers in technical details', () => {
  const status = read('../src/views/ScanStatus.vue')
  assert.match(status, /<details class="coverage-technical"><summary>技术详情<\/summary>/)
  assert.doesNotMatch(status, /进程范围 · 开发指标/)
  assert.match(status, /当前任务资源概览/)
})

test('successful bootstrap exchange reliably removes the URL fragment', async () => {
  const originalWindow = globalThis.window
  const originalFetch = globalThis.fetch
  const replacements = []
  globalThis.window = {
    location: { hash: '#bootstrap=one-time-token', pathname: '/dashboard', search: '?from=launcher' },
    history: { state: { position: 1 }, replaceState: (state, title, url) => replacements.push({ state, title, url }) },
  }
  globalThis.fetch = async () => ({ ok: true })
  try {
    assert.equal(await establishSession(), true)
    assert.equal(replacements.length, 2)
    assert.equal(replacements.every(item => item.url === '/dashboard?from=launcher'), true)
    assert.equal(replacements.some(item => item.url.includes('bootstrap')), false)
  } finally {
    globalThis.window = originalWindow
    globalThis.fetch = originalFetch
  }
})
