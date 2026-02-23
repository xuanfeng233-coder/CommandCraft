<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { EditorView } from '@codemirror/view'
import { McButton } from '@/components/mc-ui'
import { useEditorStore } from '@/stores/editor'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import { useCodeMirror } from './setup'
import { mcCompletion } from './extensions/mc-completion'
import { mcValidation } from './extensions/mc-validation'
import { parseCursorContext } from './state-machine/command-parser'
import type { CursorContext } from './state-machine/types'
import ItemPanel from './panels/ItemPanel.vue'
import EnchantmentPanel from './panels/EnchantmentPanel.vue'
import EntityPanel from './panels/EntityPanel.vue'
import EffectPanel from './panels/EffectPanel.vue'
import CoordinatePanel from './panels/CoordinatePanel.vue'
import ParameterHintPanel from './panels/ParameterHintPanel.vue'
import McToolbox from './panels/McToolbox.vue'
import { undo, redo } from '@codemirror/commands'

const TOOLBOX_KEY = 'mcbe-ai-toolbox-open'
const showToolbox = ref(
  localStorage.getItem(TOOLBOX_KEY) !== 'false'
)

function handleToggleToolbox() {
  showToolbox.value = !showToolbox.value
  localStorage.setItem(TOOLBOX_KEY, String(showToolbox.value))
}

const editorStore = useEditorStore()
const knowledgeCache = useKnowledgeCache()
const containerRef = ref<HTMLElement | null>(null)

const cursorLine = ref(1)
const cursorCol = ref(1)
const cursorContext = ref<CursorContext | null>(null)

/** Extension that tracks cursor position and context */
const cursorTracker = EditorView.updateListener.of((update) => {
  if (update.selectionSet || update.docChanged) {
    const pos = update.state.selection.main.head
    const line = update.state.doc.lineAt(pos)
    cursorLine.value = line.number
    cursorCol.value = pos - line.from + 1

    // Update cursor context for panels
    if (knowledgeCache.loaded) {
      try {
        cursorContext.value = parseCursorContext(
          line.text,
          pos - line.from,
          (name) => knowledgeCache.getCommand(name),
          (name) => knowledgeCache.getSubcommandTree(name)
        )
      } catch (err) {
        console.error('[MC Editor] Cursor context error:', err)
        cursorContext.value = null
      }
    }
  }
})

const viewRef = useCodeMirror({
  container: containerRef,
  doc: '',
  onViewCreated(view) {
    editorStore.setView(view)
  },
  extensions: [
    cursorTracker,
    mcCompletion(),
    mcValidation(),
  ],
})

// Load knowledge cache on mount
onMounted(() => {
  knowledgeCache.load()
})

const modeLabel = computed(() =>
  editorStore.mode === 'single' ? '单行' : '多行'
)

/** Which panel to show based on cursor context */
const activePanel = computed<string | null>(() => {
  const ctx = cursorContext.value
  if (!ctx || !ctx.expectedType) return null
  const type = ctx.expectedType
  if (type === 'Item' || type === 'Block') return 'item'
  if (type === 'Enchantment' || type === 'Enchant') return 'enchantment'
  if (type === 'EntityType') return 'entity'
  if (type === 'Effect') return 'effect'
  if (type === 'x y z') return 'coordinate'
  return null
})

/** Category for item panel (items vs blocks) */
const itemCategory = computed(() => {
  const ctx = cursorContext.value
  return ctx?.expectedType === 'Block' ? 'blocks' : 'items'
})

/** Insert a value from a panel into the editor at cursor */
function insertFromPanel(value: string) {
  const v = viewRef.value
  if (!v) return
  const pos = v.state.selection.main.head
  const ctx = cursorContext.value

  // If there's a partial input, replace it
  if (ctx && ctx.partialInput) {
    const from = pos - ctx.partialInput.length
    v.dispatch({
      changes: { from, to: pos, insert: value },
      selection: { anchor: from + value.length },
    })
  } else {
    v.dispatch({
      changes: { from: pos, insert: value },
      selection: { anchor: pos + value.length },
    })
  }
  v.focus()
}

function handleUndo() {
  if (viewRef.value) undo(viewRef.value)
}

function handleRedo() {
  if (viewRef.value) redo(viewRef.value)
}

function handleClear() {
  editorStore.clear()
}

function handleToggleMode() {
  editorStore.toggleMode()
}
</script>

<template>
  <div class="editor-panel">
    <!-- Toolbar -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-title">命令编辑器</span>
        <McButton size="small" @click="handleToggleMode">
          {{ modeLabel }}
        </McButton>
      </div>
      <div class="toolbar-right">
        <McButton
          size="small"
          :class="{ 'toolbox-active': showToolbox }"
          @click="handleToggleToolbox"
        >
          工具箱
        </McButton>
        <McButton size="small" @click="handleUndo">撤销</McButton>
        <McButton size="small" @click="handleRedo">重做</McButton>
        <McButton size="small" @click="handleClear">清空</McButton>
      </div>
    </div>

    <!-- CM6 editor container -->
    <div ref="containerRef" class="editor-container" />

    <!-- Parameter hint panel -->
    <div v-if="cursorContext && cursorContext.commandDef" class="hint-panel-wrapper">
      <ParameterHintPanel
        :context="cursorContext"
        @select="insertFromPanel"
      />
    </div>

    <!-- Context-aware parameter panel -->
    <div v-if="activePanel" class="param-panel">
      <ItemPanel
        v-if="activePanel === 'item'"
        :category="itemCategory"
        @select="insertFromPanel"
      />
      <EnchantmentPanel
        v-if="activePanel === 'enchantment'"
        @select="insertFromPanel"
      />
      <EntityPanel
        v-if="activePanel === 'entity'"
        @select="insertFromPanel"
      />
      <EffectPanel
        v-if="activePanel === 'effect'"
        @select="insertFromPanel"
      />
      <CoordinatePanel
        v-if="activePanel === 'coordinate'"
        @select="insertFromPanel"
      />
    </div>

    <!-- Toolbox panel -->
    <div v-if="showToolbox" class="toolbox-panel">
      <McToolbox @select="insertFromPanel" />
    </div>

    <!-- Status bar -->
    <div class="editor-status">
      <span class="status-pos">行 {{ cursorLine }}, 列 {{ cursorCol }}</span>
      <span class="status-mode">{{ modeLabel }}模式</span>
    </div>
  </div>
</template>

<style scoped>
.editor-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--mc-bg-main);
  border-left: 2px solid var(--mc-border);
  overflow: hidden;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 2px solid var(--mc-border);
  background: rgba(0, 0, 0, 0.15);
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-title {
  font-family: var(--mc-font-title);
  font-size: 14px;
  color: var(--mc-text-primary);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.editor-container {
  flex: 1;
  overflow: hidden;
}

/* Make CM6 fill the container */
.editor-container :deep(.cm-editor) {
  height: 100%;
}

.editor-container :deep(.cm-scroller) {
  overflow: auto;
}

.hint-panel-wrapper {
  border-top: 2px solid var(--mc-border);
  background: var(--mc-bg-card);
  flex-shrink: 0;
}

.param-panel {
  max-height: 200px;
  overflow-y: auto;
  border-top: 2px solid var(--mc-border);
  background: var(--mc-bg-card);
  flex-shrink: 0;
  scrollbar-width: thin;
  scrollbar-color: var(--mc-border) transparent;
}

.toolbox-panel {
  border-top: 2px solid var(--mc-border);
  background: var(--mc-bg-card);
  flex-shrink: 0;
}

.toolbox-active {
  color: var(--mc-gold) !important;
  border-color: var(--mc-gold) !important;
}

.editor-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  border-top: 2px solid var(--mc-border);
  background: rgba(0, 0, 0, 0.15);
  flex-shrink: 0;
  font-size: 11px;
  color: var(--mc-text-dim);
}

.status-pos {
  font-family: var(--mc-font-mono);
}

.status-mode {
  font-family: var(--mc-font-body);
}
</style>
