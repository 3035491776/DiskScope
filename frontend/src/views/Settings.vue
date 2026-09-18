<script setup lang="ts">
import LowImpactCard from '../components/LowImpactCard.vue'
import { useScanStore } from '../stores/scan'

const store = useScanStore()
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">关于 DiskScope</p><h1>设置与说明</h1><p class="page-description">了解版本、数据保存位置，以及 DiskScope 如何保护你的文件。</p></div></div>
  <LowImpactCard />
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">应用信息</p><h2>版本与数据位置</h2></div></div><div class="detail-grid"><div><span>DiskScope 版本</span><strong>{{ store.health?.version ?? '—' }}</strong></div><div><span>扫描记录</span><strong>DiskScope\data</strong></div><div><span>运行日志</span><strong>DiskScope\logs</strong></div><div><span>处理方式</span><strong>仅单个合格临时文件移入回收站</strong></div></div><details class="technical-details"><summary>技术详情</summary><p>扫描 C 盘和当前用户临时文件时，只读取文件基本信息。处理门只允许逐个确认的严格合格文件进入 Windows 回收站。</p></details></section>
  <section class="panel"><div class="panel-heading"><div><p class="eyebrow">功能边界</p><h2>DiskScope 不会做什么</h2></div></div><p class="inline-note">不会批量清理、删除文件夹、处理应用缓存或系统转储，也不会永久删除文件。</p></section>
</template>
