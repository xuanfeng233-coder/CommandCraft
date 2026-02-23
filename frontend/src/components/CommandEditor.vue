<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { McButton, McInput } from '@/components/mc-ui'
import { fetchCommandParams, fetchIdsFull, paramTypeToCategory } from '@/api/knowledge'
import type { CommandTemplate, CommandParamDef, QuestionOption } from '@/types'

const props = defineProps<{
  template: CommandTemplate
}>()

const emit = defineEmits<{
  'update:command': [command: string]
}>()

// Local editable params (initialized from template)
const editParams = ref<Record<string, string>>({})
const paramDefs = ref<CommandParamDef[]>([])
const idOptions = ref<Record<string, QuestionOption[]>>({})
const searchTerms = ref<Record<string, string>>({})
const openDropdown = ref<string | null>(null)

// Initialize from template
onMounted(async () => {
  editParams.value = { ...props.template.params }

  // Use template param_defs if available, otherwise fetch from API
  if (props.template.param_defs?.length) {
    paramDefs.value = props.template.param_defs
  } else {
    paramDefs.value = await fetchCommandParams(props.template.command_name)
  }

  // Pre-load ID options for ID-based params
  for (const pdef of paramDefs.value) {
    const cat = paramTypeToCategory(pdef.type, pdef.name)
    if (cat && !pdef.options?.length) {
      try {
        const entries = await fetchIdsFull(cat)
        idOptions.value[pdef.name] = entries.map(e => ({
          value: e.id,
          label: `${e.id} (${e.name})`,
        }))
      } catch { /* ignore */ }
    }
  }
})

// Compute the full command string
const commandString = computed(() => {
  const parts = [`/${props.template.command_name}`]
  for (const pdef of paramDefs.value) {
    const val = editParams.value[pdef.name]
    if (val) {
      parts.push(val)
    } else if (pdef.required) {
      parts.push(`<${pdef.name}>`)
    }
  }
  return parts.join(' ')
})

// Emit whenever command changes
watch(commandString, (val) => {
  emit('update:command', val)
})

function updateParam(name: string, value: string) {
  editParams.value[name] = value
}

function getOptions(pdef: CommandParamDef): QuestionOption[] {
  // First check inline options from template
  if (pdef.options?.length) return pdef.options
  // Then check loaded ID options
  if (idOptions.value[pdef.name]?.length) return idOptions.value[pdef.name]
  // Pipe-delimited type auto-generates options
  if (pdef.type.includes('|') && !pdef.type.includes(' ')) {
    return pdef.type.split('|').map(v => ({ value: v.trim(), label: v.trim() }))
  }
  return []
}

function filteredOptions(pdef: CommandParamDef): QuestionOption[] {
  const opts = getOptions(pdef)
  const term = (searchTerms.value[pdef.name] || '').toLowerCase()
  if (!term) return opts.slice(0, 30)
  return opts.filter(o =>
    o.value.toLowerCase().includes(term) || o.label.toLowerCase().includes(term)
  ).slice(0, 30)
}

function isTargetType(pdef: CommandParamDef): boolean {
  return pdef.type === 'target' || ['player', 'target', 'origin', 'destination'].includes(pdef.name)
}

const ENUM_TYPES = new Set([
  'Boolean', 'boolean', 'GameMode', 'gamemode', 'Difficulty',
  'FillMode', 'SetBlockMode', 'MaskMode', 'CloneMode',
  'DamageCause', 'HudElement', 'InputPermission', 'Ability',
  'EaseType', 'CameraPreset', 'MobEvent', 'Dimension',
  'EntityEquipmentSlot', 'operator',
])

function isEnumType(pdef: CommandParamDef): boolean {
  if (ENUM_TYPES.has(pdef.type)) return true
  // Pipe-delimited types like "hide|reset"
  if (pdef.type.includes('|') && !pdef.type.includes(' ')) return true
  // Backend-provided small option sets that aren't ID categories
  const opts = getOptions(pdef)
  if (opts.length > 0 && opts.length <= 30 && !paramTypeToCategory(pdef.type, pdef.name)) return true
  return false
}

function isIdType(pdef: CommandParamDef): boolean {
  if (isTargetType(pdef)) return false
  if (isEnumType(pdef)) return false
  return paramTypeToCategory(pdef.type, pdef.name) !== null || (pdef.options?.length ?? 0) > 30
}

function isNumberType(pdef: CommandParamDef): boolean {
  return pdef.type === 'int' || pdef.type === 'float'
}

function selectOption(pname: string, value: string) {
  updateParam(pname, value)
  openDropdown.value = null
  searchTerms.value[pname] = ''
}

function toggleDropdown(pname: string) {
  openDropdown.value = openDropdown.value === pname ? null : pname
}

const copied = ref(false)
async function copyCommand() {
  try {
    await navigator.clipboard.writeText(commandString.value)
  } catch {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = commandString.value
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}
</script>

<template>
  <div class="command-editor">
    <!-- Live command preview -->
    <div class="preview-bar">
      <code class="preview-text">{{ commandString }}</code>
      <McButton size="small" :variant="copied ? 'primary' : 'default'" @click="copyCommand">
        {{ copied ? '已复制' : '复制' }}
      </McButton>
    </div>

    <!-- Parameter fields -->
    <div class="params-grid">
      <div
        v-for="pdef in paramDefs"
        :key="pdef.name"
        class="param-field"
      >
        <label class="param-label">
          {{ pdef.description || pdef.name }}
          <span v-if="pdef.required" class="required-mark">*</span>
          <span v-if="pdef.range" class="range-hint">({{ pdef.range }})</span>
        </label>

        <!-- Target selector: simple dropdown -->
        <div v-if="isTargetType(pdef)" class="select-wrapper">
          <select
            class="mc-select"
            :value="editParams[pdef.name] || ''"
            @change="updateParam(pdef.name, ($event.target as HTMLSelectElement).value)"
          >
            <option value="" disabled>选择目标...</option>
            <option
              v-for="opt in getOptions(pdef)"
              :key="opt.value"
              :value="opt.value"
            >{{ opt.label }}</option>
          </select>
        </div>

        <!-- Enum type: simple dropdown (Boolean, GameMode, FillMode, etc.) -->
        <div v-else-if="isEnumType(pdef)" class="select-wrapper">
          <select
            class="mc-select"
            :value="editParams[pdef.name] || ''"
            @change="updateParam(pdef.name, ($event.target as HTMLSelectElement).value)"
          >
            <option value="" disabled>选择{{ pdef.description || pdef.name }}...</option>
            <option
              v-for="opt in getOptions(pdef)"
              :key="opt.value"
              :value="opt.value"
            >{{ opt.label }}</option>
          </select>
        </div>

        <!-- ID-based: searchable dropdown -->
        <div v-else-if="isIdType(pdef)" class="search-select">
          <div class="search-input-row">
            <input
              class="mc-input search-input"
              :value="editParams[pdef.name] || ''"
              :placeholder="`搜索${pdef.description || pdef.name}...`"
              spellcheck="false"
              autocorrect="off"
              autocomplete="off"
              @input="searchTerms[pdef.name] = ($event.target as HTMLInputElement).value; updateParam(pdef.name, ($event.target as HTMLInputElement).value)"
              @focus="openDropdown = pdef.name"
            />
            <button class="dropdown-toggle" @click="toggleDropdown(pdef.name)">▾</button>
          </div>
          <div v-if="openDropdown === pdef.name" class="dropdown-list">
            <div
              v-for="opt in filteredOptions(pdef)"
              :key="opt.value"
              class="dropdown-item"
              :class="{ active: editParams[pdef.name] === opt.value }"
              @mousedown.prevent="selectOption(pdef.name, opt.value)"
            >
              {{ opt.label }}
            </div>
            <div v-if="filteredOptions(pdef).length === 0" class="dropdown-empty">
              无匹配结果
            </div>
          </div>
        </div>

        <!-- Number input -->
        <div v-else-if="isNumberType(pdef)">
          <input
            class="mc-input number-input"
            type="number"
            :value="editParams[pdef.name] || ''"
            :placeholder="pdef.default ?? ''"
            spellcheck="false"
            autocomplete="off"
            @input="updateParam(pdef.name, ($event.target as HTMLInputElement).value)"
          />
        </div>

        <!-- Default text input -->
        <div v-else>
          <McInput
            :model-value="editParams[pdef.name] || ''"
            :placeholder="pdef.default ?? pdef.description ?? ''"
            @update:model-value="updateParam(pdef.name, $event)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.command-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.preview-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-sunken);
  padding: 8px 12px;
}

.preview-text {
  flex: 1;
  font-family: var(--mc-font-mono);
  font-size: 14px;
  color: var(--mc-syn-command);
  white-space: pre-wrap;
  word-break: break-all;
}

.params-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.param-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-label {
  font-size: 12px;
  color: var(--mc-text-dim);
  font-weight: 500;
}

.required-mark {
  color: var(--mc-red, #ff5555);
}

.range-hint {
  color: var(--mc-text-dim);
  font-size: 11px;
}

.mc-select {
  width: 100%;
  font-family: var(--mc-font-body);
  font-size: 14px;
  color: var(--mc-text-primary);
  background-color: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-sunken);
  padding: 6px 8px;
  outline: none;
  cursor: pointer;
}

.mc-select:focus {
  border-color: var(--mc-green);
}

.search-select {
  position: relative;
}

.search-input-row {
  display: flex;
}

.search-input {
  flex: 1;
  width: 100%;
  font-family: var(--mc-font-body);
  font-size: 14px;
  color: var(--mc-text-primary);
  background-color: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-sunken);
  padding: 6px 8px;
  outline: none;
}

.search-input:focus {
  border-color: var(--mc-green);
}

.dropdown-toggle {
  background: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  border-left: none;
  color: var(--mc-text-dim);
  padding: 0 8px;
  cursor: pointer;
  font-size: 12px;
}

.dropdown-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  max-height: 200px;
  overflow-y: auto;
  background: var(--mc-bg-surface);
  border: 2px solid var(--mc-border);
  z-index: 100;
}

.dropdown-item {
  padding: 6px 10px;
  font-size: 13px;
  color: var(--mc-text-secondary);
  cursor: pointer;
}

.dropdown-item:hover {
  background: var(--mc-bg-hover);
  color: var(--mc-text-primary);
}

.dropdown-item.active {
  background: rgba(85, 255, 85, 0.15);
  color: var(--mc-green);
}

.dropdown-empty {
  padding: 8px 10px;
  font-size: 12px;
  color: var(--mc-text-dim);
  text-align: center;
}

.number-input {
  width: 120px;
  font-family: var(--mc-font-body);
  font-size: 14px;
  color: var(--mc-text-primary);
  background-color: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-sunken);
  padding: 6px 8px;
  outline: none;
}

.number-input:focus {
  border-color: var(--mc-green);
}
</style>
