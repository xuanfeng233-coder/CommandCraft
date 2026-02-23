<script setup lang="ts">
import CommandCard from './CommandCard.vue'
import ParameterGuide from './ParameterGuide.vue'
import { useChatStore } from '@/stores/chat'
import type { TaskItem } from '@/types'

const props = defineProps<{
  subTasks: TaskItem[]
}>()

const chatStore = useChatStore()

function handleTaskAnswer(taskId: string, answers: Record<string, string>) {
  const parts: string[] = []
  for (const [key, value] of Object.entries(answers)) {
    if (value) parts.push(`${key}: ${value}`)
  }
  if (parts.length > 0) {
    // Immediately hide ParameterGuide and show spinner to prevent duplicate submission
    const task = props.subTasks.find(t => t.task_id === taskId)
    if (task) {
      task.status = 'generating'
    }
    chatStore.sendMessage(parts.join(', '), taskId)
  }
}

const statusIcon: Record<string, string> = {
  pending: '\u25A1',      // hollow square
  blocked: '\u25A3',      // half-filled square
  retrieving: '\u25B7',   // hollow triangle
  generating: '\u25B6',   // play triangle
  validating: '\u25C6',   // diamond
  paused: '\u275A\u275A', // pause
  completed: '\u2714',    // checkmark
  failed: '\u2716',       // cross
  // Legacy
  done: '\u2714',
  error: '\u2716',
}

const statusLabel: Record<string, string> = {
  pending: '待执行',
  blocked: '等待前置',
  retrieving: '检索中',
  generating: '生成中',
  validating: '校验中',
  paused: '等待输入',
  completed: '完成',
  failed: '失败',
  // Legacy
  done: '完成',
  error: '失败',
}

function isSpinning(status: string): boolean {
  return status === 'retrieving' || status === 'generating' || status === 'validating'
}

function isDone(status: string): boolean {
  return status === 'completed' || status === 'done'
}

function isFailed(status: string): boolean {
  return status === 'failed' || status === 'error'
}

function isPaused(status: string): boolean {
  return status === 'paused'
}

function isBlocked(status: string): boolean {
  return status === 'blocked'
}

function blockedByText(task: TaskItem): string {
  const deps = task.depends_on
  if (!deps || deps.length === 0) return ''
  return `等待任务 ${deps.join(', ')} 完成`
}
</script>

<template>
  <div class="subtask-progress">
    <div class="subtask-header">
      <span class="subtask-title">任务拆解</span>
      <span class="subtask-count">
        {{ subTasks.filter(t => isDone(t.status)).length }}/{{ subTasks.length }}
      </span>
    </div>

    <div class="subtask-list">
      <div
        v-for="task in subTasks"
        :key="task.task_id"
        class="subtask-item"
        :class="{
          'subtask-item--generating': isSpinning(task.status),
          'subtask-item--done': isDone(task.status),
          'subtask-item--error': isFailed(task.status),
          'subtask-item--paused': isPaused(task.status),
          'subtask-item--blocked': isBlocked(task.status),
        }"
      >
        <div class="subtask-row">
          <span class="subtask-icon" :class="{
            'icon--pending': task.status === 'pending',
            'icon--blocked': isBlocked(task.status),
            'icon--generating': isSpinning(task.status),
            'icon--done': isDone(task.status),
            'icon--error': isFailed(task.status),
            'icon--paused': isPaused(task.status),
          }">
            {{ statusIcon[task.status] || statusIcon.pending }}
          </span>
          <span class="subtask-desc">{{ task.description }}</span>
          <span class="subtask-status" :class="{
            'status--pending': task.status === 'pending',
            'status--blocked': isBlocked(task.status),
            'status--generating': isSpinning(task.status),
            'status--done': isDone(task.status),
            'status--error': isFailed(task.status),
            'status--paused': isPaused(task.status),
          }">
            {{ statusLabel[task.status] || task.status }}
          </span>
        </div>

        <!-- Blocked hint -->
        <div v-if="isBlocked(task.status)" class="subtask-blocked-hint">
          {{ blockedByText(task) }}
        </div>

        <!-- Generating spinner -->
        <div v-if="isSpinning(task.status)" class="subtask-spinner">
          <span class="dot" /><span class="dot" /><span class="dot" />
        </div>

        <!-- Error message -->
        <div v-if="isFailed(task.status) && task.error" class="subtask-error">
          {{ task.error }}
        </div>

        <!-- Paused: show ParameterGuide bound to task_id -->
        <div v-if="isPaused(task.status) && task.result" class="subtask-result">
          <div v-if="task.result.current_progress" class="subtask-progress-text">
            {{ task.result.current_progress }}
          </div>
          <ParameterGuide
            v-if="task.result.type === 'conversation' && task.result.questions && task.result.questions.length > 0"
            :questions="task.result.questions"
            @answer="(answers: Record<string, string>) => handleTaskAnswer(task.task_id, answers)"
          />
        </div>

        <!-- Completed: show command card or conversation -->
        <div v-if="isDone(task.status) && task.result" class="subtask-result">
          <CommandCard
            v-if="task.result.type === 'single_command' && task.result.command"
            :command="task.result.command"
          />
          <ParameterGuide
            v-if="task.result.type === 'conversation' && task.result.questions && task.result.questions.length > 0"
            :questions="task.result.questions"
            @answer="(answers: Record<string, string>) => handleTaskAnswer(task.task_id, answers)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.subtask-progress {
  margin: 8px 0;
}

.subtask-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 2px;
}

.subtask-title {
  font-family: var(--mc-font-title);
  font-size: 14px;
  font-weight: bold;
  color: var(--mc-gold);
}

.subtask-count {
  font-family: var(--mc-font-mono);
  font-size: 12px;
  color: var(--mc-text-secondary);
}

.subtask-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.subtask-item {
  border: 2px solid var(--mc-border);
  background: var(--mc-bg-card);
  padding: 8px 10px;
  transition: border-color 200ms;
}

.subtask-item--generating {
  border-color: #55FFFF;
}

.subtask-item--done {
  border-color: var(--mc-green);
}

.subtask-item--error {
  border-color: var(--mc-red);
}

.subtask-item--paused {
  border-color: var(--mc-gold);
}

.subtask-item--blocked {
  border-color: var(--mc-text-dim);
  opacity: 0.7;
}

.subtask-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtask-icon {
  flex-shrink: 0;
  width: 16px;
  text-align: center;
  font-size: 12px;
}

.icon--pending { color: var(--mc-text-dim); }
.icon--blocked { color: var(--mc-text-dim); }
.icon--generating { color: #55FFFF; }
.icon--done { color: var(--mc-green); }
.icon--error { color: var(--mc-red); }
.icon--paused { color: var(--mc-gold); }

.subtask-desc {
  flex: 1;
  font-size: 13px;
  color: var(--mc-text-primary);
}

.subtask-status {
  flex-shrink: 0;
  font-size: 11px;
  font-family: var(--mc-font-body);
}

.status--pending { color: var(--mc-text-dim); }
.status--blocked { color: var(--mc-text-dim); }
.status--generating { color: #55FFFF; }
.status--done { color: var(--mc-green); }
.status--error { color: var(--mc-red); }
.status--paused { color: var(--mc-gold); }

.subtask-spinner {
  display: flex;
  gap: 4px;
  padding: 4px 0 0 24px;
}

.subtask-spinner .dot {
  width: 6px;
  height: 6px;
  background-color: #55FFFF;
  animation: mc-pixel-bounce 1.4s infinite ease-in-out both;
}

.subtask-spinner .dot:nth-child(1) { animation-delay: 0s; }
.subtask-spinner .dot:nth-child(2) { animation-delay: 0.16s; }
.subtask-spinner .dot:nth-child(3) { animation-delay: 0.32s; }

.subtask-blocked-hint {
  margin-top: 2px;
  padding: 2px 8px 2px 24px;
  font-size: 11px;
  color: var(--mc-text-dim);
  font-style: italic;
}

.subtask-error {
  margin-top: 4px;
  padding: 4px 8px 4px 24px;
  font-size: 12px;
  color: var(--mc-red);
}

.subtask-result {
  margin-top: 6px;
  padding-left: 0;
}

.subtask-progress-text {
  font-size: 12px;
  color: var(--mc-text-secondary);
  margin-bottom: 6px;
  padding: 4px 8px;
  background: rgba(255, 170, 0, 0.08);
  border-left: 2px solid var(--mc-gold);
}
</style>
