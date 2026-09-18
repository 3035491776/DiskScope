<script setup lang="ts">
import { RouterLink } from 'vue-router'

const links = [
  { to: '/dashboard', label: '总览', icon: '▦' },
  { to: '/analysis', label: '空间分析', icon: '▤' },
  { to: '/large-items', label: '大文件与目录', icon: '▣' },
  { to: '/status', label: '扫描状态', icon: '◷' },
  { to: '/history', label: '扫描历史', icon: '◫' },
  { to: '/recommendations', label: '空间建议', icon: '◇' },
  { to: '/settings', label: '设置与说明', icon: '⚙' },
]
</script>

<template>
  <aside class="sidebar" aria-label="主导航">
    <div class="sidebar-brand"><span class="brand-symbol">D</span><span><strong>DiskScope</strong><small>磁盘空间分析</small></span></div>
    <p class="nav-caption">工作区</p>
    <nav class="nav-links">
      <RouterLink v-for="link in links" :key="link.to" :to="link.to" class="nav-link">
        <span class="nav-icon" aria-hidden="true">{{ link.icon }}</span><span>{{ link.label }}</span>
      </RouterLink>
    </nav>
    <div class="sidebar-foot"><span class="foot-dot"></span> v0.1.1 · 安全诊断</div>
  </aside>
</template>
