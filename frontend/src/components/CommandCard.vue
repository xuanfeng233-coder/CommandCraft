<script setup lang="ts">
import { ref, computed } from 'vue'
import { McCard, McButton, McTag } from '@/components/mc-ui'
import CommandEditor from '@/components/CommandEditor.vue'
import { useEditorStore } from '@/stores/editor'
import type { CommandOutput } from '@/types'

const props = defineProps<{
  command: CommandOutput
}>()

const editorStore = useEditorStore()
const copied = ref(false)
const goldFlash = ref(false)
const editMode = ref(false)
const editedCommand = ref('')

const hasTemplate = computed(() => !!props.command.template)

function onEditorUpdate(cmd: string) {
  editedCommand.value = cmd
}

function toggleEditMode() {
  editMode.value = !editMode.value
  if (editMode.value) {
    editedCommand.value = props.command.command
  }
}

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(props.command.command)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = props.command.command
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
  copied.value = true
  goldFlash.value = true
  setTimeout(() => { copied.value = false }, 2000)
  setTimeout(() => { goldFlash.value = false }, 300)
}

const coloredSegments = computed(() => {
  const cmd = props.command.command
  if (!cmd) return [{ text: '', cls: '' }]

  const segments: { text: string; cls: string }[] = []
  let remaining = cmd

  if (remaining.startsWith('/')) {
    segments.push({ text: '/', cls: 'cmd-slash' })
    remaining = remaining.slice(1)
  }

  const cmdNameMatch = remaining.match(/^(\S+)/)
  if (cmdNameMatch) {
    segments.push({ text: cmdNameMatch[1], cls: 'cmd-name' })
    remaining = remaining.slice(cmdNameMatch[1].length)
  }

  if (remaining) {
    const tokenPattern =
      /(\s+)|(@[aeprs](?:\[[^\]]*\])?)|("(?:[^"\\]|\\.)*")|(\S+)/g
    let match: RegExpExecArray | null
    while ((match = tokenPattern.exec(remaining)) !== null) {
      const [full] = match
      if (match[1]) {
        segments.push({ text: full, cls: '' })
      } else if (match[2]) {
        segments.push({ text: full, cls: 'cmd-selector' })
      } else if (match[3]) {
        segments.push({ text: full, cls: 'cmd-string' })
      } else if (match[4]) {
        if (/^-?\d+(\.\d+)?$/.test(full)) {
          segments.push({ text: full, cls: 'cmd-number' })
        } else if (full.startsWith('~') || full.startsWith('^')) {
          segments.push({ text: full, cls: 'cmd-relative' })
        } else {
          segments.push({ text: full, cls: 'cmd-param' })
        }
      }
    }
  }

  return segments
})
</script>

<template>
  <McCard class="command-card">
    <template #header>
      <span class="card-title">生成命令</span>
      <McTag
        v-if="command.validation"
        :type="command.validation.valid ? 'success' : 'error'"
        size="tiny"
      >
        {{ command.validation.valid ? '校验通过' : `${command.validation.error_count} 个问题` }}
      </McTag>
    </template>
    <template #header-extra>
      <div class="header-buttons">
        <McButton
          v-if="hasTemplate"
          size="small"
          :variant="editMode ? 'primary' : 'default'"
          @click="toggleEditMode"
        >
          {{ editMode ? '查看命令' : '编辑参数' }}
        </McButton>
        <McButton
          size="small"
          @click="editorStore.insertCommand(editMode ? editedCommand : command.command)"
        >
          插入编辑器
        </McButton>
        <McButton
          size="small"
          :variant="copied ? 'primary' : 'default'"
          @click="copyCommand"
        >
          {{ copied ? '已复制' : '复制' }}
        </McButton>
      </div>
    </template>

    <!-- Edit mode: parameter editor -->
    <CommandEditor
      v-if="editMode && command.template"
      :template="command.template"
      @update:command="onEditorUpdate"
    />

    <!-- View mode: syntax-highlighted command -->
    <div v-else class="command-code" :class="{ 'gold-flash': goldFlash }">
      <code class="command-line">
        <span
          v-for="(seg, idx) in coloredSegments"
          :key="idx"
          :class="seg.cls"
        >{{ seg.text }}</span>
      </code>
    </div>

    <div v-if="command.explanation" class="mc-divider" />

    <div v-if="command.explanation" class="explanation">
      <div class="section-label">命令说明</div>
      <div class="explanation-text">{{ command.explanation }}</div>
    </div>

    <template v-if="command.variants && command.variants.length > 0">
      <div class="mc-divider" />
      <div class="variants">
        <div class="section-label">其他写法</div>
        <div class="variants-list">
          <code
            v-for="(variant, idx) in command.variants"
            :key="idx"
            class="variant-code"
          >{{ variant }}</code>
        </div>
      </div>
    </template>

    <template v-if="command.warnings && command.warnings.length > 0">
      <div class="mc-divider" />
      <div class="warnings-list">
        <div
          v-for="(warning, idx) in command.warnings"
          :key="idx"
          class="warning-item"
        >
          ⚠ {{ warning }}
        </div>
      </div>
    </template>
  </McCard>
</template>

<style scoped>
.command-card {
  margin: 4px 0;
}

.header-buttons {
  display: flex;
  gap: 4px;
}

.card-title {
  font-family: var(--mc-font-title);
  font-size: 14px;
  font-weight: bold;
  color: var(--mc-gold);
}

.command-code {
  background-color: var(--mc-bg-deep);
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-sunken);
  padding: 12px 16px;
  overflow-x: auto;
}

.command-line {
  font-family: var(--mc-font-mono);
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--mc-text-primary);
}

.cmd-slash { color: var(--mc-syn-command); }
.cmd-name { color: var(--mc-syn-command); font-weight: bold; }
.cmd-selector { color: var(--mc-syn-selector); }
.cmd-string { color: var(--mc-syn-string); }
.cmd-number { color: var(--mc-syn-number); }
.cmd-relative { color: var(--mc-syn-optional); }
.cmd-param { color: var(--mc-syn-required); }

.mc-divider {
  height: 2px;
  background: var(--mc-border);
  margin: 12px 0;
}

.section-label {
  font-size: 12px;
  color: var(--mc-gold);
  margin-bottom: 4px;
  font-weight: 500;
}

.explanation-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--mc-text-primary);
}

.variants-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.variant-code {
  display: block;
  font-family: var(--mc-font-mono);
  font-size: 13px;
  background-color: var(--mc-bg-deep);
  padding: 6px 10px;
  color: var(--mc-text-secondary);
  border: 1px solid var(--mc-border);
}

.warnings-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.warning-item {
  font-size: 13px;
  color: var(--mc-gold);
  padding: 6px 8px;
  background: rgba(221, 165, 32, 0.1);
  border: 1px solid rgba(221, 165, 32, 0.3);
}

.gold-flash {
  animation: mc-gold-flash 300ms ease-out;
}
</style>
