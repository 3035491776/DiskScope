import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('health contract exposes release developer mode explicitly', () => {
  const api = read('../src/services/api.ts')
  assert.match(api, /developer_mode: boolean/)
  assert.match(api, /typeof payload\.developer_mode !== 'boolean'/)
})

test('development scan and result selectors are hidden outside developer mode', () => {
  const store = read('../src/stores/scan.ts')
  const controls = read('../src/components/ScanControls.vue')
  const results = read('../src/components/ResultSourceBanner.vue')
  const history = read('../src/views/History.vue')
  assert.match(store, /developerMode = computed/)
  assert.match(controls, /v-if="store\.developerMode" class="developer-scan-tools"/)
  assert.match(results, /v-if="store\.developerMode" class="developer-scan-tools"/)
  assert.match(history, /<optgroup v-if="store\.developerMode"/)
})

test('normal release guidance does not send users to the source launcher', () => {
  const store = read('../src/stores/scan.ts')
  const recommendations = read('../src/views/Recommendations.vue')
  assert.doesNotMatch(store, /请从 start\.bat/)
  assert.doesNotMatch(recommendations, /请从 start\.bat/)
  assert.match(store, /DiskScope 启动入口/)
})

test('frontend bundle contains no development-machine absolute path', () => {
  const api = read('../src/services/api.ts')
  const largeItems = read('../src/views/LargeItems.vue')
  assert.doesNotMatch(api, /Artilius|Windows-C-clear/)
  assert.doesNotMatch(largeItems, /Artilius|Windows-C-clear/)
  assert.match(api, /scope_key: target === 'project' \? 'project_workspace' : 'fixture_sample'/)
})

test('release UI displays the complete frozen version', () => {
  const sidebar = read('../src/components/AppSidebar.vue')
  assert.match(sidebar, /v0\.1\.0 · 只读诊断模式/)
  assert.doesNotMatch(sidebar, />\s*V0\.1 ·/)
})
