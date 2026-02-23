<script setup lang="ts">
import { reactive, ref } from 'vue'
import { McCard, McButton, McInput, McRadioGroup, McRadio } from '@/components/mc-ui'
import type { ParameterQuestion } from '@/types'

const props = defineProps<{
  questions: ParameterQuestion[]
}>()

const emit = defineEmits<{
  answer: [answers: Record<string, string>]
}>()

const selections = reactive<Record<string, string>>({})
const useCustom = reactive<Record<string, boolean>>({})
const customValues = reactive<Record<string, string>>({})

const initialized = ref(false)
if (!initialized.value) {
  for (const q of props.questions) {
    if (q.default) {
      selections[q.param] = q.default
    }
    // Questions without options render McInput directly — must use custom mode
    // so handleSubmit reads from customValues instead of selections (defaults)
    if (!q.options || q.options.length === 0) {
      useCustom[q.param] = true
    }
  }
  initialized.value = true
}

function toggleCustom(param: string) {
  useCustom[param] = !useCustom[param]
  if (useCustom[param]) {
    selections[param] = ''
  } else {
    customValues[param] = ''
  }
}

function handleSubmit() {
  const answers: Record<string, string> = {}
  for (const q of props.questions) {
    if (useCustom[q.param]) {
      // Fall back to default if user left the input empty
      answers[q.param] = customValues[q.param] || q.default || ''
    } else {
      answers[q.param] = selections[q.param] ?? ''
    }
  }
  emit('answer', answers)
}

function getEffectiveValue(param: string): string {
  if (useCustom[param]) {
    return customValues[param] ?? ''
  }
  return selections[param] ?? ''
}
</script>

<template>
  <McCard class="parameter-guide" title="参数补充">
    <div class="questions-list">
      <div
        v-for="q in questions"
        :key="q.param"
        class="question-item"
      >
        <div class="question-text">{{ q.question }}</div>

        <template v-if="q.options && q.options.length > 0 && !useCustom[q.param]">
          <McRadioGroup
            :model-value="selections[q.param]"
            @update:model-value="selections[q.param] = $event"
          >
            <McRadio
              v-for="opt in q.options"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </McRadioGroup>
          <McButton
            size="small"
            class="custom-toggle"
            @click="toggleCustom(q.param)"
          >
            自定义输入
          </McButton>
        </template>

        <template v-else>
          <McInput
            :model-value="customValues[q.param]"
            :placeholder="q.default ? `默认: ${q.default}` : '请输入...'"
            @update:model-value="customValues[q.param] = $event"
          />
          <McButton
            v-if="q.options && q.options.length > 0"
            size="small"
            class="custom-toggle"
            @click="toggleCustom(q.param)"
          >
            选择选项
          </McButton>
        </template>

        <div
          v-if="q.default && !getEffectiveValue(q.param)"
          class="default-hint"
        >
          默认值: {{ q.default }}
        </div>
      </div>
    </div>

    <div class="mc-divider" />

    <McButton variant="primary" size="small" @click="handleSubmit">
      提交参数
    </McButton>
  </McCard>
</template>

<style scoped>
.parameter-guide {
  margin: 4px 0;
}

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

.mc-divider {
  height: 2px;
  background: var(--mc-border);
  margin: 12px 0;
}
</style>
