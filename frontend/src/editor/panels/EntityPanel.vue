<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeCache } from '@/stores/knowledge-cache'

const emit = defineEmits<{
  select: [value: string]
}>()

const cache = useKnowledgeCache()
const search = ref('')

const filtered = computed(() => {
  const entries = cache.getIds('entities')
  if (!search.value) return entries
  const lower = search.value.toLowerCase()
  return entries.filter(
    (e) =>
      e.id.toLowerCase().includes(lower) ||
      (e.name && e.name.toLowerCase().includes(lower))
  )
})
</script>

<template>
  <div class="panel-content">
    <div class="panel-header">
      <span class="panel-label">实体</span>
      <input
        v-model="search"
        class="panel-search"
        placeholder="搜索实体..."
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
        <span class="entity-id">{{ entry.id }}</span>
        <span v-if="entry.name" class="entity-name">{{ entry.name }}</span>
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
}

.panel-item:hover {
  background: var(--mc-bg-hover);
  border-color: var(--mc-gold);
}

.entity-id {
  color: var(--mc-syn-number);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.entity-name {
  color: var(--mc-text-dim);
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
</style>
