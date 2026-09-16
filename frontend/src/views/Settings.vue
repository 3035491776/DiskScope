<script setup lang="ts">
import LowImpactCard from '../components/LowImpactCard.vue'
import { useScanStore } from '../stores/scan'

const store = useScanStore()
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">ABOUT / SAFETY</p><h1>设置与说明</h1><p class="page-description">扫描保持只读；清理仅允许严格合格的当前用户 Temp 单文件，经确认后移入 Windows 回收站。</p></div></div>
  <LowImpactCard />
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">APP INFORMATION</p><h2>版本与范围</h2></div></div><div class="detail-grid"><div><span>后端版本</span><strong>{{ store.health?.version ?? '—' }}</strong></div><div><span>当前模式</span><strong>受保护清理</strong></div><div><span>扫描能力</span><strong>只读 metadata-only</strong></div><div><span>清理能力</span><strong>当前用户 Temp · 单文件 · 回收站</strong></div></div></section>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">NOT AVAILABLE</p><h2>尚未开放</h2></div></div><p class="inline-note">批量清理、目录清理、应用缓存、系统转储、回收站管理和 DiskScope 撤销功能均未开放。</p></section>
</template>
