<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  open: boolean
  titleId: string
  descriptionId?: string
  closeOnBackdrop?: boolean
  panelClass?: string
}>(), {
  descriptionId: undefined,
  closeOnBackdrop: true,
  panelClass: '',
})

const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLElement | null>(null)
let returnFocus: HTMLElement | null = null

function focusableElements(): HTMLElement[] {
  if (!dialog.value) return []
  return Array.from(dialog.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter(element => !element.hasAttribute('hidden'))
}

async function focusDialog() {
  await nextTick()
  const initial = dialog.value?.querySelector<HTMLElement>('[data-dialog-initial]')
  const target = initial ?? focusableElements()[0] ?? dialog.value
  target?.focus()
}

function close() {
  emit('close')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const elements = focusableElements()
  if (!elements.length) {
    event.preventDefault()
    dialog.value?.focus()
    return
  }
  const first = elements[0]!
  const last = elements[elements.length - 1]!
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => props.open, async (open, previous) => {
  if (open) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await focusDialog()
  } else if (previous) {
    await nextTick()
    returnFocus?.focus()
    returnFocus = null
  }
}, { immediate: true })

onBeforeUnmount(() => returnFocus?.focus())
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @mousedown.self="closeOnBackdrop && close()">
      <section
        ref="dialog"
        class="confirm-dialog"
        :class="panelClass"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="descriptionId"
        tabindex="-1"
        @keydown="handleKeydown"
      >
        <slot />
      </section>
    </div>
  </Teleport>
</template>
