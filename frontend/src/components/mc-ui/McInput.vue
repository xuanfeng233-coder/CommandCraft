<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps<{
  modelValue?: string
  placeholder?: string
  disabled?: boolean
  type?: 'text' | 'textarea'
  autosize?: { minRows?: number; maxRows?: number }
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  keydown: [e: KeyboardEvent]
}>()

const textareaRef = ref<HTMLTextAreaElement | null>(null)

const isTextarea = computed(() => props.type === 'textarea')

function onInput(e: Event) {
  const target = e.target as HTMLInputElement | HTMLTextAreaElement
  emit('update:modelValue', target.value)
}

function adjustHeight() {
  if (!isTextarea.value || !textareaRef.value) return
  const el = textareaRef.value
  el.style.height = 'auto'
  const lineHeight = 22
  const minH = (props.autosize?.minRows || 1) * lineHeight + 12
  const maxH = (props.autosize?.maxRows || 8) * lineHeight + 12
  const scrollH = Math.min(Math.max(el.scrollHeight, minH), maxH)
  el.style.height = scrollH + 'px'
}

watch(() => props.modelValue, () => {
  nextTick(adjustHeight)
})
</script>

<template>
  <textarea
    v-if="isTextarea"
    ref="textareaRef"
    class="mc-input mc-input--textarea"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    spellcheck="false"
    autocorrect="off"
    autocapitalize="off"
    autocomplete="off"
    @input="onInput"
    @keydown="$emit('keydown', $event)"
    @vue:mounted="adjustHeight"
  />
  <input
    v-else
    class="mc-input"
    type="text"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    spellcheck="false"
    autocorrect="off"
    autocapitalize="off"
    autocomplete="off"
    @input="onInput"
    @keydown="$emit('keydown', $event)"
  />
</template>

<style scoped>
.mc-input {
  width: 100%;
  font-family: var(--mc-font-body);
  font-size: 14px;
  color: var(--mc-text-primary);
  background-color: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-sunken);
  padding: 6px 8px;
  outline: none;
  transition: border-color 150ms;
}

.mc-input::placeholder {
  color: var(--mc-text-dim);
}

.mc-input:focus {
  border-color: var(--mc-green);
}

.mc-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mc-input--textarea {
  resize: none;
  line-height: 22px;
  min-height: 34px;
}
</style>
