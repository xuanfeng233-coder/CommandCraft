<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'

const props = defineProps<{
  step: string
  steps?: string[]
  isStreaming: boolean
}>()

const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  if (props.isStreaming) {
    timer = setInterval(() => { elapsed.value++ }, 1000)
  }
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const elapsedText = computed(() => {
  if (elapsed.value < 60) return `${elapsed.value}s`
  const m = Math.floor(elapsed.value / 60)
  const s = elapsed.value % 60
  return `${m}m ${s}s`
})

const displaySteps = computed(() => props.steps?.length ? props.steps : [])
</script>

<template>
  <div class="thinking-chain">
    <template v-if="isStreaming">
      <!-- Completed steps -->
      <div
        v-for="(s, i) in displaySteps.slice(0, -1)"
        :key="i"
        class="step-row step-row--done"
      >
        <span class="step-icon step-icon--done">&#x2714;</span>
        <span class="step-label step-label--done">{{ s }}</span>
      </div>

      <!-- Current active step -->
      <div class="step-row step-row--active">
        <span class="step-icon step-icon--active" />
        <span class="step-label step-label--active">
          {{ displaySteps.length ? displaySteps[displaySteps.length - 1] : (step || '思考中...') }}
        </span>
        <span class="elapsed">{{ elapsedText }}</span>
      </div>
    </template>

    <template v-else>
      <!-- All steps completed -->
      <div
        v-for="(s, i) in displaySteps"
        :key="i"
        class="step-row step-row--done"
      >
        <span class="step-icon step-icon--done">&#x2714;</span>
        <span class="step-label step-label--done">{{ s }}</span>
      </div>
      <div v-if="displaySteps.length === 0" class="step-row step-row--done">
        <span class="step-icon step-icon--done">&#x2714;</span>
        <span class="step-label step-label--done">完成</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.thinking-chain {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
  padding: 8px 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--mc-border);
}

.step-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.step-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
}

.step-icon--done {
  color: #55FF55;
}

.step-icon--active {
  background: var(--mc-gold);
  animation: step-pulse 1s ease-in-out infinite;
}

.step-label--done {
  color: #55FF55;
}

.step-label--active {
  color: var(--mc-gold);
  font-weight: 500;
}

.elapsed {
  margin-left: auto;
  font-family: var(--mc-font-mono);
  font-size: 11px;
  color: var(--mc-text-dim);
}

@keyframes step-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
