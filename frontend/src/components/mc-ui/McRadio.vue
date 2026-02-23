<script setup lang="ts">
import { inject, computed } from 'vue'
import type { ComputedRef } from 'vue'

const props = defineProps<{
  value: string
  label?: string
  disabled?: boolean
}>()

const group = inject<{
  currentValue: ComputedRef<string | undefined>
  select: (val: string) => void
}>('mc-radio-group')

const isSelected = computed(() => group?.currentValue.value === props.value)

function handleClick() {
  if (props.disabled) return
  group?.select(props.value)
}
</script>

<template>
  <button
    class="mc-radio"
    :class="{ 'mc-radio--selected': isSelected, 'mc-radio--disabled': disabled }"
    :disabled="disabled"
    @click="handleClick"
  >
    <slot>{{ label || value }}</slot>
  </button>
</template>

<style scoped>
.mc-radio {
  font-family: var(--mc-font-body);
  font-size: 12px;
  padding: 4px 12px;
  border: 2px solid var(--mc-border);
  background: var(--mc-bg-card);
  color: var(--mc-text-secondary);
  cursor: pointer;
  box-shadow: var(--mc-shadow-raised-sm);
  transition: transform 100ms;
}

.mc-radio:hover:not(:disabled) {
  background: var(--mc-bg-hover);
  color: var(--mc-text-primary);
}

.mc-radio--selected {
  background: var(--mc-green);
  color: #fff;
  border-color: #2d7a16;
  box-shadow: var(--mc-shadow-sunken-sm);
}

.mc-radio--disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
