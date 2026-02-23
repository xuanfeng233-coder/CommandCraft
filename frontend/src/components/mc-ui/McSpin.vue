<script setup lang="ts">
defineProps<{
  show: boolean
}>()
</script>

<template>
  <div class="mc-spin-wrapper">
    <slot />
    <div v-if="show" class="mc-spin-overlay">
      <div class="mc-spin-icon" />
    </div>
  </div>
</template>

<style scoped>
.mc-spin-wrapper {
  position: relative;
}

.mc-spin-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(45, 27, 14, 0.7);
  z-index: 10;
}

.mc-spin-icon {
  width: 24px;
  height: 24px;
  border: 3px solid var(--mc-border);
  border-top-color: var(--mc-green);
  animation: mc-spin 0.7s linear infinite;
}

@keyframes mc-spin {
  to { transform: rotate(360deg); }
}
</style>
