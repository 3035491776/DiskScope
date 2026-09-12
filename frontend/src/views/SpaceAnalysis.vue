<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import SpaceBreakdownChart from '../components/SpaceBreakdownChart.vue'
import { getDirectories } from '../services/api'
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
const currentSize = computed(() => current.value?.size ?? store.scan?.logical_bytes ?? 0)

async function loadLevel(parentId: string) {
  if (!store.scan) return
  const request = ++requestNumber
  loading.value = true
  error.value = ''
  try {
    const items = await getDirectories(store.scan.scan_id, parentId)
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

watch([() => store.scan?.scan_id, () => store.scan?.state], ([id, state]) => {
  if (id && (state === 'completed' || state === 'cancelled')) {
    crumbs.value = [{ id: '', name: targetName(store.resultTarget), size: store.scan?.logical_bytes ?? 0 }]
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
  <div class="page-heading"><div><p class="eyebrow">EXPLORE / DIRECTORY</p><h1>空间分析</h1><p class="page-description">每次只读取当前层级；数字、图表和目录表对应同一份扫描结果。</p></div></div>
  <EmptyState v-if="!store.scan || !['completed', 'cancelled'].includes(store.scan.state)" title="需要完成一次扫描" description="前往总览选择固定范围。扫描完成后，可逐层查看目录占用。" />
  <template v-else>
    <section class="panel analysis-head">
      <nav class="breadcrumbs" aria-label="目录路径"><template v-for="(crumb, index) in crumbs" :key="crumb.id"><span v-if="index" class="breadcrumb-divider">›</span><button type="button" :aria-current="index === crumbs.length - 1 ? 'page' : undefined" @click="navigateTo(index)">{{ crumb.name }}</button></template></nav>
      <div class="analysis-current"><div><p class="eyebrow">当前目录逻辑大小</p><strong>{{ formatBytes(currentSize) }}</strong></div><span>{{ children.length }} 个直接子目录</span></div>
      <p v-if="store.scan.state === 'cancelled'" class="inline-note">扫描已取消；此处仅展示取消前收集到的目录。</p>
    </section>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="inline-note">正在读取当前层级…</p>
    <template v-else-if="children.length">
      <section class="panel chart-panel"><div class="panel-heading"><div><p class="eyebrow">CURRENT LEVEL</p><h2>子目录占比</h2></div><span class="subtle-label">最多显示前 20 项，其余合并</span></div><SpaceBreakdownChart :items="children" :total-bytes="currentSize" /></section>
      <section class="panel table-panel"><div class="panel-heading"><div><p class="eyebrow">DIRECTORIES</p><h2>当前层级目录</h2></div><span class="subtle-label">点击目录继续下钻</span></div>
        <div class="table-scroll"><table><thead><tr><th>目录</th><th>逻辑大小</th><th>占比</th><th>文件</th><th>子目录</th><th>覆盖</th></tr></thead><tbody><tr v-for="item in children" :key="item.node_id"><td><button class="directory-link" type="button" @click="openDirectory(item)">{{ item.name }} <span aria-hidden="true">›</span></button></td><td>{{ formatBytes(item.subtree_bytes) }}</td><td>{{ currentSize > 0 ? (item.subtree_bytes / currentSize * 100).toFixed(1) + '%' : '未知' }}</td><td>{{ formatNumber(item.file_count) }}</td><td>{{ formatNumber(item.children_count) }}</td><td>{{ item.coverage === 'complete' ? '完整' : '受限' }}</td></tr></tbody></table></div>
      </section>
    </template>
    <EmptyState v-else title="此层没有子目录" description="空目录或只有直接文件时，大小仍计入当前目录；可通过面包屑返回上一级。" />
  </template>
</template>
