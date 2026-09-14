<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useScanStore } from '../stores/scan'
import type { ScanTarget } from '../services/api'
import { formatLocalTime } from '../utils/format'
import { isActive } from '../utils/presentation'

const store = useScanStore()
function changeScope(event: Event) {
  void store.loadResult((event.target as HTMLSelectElement).value as ScanTarget)
}
</script>

<template>
  <section class="panel result-source" aria-label="结果来源">
    <div class="result-source-main"><div><strong>{{ store.resultLoading ? '正在读取已保存扫描结果…' : store.result?.source_type === 'snapshot' ? '显示已保存扫描结果' : store.result?.source_type === 'live' ? '最新扫描结果' : '暂无已保存扫描结果' }}</strong><p v-if="store.result?.completed_at">扫描时间：{{ formatLocalTime(store.result.completed_at) }} · {{ store.result.coverage === 'limited' ? '覆盖受限' : '覆盖完整' }}</p><p v-else-if="store.result?.storage_status === 'unavailable'">快照数据库暂不可用；只读扫描仍可正常启动。</p><p v-else>选择已有扫描范围，或从总览开始只读扫描。</p></div><div class="result-source-actions"><label>浏览范围 <select :value="store.resultTarget" @change="changeScope"><option value="c_drive">Windows C:</option><option value="project">Project Workspace</option><option value="fixture">Fixture Sample</option></select></label><RouterLink to="/" class="text-button">重新扫描 →</RouterLink></div></div>
    <p v-if="store.scan && isActive(store.scan) && store.scan.scope_key === store.result?.scope_key" class="inline-note">新的扫描正在进行中；当前浏览的是上一次已完成结果。</p>
    <p v-if="store.result?.source_type === 'snapshot'" class="fine-print">此处是历史元数据，不代表目标文件的当前状态。</p>
  </section>
</template>
