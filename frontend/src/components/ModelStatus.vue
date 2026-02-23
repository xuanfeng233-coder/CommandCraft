<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { getHealth } from '@/api/model'
import { useSubscriptionStore } from '@/stores/subscription'

const emit = defineEmits<{ 'open-settings': [] }>()

const subStore = useSubscriptionStore()

const status = ref<'ok' | 'not_configured' | 'api_unreachable' | 'model_unavailable' | 'unknown'>('unknown')
const providerName = ref('')
const modelName = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try {
    const data = await getHealth()
    status.value = data.status as typeof status.value
    providerName.value = data.provider_name
    modelName.value = data.model_name
  } catch {
    status.value = 'unknown'
  }
}

onMounted(async () => {
  await poll()
  pollTimer = setInterval(poll, 30000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function displayLabel(): string {
  switch (status.value) {
    case 'ok':
      return providerName.value && modelName.value
        ? `${providerName.value} / ${modelName.value}`
        : modelName.value || '已连接'
    case 'not_configured':
      return '未配置'
    case 'api_unreachable':
      return 'API 不可达'
    case 'model_unavailable':
      return '模型不可用'
    default:
      return '检测中...'
  }
}
</script>

<template>
  <div class="model-status" @click="emit('open-settings')" role="button" tabindex="0">
    <span
      class="status-dot"
      :class="{
        'status-dot--on': status === 'ok' || subStore.isActive,
        'status-dot--off': status === 'not_configured' && !subStore.isActive,
        'status-dot--offline': (status === 'api_unreachable' || status === 'model_unavailable') && !subStore.isActive,
        'status-dot--unknown': status === 'unknown' && !subStore.isActive,
      }"
    />
    <span class="status-label">
      {{ subStore.isActive ? `订阅: ${subStore.planName} (${subStore.usageText})` : displayLabel() }}
    </span>
  </div>
</template>

<style scoped>
.model-status {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.model-status:hover .status-label {
  color: var(--mc-gold);
}

.status-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
}

.status-dot--on {
  background: var(--mc-green);
  box-shadow: 0 0 6px var(--mc-green);
}

.status-dot--off {
  background: var(--mc-red);
  box-shadow: 0 0 6px var(--mc-red);
}

.status-dot--offline {
  background: var(--mc-red);
  box-shadow: 0 0 6px var(--mc-red);
}

.status-dot--unknown {
  background: var(--mc-text-dim);
  box-shadow: none;
}

.status-label {
  font-family: var(--mc-font-mono);
  font-size: 12px;
  color: #ffffff;
  transition: color 150ms;
}
</style>
