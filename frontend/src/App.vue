<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppHeader from './components/AppHeader.vue'
import { useScanStore } from './stores/scan'

const store = useScanStore()
onMounted(() => void store.initialize())
</script>

<template>
  <div class="app-shell">
    <AppSidebar />
    <div class="app-main">
      <AppHeader />
      <main class="page-content"><RouterView /></main>
    </div>
  </div>
</template>
