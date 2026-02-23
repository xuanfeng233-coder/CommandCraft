<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeCache } from '@/stores/knowledge-cache'

const props = defineProps<{
  category: string
}>()

const emit = defineEmits<{
  select: [value: string]
}>()

const cache = useKnowledgeCache()
const search = ref('')

const filtered = computed(() => {
  const entries = cache.getIds(props.category)
  if (!search.value) return entries.slice(0, 60)
  const lower = search.value.toLowerCase()
  return entries.filter(
    (e) =>
      e.id.toLowerCase().includes(lower) ||
      (e.name && e.name.toLowerCase().includes(lower))
  ).slice(0, 60)
})

const panelTitle = computed(() =>
  props.category === 'blocks' ? '方块' : '物品'
)
</script>

<template>
  <div class="panel-content">
    <div class="panel-header">
      <span class="panel-label">{{ panelTitle }}</span>
      <input
        v-model="search"
        class="panel-search"
        :placeholder="`搜索${panelTitle} ID...`"
      />
    </div>
    <div class="panel-grid">
      <button
        v-for="entry in filtered"
        :key="entry.id"
        class="panel-item"
        :title="entry.description || entry.name || entry.id"
        @click="emit('select', entry.id)"
      >
        <span class="item-id">{{ entry.id }}</span>
        <span v-if="entry.name" class="item-name">{{ entry.name }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.panel-content {
  padding: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.panel-label {
  font-family: var(--mc-font-title);
  font-size: 12px;
  color: var(--mc-text-secondary);
  flex-shrink: 0;
}

.panel-search {
  flex: 1;
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  color: var(--mc-text-primary);
  font-family: var(--mc-font-mono);
  font-size: 12px;
  padding: 3px 8px;
  outline: none;
}

.panel-search:focus {
  border-color: var(--mc-gold);
}

.panel-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.panel-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-primary);
  padding: 4px 8px;
  font-family: var(--mc-font-mono);
  font-size: 11px;
  cursor: pointer;
  max-width: 160px;
  overflow: hidden;
}

.panel-item:hover {
  background: var(--mc-bg-hover);
  border-color: var(--mc-gold);
}

.item-id {
  color: var(--mc-syn-command);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.item-name {
  color: var(--mc-text-dim);
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
</style>
