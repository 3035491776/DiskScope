<script setup lang="ts">
import LowImpactCard from '../components/LowImpactCard.vue'
import { useScanStore } from '../stores/scan'

const store = useScanStore()
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">ABOUT / SAFETY</p><h1>设置与说明</h1><p class="page-description">当前版本只读，不提供删除、移动或整卷扫描操作。</p></div></div>
  <LowImpactCard />
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">APP INFORMATION</p><h2>版本与范围</h2></div></div><div class="detail-grid"><div><span>后端版本</span><strong>{{ store.health?.version ?? '—' }}</strong></div><div><span>当前模式</span><strong>V0.1 · 只读诊断</strong></div><div><span>允许范围</span><strong>Fixture Sample / Project Workspace</strong></div><div><span>整卷扫描</span><strong>尚未开放</strong></div></div></section>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">COMING LATER</p><h2>缓存线索</h2></div></div><p class="inline-note">缓存识别将在后续版本逐步开放。当前不展示未经核实的缓存数据，也不提供清理操作。</p></section>
</template>
