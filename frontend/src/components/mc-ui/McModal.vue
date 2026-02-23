<script setup lang="ts">
import { watch } from 'vue'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [val: boolean]
}>()

function close() {
  emit('update:show', false)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

watch(() => props.show, (val) => {
  if (val) {
    document.addEventListener('keydown', onKeydown)
  } else {
    document.removeEventListener('keydown', onKeydown)
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="mc-modal">
      <div v-if="show" class="mc-modal-overlay" @click.self="close">
        <div class="mc-modal-content mc-tex-oak">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.mc-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.65);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mc-modal-content {
  border: 2px solid var(--mc-border);
  box-shadow: 0 8px 32px rgba(0,0,0,0.6);
  color: var(--mc-text-primary);
  max-width: 90vw;
  max-height: 90vh;
  overflow-y: auto;
}

/* Transition */
.mc-modal-enter-active,
.mc-modal-leave-active {
  transition: opacity 200ms;
}

.mc-modal-enter-active .mc-modal-content,
.mc-modal-leave-active .mc-modal-content {
  transition: transform 200ms;
}

.mc-modal-enter-from,
.mc-modal-leave-to {
  opacity: 0;
}

.mc-modal-enter-from .mc-modal-content,
.mc-modal-leave-to .mc-modal-content {
  transform: scale(0.95);
}
</style>
