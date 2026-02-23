<script setup lang="ts">
import { ref } from 'vue'

const visible = ref(false)
const tooltipRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLElement | null>(null)
const pos = ref({ top: '0px', left: '0px' })

function show() {
  visible.value = true
  requestAnimationFrame(updatePosition)
}

function hide() {
  visible.value = false
}

function updatePosition() {
  if (!triggerRef.value || !tooltipRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  const tip = tooltipRef.value.getBoundingClientRect()
  let top = rect.top - tip.height - 6
  let left = rect.left + rect.width / 2 - tip.width / 2
  if (top < 4) top = rect.bottom + 6
  if (left < 4) left = 4
  if (left + tip.width > window.innerWidth - 4) left = window.innerWidth - tip.width - 4
  pos.value = { top: top + 'px', left: left + 'px' }
}
</script>

<template>
  <span ref="triggerRef" class="mc-tooltip-trigger" @mouseenter="show" @mouseleave="hide">
    <slot name="trigger" />
  </span>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="tooltipRef"
      class="mc-tooltip"
      :style="{ top: pos.top, left: pos.left }"
    >
      <slot />
    </div>
  </Teleport>
</template>

<style scoped>
.mc-tooltip-trigger {
  display: inline-flex;
}

.mc-tooltip {
  position: fixed;
  z-index: 1200;
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  color: var(--mc-text-primary);
  font-family: var(--mc-font-body);
  font-size: 12px;
  padding: 6px 8px;
  max-width: 300px;
  pointer-events: none;
  box-shadow: 2px 2px 0 rgba(0,0,0,0.5);
}
</style>
