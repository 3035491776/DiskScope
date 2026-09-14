import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { getLatestResult, getResultDirectories, getResultTop } from '../src/services/api.ts'
import { coverageHeading, coverageIssueCount, coverageReasons } from '../src/utils/coverage.ts'

test('saved result API keeps source and scope explicit for drilldown and Top-K', async () => {
  const previous = globalThis.fetch
  const calls = []
  const result = { scope_key: 'system_drive_c', source_type: 'snapshot', result_id: 'saved-1' }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return { ok: true, json: async () => String(url).includes('/latest') ? result : { items: [] } }
  }
  try {
    assert.equal((await getLatestResult('c_drive')).source_type, 'snapshot')
    await getResultDirectories(result, 'Windows/System32')
    await getResultTop(result, 'file', 100)
    await getResultTop(result, 'directory', 100)
    assert.match(calls[0], /scope_key=system_drive_c/)
    assert.match(calls[1], /\/snapshot\/saved-1\/directories\?scope_key=system_drive_c&parent_id=Windows%2FSystem32/)
    assert.match(calls[2], /kind=file&limit=100/)
    assert.match(calls[3], /kind=directory&limit=100/)
  } finally { globalThis.fetch = previous }
})

test('coverage is human-readable while technical codes remain available', () => {
  assert.equal(coverageReasons.ACCESS_DENIED.label, '权限受限')
  assert.equal(coverageReasons.REPARSE_POINT_SKIPPED.label, '链接/系统重定向未跟随')
  assert.equal(coverageReasons.FILE_NOT_FOUND.label, '扫描期间发生变化')
  assert.equal(coverageReasons.PATH_TOO_LONG.label, '路径限制')
  assert.equal(coverageReasons.IO_ERROR.label, '读取元数据失败')
  const completed = { state: 'completed', errors_count: 407, skipped_count: 407 }
  assert.equal(coverageIssueCount(completed), 407)
  assert.equal(coverageHeading(completed), '扫描完成 · 部分位置未覆盖')
  assert.equal(coverageHeading({ ...completed, state: 'failed' }), '扫描失败')
  const status = readFileSync(new URL('../src/views/ScanStatus.vue', import.meta.url), 'utf8')
  assert.match(status, /技术详情/)
  assert.match(status, /\{\{ code \}\}/)
})

test('long paths shrink but sizes, risk and actions remain visible', () => {
  const css = readFileSync(new URL('../src/styles/main.css', import.meta.url), 'utf8')
  const recommendations = readFileSync(new URL('../src/views/Recommendations.vue', import.meta.url), 'utf8')
  const large = readFileSync(new URL('../src/views/LargeItems.vue', import.meta.url), 'utf8')
  assert.match(css, /\.recommendation-item-head>div\{flex:1;min-width:0\}/)
  assert.match(css, /\.member-list \.path-cell\{flex:1;min-width:0/)
  assert.match(css, /\.size-cell\{flex-shrink:0;white-space:nowrap/)
  assert.match(css, /\.large-items-table\{table-layout:fixed/)
  assert.match(recommendations, /:title="member.display_path"/)
  assert.match(recommendations, /copyPath\(selected.display_path\)/)
  assert.match(recommendations, /riskLabel\(item.risk_level\)/)
  assert.match(recommendations, /为什么被识别/)
  assert.match(large, /class="size-cell"/)
  assert.match(large, /:title="file.relative_path"/)
})
