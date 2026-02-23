<script setup lang="ts">
import { useToast } from '@/composables/useToast'

const { queue } = useToast()

const typeColors: Record<string, string> = {
  success: 'var(--mc-green)',
  error: 'var(--mc-red)',
  info: 'var(--mc-blue)',
  warning: 'var(--mc-gold)',
}
</script>

<template>
  <Teleport to="body">
    <div class="mc-toast-container">
      <TransitionGroup name="mc-toast">
        <div
          v-for="t in queue"
          :key="t.id"
          class="mc-toast"
          :style="{ borderLeftColor: typeColors[t.type] }"
        >
          {{ t.message }}
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.mc-toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.mc-toast {
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  border-left-width: 4px;
  color: var(--mc-text-primary);
  font-family: var(--mc-font-body);
  font-size: 13px;
  padding: 8px 16px;
  box-shadow: 2px 2px 0 rgba(0,0,0,0.5);
  pointer-events: auto;
}

.mc-toast-enter-active {
  animation: mc-slide-up 200ms ease-out;
}

.mc-toast-leave-active {
  transition: opacity 200ms, transform 200ms;
}

.mc-toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
