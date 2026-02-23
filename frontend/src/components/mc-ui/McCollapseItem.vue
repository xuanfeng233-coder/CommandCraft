<script setup lang="ts">
import { inject, computed } from 'vue'

const props = defineProps<{
  name: string
  title?: string
}>()

const collapse = inject<{
  toggle: (name: string) => void
  isExpanded: (name: string) => boolean
}>('mc-collapse')

const open = computed(() => collapse?.isExpanded(props.name) ?? false)

function handleToggle() {
  collapse?.toggle(props.name)
}
</script>

<template>
  <div class="mc-collapse-item" :class="{ 'mc-collapse-item--open': open }">
    <div class="mc-collapse-item-header" @click="handleToggle">
      <span class="mc-collapse-arrow">{{ open ? '▼' : '▶' }}</span>
      <slot name="header">
        <span>{{ title }}</span>
      </slot>
    </div>
    <div v-show="open" class="mc-collapse-item-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.mc-collapse-item {
  border-bottom: 1px solid var(--mc-border);
}

.mc-collapse-item:last-child {
  border-bottom: none;
}

.mc-collapse-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 4px;
  cursor: pointer;
  color: var(--mc-text-primary);
  font-size: 14px;
  user-select: none;
}

.mc-collapse-item-header:hover {
  color: var(--mc-gold);
}

.mc-collapse-arrow {
  font-size: 10px;
  width: 14px;
  flex-shrink: 0;
  color: var(--mc-text-dim);
  transition: color 150ms;
}

.mc-collapse-item--open .mc-collapse-arrow {
  color: var(--mc-green);
}

.mc-collapse-item-body {
  padding: 4px 4px 8px 22px;
}
</style>
