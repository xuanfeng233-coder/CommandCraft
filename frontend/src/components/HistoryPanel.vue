<script setup lang="ts">
import { onMounted } from 'vue'
import { McDrawer, McButton, McSpin, McPopconfirm } from '@/components/mc-ui'
import { useChatStore } from '@/stores/chat'
import { storeToRefs } from 'pinia'

defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

const chatStore = useChatStore()
const { sessions, sessionsLoading, sessionId } = storeToRefs(chatStore)

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
    :width="320"
    title="历史对话"
    @update:show="emit('update:show', $event)"
  >
    <div class="history-actions">
      <McButton size="small" @click="chatStore.fetchSessions()">
        刷新
      </McButton>
    </div>

    <McSpin :show="sessionsLoading">
      <div v-if="sessions.length === 0 && !sessionsLoading" class="empty-msg">
        暂无历史对话
      </div>

      <div v-else class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === sessionId }"
          @click="handleSelect(s.id)"
        >
          <div class="session-info">
            <div class="session-title">{{ s.title || '未命名对话' }}</div>
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
  justify-content: flex-end;
  margin-bottom: 8px;
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

.session-title {
  font-size: 14px;
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
