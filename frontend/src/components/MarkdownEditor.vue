<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, shallowRef, nextTick } from 'vue'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

type ViewMode = 'edit' | 'split' | 'preview'
const viewMode = ref<ViewMode>('edit')

const editorContainer = ref<HTMLElement>()
const editorView = shallowRef<EditorView>()
const previewHtml = ref('')
let skipUpdate = false

// --- Draggable split ratio ---
const splitRatio = ref(0.5) // 0..1, left pane fraction
const isDragging = ref(false)
const editorRoot = ref<HTMLElement>()

function onDividerMouseDown(e: MouseEvent) {
  e.preventDefault()
  isDragging.value = true
  document.addEventListener('mousemove', onDividerMouseMove)
  document.addEventListener('mouseup', onDividerMouseUp)
}

function onDividerMouseMove(e: MouseEvent) {
  if (!editorRoot.value) return
  const rect = editorRoot.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const ratio = Math.max(0.2, Math.min(0.8, x / rect.width))
  splitRatio.value = ratio
}

function onDividerMouseUp() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDividerMouseMove)
  document.removeEventListener('mouseup', onDividerMouseUp)
}

// Touch support for mobile
function onDividerTouchStart(e: TouchEvent) {
  e.preventDefault()
  isDragging.value = true
  document.addEventListener('touchmove', onDividerTouchMove, { passive: false })
  document.addEventListener('touchend', onDividerTouchEnd)
}

function onDividerTouchMove(e: TouchEvent) {
  e.preventDefault()
  if (!editorRoot.value) return
  const rect = editorRoot.value.getBoundingClientRect()
  const x = e.touches[0].clientX - rect.left
  const ratio = Math.max(0.2, Math.min(0.8, x / rect.width))
  splitRatio.value = ratio
}

function onDividerTouchEnd() {
  isDragging.value = false
  document.removeEventListener('touchmove', onDividerTouchMove)
  document.removeEventListener('touchend', onDividerTouchEnd)
}

// Simple markdown to HTML renderer (basic subset)
function renderMarkdown(md: string): string {
  let html = md
    // Headers
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Checkboxes
    .replace(/^- \[x\] (.+)$/gm, '<div class="md-check done">$1</div>')
    .replace(/^- \[ \] (.+)$/gm, '<div class="md-check">$1</div>')
    .replace(/^- \[>\] (.+)$/gm, '<div class="md-check progress">$1</div>')
    // List items
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // Paragraphs (double newline)
    .replace(/\n\n/g, '</p><p>')

  html = '<p>' + html + '</p>'
  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '')
  // Wrap consecutive <li> in <ul>
  html = html.replace(/(<li>.*?<\/li>\s*)+/gs, '<ul>$&</ul>')
  return html
}

function createEditorState(content: string): EditorState {
  return EditorState.create({
    doc: content,
    extensions: [
      lineNumbers(),
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged && !skipUpdate) {
          const value = update.state.doc.toString()
          emit('update:modelValue', value)
          previewHtml.value = renderMarkdown(value)
        }
      }),
      EditorView.lineWrapping,
      EditorView.theme({
        '&': {
          height: '100%',
          fontSize: '13px',
        },
        '.cm-scroller': {
          fontFamily: 'var(--mc-font-mono, monospace)',
          overflow: 'auto',
        },
        '.cm-content': {
          caretColor: 'var(--mc-gold)',
          color: 'var(--mc-text-primary)',
        },
        '.cm-gutters': {
          background: 'rgba(0,0,0,0.2)',
          color: 'var(--mc-text-dim)',
          border: 'none',
        },
        '&.cm-focused .cm-cursor': {
          borderLeftColor: 'var(--mc-gold)',
        },
        '&.cm-focused .cm-selectionBackground, ::selection': {
          background: 'rgba(255, 170, 0, 0.2)',
        },
        '.cm-activeLine': {
          background: 'rgba(255, 170, 0, 0.05)',
        },
      }),
    ],
  })
}

function mountEditor() {
  if (!editorContainer.value) return
  // Destroy stale instance if attached to a removed DOM node
  if (editorView.value) {
    editorView.value.destroy()
    editorView.value = undefined
  }

  editorView.value = new EditorView({
    state: createEditorState(props.modelValue),
    parent: editorContainer.value,
  })
}

function destroyEditor() {
  editorView.value?.destroy()
  editorView.value = undefined
}

onMounted(() => {
  previewHtml.value = renderMarkdown(props.modelValue)
  // Mount editor if visible on initial mode
  if (viewMode.value !== 'preview') {
    mountEditor()
  }
})

onBeforeUnmount(() => {
  destroyEditor()
  document.removeEventListener('mousemove', onDividerMouseMove)
  document.removeEventListener('mouseup', onDividerMouseUp)
  document.removeEventListener('touchmove', onDividerTouchMove)
  document.removeEventListener('touchend', onDividerTouchEnd)
})

// Destroy and remount editor when switching modes
// (the editorContainer ref changes between v-if branches)
watch(viewMode, (mode) => {
  destroyEditor()
  if (mode !== 'preview') {
    nextTick(() => mountEditor())
  }
})

// Sync external changes to editor
watch(
  () => props.modelValue,
  (newVal) => {
    previewHtml.value = renderMarkdown(newVal)
    const view = editorView.value
    if (!view) return

    const currentVal = view.state.doc.toString()
    if (newVal !== currentVal) {
      skipUpdate = true
      view.dispatch({
        changes: { from: 0, to: currentVal.length, insert: newVal },
      })
      skipUpdate = false
    }
  },
)
</script>

<template>
  <div ref="editorRoot" class="md-editor" :class="{ 'is-dragging': isDragging }">
    <!-- Toolbar tabs -->
    <div class="md-toolbar">
      <button
        class="md-tab"
        :class="{ active: viewMode === 'edit' }"
        @click="viewMode = 'edit'"
      >
        编辑
      </button>
      <button
        class="md-tab"
        :class="{ active: viewMode === 'split' }"
        @click="viewMode = 'split'"
      >
        分屏
      </button>
      <button
        class="md-tab"
        :class="{ active: viewMode === 'preview' }"
        @click="viewMode = 'preview'"
      >
        预览
      </button>
    </div>

    <!-- Content area -->
    <div class="md-body">
      <!-- Edit-only mode -->
      <div v-if="viewMode === 'edit'" class="md-pane-full">
        <div ref="editorContainer" class="md-codemirror" />
      </div>

      <!-- Preview-only mode -->
      <div v-if="viewMode === 'preview'" class="md-pane-full">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div class="md-preview-content" v-html="previewHtml" />
      </div>

      <!-- Split mode -->
      <template v-if="viewMode === 'split'">
        <div class="md-split-left" :style="{ flex: `0 0 calc(${splitRatio * 100}% - 3px)` }">
          <div ref="editorContainer" class="md-codemirror" />
        </div>
        <div
          class="md-split-divider"
          @mousedown="onDividerMouseDown"
          @touchstart="onDividerTouchStart"
        />
        <div class="md-split-right" :style="{ flex: `0 0 calc(${(1 - splitRatio) * 100}% - 3px)` }">
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div class="md-preview-content" v-html="previewHtml" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.md-editor {
  display: flex;
  flex-direction: column;
  border: 2px solid var(--mc-border);
  overflow: hidden;
  background: var(--mc-bg-card);
}

.md-editor.is-dragging {
  user-select: none;
  cursor: col-resize;
}

/* Toolbar tabs */
.md-toolbar {
  display: flex;
  gap: 0;
  background: rgba(0, 0, 0, 0.15);
  border-bottom: 1px solid var(--mc-border);
  flex-shrink: 0;
}

.md-tab {
  padding: 6px 16px;
  font-family: var(--mc-font-title);
  font-size: 12px;
  color: var(--mc-text-dim);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color 150ms, border-color 150ms;
}

.md-tab:hover {
  color: var(--mc-text-primary);
}

.md-tab.active {
  color: var(--mc-gold);
  border-bottom-color: var(--mc-gold);
}

/* Body */
.md-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Full-width pane (edit-only or preview-only) */
.md-pane-full {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

/* CodeMirror container */
.md-codemirror {
  flex: 1;
  overflow: auto;
  min-width: 0;
}

.md-codemirror :deep(.cm-editor) {
  height: 100%;
}

/* Split mode panes */
.md-split-left,
.md-split-right {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

/* Draggable divider */
.md-split-divider {
  flex: 0 0 6px;
  background: var(--mc-border);
  cursor: col-resize;
  position: relative;
  transition: background 150ms;
}

.md-split-divider:hover,
.md-editor.is-dragging .md-split-divider {
  background: var(--mc-gold);
}

/* Preview content */
.md-preview-content {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.6;
  color: var(--mc-text-primary);
}

.md-preview-content :deep(h1) {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 18px;
  margin: 0 0 12px;
}

.md-preview-content :deep(h2) {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 15px;
  margin: 16px 0 8px;
}

.md-preview-content :deep(h3) {
  font-family: var(--mc-font-title);
  color: var(--mc-text-primary);
  font-size: 13px;
  margin: 12px 0 6px;
}

.md-preview-content :deep(strong) {
  color: var(--mc-gold);
}

.md-preview-content :deep(code) {
  background: rgba(0, 0, 0, 0.2);
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 12px;
}

.md-preview-content :deep(.md-check) {
  padding: 2px 0 2px 22px;
  position: relative;
}

.md-preview-content :deep(.md-check::before) {
  content: '[ ]';
  position: absolute;
  left: 0;
  color: var(--mc-text-dim);
  font-family: var(--mc-font-mono);
}

.md-preview-content :deep(.md-check.done::before) {
  content: '[x]';
  color: var(--mc-green, #55ff55);
}

.md-preview-content :deep(.md-check.progress::before) {
  content: '[>]';
  color: var(--mc-gold);
}

.md-preview-content :deep(ul) {
  padding-left: 20px;
  margin: 4px 0;
}

.md-preview-content :deep(li) {
  margin: 2px 0;
}

/* Mobile: force stacked layout in split mode */
@media (max-width: 768px) {
  .md-body {
    flex-direction: column;
  }

  .md-split-left,
  .md-split-right {
    flex: 1 !important;
    min-height: 150px;
  }

  .md-split-divider {
    flex: 0 0 6px;
    cursor: row-resize;
  }
}
</style>
