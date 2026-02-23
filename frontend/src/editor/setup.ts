/**
 * CodeMirror 6 setup composable.
 * Creates an EditorView with MC command extensions.
 */
import { onMounted, onBeforeUnmount, ref, type Ref, type ShallowRef, watch } from 'vue'
import { EditorView, keymap, lineNumbers, drawSelection, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { EditorState, type Extension } from '@codemirror/state'
import { history, historyKeymap, defaultKeymap } from '@codemirror/commands'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { mcLanguage } from './extensions/mc-language'
import { mcTheme } from './extensions/mc-theme'

export interface UseCodeMirrorOptions {
  /** Container element ref */
  container: Ref<HTMLElement | null>
  /** Initial document content */
  doc?: string
  /** Additional extensions to append */
  extensions?: Extension[]
  /** Called when the view is created */
  onViewCreated?: (view: EditorView) => void
}

/**
 * Composable that creates a CM6 EditorView.
 * Returns a ShallowRef to the view for external access.
 */
export function useCodeMirror(options: UseCodeMirrorOptions): ShallowRef<EditorView | null> {
  const viewRef = ref<EditorView | null>(null) as ShallowRef<EditorView | null>

  function createView(container: HTMLElement) {
    const extraExtensions = options.extensions ?? []

    const state = EditorState.create({
      doc: options.doc ?? '',
      extensions: [
        // Core
        lineNumbers(),
        history(),
        drawSelection(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        closeBrackets(),
        EditorState.allowMultipleSelections.of(true),

        // Keymaps
        keymap.of([
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
        ]),

        // MC language + theme
        mcLanguage,
        ...mcTheme,

        // User extensions (completion, lint, ghost text, etc.)
        ...extraExtensions,

        // Placeholder
        EditorView.contentAttributes.of({
          'aria-label': 'Minecraft command editor',
        }),
      ],
    })

    const view = new EditorView({ state, parent: container })
    viewRef.value = view
    options.onViewCreated?.(view)
  }

  onMounted(() => {
    if (options.container.value) {
      createView(options.container.value)
    }
  })

  // If container mounts late (v-if, etc.)
  watch(
    () => options.container.value,
    (el) => {
      if (el && !viewRef.value) {
        createView(el)
      }
    }
  )

  onBeforeUnmount(() => {
    viewRef.value?.destroy()
    viewRef.value = null
  })

  return viewRef
}
