/**
 * Editor Pinia store — manages editor state, mode, and content.
 */
import { ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import type { EditorView } from '@codemirror/view'

export type EditorMode = 'single' | 'multi'

export const useEditorStore = defineStore('editor', () => {
  /** Current editor mode */
  const mode = ref<EditorMode>('multi')

  /** The CM6 EditorView reference (shallow to avoid deep reactivity on CM internals) */
  const view = shallowRef<EditorView | null>(null)

  /** Register the EditorView instance */
  function setView(v: EditorView) {
    view.value = v
  }

  /** Get current editor content */
  function getContent(): string {
    return view.value?.state.doc.toString() ?? ''
  }

  /** Replace entire editor content */
  function setContent(text: string) {
    const v = view.value
    if (!v) return
    v.dispatch({
      changes: { from: 0, to: v.state.doc.length, insert: text },
    })
  }

  /** Insert a command into the editor */
  function insertCommand(cmd: string) {
    const v = view.value
    if (!v) return

    if (mode.value === 'single') {
      // Single-line mode: replace entire content
      setContent(cmd)
    } else {
      // Multi-line mode: append on new line
      const doc = v.state.doc
      const currentText = doc.toString()
      const needsNewline = currentText.length > 0 && !currentText.endsWith('\n')
      const insertText = (needsNewline ? '\n' : '') + cmd + '\n'
      v.dispatch({
        changes: { from: doc.length, insert: insertText },
        selection: { anchor: doc.length + insertText.length },
      })
    }
    v.focus()
  }

  /** Clear editor content */
  function clear() {
    setContent('')
  }

  /** Toggle between single and multi-line modes */
  function toggleMode() {
    mode.value = mode.value === 'single' ? 'multi' : 'single'
  }

  return {
    mode,
    view,
    setView,
    getContent,
    setContent,
    insertCommand,
    clear,
    toggleMode,
  }
})
