<script setup lang="ts">
import { ref, computed } from 'vue'
import { McButton, McInput, McScrollbar } from '@/components/mc-ui'
import TaskProgress from './TaskProgress.vue'
import { useBuildStore } from '@/stores/build'
import { storeToRefs } from 'pinia'
import { marked } from 'marked'

marked.setOptions({ async: false, breaks: true, gfm: true })

const buildStore = useBuildStore()
const {
  phase,
  isLoading,
  thinking,
  errorMessage,
  clarifySummary,
  clarifyQuestions,
  suggestedSteps,
  planContent,
  steps,
  tasks,
  currentStepIndex,
  completedCommands,
  searchActivities,
  buildUsageText,
} = storeToRefs(buildStore)

const buildInput = ref('')
const clarifyAnswers = ref<Record<string, string>>({})
const editingPlan = ref(false)
const editedPlan = ref('')

const renderedPlan = computed(() => {
  if (!planContent.value) return ''
  return marked.parse(planContent.value) as string
})

const renderedThinking = computed(() => {
  const t = thinking.value.trim()
  if (!t) return ''
  // Show last 5 lines
  const lines = t.split('\n').filter(Boolean)
  return lines.slice(-5).join('\n')
})

function handleStart() {
  const text = buildInput.value.trim()
  if (!text) return
  buildInput.value = ''
  buildStore.start(text)
}

function handleClarifySubmit() {
  buildStore.submitClarify(clarifyAnswers.value)
  clarifyAnswers.value = {}
}

function startEditPlan() {
  editedPlan.value = planContent.value
  editingPlan.value = true
}

function cancelEditPlan() {
  editingPlan.value = false
}

function handleConfirm() {
  if (editingPlan.value) {
    buildStore.savePlan(editedPlan.value)
    editingPlan.value = false
  }
  buildStore.confirmPlan(editingPlan.value ? editedPlan.value : undefined)
}

function handleReset() {
  buildStore.reset()
  editingPlan.value = false
  clarifyAnswers.value = {}
}
</script>

<template>
  <div class="build-panel">
    <McScrollbar class="build-scrollbar">
      <div class="build-content">
        <!-- Idle: Input -->
        <template v-if="phase === 'idle'">
          <div class="build-welcome">
            <div class="build-title">构建模式</div>
            <div class="build-desc">
              描述你要构建的命令系统，AI 将自动规划、生成并审查多步骤命令方案。
            </div>
            <div v-if="buildUsageText" class="build-quota">
              本月配额: {{ buildUsageText }}
            </div>
            <div class="build-input-area">
              <McInput
                :model-value="buildInput"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="描述你要构建的命令系统，例如：做一个自定义商店系统，可以用计分板购买物品..."
                @update:model-value="buildInput = $event"
                @keydown.enter.ctrl.exact="handleStart"
              />
              <McButton variant="primary" :disabled="!buildInput.trim()" @click="handleStart">
                开始构建
              </McButton>
            </div>
          </div>
        </template>

        <!-- Planning -->
        <template v-if="phase === 'planning'">
          <div class="phase-header">
            <span class="phase-badge planning">规划中</span>
            <span class="phase-text">正在分析需求并生成构建方案...</span>
          </div>
          <div v-if="renderedThinking" class="thinking-block">
            <pre>{{ renderedThinking }}</pre>
          </div>
          <div v-if="searchActivities.length > 0" class="search-list">
            <div v-for="sa in searchActivities" :key="sa.query" class="search-item">
              <span class="search-icon">{{ sa.status === 'done' ? '✓' : '⟳' }}</span>
              搜索: {{ sa.query }}
              <span v-if="sa.count !== undefined" class="search-count">({{ sa.count }} 条)</span>
            </div>
          </div>
        </template>

        <!-- Clarifying -->
        <template v-if="phase === 'clarifying'">
          <div class="phase-header">
            <span class="phase-badge clarifying">需要补充</span>
          </div>
          <div v-if="clarifySummary" class="clarify-summary">{{ clarifySummary }}</div>
          <div v-if="suggestedSteps.length > 0" class="suggested-steps">
            <div class="steps-title">预计步骤:</div>
            <div v-for="(step, i) in suggestedSteps" :key="i" class="step-item">
              {{ i + 1 }}. {{ step }}
            </div>
          </div>
          <div class="clarify-form">
            <div v-for="(q, idx) in clarifyQuestions" :key="q.key || `q-${idx}`" class="clarify-question">
              <label>{{ q.question }}</label>
              <McInput
                :model-value="clarifyAnswers[q.key || `q-${idx}`] || ''"
                @update:model-value="clarifyAnswers[q.key || `q-${idx}`] = $event"
                :placeholder="q.default ? `默认: ${q.default}` : '输入回答...'"
              />
            </div>
            <McButton variant="primary" :loading="isLoading" @click="handleClarifySubmit">
              提交补充信息
            </McButton>
          </div>
        </template>

        <!-- Reviewing (plan generated) -->
        <template v-if="phase === 'reviewing'">
          <div class="phase-header">
            <span class="phase-badge reviewing">方案审查</span>
            <span class="phase-text">请审查构建方案，确认后开始执行</span>
          </div>
          <div v-if="!editingPlan" class="plan-display markdown-body" v-html="renderedPlan" />
          <div v-else class="plan-edit">
            <McInput
              :model-value="editedPlan"
              type="textarea"
              :autosize="{ minRows: 10, maxRows: 30 }"
              @update:model-value="editedPlan = $event"
            />
          </div>
          <div class="plan-actions">
            <McButton v-if="!editingPlan" size="small" @click="startEditPlan">编辑方案</McButton>
            <McButton v-if="editingPlan" size="small" @click="cancelEditPlan">取消编辑</McButton>
            <McButton variant="primary" :loading="isLoading" @click="handleConfirm">
              {{ editingPlan ? '保存并执行' : '确认执行' }}
            </McButton>
            <McButton @click="handleReset">放弃</McButton>
          </div>
        </template>

        <!-- Executing -->
        <template v-if="phase === 'executing'">
          <div class="phase-header">
            <span class="phase-badge executing">执行中</span>
            <span class="phase-text">
              步骤 {{ currentStepIndex }} / {{ steps.length || '...' }}
            </span>
          </div>
          <div v-if="renderedThinking" class="thinking-block">
            <pre>{{ renderedThinking }}</pre>
          </div>
          <!-- Step progress -->
          <div class="steps-progress">
            <div v-for="s in steps" :key="s.index" class="step-row" :class="'step-' + s.status">
              <span class="step-idx">步骤 {{ s.index }}</span>
              <span class="step-status">{{ s.status }}</span>
              <span v-if="s.resultSummary" class="step-result">{{ s.resultSummary }}</span>
              <span v-if="s.error" class="step-error">{{ s.error }}</span>
            </div>
          </div>
          <!-- Task progress for current step -->
          <TaskProgress v-if="tasks.length > 0" :sub-tasks="tasks" />
        </template>

        <!-- Completed -->
        <template v-if="phase === 'completed'">
          <div class="phase-header">
            <span class="phase-badge completed">构建完成</span>
          </div>
          <div class="completed-info">
            已生成 {{ completedCommands.length || 0 }} 条命令，已插入编辑器。
          </div>
          <div v-if="planContent" class="plan-display markdown-body" v-html="renderedPlan" />
          <McButton @click="handleReset">新建构建</McButton>
        </template>

        <!-- Error -->
        <template v-if="phase === 'error'">
          <div class="phase-header">
            <span class="phase-badge error-badge">错误</span>
          </div>
          <div class="error-block">{{ errorMessage }}</div>
          <McButton @click="handleReset">重试</McButton>
        </template>
      </div>
    </McScrollbar>
  </div>
</template>

<style scoped>
.build-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.build-scrollbar {
  flex: 1;
}

.build-content {
  padding: 20px;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* Welcome / Idle */
.build-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 300px;
  text-align: center;
  gap: 12px;
}

.build-title {
  font-family: var(--mc-font-title);
  font-size: 22px;
  color: var(--mc-gold);
  text-shadow: 2px 2px 0 rgba(0, 0, 0, 0.5);
}

.build-desc {
  font-size: 13px;
  color: var(--mc-text-secondary);
  max-width: 480px;
  line-height: 1.6;
}

.build-quota {
  font-size: 12px;
  color: var(--mc-text-dim);
}

.build-input-area {
  width: 100%;
  max-width: 520px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

/* Phase headers */
.phase-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.phase-badge {
  font-family: var(--mc-font-title);
  font-size: 12px;
  padding: 2px 8px;
  border: 2px solid;
}

.phase-badge.planning { color: var(--mc-gold); border-color: var(--mc-gold); }
.phase-badge.clarifying { color: #55FFFF; border-color: #55FFFF; }
.phase-badge.reviewing { color: #55FF55; border-color: #55FF55; }
.phase-badge.executing { color: var(--mc-gold); border-color: var(--mc-gold); }
.phase-badge.completed { color: #55FF55; border-color: #55FF55; }
.phase-badge.error-badge { color: var(--mc-red); border-color: var(--mc-red); }

.phase-text {
  font-size: 13px;
  color: var(--mc-text-secondary);
}

/* Thinking */
.thinking-block {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--mc-border);
  padding: 8px 10px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--mc-text-dim);
  overflow: hidden;
}

.thinking-block pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: var(--mc-font-mono);
}

/* Search */
.search-list {
  margin-bottom: 12px;
}

.search-item {
  font-size: 12px;
  color: var(--mc-text-secondary);
  padding: 2px 0;
}

.search-icon {
  margin-right: 4px;
}

.search-count {
  color: var(--mc-text-dim);
}

/* Clarify */
.clarify-summary {
  font-size: 13px;
  color: var(--mc-text-primary);
  margin-bottom: 12px;
  line-height: 1.6;
}

.suggested-steps {
  margin-bottom: 16px;
  padding: 8px 12px;
  background: rgba(85, 255, 255, 0.05);
  border: 1px solid rgba(85, 255, 255, 0.2);
}

.steps-title {
  font-size: 12px;
  color: #55FFFF;
  margin-bottom: 4px;
  font-family: var(--mc-font-title);
}

.step-item {
  font-size: 12px;
  color: var(--mc-text-secondary);
  padding: 2px 0;
}

.clarify-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.clarify-question label {
  display: block;
  font-size: 13px;
  color: var(--mc-text-primary);
  margin-bottom: 4px;
}

/* Plan display */
.plan-display {
  background: rgba(0, 0, 0, 0.2);
  border: 2px solid var(--mc-border);
  padding: 16px;
  margin-bottom: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--mc-text-primary);
  max-height: 60vh;
  overflow-y: auto;
}

.plan-edit {
  margin-bottom: 12px;
}

.plan-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Markdown in plan */
.plan-display :deep(h1),
.plan-display :deep(h2),
.plan-display :deep(h3) {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  margin: 10px 0 6px;
}

.plan-display :deep(h1) { font-size: 17px; }
.plan-display :deep(h2) { font-size: 15px; }
.plan-display :deep(h3) { font-size: 14px; }

.plan-display :deep(code) {
  font-family: var(--mc-font-mono);
  background: rgba(0, 0, 0, 0.4);
  padding: 1px 4px;
  font-size: 12px;
  color: var(--mc-green);
}

.plan-display :deep(ul),
.plan-display :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.plan-display :deep(li::marker) {
  color: var(--mc-gold);
}

/* Steps progress */
.steps-progress {
  margin-bottom: 12px;
}

.step-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  font-size: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.step-idx {
  color: var(--mc-text-primary);
  font-family: var(--mc-font-title);
  min-width: 50px;
}

.step-status {
  color: var(--mc-text-dim);
  min-width: 60px;
}

.step-complete .step-status { color: #55FF55; }
.step-executing .step-status { color: var(--mc-gold); }
.step-failed .step-status { color: var(--mc-red); }

.step-result {
  color: var(--mc-text-secondary);
  font-size: 11px;
}

.step-error {
  color: var(--mc-red);
  font-size: 11px;
}

/* Completed */
.completed-info {
  font-size: 14px;
  color: #55FF55;
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 2px solid rgba(85, 255, 85, 0.3);
  background: rgba(85, 255, 85, 0.05);
}

/* Error */
.error-block {
  color: var(--mc-red);
  padding: 8px 12px;
  border: 2px solid var(--mc-red);
  background: rgba(176, 46, 38, 0.15);
  font-size: 13px;
  margin-bottom: 12px;
}

.completedCommands {
  margin-bottom: 12px;
}
</style>
