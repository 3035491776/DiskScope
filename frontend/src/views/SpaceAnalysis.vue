<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import SpaceBreakdownChart from '../components/SpaceBreakdownChart.vue'
import ResultSourceBanner from '../components/ResultSourceBanner.vue'
import { getResultDirectories } from '../services/api'
import type { DirectoryItem } from '../services/api'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatNumber } from '../utils/format'
import { targetName } from '../utils/presentation'

const store = useScanStore()
const children = ref<DirectoryItem[]>([])
const crumbs = ref<{ id: string; name: string; size: number }[]>([])
const loading = ref(false)
const error = ref('')
let requestNumber = 0
const current = computed(() => crumbs.value.at(-1))
const currentSize = computed(() => current.value?.size ?? store.result?.summary?.total_bytes ?? 0)

async function loadLevel(parentId: string) {
  const result = store.result
  if (!result || result.source_type === 'none') return
  const request = ++requestNumber
  loading.value = true
  error.value = ''
  try {
    const items = await getResultDirectories(result, parentId)
    if (request === requestNumber) children.value = items
  } catch (reason) {
    if (request === requestNumber) {
      children.value = []
      error.value = reason instanceof Error ? reason.message : '无法读取此层目录'
    }
  } finally {
    if (request === requestNumber) loading.value = false
  }
}

function openDirectory(item: DirectoryItem) {
  crumbs.value.push({ id: item.node_id, name: item.name, size: item.subtree_bytes })
  void loadLevel(item.node_id)
}

function navigateTo(index: number) {
  crumbs.value = crumbs.value.slice(0, index + 1)
  void loadLevel(crumbs.value[index]?.id ?? '')
}

watch([() => store.result?.result_id, () => store.result?.source_type, () => store.result?.scope_key], ([id, source]) => {
  if (id && source !== 'none') {
    crumbs.value = [{ id: '', name: targetName(store.resultTarget), size: store.result?.summary?.total_bytes ?? 0 }]
    void loadLevel('')
  } else {
    requestNumber += 1
    children.value = []
    crumbs.value = []
    loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">文件夹占用</p><h1>空间主要被哪些文件夹占用？</h1><p class="page-description">从最上层开始，逐层查看哪些文件夹占用最多空间。</p></div></div>
  <ResultSourceBanner />
  <EmptyState v-if="!store.result || store.result.source_type === 'none'" title="暂无已保存扫描结果" description="前往总览选择固定范围。扫描完成后，可逐层查看目录占用。" />
  <template v-else>
    <p v-if="store.resultTarget === 'c_drive'" class="coverage-note">这里显示 DiskScope 能读取到的文件大小，不一定等于 Windows 显示的磁盘已用空间；部分受保护位置可能无法扫描。</p>
    <section class="panel analysis-head">
      <nav class="breadcrumbs" aria-label="目录路径"><template v-for="(crumb, index) in crumbs" :key="crumb.id"><span v-if="index" class="breadcrumb-divider">›</span><button type="button" :aria-current="index === crumbs.length - 1 ? 'page' : undefined" @click="navigateTo(index)">{{ crumb.name }}</button></template></nav>
      <div class="analysis-current"><div><p class="eyebrow">当前文件夹大小</p><strong>{{ formatBytes(currentSize) }}</strong></div><span>{{ children.length }} 个直接子文件夹</span></div>
      <p v-if="store.scan?.state === 'cancelled' && store.scan.scope_key === store.result?.scope_key" class="inline-note">最近任务已取消；此处仍展示上一次完成的扫描结果。</p>
    </section>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="inline-note">正在读取当前层级…</p>
    <template v-else-if="children.length">
      <section class="panel chart-panel"><div class="panel-heading"><div><p class="eyebrow">当前层级</p><h2>子文件夹占比</h2></div><span class="subtle-label">最多显示前 20 项，其余合并</span></div><SpaceBreakdownChart :items="children" :total-bytes="currentSize" /></section>
      <section class="panel table-panel"><div class="panel-heading"><div><p class="eyebrow">文件夹列表</p><h2>当前层级文件夹</h2></div><span class="subtle-label">点击文件夹继续查看</span></div>
        <div class="table-scroll"><table><thead><tr><th>文件夹</th><th>大小</th><th>占比</th><th v-if="store.resultTarget === 'c_drive'">类型</th><th>文件</th><th>子文件夹</th><th>扫描完整度</th></tr></thead><tbody><tr v-for="item in children" :key="item.node_id"><td><button class="directory-link" type="button" @click="openDirectory(item)">{{ item.name }} <span aria-hidden="true">›</span></button></td><td>{{ formatBytes(item.subtree_bytes) }}</td><td>{{ currentSize > 0 ? (item.subtree_bytes / currentSize * 100).toFixed(1) + '%' : '未知' }}</td><td v-if="store.resultTarget === 'c_drive'">{{ item.category_label || '其他文件夹' }}</td><td>{{ formatNumber(item.file_count) }}</td><td>{{ formatNumber(item.children_count) }}</td><td>{{ item.coverage === 'complete' ? '完整' : '部分位置未扫描' }}</td></tr></tbody></table></div>
      </section>
    </template>
    <EmptyState v-else title="这里没有子文件夹" description="只有直接文件时，大小仍会计入当前文件夹；可通过上方路径返回。" />
  </template>
</template>
