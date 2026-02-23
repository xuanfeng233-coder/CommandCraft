<script setup lang="ts">
import { provide, ref, watch } from 'vue'

const props = defineProps<{
  expandedNames?: string[]
}>()

const emit = defineEmits<{
  'update:expandedNames': [names: string[]]
}>()

const expanded = ref<Set<string>>(new Set(props.expandedNames || []))

watch(() => props.expandedNames, (val) => {
  expanded.value = new Set(val || [])
})

function toggle(name: string) {
  const s = new Set(expanded.value)
  if (s.has(name)) {
    s.delete(name)
  } else {
    s.add(name)
  }
  expanded.value = s
  emit('update:expandedNames', [...s])
}

function isExpanded(name: string): boolean {
  return expanded.value.has(name)
}

provide('mc-collapse', { toggle, isExpanded })
</script>

<template>
  <div class="mc-collapse">
    <slot />
  </div>
</template>

<style scoped>
.mc-collapse {
  display: flex;
  flex-direction: column;
}
</style>
