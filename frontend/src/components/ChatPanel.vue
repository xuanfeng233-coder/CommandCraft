<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { McScrollbar } from '@/components/mc-ui'
import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import { storeToRefs } from 'pinia'

const chatStore = useChatStore()
const { messages } = storeToRefs(chatStore)

const knowledgeCache = useKnowledgeCache()

const editionLabel = computed(() => {
  return knowledgeCache.currentEdition === 'java' ? 'Java 版' : '基岩版'
})

const emit = defineEmits<{
  example: [text: string]
}>()

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

const examples = [
  '给最近的玩家一把钻石剑',
  '在自己位置生成一只苦力怕',
  '设置白天，关闭下雨',
  '给所有玩家10秒速度II效果',
  '传送所有玩家到坐标 0 100 0',
]

function handleExample(text: string) {
  emit('example', text)
}
</script>

<template>
  <div class="chat-panel">
    <McScrollbar ref="scrollbarRef" class="chat-scrollbar">
      <div class="messages-container">
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-title">CommandCraft</div>
          <div class="empty-subtitle">
            输入你的需求，AI 将帮你生成 Minecraft {{ editionLabel }}命令
          </div>
          <div class="empty-examples">
            <div
              v-for="ex in examples"
              :key="ex"
              class="example-item"
              @click="handleExample(ex)"
            >
              {{ ex }}
            </div>
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
  cursor: pointer;
  background: var(--mc-bg-card);
  transition: border-color 200ms, color 200ms;
}

.example-item:hover {
  border-color: var(--mc-green);
  color: var(--mc-green);
}

.example-item:active {
  transform: translateY(1px);
  box-shadow: var(--mc-shadow-sunken-sm);
}
</style>
