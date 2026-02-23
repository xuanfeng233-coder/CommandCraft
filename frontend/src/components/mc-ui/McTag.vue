<script setup lang="ts">
defineProps<{
  type?: 'default' | 'success' | 'warning' | 'error' | 'info'
  size?: 'small' | 'tiny'
}>()
</script>

<template>
  <span
    class="mc-tag"
    :class="[`mc-tag--${type || 'default'}`, `mc-tag--${size || 'small'}`]"
  >
    <slot />
  </span>
</template>

<style scoped>
.mc-tag {
  display: inline-flex;
  align-items: center;
  font-family: var(--mc-font-body);
  border: 2px solid;
  white-space: nowrap;
  vertical-align: middle;
}

.mc-tag--small {
  padding: 0 6px;
  font-size: 12px;
  line-height: 20px;
}

.mc-tag--tiny {
  padding: 0 4px;
  font-size: 10px;
  line-height: 16px;
}

.mc-tag--default {
  background: var(--mc-bg-card);
  border-color: var(--mc-border);
  color: var(--mc-text-secondary);
}

.mc-tag--success {
  background: rgba(58, 151, 30, 0.2);
  border-color: var(--mc-green);
  color: #6cdf40;
}

.mc-tag--warning {
  background: rgba(221, 165, 32, 0.2);
  border-color: var(--mc-gold);
  color: var(--mc-gold);
}

.mc-tag--error {
  background: rgba(176, 46, 38, 0.2);
  border-color: var(--mc-red);
  color: #e05a50;
}

.mc-tag--info {
  background: rgba(60, 68, 170, 0.2);
  border-color: var(--mc-blue);
  color: #7b82e0;
}
</style>
