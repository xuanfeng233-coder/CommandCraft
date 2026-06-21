/**
 * Inlay Hints — JetBrains-style inline parameter labels.
 * Shows parameter names before argument values:
 *   /give  player: @s  itemName: diamond_sword  amount: 64
 */
import {
  ViewPlugin,
  Decoration,
  WidgetType,
  type DecorationSet,
  type ViewUpdate,
  type EditorView,
} from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'
import { astCacheField } from '../ast/mc-ast-cache'
import type { CommandLine } from '../ast/mc-ast'

// ─── Inlay Hint Widget ──────────────────────────────────────────────

class InlayHintWidget extends WidgetType {
  constructor(private label: string) {
    super()
  }

  toDOM(): HTMLElement {
    const span = document.createElement('span')
    span.className = 'mc-inlay-hint'
    span.textContent = this.label + ':'
    return span
  }

  eq(other: InlayHintWidget): boolean {
    return this.label === other.label
  }

  get estimatedHeight(): number { return -1 }
  ignoreEvent(): boolean { return true }
}

// ─── Build inlay hints from AST ─────────────────────────────────────

function buildInlayHints(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const doc = view.state.doc
  const astMap = view.state.field(astCacheField, false)
  if (!astMap) return builder.finish()

  const decos: Array<{ from: number; deco: Decoration }> = []

  for (const { from, to } of view.visibleRanges) {
    const startLine = doc.lineAt(from).number
    const endLine = doc.lineAt(to).number

    for (let ln = startLine; ln <= endLine; ln++) {
      const ast = astMap.get(ln)
      if (!ast || ast.kind !== 'command') continue

      const cmdAST = ast as CommandLine
      if (!cmdAST.commandDef) continue // skip unknown commands

      // Track last paramDef name to avoid duplicate labels for multi-token params
      let lastParamName: string | null = null

      for (const pn of cmdAST.parameters) {
        if (!pn.paramDef) continue

        // Skip subcommand keywords and nested command markers
        if (pn.expectedType === '子命令' || pn.expectedType === 'Command') continue
        if (pn.token.tokenType === 'keyword') continue

        // Skip coordinate params (already have X/Y/Z axis labels from mc-decorations)
        if (pn.expectedType === 'x y z') continue

        // Skip duplicate labels for same multi-token param
        if (pn.paramDef.name === lastParamName) continue
        lastParamName = pn.paramDef.name

        decos.push({
          from: pn.token.from,
          deco: Decoration.widget({
            widget: new InlayHintWidget(pn.paramDef.name),
            side: -1,
          }),
        })
      }
    }
  }

  // Sort by position (required for RangeSetBuilder)
  decos.sort((a, b) => a.from - b.from)
  for (const { from, deco } of decos) {
    builder.add(from, from, deco)
  }

  return builder.finish()
}

// ─── ViewPlugin ─────────────────────────────────────────────────────

export const mcInlayHints = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet

    constructor(view: EditorView) {
      this.decorations = buildInlayHints(view)
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged || update.selectionSet) {
        this.decorations = buildInlayHints(update.view)
      }
    }
  },
  {
    decorations: (v) => v.decorations,
  }
)
