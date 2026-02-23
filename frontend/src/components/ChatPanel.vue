<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { McScrollbar } from '@/components/mc-ui'
import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '@/stores/chat'
import { storeToRefs } from 'pinia'

const chatStore = useChatStore()
const { messages } = storeToRefs(chatStore)

const scrollbarRef = ref<InstanceType<typeof McScrollbar> | null>(null)

function scrollToBottom() {
  nextTick(() => {
    if (scrollbarRef.value) {
      scrollbarRef.value.scrollTo({ top: 99999, behavior: 'smooth' })
    }
  })
}

watch(
  () => messages.value.length,
  () => { scrollToBottom() }
)

watch(
  () => {
    const last = messages.value[messages.value.length - 1]
    if (!last) return ''
    return (
      (last.content ?? '') +
      (last.thinking ?? '') +
      (last.command?.command ?? '')
    )
  },
  () => { scrollToBottom() }
)

onMounted(() => { scrollToBottom() })
</script>

<template>
  <div class="chat-panel">
    <McScrollbar ref="scrollbarRef" class="chat-scrollbar">
      <div class="messages-container">
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-title">MC 命令 AI 助手</div>
          <div class="empty-subtitle">
            输入你的需求，AI 将帮你生成 Minecraft 基岩版命令
          </div>
          <div class="empty-examples">
            <div class="example-item">给我一把附魔钻石剑</div>
            <div class="example-item">清除所有掉落物</div>
            <div class="example-item">做一个击杀计分板系统</div>
          </div>
        </div>

        <MessageBubble
          v-for="msg in messages"
          :key="msg.id"
          :message="msg"
        />
      </div>
    </McScrollbar>
  </div>
</template>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chat-scrollbar {
  flex: 1;
}

.messages-container {
  display: flex;
  flex-direction: column;
  padding: 16px;
  min-height: 100%;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 300px;
  text-align: center;
}

.empty-title {
  font-family: var(--mc-font-title);
  font-size: 24px;
  font-weight: bold;
  color: var(--mc-gold);
  margin-bottom: 8px;
  text-shadow: 2px 2px 0 rgba(0, 0, 0, 0.5);
}

.empty-subtitle {
  font-size: 14px;
  color: #fff;
  margin-bottom: 24px;
}

.empty-examples {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.example-item {
  padding: 8px 20px;
  border: 2px solid var(--mc-border);
  font-size: 13px;
  color: var(--mc-text-secondary);
  cursor: default;
  background: var(--mc-bg-card);
  transition: border-color 200ms, color 200ms;
}

.example-item:hover {
  border-color: var(--mc-green);
  color: var(--mc-green);
}
</style>
