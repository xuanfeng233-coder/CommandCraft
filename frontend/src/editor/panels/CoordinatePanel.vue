<script setup lang="ts">
import { ref, computed } from 'vue'

const emit = defineEmits<{
  select: [value: string]
}>()

type CoordMode = 'absolute' | 'relative' | 'local'

const mode = ref<CoordMode>('relative')
const x = ref('0')
const y = ref('0')
const z = ref('0')

const prefix = computed(() => {
  if (mode.value === 'relative') return '~'
  if (mode.value === 'local') return '^'
  return ''
})

const coordString = computed(() => {
  const p = prefix.value
  const xv = x.value || '0'
  const yv = y.value || '0'
  const zv = z.value || '0'

  if (mode.value === 'absolute') {
    return `${xv} ${yv} ${zv}`
  }

  // For relative/local, omit the number if it's 0
  const xStr = xv === '0' ? p : `${p}${xv}`
  const yStr = yv === '0' ? p : `${p}${yv}`
  const zStr = zv === '0' ? p : `${p}${zv}`
  return `${xStr} ${yStr} ${zStr}`
})

function insertCoord() {
  emit('select', coordString.value)
}

function insertPreset(value: string) {
  emit('select', value)
}
</script>

<template>
  <div class="panel-content">
    <div class="panel-header">
      <span class="panel-label">坐标</span>
      <div class="mode-buttons">
        <button
          class="mode-btn"
          :class="{ active: mode === 'relative' }"
          @click="mode = 'relative'"
        >
          ~ 相对
        </button>
        <button
          class="mode-btn"
          :class="{ active: mode === 'local' }"
          @click="mode = 'local'"
        >
          ^ 局部
        </button>
        <button
          class="mode-btn"
          :class="{ active: mode === 'absolute' }"
          @click="mode = 'absolute'"
        >
          绝对
        </button>
      </div>
    </div>

    <div class="coord-inputs">
      <div class="coord-field">
        <label class="coord-label">X</label>
        <input v-model="x" class="coord-input" type="text" placeholder="0" />
      </div>
      <div class="coord-field">
        <label class="coord-label">Y</label>
        <input v-model="y" class="coord-input" type="text" placeholder="0" />
      </div>
      <div class="coord-field">
        <label class="coord-label">Z</label>
        <input v-model="z" class="coord-input" type="text" placeholder="0" />
      </div>
      <button class="insert-btn" @click="insertCoord">
        {{ coordString }}
      </button>
    </div>

    <div class="presets">
      <span class="presets-label">常用:</span>
      <button class="preset-btn" @click="insertPreset('~ ~ ~')">~ ~ ~</button>
      <button class="preset-btn" @click="insertPreset('~ ~1 ~')">~ ~1 ~</button>
      <button class="preset-btn" @click="insertPreset('^ ^ ^1')">^ ^ ^1</button>
      <button class="preset-btn" @click="insertPreset('0 0 0')">0 0 0</button>
    </div>
  </div>
</template>

<style scoped>
.panel-content {
  padding: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.panel-label {
  font-family: var(--mc-font-title);
  font-size: 12px;
  color: var(--mc-text-secondary);
  flex-shrink: 0;
}

.mode-buttons {
  display: flex;
  gap: 4px;
}

.mode-btn {
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-dim);
  font-family: var(--mc-font-mono);
  font-size: 11px;
  padding: 2px 8px;
  cursor: pointer;
}

.mode-btn.active {
  background: var(--mc-bg-hover);
  color: var(--mc-gold);
  border-color: var(--mc-gold);
}

.mode-btn:hover {
  background: var(--mc-bg-hover);
}

.coord-inputs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.coord-field {
  display: flex;
  align-items: center;
  gap: 4px;
}

.coord-label {
  font-family: var(--mc-font-mono);
  font-size: 12px;
  color: var(--mc-syn-optional);
  font-weight: bold;
}

.coord-input {
  width: 48px;
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  color: var(--mc-text-primary);
  font-family: var(--mc-font-mono);
  font-size: 12px;
  padding: 2px 4px;
  outline: none;
  text-align: center;
}

.coord-input:focus {
  border-color: var(--mc-gold);
}

.insert-btn {
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-green);
  color: var(--mc-syn-command);
  font-family: var(--mc-font-mono);
  font-size: 12px;
  padding: 2px 10px;
  cursor: pointer;
  margin-left: auto;
}

.insert-btn:hover {
  background: var(--mc-green);
  color: var(--mc-text-primary);
}

.presets {
  display: flex;
  align-items: center;
  gap: 4px;
}

.presets-label {
  font-size: 11px;
  color: var(--mc-text-dim);
}

.preset-btn {
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-syn-optional);
  font-family: var(--mc-font-mono);
  font-size: 11px;
  padding: 2px 6px;
  cursor: pointer;
}

.preset-btn:hover {
  background: var(--mc-bg-hover);
  border-color: var(--mc-gold);
}
</style>
