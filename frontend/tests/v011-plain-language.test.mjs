import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('everyday navigation and primary pages use plain-language labels', () => {
  const sidebar = read('../src/components/AppSidebar.vue')
  const dashboard = read('../src/views/Dashboard.vue')
  const status = read('../src/views/ScanStatus.vue')
  const history = read('../src/views/History.vue')
  assert.match(sidebar, /扫描历史/)
  assert.match(dashboard, /我的 C 盘空间/)
  assert.match(dashboard, /扫描 C 盘/)
  assert.match(status, /扫描过程中不会修改你的文件/)
  assert.match(status, /结果完整度/)
  assert.match(history, /比较两次扫描/)
  assert.match(history, /新增|减少|变大|变小|没有明显变化/)
})

test('internal identifiers stay behind technical details and developer mode', () => {
  const status = read('../src/views/ScanStatus.vue')
  const recommendations = read('../src/views/Recommendations.vue')
  assert.match(status, /<details class="coverage-technical"><summary>技术详情<\/summary>[^]*scan_id/)
  assert.match(recommendations, /<details class="technical-details"><summary>技术详情<\/summary>[^]*candidate_id/)
  assert.match(recommendations, /v-if="store\.developerMode"[^]*安全执行测试/)
  assert.match(recommendations, /v-if="store\.developerMode"[^]*原始操作记录/)
})

test('blocked advice has no action while eligible advice remains single-file recycle only', () => {
  const page = read('../src/views/Recommendations.vue')
  assert.match(page, /v-if="selected\.execution_hint === 'prepare_available'"/)
  assert.match(page, /准备处理/)
  assert.match(page, /移入 Windows 回收站/)
  assert.doesNotMatch(page, /Clean All|Batch|Permanent Delete|批量处理|全部处理|>永久删除</)
})

test('plain error and bounded-detail wording remains visible', () => {
  const coverage = read('../src/utils/coverage.ts')
  const banner = read('../src/components/ResultSourceBanner.vue')
  assert.match(coverage, /有些位置没有访问权限/)
  assert.match(coverage, /文件在扫描过程中发生了变化/)
  assert.match(coverage, /已跳过系统链接或重定向位置/)
  assert.match(coverage, /扫描没有完成。你可以稍后重试/)
  assert.match(banner, /为了控制资源占用/)
})
