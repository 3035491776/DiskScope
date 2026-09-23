import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
const cleanup = read('views/CleanupCenter.vue')
const api = read('services/api.ts')
const router = read('router.ts')
const sidebar = read('components/AppSidebar.vue')
const dashboard = read('views/Dashboard.vue')

test('Cleanup Center exposes the three plain-language classifications', () => {
  assert.match(cleanup, />可处理</)
  assert.match(cleanup, />建议手动检查</)
  assert.match(cleanup, />不建议处理</)
  assert.match(api, /SAFE_ACTIONABLE.*REVIEW_REQUIRED.*DO_NOT_TOUCH/s)
  assert.match(router, /path: '\/cleanup'/)
  assert.match(sidebar, /label: '清理空间'/)
})

test('safe supports bounded page selection while review requires an explicit filter', () => {
  assert.match(cleanup, /toggleAllSafe/)
  assert.match(cleanup, /全选当前列表/)
  assert.doesNotMatch(cleanup, /toggleAllReview/)
  assert.match(cleanup, /不会默认选择，也不提供无条件一键全选/)
  assert.match(cleanup, /选择当前筛选结果/)
  assert.match(cleanup, /activeUserFilter/)
  assert.match(cleanup, /我已经检查过所选文件，并确认不再需要/)
  assert.match(cleanup, /confirmMode==='review'&&!reviewAcknowledged/)
})

test('protected items have no checkbox or override action', () => {
  assert.match(cleanup, /v-if="activeTab !== 'protected'" class="cleanup-check"/)
  assert.match(cleanup, /不提供勾选或强制处理入口/)
  assert.doesNotMatch(cleanup, /强制删除|永久删除所选/)
})

test('smart triage is server-filtered, paged, and reports bounded coverage', () => {
  assert.match(cleanup, /快速找出值得检查的内容/)
  assert.match(cleanup, /已扫描个人文件/)
  assert.match(cleanup, /筛选结果不代表整个 C 盘的全部文件/)
  assert.match(cleanup, /categoryOptions/)
  assert.match(cleanup, /olderThanDays/)
  assert.match(cleanup, /每页/)
  assert.match(api, /\/api\/v1\/cleanup\/triage/)
  assert.match(api, /matched_count/)
})

test('batch confirmation and partial result wording preserve Recycle Bin semantics', () => {
  assert.match(cleanup, /移入 Windows 回收站？/)
  assert.match(cleanup, /成功：.*跳过：.*失败：/s)
  assert.match(cleanup, /这些文件仍可能占用磁盘空间/)
  assert.match(cleanup, /不会永久删除/)
  assert.doesNotMatch(cleanup, /已释放\s*\{\{|释放了.*GB/)
})

test('zero-safe and no-action states point to useful next steps', () => {
  assert.match(cleanup, /暂时没有可以直接处理的文件/)
  assert.match(cleanup, /当前没有适合通过 DiskScope 处理的文件/)
  assert.match(cleanup, /to="\/analysis"/)
  assert.match(cleanup, /to="\/large-items"/)
})

test('batch API accepts only server item IDs and a short-lived server token', () => {
  assert.match(api, /item_ids: itemIds/)
  assert.match(api, /execution_token: executionToken/)
  assert.doesNotMatch(api, /batches\/prepare[\s\S]{0,500}path:/)
  assert.match(cleanup, /getCleanupBatch\(batchId\)/)
  assert.match(cleanup, /正在处理 \{\{ processing\.completed \}\} \/ \{\{ processing\.total \}\}/)
})

test('dashboard makes post-scan actions obvious', () => {
  for (const label of ['查看空间占用', '查看大文件', '清理空间', '扫描历史']) {
    assert.match(dashboard, new RegExp(label))
  }
})
