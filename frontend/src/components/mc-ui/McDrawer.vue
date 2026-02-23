<script setup lang="ts">
import { watch } from 'vue'

const props = defineProps<{
  show: boolean
  width?: number
  title?: string
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
    <Transition name="mc-drawer">
      <div v-if="show" class="mc-drawer-overlay" @click.self="close">
        <div
          class="mc-drawer mc-tex-smooth-stone"
          :style="{ width: (width || 320) + 'px' }"
        >
          <div class="mc-drawer-header">
            <span class="mc-drawer-title">{{ title }}</span>
            <button class="mc-drawer-close" @click="close">✕</button>
          </div>
          <div class="mc-drawer-body">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.mc-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  z-index: 1000;
  display: flex;
}

.mc-drawer {
  height: 100%;
  border-right: 2px solid var(--mc-border);
  display: flex;
  flex-direction: column;
  color: var(--mc-text-primary);
  box-shadow: 4px 0 16px rgba(0,0,0,0.5);
}

.mc-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 2px solid var(--mc-border);
  background: rgba(0,0,0,0.15);
}

.mc-drawer-title {
  font-family: var(--mc-font-title);
  font-size: 16px;
}

.mc-drawer-close {
  background: none;
  border: none;
  color: var(--mc-text-secondary);
  font-size: 16px;
  cursor: pointer;
  padding: 2px 6px;
}

.mc-drawer-close:hover {
  color: var(--mc-text-primary);
}

.mc-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

/* Transition */
.mc-drawer-enter-active,
.mc-drawer-leave-active {
  transition: opacity 200ms;
}

.mc-drawer-enter-active .mc-drawer,
.mc-drawer-leave-active .mc-drawer {
  transition: transform 200ms;
}

.mc-drawer-enter-from,
.mc-drawer-leave-to {
  opacity: 0;
}

.mc-drawer-enter-from .mc-drawer,
.mc-drawer-leave-to .mc-drawer {
  transform: translateX(-100%);
}
</style>
