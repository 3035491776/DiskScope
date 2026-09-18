<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import ResultSourceBanner from '../components/ResultSourceBanner.vue'
import { getResultTop } from '../services/api'
import type { DirectoryItem, FileItem } from '../services/api'
import { useScanStore } from '../stores/scan'
import { formatBytes, formatLocalTime, formatNumber } from '../utils/format'

const store = useScanStore()
const tab = ref<'files' | 'directories'>('files')
const descending = ref(true)
const files = ref<FileItem[]>([])
const directories = ref<DirectoryItem[]>([])
const loading = ref(false)
const message = ref('')
let requestNumber = 0
const sortedFiles = computed(() => [...files.value].sort((a, b) => descending.value ? b.size_bytes - a.size_bytes || a.relative_path.localeCompare(b.relative_path) : a.size_bytes - b.size_bytes || a.relative_path.localeCompare(b.relative_path)))
const sortedDirectories = computed(() => [...directories.value].sort((a, b) => descending.value ? b.subtree_bytes - a.subtree_bytes || a.relative_path.localeCompare(b.relative_path) : a.subtree_bytes - b.subtree_bytes || a.relative_path.localeCompare(b.relative_path)))

watch([() => store.result?.result_id, () => store.result?.source_type, () => store.result?.scope_key], async ([id, source]) => {
  const request = ++requestNumber
  files.value = []
  directories.value = []
  if (!id || source === 'none' || !store.result) return
  loading.value = true
  message.value = ''
  try {
    const [topFiles, topDirectories] = await Promise.all([getResultTop(store.result, 'file', 100), getResultTop(store.result, 'directory', 100)])
    if (request === requestNumber) {
      files.value = topFiles
      directories.value = topDirectories
    }
  } catch (error) {
    if (request === requestNumber) message.value = error instanceof Error ? error.message : '无法读取大文件与目录'
  } finally {
    if (request === requestNumber) loading.value = false
  }
}, { immediate: true })

function absolutePath(relativePath: string): string {
  if (store.resultTarget === 'c_drive') return `C:\\${relativePath.replaceAll('/', '\\')}`
  if (store.resultTarget === 'user_temp') return `%LOCALAPPDATA%\\Temp\\${relativePath.replaceAll('/', '\\')}`
  const root = store.resultTarget === 'project' ? 'Project Workspace' : 'Fixture Sample'
  return `${root}\\${relativePath.replaceAll('/', '\\')}`
}

async function copyPath(relativePath: string) {
  try {
    await navigator.clipboard.writeText(absolutePath(relativePath))
    message.value = '完整路径已复制到剪贴板。'
  } catch {
    message.value = '无法复制路径，请检查浏览器剪贴板权限。'
  }
}
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">占用最大的项目</p><h1>大文件与文件夹</h1><p class="page-description">查看本次扫描中最大的 100 个文件或文件夹；DiskScope 不会打开或修改它们。</p></div></div>
  <ResultSourceBanner />
  <EmptyState v-if="!store.result || store.result.source_type === 'none'" title="暂无可分析的项目" description="先完成一次固定范围扫描，再查看大文件与大目录。" />
  <section v-else class="panel table-panel">
    <div class="tab-row" role="tablist" aria-label="大项目类型"><button type="button" role="tab" :aria-selected="tab === 'files'" :class="{ active: tab === 'files' }" @click="tab = 'files'">大文件</button><button type="button" role="tab" :aria-selected="tab === 'directories'" :class="{ active: tab === 'directories' }" @click="tab = 'directories'">大文件夹</button><button type="button" class="sort-button" @click="descending = !descending">大小：{{ descending ? '从大到小 ↓' : '从小到大 ↑' }}</button></div>
    <p v-if="message" class="inline-note" role="status">{{ message }}</p>
    <p v-if="loading" class="inline-note">正在读取最大的项目…</p>
    <template v-else-if="tab === 'files'">
      <EmptyState v-if="!sortedFiles.length" title="没有可显示的大文件" description="此扫描范围内没有文件，或扫描未覆盖到文件。" />
      <div v-else class="table-scroll"><table class="large-items-table"><thead><tr><th>文件名</th><th>所在位置</th><th>大小</th><th>最后修改时间</th><th>操作</th></tr></thead><tbody><tr v-for="file in sortedFiles" :key="file.relative_path"><td class="strong-cell path-cell" :title="file.name">{{ file.name }}</td><td class="path-cell" :title="absolutePath(file.relative_path)">{{ absolutePath(file.relative_path) }}</td><td class="size-cell">{{ formatBytes(file.size_bytes) }}</td><td>{{ formatLocalTime(file.mtime) }}</td><td><button class="table-action" type="button" :aria-label="`复制 ${file.name} 的路径`" @click="copyPath(file.relative_path)">复制路径</button></td></tr></tbody></table></div>
    </template>
    <template v-else>
      <EmptyState v-if="!sortedDirectories.length" title="没有可显示的大文件夹" description="这个扫描位置内没有子文件夹。" />
      <div v-else class="table-scroll"><table class="large-items-table"><thead><tr><th>文件夹</th><th>所在位置</th><th>大小</th><th>文件</th><th>子文件夹</th><th>扫描完整度</th></tr></thead><tbody><tr v-for="directory in sortedDirectories" :key="directory.node_id"><td class="strong-cell path-cell" :title="directory.name">{{ directory.name }}</td><td class="path-cell" :title="absolutePath(directory.relative_path)">{{ absolutePath(directory.relative_path) }}</td><td class="size-cell">{{ formatBytes(directory.subtree_bytes) }}</td><td>{{ formatNumber(directory.file_count) }}</td><td>{{ formatNumber(directory.children_count) }}</td><td>{{ directory.coverage === 'complete' ? '完整' : '部分位置未扫描' }}</td></tr></tbody></table></div>
    </template>
  </section>
</template>
