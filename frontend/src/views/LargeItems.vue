<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { PROJECT_WORKSPACE_PATH, getTopDirectories, getTopFiles } from '../services/api'
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

watch([() => store.scan?.scan_id, () => store.scan?.state], async ([id, state]) => {
  const request = ++requestNumber
  files.value = []
  directories.value = []
  if (!id || (state !== 'completed' && state !== 'cancelled')) return
  loading.value = true
  message.value = ''
  try {
    const [topFiles, topDirectories] = await Promise.all([getTopFiles(id, 100), getTopDirectories(id, 100)])
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
  const root = store.resultTarget === 'project'
    ? PROJECT_WORKSPACE_PATH
    : `${PROJECT_WORKSPACE_PATH}\\tests\\fixtures\\sample_disk`
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
  <div class="page-heading"><div><p class="eyebrow">EXPLORE / LARGEST ITEMS</p><h1>大文件与目录</h1><p class="page-description">仅显示扫描结果中的 Top 100；默认展示相对路径，不打开或修改文件。</p></div></div>
  <EmptyState v-if="!store.scan || !['completed', 'cancelled'].includes(store.scan.state)" title="暂无可分析的项目" description="先完成一次固定范围扫描，再查看大文件与大目录。" />
  <section v-else class="panel table-panel">
    <div class="tab-row" role="tablist" aria-label="大项目类型"><button type="button" role="tab" :aria-selected="tab === 'files'" :class="{ active: tab === 'files' }" @click="tab = 'files'">大文件</button><button type="button" role="tab" :aria-selected="tab === 'directories'" :class="{ active: tab === 'directories' }" @click="tab = 'directories'">大目录</button><button type="button" class="sort-button" @click="descending = !descending">大小：{{ descending ? '从大到小 ↓' : '从小到大 ↑' }}</button></div>
    <p v-if="message" class="inline-note" role="status">{{ message }}</p>
    <p v-if="loading" class="inline-note">正在读取 Top 项目…</p>
    <template v-else-if="tab === 'files'">
      <EmptyState v-if="!sortedFiles.length" title="没有可显示的大文件" description="此扫描范围内没有文件，或扫描未覆盖到文件。" />
      <div v-else class="table-scroll"><table><thead><tr><th>名称</th><th>相对路径</th><th>大小</th><th>修改时间</th><th>所属目录</th><th>操作</th></tr></thead><tbody><tr v-for="file in sortedFiles" :key="file.relative_path"><td class="strong-cell">{{ file.name }}</td><td class="path-cell">{{ file.relative_path }}</td><td>{{ formatBytes(file.size_bytes) }}</td><td>{{ formatLocalTime(file.mtime) }}</td><td>{{ file.parent || '扫描根' }}</td><td><button class="table-action" type="button" :aria-label="`复制 ${file.name} 的路径`" @click="copyPath(file.relative_path)">复制路径</button></td></tr></tbody></table></div>
    </template>
    <template v-else>
      <EmptyState v-if="!sortedDirectories.length" title="没有可显示的大目录" description="此扫描范围内没有子目录。" />
      <div v-else class="table-scroll"><table><thead><tr><th>目录</th><th>相对路径</th><th>逻辑大小</th><th>文件</th><th>子目录</th><th>覆盖</th></tr></thead><tbody><tr v-for="directory in sortedDirectories" :key="directory.node_id"><td class="strong-cell">{{ directory.name }}</td><td class="path-cell">{{ directory.relative_path }}</td><td>{{ formatBytes(directory.subtree_bytes) }}</td><td>{{ formatNumber(directory.file_count) }}</td><td>{{ formatNumber(directory.children_count) }}</td><td>{{ directory.coverage === 'complete' ? '完整' : '受限' }}</td></tr></tbody></table></div>
    </template>
  </section>
</template>
