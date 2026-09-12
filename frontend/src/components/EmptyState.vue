<script setup lang="ts">
defineProps<{ title: string; description: string }>()
</script>

<template>
  <div class="empty-state"><span class="empty-symbol" aria-hidden="true">◫</span><strong>{{ title }}</strong><p>{{ description }}</p></div>
</template>
