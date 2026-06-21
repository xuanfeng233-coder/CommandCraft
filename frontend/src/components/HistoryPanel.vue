<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { McDrawer, McButton, McSpin, McPopconfirm } from '@/components/mc-ui'
import { useChatStore } from '@/stores/chat'
import { storeToRefs } from 'pinia'
import type { SessionSummary } from '@/types'

defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

const chatStore = useChatStore()
const { sessions, sessionsLoading, sessionId } = storeToRefs(chatStore)

const editionFilter = ref<'all' | 'bedrock' | 'java'>('all')

const filteredSessions = computed(() => {
  if (editionFilter.value === 'all') return sessions.value
  return sessions.value.filter((s: SessionSummary) => (s.edition || 'bedrock') === editionFilter.value)
})

const bedrockCount = computed(() => sessions.value.filter((s: SessionSummary) => (s.edition || 'bedrock') === 'bedrock').length)
const javaCount = computed(() => sessions.value.filter((s: SessionSummary) => (s.edition || 'bedrock') === 'java').length)

onMounted(() => {
  chatStore.fetchSessions()
})

function handleSelect(id: string) {
  chatStore.loadSession(id)
  emit('update:show', false)
}

function handleDelete(id: string) {
  chatStore.removeSession(id)
}

function formatTime(isoString: string): string {
  const d = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} 小时前`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay} 天前`
  return d.toLocaleDateString('zh-CN')
}
</script>

<template>
  <McDrawer
    :show="show"
    :width="340"
    title="历史对话"
    @update:show="emit('update:show', $event)"
  >
    <div class="history-actions">
      <div class="edition-tabs">
        <button
          class="edition-tab"
          :class="{ active: editionFilter === 'all' }"
          @click="editionFilter = 'all'"
        >全部 ({{ sessions.length }})</button>
        <button
          class="edition-tab"
          :class="{ active: editionFilter === 'bedrock' }"
          @click="editionFilter = 'bedrock'"
        >基岩版 ({{ bedrockCount }})</button>
        <button
          class="edition-tab"
          :class="{ active: editionFilter === 'java' }"
          @click="editionFilter = 'java'"
        >Java版 ({{ javaCount }})</button>
      </div>
      <McButton size="small" @click="chatStore.fetchSessions()">
        刷新
      </McButton>
    </div>

    <McSpin :show="sessionsLoading">
      <div v-if="filteredSessions.length === 0 && !sessionsLoading" class="empty-msg">
        暂无历史对话
      </div>

      <div v-else class="session-list">
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === sessionId }"
          @click="handleSelect(s.id)"
        >
          <div class="session-info">
            <div class="session-title-row">
              <span v-if="s.mode === 'build'" class="session-badge build">构建</span>
              <span class="session-edition-badge" :class="(s.edition || 'bedrock')">
                {{ (s.edition || 'bedrock') === 'java' ? 'JE' : 'BE' }}
              </span>
              <span class="session-title">{{ s.title || '未命名对话' }}</span>
            </div>
            <div class="session-time">{{ formatTime(s.updated_at) }}</div>
          </div>
          <McPopconfirm @confirm="handleDelete(s.id)">
            <template #trigger>
              <McButton size="small" variant="danger">
                删除
              </McButton>
            </template>
            确认删除此对话？
          </McPopconfirm>
        </div>
      </div>
    </McSpin>
  </McDrawer>
</template>

<style scoped>
.history-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
}

.edition-tabs {
  display: flex;
  gap: 2px;
}

.edition-tab {
  background: transparent;
  border: 1px solid var(--mc-border);
  color: var(--mc-text-dim);
  font-size: 11px;
  font-family: var(--mc-font-title);
  padding: 2px 6px;
  cursor: pointer;
  transition: all 150ms;
}

.edition-tab:hover {
  color: var(--mc-text-primary);
}

.edition-tab.active {
  color: var(--mc-gold);
  border-color: var(--mc-gold);
  background: rgba(255, 170, 0, 0.1);
}

.empty-msg {
  text-align: center;
  color: var(--mc-text-dim);
  padding: 32px 0;
  font-size: 13px;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border: 2px solid transparent;
  cursor: pointer;
  transition: background-color 150ms, border-color 150ms;
}

.session-item:hover {
  background: rgba(255,255,255,0.05);
  border-color: var(--mc-border);
}

.session-item.active {
  border-left: 4px solid var(--mc-green);
  background: rgba(58, 151, 30, 0.1);
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-title-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.session-badge {
  font-family: var(--mc-font-title);
  font-size: 10px;
  padding: 0 4px;
  border: 1px solid;
  flex-shrink: 0;
}

.session-badge.build {
  color: #55FFFF;
  border-color: #55FFFF;
}

.session-edition-badge {
  font-family: var(--mc-font-title);
  font-size: 10px;
  padding: 0 3px;
  border: 1px solid;
  flex-shrink: 0;
}

.session-edition-badge.bedrock {
  color: var(--mc-gold);
  border-color: var(--mc-gold);
}

.session-edition-badge.java {
  color: #55FF55;
  border-color: #55FF55;
}

.session-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--mc-text-primary);
}

.session-time {
  font-size: 12px;
  color: #ff9700;
  margin-top: 2px;
}
</style>
