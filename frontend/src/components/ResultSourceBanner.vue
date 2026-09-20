<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useScanStore } from '../stores/scan'
import type { ScanTarget } from '../services/api'
import { formatLocalTime } from '../utils/format'
import { isActive, targetName } from '../utils/presentation'

const store = useScanStore()
const isDevResult = computed(() => store.resultTarget === 'fixture' || store.resultTarget === 'project')
const coverageLabel = computed(() => {
  if (store.result?.coverage !== 'limited') return '已完整扫描可访问位置'
  if (store.result.summary?.skipped_count === 0 &&
      (store.result.summary.metadata_warning_count || store.result.summary.error_count)) {
    return '部分文件的信息不完整'
  }
  return '部分内容未能完整读取'
})
function changeScope(event: Event) {
  void store.loadResult((event.target as HTMLSelectElement).value as ScanTarget)
}
</script>

<template>
  <section class="panel result-source" aria-label="扫描记录来源">
    <div class="result-source-main"><div><strong>{{ store.resultLoading ? '正在读取扫描记录…' : store.result?.source_type === 'snapshot' ? '上次扫描结果' : store.result?.source_type === 'live' ? '刚刚完成的扫描结果' : '还没有扫描结果' }}</strong><p v-if="store.result?.completed_at">扫描时间：{{ formatLocalTime(store.result.completed_at) }} · {{ coverageLabel }}</p><p v-else-if="store.result?.storage_status === 'unavailable'">扫描记录暂时无法读取；你仍然可以开始新的安全扫描。</p><p v-else>选择一个扫描位置，或从总览开始扫描。</p></div><div class="result-source-actions"><label>扫描位置 <select :value="store.resultTarget" @change="changeScope"><option value="c_drive">Windows C 盘</option><option value="user_temp">临时文件</option><option v-if="isDevResult" :value="store.resultTarget">{{ targetName(store.resultTarget) }}</option></select></label><RouterLink to="/" class="text-button">重新扫描 →</RouterLink></div></div>
    <details v-if="store.developerMode" class="developer-scan-tools"><summary>开发与测试结果</summary><div class="result-source-actions"><label>浏览开发范围 <select :value="isDevResult ? store.resultTarget : 'fixture'" @change="changeScope"><option value="fixture">Fixture Sample</option><option value="project">Project Workspace</option></select></label></div></details>
    <p v-if="store.result?.scope_key === 'current_user_temp' && store.result.summary" class="inline-note">这次发现了 {{ store.result.summary.observed_file_count.toLocaleString() }} 个文件。{{ store.result.summary.file_metadata_coverage === 'complete' ? '已保存全部文件的详细信息。' : `为了控制资源占用，保存了其中 ${store.result.summary.persisted_file_count.toLocaleString()} 个文件的详细信息。` }}</p>
    <p v-if="store.scan && isActive(store.scan) && store.scan.scope_key === store.result?.scope_key" class="inline-note">新的扫描正在进行中；当前浏览的是上一次已完成结果。</p>
    <details v-if="store.result?.source_type === 'snapshot'" class="technical-details"><summary>技术详情</summary><p>这里显示的是扫描时保存的文件基本信息，不代表文件现在仍处于相同状态。</p></details>
  </section>
</template>
