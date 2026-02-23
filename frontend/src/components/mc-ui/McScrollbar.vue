<script setup lang="ts">
import { ref } from 'vue'

const containerRef = ref<HTMLElement | null>(null)

function scrollTo(opts: ScrollToOptions) {
  containerRef.value?.scrollTo(opts)
}

defineExpose({ scrollTo })
</script>

<template>
  <div ref="containerRef" class="mc-scrollbar">
    <slot />
  </div>
</template>

<style scoped>
.mc-scrollbar {
  overflow-y: auto;
  overflow-x: hidden;
  height: 100%;
}

.mc-scrollbar::-webkit-scrollbar {
  width: 8px;
}

.mc-scrollbar::-webkit-scrollbar-track {
  background: var(--mc-bg-deep);
}

.mc-scrollbar::-webkit-scrollbar-thumb {
  background: var(--mc-bg-hover);
  border: 2px solid var(--mc-bg-deep);
}

.mc-scrollbar::-webkit-scrollbar-thumb:hover {
  background: var(--mc-border-light);
}
</style>
