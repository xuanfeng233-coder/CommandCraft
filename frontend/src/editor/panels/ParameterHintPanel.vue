<script setup lang="ts">
import { computed } from 'vue'
import type { CursorContext } from '../state-machine/types'
import { FIXED_OPTIONS } from '../constants/type-mappings'

const props = defineProps<{
  context: CursorContext
}>()

const emit = defineEmits<{
  select: [value: string]
}>()

/** Build syntax signature with current param highlighted */
const syntaxParts = computed(() => {
  const ctx = props.context
  if (!ctx.commandDef) return []

  const parts: { text: string; active: boolean }[] = []
  parts.push({ text: '/' + ctx.commandDef.name, active: false })

  const params = ctx.commandDef.parameters
  for (let i = 0; i < params.length; i++) {
    const p = params[i]
    if (p.type === '子命令') continue // Skip subcommand entries in syntax bar
    const label = p.required ? `<${p.name}>` : `[${p.name}]`
    parts.push({ text: label, active: i === ctx.paramIndex })
  }
  return parts
})

/** Current param info to display */
const paramInfo = computed<{
  name: string
  type: string
  required: boolean
  description: string
  defaultVal?: string
  range?: string
} | null>(() => {
  const ctx = props.context
  // Prefer sub-param info
  if (ctx.currentSubParam) {
    return {
      name: ctx.currentSubParam.name,
      type: ctx.currentSubParam.type,
      required: ctx.currentSubParam.required,
      description: ctx.subcommandVariant?.description ?? '',
    }
  }
  if (ctx.currentParam) {
    return {
      name: ctx.currentParam.name,
      type: ctx.currentParam.type,
      required: ctx.currentParam.required,
      description: ctx.currentParam.description ?? '',
      defaultVal: ctx.currentParam.default,
      range: ctx.currentParam.range,
    }
  }
  return null
})

/** Fixed options for the current param type (with descriptions) */
const fixedOptions = computed(() => {
  const ctx = props.context
  const type = ctx.expectedType
  if (!type) return null

  // Check FIXED_OPTIONS
  const opts = FIXED_OPTIONS[type]
  if (opts) return opts

  // Check sub-param literal options
  if (ctx.currentSubParam?.options) {
    return ctx.currentSubParam.options.map((o) => ({ value: o, description: '' }))
  }

  return null
})

/** Subcommand list when at keyword position */
const subcommandList = computed(() => {
  const ctx = props.context
  if (ctx.expectedType !== '子命令' || !ctx.availableSubcommands) return null

  // Deduplicate by first keyword
  const seen = new Set<string>()
  const items: { keyword: string; description: string; syntax: string }[] = []
  for (const v of ctx.availableSubcommands) {
    const kw = v.keywords[0]
    if (!kw || seen.has(kw)) continue
    seen.add(kw)
    const paramParts = v.params.map((p) =>
      p.required ? `<${p.name}>` : `[${p.name}]`
    )
    items.push({
      keyword: kw,
      description: v.description,
      syntax: [...v.keywords, ...paramParts].join(' '),
    })
  }
  return items.length > 0 ? items : null
})

/** Whether anything is visible */
const hasContent = computed(() => {
  return paramInfo.value || fixedOptions.value || subcommandList.value
})

function onOptionClick(value: string) {
  emit('select', value)
}
</script>

<template>
  <div v-if="hasContent" class="hint-panel">
    <!-- Syntax overview bar -->
    <div v-if="syntaxParts.length > 0" class="syntax-bar">
      <span
        v-for="(part, i) in syntaxParts"
        :key="i"
        :class="['syntax-token', { active: part.active }]"
      >{{ part.text }}</span>
    </div>

    <!-- Current parameter details -->
    <div v-if="paramInfo && context.expectedType !== '子命令'" class="param-detail">
      <div class="param-header">
        <span class="param-name">{{ paramInfo.name }}</span>
        <span class="param-type">{{ paramInfo.type }}</span>
        <span :class="['param-badge', paramInfo.required ? 'required' : 'optional']">
          {{ paramInfo.required ? '必填' : '可选' }}
        </span>
        <span v-if="paramInfo.defaultVal" class="param-default">
          默认: {{ paramInfo.defaultVal }}
        </span>
        <span v-if="paramInfo.range" class="param-range">
          范围: {{ paramInfo.range }}
        </span>
      </div>
      <div v-if="paramInfo.description" class="param-desc">
        {{ paramInfo.description }}
      </div>
    </div>

    <!-- Fixed options grid -->
    <div v-if="fixedOptions && context.expectedType !== '子命令'" class="options-grid">
      <button
        v-for="opt in fixedOptions"
        :key="opt.value"
        class="option-item"
        @click="onOptionClick(opt.value)"
      >
        <span class="option-value">{{ opt.value }}</span>
        <span v-if="opt.description" class="option-desc">{{ opt.description }}</span>
      </button>
    </div>

    <!-- Subcommand list -->
    <div v-if="subcommandList" class="subcmd-list">
      <div class="subcmd-header">子命令</div>
      <button
        v-for="item in subcommandList"
        :key="item.keyword"
        class="subcmd-item"
        @click="onOptionClick(item.keyword)"
      >
        <div class="subcmd-top">
          <span class="subcmd-keyword">{{ item.keyword }}</span>
          <span class="subcmd-syntax">{{ item.syntax }}</span>
        </div>
        <div v-if="item.description" class="subcmd-desc">{{ item.description }}</div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.hint-panel {
  padding: 6px 8px;
  max-height: 180px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--mc-border) transparent;
}

.syntax-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 0;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--mc-border);
  font-family: var(--mc-font-mono);
  font-size: 12px;
}

.syntax-token {
  color: var(--mc-text-dim);
}

.syntax-token.active {
  color: var(--mc-syn-command, #55ff55);
  font-weight: bold;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.param-detail {
  margin-bottom: 4px;
}

.param-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}

.param-name {
  font-family: var(--mc-font-mono);
  color: var(--mc-text-primary);
  font-weight: bold;
}

.param-type {
  font-family: var(--mc-font-mono);
  color: var(--mc-syn-optional, #aaaaaa);
  font-size: 11px;
}

.param-badge {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 2px;
  font-family: var(--mc-font-body);
}

.param-badge.required {
  background: rgba(255, 85, 85, 0.2);
  color: #ff5555;
  border: 1px solid rgba(255, 85, 85, 0.4);
}

.param-badge.optional {
  background: rgba(85, 85, 255, 0.2);
  color: #8888ff;
  border: 1px solid rgba(85, 85, 255, 0.4);
}

.param-default,
.param-range {
  font-size: 11px;
  color: var(--mc-text-dim);
  font-family: var(--mc-font-mono);
}

.param-desc {
  font-size: 11px;
  color: var(--mc-text-secondary);
  font-family: var(--mc-font-body);
  margin-top: 2px;
  line-height: 1.4;
}

.options-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin-top: 4px;
}

.option-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-primary);
  padding: 2px 6px;
  font-family: var(--mc-font-mono);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}

.option-item:hover {
  background: var(--mc-bg-hover);
  border-color: var(--mc-gold);
}

.option-value {
  color: var(--mc-syn-optional, #aaaaaa);
}

.option-desc {
  color: var(--mc-text-dim);
  font-family: var(--mc-font-body);
  font-size: 10px;
}

.subcmd-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.subcmd-header {
  font-family: var(--mc-font-title);
  font-size: 11px;
  color: var(--mc-text-secondary);
  margin-bottom: 2px;
}

.subcmd-item {
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-primary);
  padding: 4px 6px;
  cursor: pointer;
  text-align: left;
}

.subcmd-item:hover {
  background: var(--mc-bg-hover);
  border-color: var(--mc-gold);
}

.subcmd-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subcmd-keyword {
  font-family: var(--mc-font-mono);
  font-size: 12px;
  font-weight: bold;
  color: var(--mc-syn-command, #55ff55);
}

.subcmd-syntax {
  font-family: var(--mc-font-mono);
  font-size: 11px;
  color: var(--mc-text-dim);
}

.subcmd-desc {
  font-size: 10px;
  color: var(--mc-text-secondary);
  font-family: var(--mc-font-body);
  margin-top: 2px;
}
</style>
