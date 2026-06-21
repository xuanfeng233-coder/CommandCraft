<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { McButton, McCard, McTag, McScrollbar, McRadioGroup, McRadio, McInput } from '@/components/mc-ui'
import TaskProgress from '@/components/TaskProgress.vue'
import ThinkingChain from '@/components/ThinkingChain.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import { useBuildStore } from '@/stores/build'
import { storeToRefs } from 'pinia'

const buildStore = useBuildStore()
const {
  phase,
  planContent,
  steps,
  currentStepIndex,
  searchActivities,
  isLoading,
  currentTasks,
  currentThinking,
  error,
  completedSteps,
  totalSteps,
  clarifySummary,
  clarifyQuestions,
  clarifySuggestedSteps,
  clarifyAnswers,
} = storeToRefs(buildStore)

const editedPlan = ref('')
const scrollbarRef = ref<InstanceType<typeof McScrollbar> | null>(null)

// Per-question custom input toggle (keyed by question text)
const useCustom = ref<Record<string, boolean>>({})

// Sync plan content to editor when entering review phase
watch(planContent, (val) => {
  if (phase.value === 'review') {
    editedPlan.value = val
  }
}, { immediate: true })

watch(phase, (val) => {
  if (val === 'review') {
    editedPlan.value = planContent.value
  }
  if (val === 'clarifying') {
    useCustom.value = {}
  }
  scrollToBottom()
})

// Auto-scroll on content changes
watch([currentThinking, currentTasks, searchActivities, steps], () => {
  scrollToBottom()
}, { deep: true })

function scrollToBottom() {
  nextTick(() => {
    scrollbarRef.value?.scrollTo({ top: 99999, behavior: 'smooth' })
  })
}

const phaseLabel = computed(() => {
  switch (phase.value) {
    case 'planning': return '规划中'
    case 'clarifying': return '需求确认'
    case 'review': return '方案审查'
    case 'executing': return '执行中'
    case 'completed': return '已完成'
    default: return ''
  }
})

function handleSelectOption(question: string, option: string) {
  useCustom.value[question] = false
  clarifyAnswers.value[question] = option
}

function toggleCustom(question: string) {
  useCustom.value[question] = !useCustom.value[question]
  if (useCustom.value[question]) {
    clarifyAnswers.value[question] = ''
  }
}

function handleSubmitClarify() {
  buildStore.submitClarification({ ...clarifyAnswers.value })
}

const stepStatusLabels: Record<string, string> = {
  pending: '等待中',
  reading: '读取中',
  decomposing: '分解中',
  executing: '执行中',
  reviewing: '审查中',
  retrying: '补充中',
  updating: '更新中',
  complete: '已完成',
  failed: '失败',
}

type TagType = 'default' | 'success' | 'warning' | 'error' | 'info'

const stepStatusColors: Record<string, TagType> = {
  pending: 'default',
  reading: 'info',
  decomposing: 'info',
  executing: 'warning',
  reviewing: 'info',
  retrying: 'warning',
  updating: 'info',
  complete: 'success',
  failed: 'error',
}

// Build thinking steps for ThinkingChain
const thinkingSteps = computed(() => {
  const result: string[] = []
  if (searchActivities.value.length) {
    for (const sa of searchActivities.value) {
      if (sa.status === 'done') {
        result.push(`搜索: ${sa.query} (${sa.results_count ?? 0} 条结果)`)
      } else {
        result.push(`搜索: ${sa.query}`)
      }
    }
  }
  if (currentThinking.value) {
    // Truncate long thinking to last meaningful line
    const lines = currentThinking.value.trim().split('\n').filter(Boolean)
    const last = lines[lines.length - 1]
    if (last) result.push(last.slice(0, 60) + (last.length > 60 ? '...' : ''))
  }
  return result
})

function handleConfirmPlan() {
  buildStore.confirmPlan(editedPlan.value)
}

function handleCancel() {
  buildStore.cancelBuild()
  buildStore.reset()
}
</script>

<template>
  <div class="build-progress">
    <!-- Phase indicator bar -->
    <div class="phase-bar">
      <div
        class="phase-step"
        :class="{
          active: phase === 'planning' || phase === 'clarifying',
          done: ['review', 'executing', 'completed'].includes(phase),
        }"
      >
        <span class="phase-dot" />
        <span>规划</span>
      </div>
      <div class="phase-line" :class="{ active: ['review', 'executing', 'completed'].includes(phase) }" />
      <div
        class="phase-step"
        :class="{ active: phase === 'review', done: ['executing', 'completed'].includes(phase) }"
      >
        <span class="phase-dot" />
        <span>审查</span>
      </div>
      <div class="phase-line" :class="{ active: ['executing', 'completed'].includes(phase) }" />
      <div
        class="phase-step"
        :class="{ active: phase === 'executing', done: phase === 'completed' }"
      >
        <span class="phase-dot" />
        <span>执行</span>
      </div>
    </div>

    <!-- Scrollable conversation-like content -->
    <McScrollbar ref="scrollbarRef" class="build-scrollbar">
      <div class="build-messages">

        <!-- Error display -->
        <div v-if="error" class="build-bubble">
          <div class="bubble-label label-ai">AI</div>
          <div class="bubble-content mc-tex-oak">
            <div class="error-alert">{{ error }}</div>
            <McButton size="small" @click="handleCancel" style="margin-top: 8px">关闭</McButton>
          </div>
        </div>

        <!-- Planning phase -->
        <template v-if="phase === 'planning'">
          <div class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <!-- ThinkingChain for search + thinking -->
              <ThinkingChain
                v-if="thinkingSteps.length || isLoading"
                :step="phaseLabel"
                :steps="thinkingSteps"
                :is-streaming="isLoading"
              />

              <!-- Task progress during planning -->
              <TaskProgress
                v-if="currentTasks.length"
                :sub-tasks="currentTasks"
              />

              <!-- Loading dots when no other content -->
              <div
                v-if="isLoading && !thinkingSteps.length && !currentTasks.length"
                class="loading-indicator"
              >
                <span class="dot" />
                <span class="dot" />
                <span class="dot" />
              </div>
            </div>
          </div>
        </template>

        <!-- Clarifying phase -->
        <template v-if="phase === 'clarifying'">
          <!-- Summary bubble -->
          <div v-if="clarifySummary || clarifySuggestedSteps.length" class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <div v-if="clarifySummary" class="clarify-summary-text">
                {{ clarifySummary }}
              </div>
              <div v-if="clarifySuggestedSteps.length" class="suggested-steps-block">
                <div class="subsection-title">初步规划</div>
                <ol class="suggested-steps">
                  <li v-for="(step, i) in clarifySuggestedSteps" :key="i">{{ step }}</li>
                </ol>
              </div>
            </div>
          </div>

          <!-- Questions bubble using McCard (ParameterGuide style) -->
          <div v-if="clarifyQuestions.length" class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <McCard title="请补充以下信息">
                <div class="questions-list">
                  <div
                    v-for="(q, qi) in clarifyQuestions"
                    :key="qi"
                    class="question-item"
                  >
                    <div class="question-text">{{ q.question }}</div>

                    <!-- Radio options (like ParameterGuide) -->
                    <template v-if="q.options.length > 0 && !useCustom[q.question]">
                      <McRadioGroup
                        :model-value="clarifyAnswers[q.question]"
                        @update:model-value="handleSelectOption(q.question, $event)"
                      >
                        <McRadio
                          v-for="opt in q.options"
                          :key="opt"
                          :value="opt"
                          :label="opt"
                        />
                      </McRadioGroup>
                      <McButton
                        size="small"
                        class="custom-toggle"
                        @click="toggleCustom(q.question)"
                      >
                        自定义输入
                      </McButton>
                    </template>

                    <!-- Custom input -->
                    <template v-else>
                      <McInput
                        :model-value="clarifyAnswers[q.question] || ''"
                        placeholder="请输入..."
                        @update:model-value="clarifyAnswers[q.question] = $event"
                      />
                      <McButton
                        v-if="q.options.length > 0"
                        size="small"
                        class="custom-toggle"
                        @click="toggleCustom(q.question)"
                      >
                        选择选项
                      </McButton>
                    </template>

                    <div
                      v-if="q.default && !clarifyAnswers[q.question]"
                      class="default-hint"
                    >
                      默认值: {{ q.default }}
                    </div>
                  </div>
                </div>

                <template #action>
                  <McButton @click="handleCancel">取消</McButton>
                  <McButton variant="primary" :loading="isLoading" @click="handleSubmitClarify">
                    确认，继续生成方案
                  </McButton>
                </template>
              </McCard>
            </div>
          </div>
        </template>

        <!-- Review phase -->
        <template v-if="phase === 'review'">
          <div class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <McCard title="方案编辑">
                <div class="review-hint">你可以修改下方方案，确认后将开始逐步执行。</div>
                <MarkdownEditor v-model="editedPlan" class="plan-editor" />

                <template #action>
                  <McButton @click="handleCancel">取消</McButton>
                  <McButton variant="primary" :loading="isLoading" @click="handleConfirmPlan">
                    确认方案，开始执行
                  </McButton>
                </template>
              </McCard>
            </div>
          </div>
        </template>

        <!-- Executing phase -->
        <template v-if="phase === 'executing'">
          <!-- Step progress bubble -->
          <div class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <div class="progress-header">
                <span class="section-title">执行进度</span>
                <span class="progress-count">
                  {{ completedSteps }} / {{ totalSteps }} 步骤
                </span>
              </div>

              <!-- Step list -->
              <div class="step-list">
                <div
                  v-for="step in steps"
                  :key="step.index"
                  class="step-item"
                  :class="{ current: step.index === currentStepIndex }"
                >
                  <div class="step-header">
                    <span class="step-label">步骤 {{ step.index }}</span>
                    <McTag
                      :type="stepStatusColors[step.status] || 'default'"
                      size="small"
                    >
                      {{ stepStatusLabels[step.status] || step.status }}
                    </McTag>
                  </div>
                  <div v-if="step.result_summary" class="step-summary">
                    {{ step.result_summary }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Current tasks bubble -->
          <div v-if="currentTasks.length" class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <ThinkingChain
                v-if="currentThinking"
                step="执行中"
                :steps="[]"
                :is-streaming="true"
              />
              <TaskProgress :sub-tasks="currentTasks" />
            </div>
          </div>
        </template>

        <!-- Completed phase -->
        <template v-if="phase === 'completed'">
          <div class="build-bubble">
            <div class="bubble-label label-ai">AI</div>
            <div class="bubble-content mc-tex-oak">
              <div class="completed-content">
                <span class="completed-icon">&#x2714;</span>
                <div>
                  <div class="section-title">构建完成</div>
                  <div class="completed-desc">所有 {{ totalSteps }} 个步骤已执行完毕。</div>
                </div>
              </div>
              <McButton style="margin-top: 12px" @click="handleCancel">关闭</McButton>
            </div>
          </div>
        </template>

      </div>
    </McScrollbar>
  </div>
</template>

<style scoped>
.build-progress {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Phase bar */
.phase-bar {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 12px 16px;
  flex-shrink: 0;
  border-bottom: 2px solid var(--mc-border);
  background: rgba(0, 0, 0, 0.15);
}

.phase-step {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--mc-text-dim);
  font-size: 13px;
  font-family: var(--mc-font-title);
}

.phase-step.active {
  color: var(--mc-gold);
}

.phase-step.done {
  color: var(--mc-green, #55ff55);
}

.phase-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--mc-text-dim);
}

.phase-step.active .phase-dot {
  background: var(--mc-gold);
  box-shadow: 0 0 6px var(--mc-gold);
}

.phase-step.done .phase-dot {
  background: var(--mc-green, #55ff55);
}

.phase-line {
  flex: 1;
  height: 2px;
  background: var(--mc-border);
  margin: 0 8px;
}

.phase-line.active {
  background: var(--mc-green, #55ff55);
}

/* Scrollable area */
.build-scrollbar {
  flex: 1;
  min-height: 0;
}

.build-messages {
  display: flex;
  flex-direction: column;
  padding: 16px;
  min-height: 100%;
}

/* Message bubble style (matches MessageBubble.vue) */
.build-bubble {
  display: flex;
  flex-direction: column;
  margin-bottom: 16px;
  max-width: 85%;
  align-self: flex-start;
  align-items: flex-start;
  animation: mc-slide-up 200ms ease-out;
}

.bubble-label {
  font-size: 12px;
  margin-bottom: 4px;
  padding: 0 4px;
  font-family: var(--mc-font-body);
  font-weight: bold;
}

.label-ai {
  color: #55FFFF;
}

.bubble-content {
  padding: 12px 16px;
  word-break: break-word;
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-raised);
  color: var(--mc-text-primary);
  min-width: 200px;
}

/* Error */
.error-alert {
  color: var(--mc-red, #ff5555);
  padding: 8px;
  border: 2px solid var(--mc-red, #ff5555);
  background: rgba(176, 46, 38, 0.15);
  font-size: 13px;
}

/* Loading dots (matches MessageBubble) */
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

/* Section titles */
.section-title {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 14px;
}

.subsection-title {
  font-family: var(--mc-font-title);
  color: var(--mc-text-primary);
  font-size: 13px;
  margin-bottom: 6px;
}

/* Clarify phase */
.clarify-summary-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--mc-text-primary);
}

.suggested-steps-block {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--mc-border);
}

.suggested-steps {
  margin: 0;
  padding-left: 20px;
  color: var(--mc-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

/* Questions (ParameterGuide style) */
.questions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.question-item {
  padding: 4px 0;
}

.question-text {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 6px;
  color: var(--mc-text-primary);
}

.custom-toggle {
  margin-top: 4px;
  font-size: 12px;
}

.default-hint {
  font-size: 12px;
  color: var(--mc-text-dim);
  margin-top: 2px;
}

/* Review */
.review-hint {
  color: var(--mc-text-dim);
  font-size: 12px;
  margin-bottom: 8px;
}

.plan-editor {
  min-height: 300px;
  max-height: 60vh;
}

/* Executing */
.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.progress-count {
  color: var(--mc-text-dim);
  font-size: 12px;
}

.step-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-item {
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.15);
  border-left: 3px solid var(--mc-border);
  border-radius: 2px;
}

.step-item.current {
  border-left-color: var(--mc-gold);
  background: rgba(255, 170, 0, 0.05);
}

.step-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.step-label {
  font-family: var(--mc-font-title);
  font-size: 13px;
  color: var(--mc-text-primary);
}

.step-summary {
  font-size: 12px;
  color: var(--mc-text-dim);
  margin-top: 4px;
}

/* Completed */
.completed-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.completed-icon {
  font-size: 24px;
  color: var(--mc-green, #55ff55);
  flex-shrink: 0;
}

.completed-desc {
  color: var(--mc-text-secondary);
  font-size: 13px;
  margin-top: 4px;
}
</style>
