<script setup lang="ts">
defineProps<{
  variant?: 'default' | 'primary' | 'danger'
  size?: 'small' | 'medium'
  disabled?: boolean
  loading?: boolean
}>()

defineEmits<{
  click: [e: MouseEvent]
}>()
</script>

<template>
  <button
    class="mc-btn"
    :class="[
      `mc-btn--${variant || 'default'}`,
      `mc-btn--${size || 'medium'}`,
      { 'mc-btn--disabled': disabled || loading, 'mc-btn--loading': loading }
    ]"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <span v-if="loading" class="mc-btn-spinner" />
    <slot />
  </button>
</template>

<style scoped>
.mc-btn {
  font-family: var(--mc-font-body);
  border: 2px solid var(--mc-border);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
  transition: transform 100ms;
  image-rendering: pixelated;
}

.mc-btn--medium {
  padding: 6px 16px;
  font-size: 14px;
}

.mc-btn--small {
  padding: 2px 8px;
  font-size: 12px;
}

.mc-btn--default {
  background-color: var(--mc-bg-card);
  color: var(--mc-text-primary);
  box-shadow: var(--mc-shadow-raised);
}

.mc-btn--default:hover:not(:disabled) {
  background-color: var(--mc-bg-hover);
}

.mc-btn--primary {
  background-color: var(--mc-green);
  color: #fff;
  border-color: #2d7a16;
  box-shadow: var(--mc-shadow-raised);
}

.mc-btn--primary:hover:not(:disabled) {
  background-color: var(--mc-green-hover);
}

.mc-btn--danger {
  background-color: var(--mc-red);
  color: #fff;
  border-color: #8b201a;
  box-shadow: var(--mc-shadow-raised);
}

.mc-btn--danger:hover:not(:disabled) {
  background-color: var(--mc-red-hover);
}

.mc-btn:active:not(:disabled) {
  box-shadow: var(--mc-shadow-sunken);
  transform: translateY(2px);
}

.mc-btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mc-btn-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  animation: mc-spin 0.6s linear infinite;
}

@keyframes mc-spin {
  to { transform: rotate(360deg); }
}
</style>
