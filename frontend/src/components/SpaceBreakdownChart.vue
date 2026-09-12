<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts } from 'echarts/core'
import type { DirectoryItem } from '../services/api'
import { formatBytes } from '../utils/format'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
const props = defineProps<{ items: DirectoryItem[]; totalBytes: number }>()
const element = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function render() {
  if (!chart) return
  const sorted = [...props.items].sort((a, b) => b.subtree_bytes - a.subtree_bytes)
  const rows = sorted.slice(0, 20).map(item => ({ name: item.name, value: item.subtree_bytes }))
  if (sorted.length > 20) {
    rows.push({ name: '其他', value: sorted.slice(20).reduce((sum, item) => sum + item.subtree_bytes, 0) })
  }
  rows.reverse()
  chart.setOption({
    animation: false,
    grid: { left: 148, right: 56, top: 14, bottom: 26 },
    xAxis: { type: 'value', axisLabel: { formatter: (value: number) => formatBytes(value) }, splitLine: { lineStyle: { color: '#edf0f3' } } },
    yAxis: { type: 'category', data: rows.map(item => item.name), axisLabel: { width: 128, overflow: 'truncate', color: '#455365' }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{ type: 'bar', data: rows.map(item => item.value), barMaxWidth: 18, itemStyle: { color: '#456f8d', borderRadius: [0, 3, 3, 0] } }],
    tooltip: {
      trigger: 'item',
      formatter: (param: unknown) => {
        const item = param as { name: string; value: number }
        const ratio = props.totalBytes > 0 ? `${(item.value / props.totalBytes * 100).toFixed(1)}%` : '未知'
        return `${item.name}<br/>${formatBytes(item.value)} · ${ratio}`
      },
    },
  }, true)
  chart.resize({ height: Math.max(220, rows.length * 34 + 50) })
}

onMounted(() => {
  if (!element.value) return
  chart = echarts.init(element.value)
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(element.value)
  render()
})
watch(() => [props.items, props.totalBytes], render)
onUnmounted(() => { resizeObserver?.disconnect(); chart?.dispose(); chart = null })
</script>

<template><div ref="element" class="breakdown-chart" role="img" aria-label="当前层级子目录逻辑大小横向柱状图"></div></template>
