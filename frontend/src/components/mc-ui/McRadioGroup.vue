<script setup lang="ts">
import { provide, computed } from 'vue'

const props = defineProps<{
  modelValue?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [val: string]
}>()

const currentValue = computed(() => props.modelValue)

function select(val: string) {
  emit('update:modelValue', val)
}

provide('mc-radio-group', { currentValue, select })
</script>

<template>
  <div class="mc-radio-group">
    <slot />
  </div>
</template>

<style scoped>
.mc-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
