<script setup lang="ts">
import LowImpactCard from '../components/LowImpactCard.vue'
import { useScanStore } from '../stores/scan'

const store = useScanStore()
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">关于 DiskScope</p><h1>设置与说明</h1><p class="page-description">了解版本、数据保存位置，以及 DiskScope 如何保护你的文件。</p></div></div>
  <LowImpactCard />
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">应用信息</p><h2>版本与数据位置</h2></div></div><div class="detail-grid"><div><span>DiskScope 版本</span><strong>{{ store.health?.version ?? '—' }}</strong></div><div><span>扫描记录</span><strong>DiskScope\data</strong></div><div><span>运行日志</span><strong>DiskScope\logs</strong></div><div><span>处理方式</span><strong>安全分级后移入 Windows 回收站</strong></div></div><details class="technical-details"><summary>技术详情</summary><p>每批最多 200 个服务器记录的文件，逐个重新检查并顺序移入回收站；人工检查文件使用独立、范围更窄的授权策略。</p></details></section>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">功能边界</p><h2>DiskScope 不会做什么</h2></div></div><p class="inline-note">不会删除文件夹、清理 Windows 或 Program Files、自动清空回收站，也不会永久删除文件。</p></section>
</template>
