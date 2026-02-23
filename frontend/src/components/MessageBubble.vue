<script setup lang="ts">
import ThinkingChain from './ThinkingChain.vue'
import CommandCard from './CommandCard.vue'
import ParameterGuide from './ParameterGuide.vue'
import ProjectCard from './ProjectCard.vue'
import TaskProgress from './TaskProgress.vue'
import { computed } from 'vue'
import { useChatStore } from '@/stores/chat'
import { storeToRefs } from 'pinia'
import { marked } from 'marked'
import type { ChatMessage } from '@/types'

// Configure marked for safe, non-async rendering
marked.setOptions({ async: false, breaks: true, gfm: true })

const props = defineProps<{
  message: ChatMessage
}>()

const chatStore = useChatStore()
const { messages, isLoading } = storeToRefs(chatStore)

/** Render markdown to HTML for assistant text content */
const renderedContent = computed(() => {
  const text = props.message.content
  if (!text) return ''
  return marked.parse(text) as string
})

const isStreaming = computed(() => {
  if (!isLoading.value) return false
  const last = messages.value[messages.value.length - 1]
  return last?.id === props.message.id
})

function handleParameterAnswer(answers: Record<string, string>) {
  // Mark this message as answered to hide the ParameterGuide
  props.message.answered = true

  const parts: string[] = []
  for (const [key, value] of Object.entries(answers)) {
    if (value) {
      parts.push(`${key}: ${value}`)
    }
  }
  if (parts.length > 0) {
    chatStore.sendMessage(parts.join(', '))
  }
}
</script>

<template>
  <div
    class="message-bubble mc-slide-in"
    :class="{
      'message-user': message.role === 'user',
      'message-assistant': message.role === 'assistant',
    }"
  >
    <div class="bubble-label" :class="message.role === 'user' ? 'label-user' : 'label-ai'">
      {{ message.role === 'user' ? '你' : 'AI' }}
    </div>

    <div class="bubble-content" :class="message.role === 'user' ? 'mc-tex-dark-oak' : 'mc-tex-oak'">
      <!-- Error state -->
      <template v-if="message.type === 'error'">
        <div class="error-alert">
          {{ message.content }}
        </div>
      </template>

      <template v-else-if="message.role === 'assistant'">
        <ThinkingChain
          v-if="message.step || message.steps || isStreaming"
          :step="message.step || ''"
          :steps="message.steps"
          :is-streaming="isStreaming"
        />

        <!-- Task decomposition progress (shown instead of ProjectCard when present) -->
        <TaskProgress
          v-if="message.subTasks && message.subTasks.length > 0"
          :sub-tasks="message.subTasks"
        />

        <CommandCard
          v-if="message.command"
          :command="message.command"
        />

        <ParameterGuide
          v-if="message.questions && message.questions.length > 0 && !message.answered"
          :questions="message.questions"
          @answer="handleParameterAnswer"
        />
        <div
          v-if="message.questions && message.questions.length > 0 && message.answered"
          class="answered-hint"
        >
          已提交参数
        </div>

        <ProjectCard
          v-if="message.project && !(message.subTasks && message.subTasks.length > 0)"
          :project="message.project"
        />

        <div
          v-if="message.content && !message.command && !message.project && (!(message.questions && message.questions.length > 0) || message.answered)"
          class="text-content markdown-body"
          v-html="renderedContent"
        />
        <span
          v-if="isStreaming && message.content && !message.command && !message.project && (!(message.questions && message.questions.length > 0) || message.answered)"
          class="streaming-cursor"
        />

        <!-- Loading indicator -->
        <div
          v-if="!message.content && !message.command && !message.project && !message.questions && !message.thinking"
          class="loading-indicator"
        >
          <span class="dot" />
          <span class="dot" />
          <span class="dot" />
        </div>
      </template>

      <template v-else>
        <div class="text-content">{{ message.content }}</div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  flex-direction: column;
  margin-bottom: 16px;
  max-width: 85%;
  animation: mc-slide-up 200ms ease-out;
}

.message-user {
  align-self: flex-end;
  align-items: flex-end;
}

.message-assistant {
  align-self: flex-start;
  align-items: flex-start;
}

.bubble-label {
  font-size: 12px;
  margin-bottom: 4px;
  padding: 0 4px;
  font-family: var(--mc-font-body);
  font-weight: bold;
}

.label-user {
  color: #a20101;
}

.label-ai {
  color: #55FFFF;
}

.bubble-content {
  padding: 12px 16px;
  word-break: break-word;
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-raised);
}

.message-user .bubble-content {
  color: var(--mc-text-primary);
}

.message-assistant .bubble-content {
  color: var(--mc-text-primary);
  min-width: 200px;
}

.text-content {
  font-size: 14px;
  line-height: 1.6;
  color: var(--mc-text-primary);
}

/* Markdown rendered content styles */
.markdown-body :deep(p) {
  margin: 0 0 8px 0;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  margin: 12px 0 6px 0;
  line-height: 1.3;
}

.markdown-body :deep(h1) { font-size: 18px; }
.markdown-body :deep(h2) { font-size: 16px; }
.markdown-body :deep(h3) { font-size: 15px; }
.markdown-body :deep(h4) { font-size: 14px; }

.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child),
.markdown-body :deep(h4:first-child) {
  margin-top: 0;
}

.markdown-body :deep(code) {
  font-family: var(--mc-font-mono);
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid var(--mc-border);
  padding: 1px 4px;
  font-size: 13px;
  color: var(--mc-green);
}

.markdown-body :deep(pre) {
  background: rgba(0, 0, 0, 0.5);
  border: 2px solid var(--mc-border);
  padding: 8px 10px;
  margin: 6px 0;
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--mc-border) transparent;
}

.markdown-body :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
  font-size: 13px;
  color: var(--mc-text-primary);
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 4px 0 8px 0;
  padding-left: 20px;
}

.markdown-body :deep(li) {
  margin: 2px 0;
}

.markdown-body :deep(li::marker) {
  color: var(--mc-gold);
}

.markdown-body :deep(strong) {
  color: #fff;
  font-weight: bold;
}

.markdown-body :deep(em) {
  color: var(--mc-text-secondary);
  font-style: italic;
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--mc-gold);
  margin: 6px 0;
  padding: 4px 10px;
  background: rgba(255, 170, 0, 0.06);
  color: var(--mc-text-secondary);
}

.markdown-body :deep(blockquote p) {
  margin: 0;
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 2px solid var(--mc-border);
  margin: 10px 0;
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 6px 0;
  font-size: 13px;
  width: 100%;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--mc-border);
  padding: 4px 8px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: rgba(0, 0, 0, 0.3);
  color: var(--mc-gold);
  font-family: var(--mc-font-title);
  font-weight: bold;
}

.markdown-body :deep(a) {
  color: var(--mc-green);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.markdown-body :deep(a:hover) {
  color: #55FF55;
}

.error-alert {
  color: var(--mc-red);
  padding: 8px;
  border: 2px solid var(--mc-red);
  background: rgba(176, 46, 38, 0.15);
  font-size: 13px;
}

.loading-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.dot {
  width: 8px;
  height: 8px;
  background-color: var(--mc-green);
  animation: mc-pixel-bounce 1.4s infinite ease-in-out both;
}

.dot:nth-child(1) { animation-delay: 0s; }
.dot:nth-child(2) { animation-delay: 0.16s; }
.dot:nth-child(3) { animation-delay: 0.32s; }

.streaming-cursor {
  display: inline-block;
  width: 8px;
  height: 14px;
  background: var(--mc-green);
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: mc-blink 500ms step-end infinite;
}

.answered-hint {
  font-size: 12px;
  color: var(--mc-text-dim);
  padding: 6px 8px;
  border: 1px solid var(--mc-border);
  background: rgba(85, 255, 85, 0.05);
}
</style>
