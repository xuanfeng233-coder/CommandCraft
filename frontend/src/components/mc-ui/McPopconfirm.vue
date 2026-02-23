<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'

defineProps<{
  confirmText?: string
  cancelText?: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const visible = ref(false)
const wrapperRef = ref<HTMLElement | null>(null)

function toggle(e: Event) {
  e.stopPropagation()
  visible.value = !visible.value
}

function handleConfirm(e: Event) {
  e.stopPropagation()
  visible.value = false
  emit('confirm')
}

function handleCancel(e: Event) {
  e.stopPropagation()
  visible.value = false
  emit('cancel')
}

function onClickOutside(e: MouseEvent) {
  if (wrapperRef.value && !wrapperRef.value.contains(e.target as Node)) {
    visible.value = false
  }
}

onMounted(() => document.addEventListener('click', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('click', onClickOutside))
</script>

<template>
  <span ref="wrapperRef" class="mc-popconfirm-wrapper">
    <span @click="toggle">
      <slot name="trigger" />
    </span>
    <div v-if="visible" class="mc-popconfirm">
      <div class="mc-popconfirm-msg">
        <slot>确认操作？</slot>
      </div>
      <div class="mc-popconfirm-actions">
        <button class="mc-pop-btn mc-pop-btn--cancel" @click="handleCancel">
          {{ cancelText || '取消' }}
        </button>
        <button class="mc-pop-btn mc-pop-btn--confirm" @click="handleConfirm">
          {{ confirmText || '确认' }}
        </button>
      </div>
    </div>
  </span>
</template>

<style scoped>
.mc-popconfirm-wrapper {
  position: relative;
  display: inline-flex;
}

.mc-popconfirm {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  padding: 8px;
  z-index: 1050;
  min-width: 140px;
  box-shadow: 2px 2px 0 rgba(0,0,0,0.5);
}

.mc-popconfirm-msg {
  font-size: 12px;
  color: var(--mc-text-primary);
  margin-bottom: 8px;
}

.mc-popconfirm-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}

.mc-pop-btn {
  font-family: var(--mc-font-body);
  font-size: 11px;
  border: 2px solid var(--mc-border);
  padding: 2px 8px;
  cursor: pointer;
}

.mc-pop-btn--cancel {
  background: var(--mc-bg-card);
  color: var(--mc-text-secondary);
}

.mc-pop-btn--confirm {
  background: var(--mc-red);
  color: #fff;
  border-color: #8b201a;
}

.mc-pop-btn:hover {
  opacity: 0.85;
}
</style>
