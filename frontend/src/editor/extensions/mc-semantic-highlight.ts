/**
 * Semantic Highlighting — overlays ID-category-based coloring
 * on top of the StreamLanguage base syntax highlighting.
 *
 * Uses the AST cache to determine what each token semantically represents,
 * then applies CSS classes via Decoration.mark().
 */
import { ViewPlugin, Decoration, type DecorationSet, type ViewUpdate, type EditorView } from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'
import { astCacheField } from '../ast/mc-ast-cache'
import type { CommandLine, ParameterNode } from '../ast/mc-ast'

// ─── Category → CSS class mapping ─────────────────────────────────────

const CATEGORY_CLASS: Record<string, string> = {
  items: 'mc-sem-item',
  blocks: 'mc-sem-block',
  entities: 'mc-sem-entity',
  effects: 'mc-sem-effect',
  enchantments: 'mc-sem-enchant',
  particles: 'mc-sem-particle',
  sounds: 'mc-sem-sound',
  biomes: 'mc-sem-biome',
  fog: 'mc-sem-particle',       // reuse particle color for fog
  animations: 'mc-sem-particle', // reuse particle color for animations
  gamerules: 'mc-sem-enum',
  structures: 'mc-sem-block',   // reuse block color for structures
}

// Decoration instances (cached for reuse)
const decorationCache = new Map<string, Decoration>()

function getDecoration(cls: string): Decoration {
  let d = decorationCache.get(cls)
  if (!d) {
    d = Decoration.mark({ class: cls })
    decorationCache.set(cls, d)
  }
  return d
}

const invalidDecoration = Decoration.mark({ class: 'mc-sem-invalid' })
const enumDecoration = Decoration.mark({ class: 'mc-sem-enum' })

// ─── Build decorations from AST ───────────────────────────────────────

function buildDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const astMap = view.state.field(astCacheField, false)
  if (!astMap) return Decoration.none

  // Only process visible lines for performance
  const visibleLines = new Set<number>()
  for (const { from, to } of view.visibleRanges) {
    const startLine = view.state.doc.lineAt(from).number
    const endLine = view.state.doc.lineAt(to).number
    for (let ln = startLine; ln <= endLine; ln++) {
      visibleLines.add(ln)
    }
  }

  // Collect all decorations, then sort by position (required by RangeSetBuilder)
  const decos: Array<{ from: number; to: number; deco: Decoration }> = []

  for (const ln of visibleLines) {
    const ast = astMap.get(ln)
    if (!ast || ast.kind !== 'command') continue

    const cmdAST = ast as CommandLine

    for (const pn of cmdAST.parameters) {
      const deco = getParameterDecoration(pn)
      if (deco && pn.token.from < pn.token.to) {
        decos.push({ from: pn.token.from, to: pn.token.to, deco })
      }

      // Also highlight inside selectors
      if (pn.selector) {
        for (const sp of pn.selector.params) {
          if (sp.value && sp.paramDef) {
            const spDeco = getSelectorValueDecoration(sp.paramDef.valueType, sp.value.text)
            if (spDeco && sp.value.from < sp.value.to) {
              decos.push({ from: sp.value.from, to: sp.value.to, deco: spDeco })
            }
          }
        }
      }
    }
  }

  // Sort by from position (required by builder)
  decos.sort((a, b) => a.from - b.from || a.to - b.to)

  for (const { from, to, deco } of decos) {
    builder.add(from, to, deco)
  }

  return builder.finish()
}

// ─── Determine decoration for a parameter node ───────────────────────

function getParameterDecoration(pn: ParameterNode): Decoration | null {
  const { token, resolvedCategory, isValid } = pn

  // Skip non-identifier tokens (selectors, JSON, strings, coords, numbers handled by base)
  if (token.tokenType === 'selector') return null
  if (token.tokenType === 'json') return null
  if (token.tokenType === 'string') return null
  if (token.tokenType === 'coord') return null
  if (token.tokenType === 'number') return null
  if (token.tokenType === 'keyword') return null
  if (token.tokenType === 'command') return null

  // Invalid ID → red underline
  if (isValid === false && resolvedCategory) {
    return invalidDecoration
  }

  // Valid ID → category-based color
  if (resolvedCategory) {
    const cls = CATEGORY_CLASS[resolvedCategory]
    if (cls) return getDecoration(cls)
  }

  // Fixed option enum values
  if (pn.paramDef && isValid === true && !resolvedCategory) {
    return enumDecoration
  }

  return null
}

// ─── Decoration for selector parameter values ─────────────────────────

function getSelectorValueDecoration(valueType: string, _valueText: string): Decoration | null {
  switch (valueType) {
    case 'entity':
      return getDecoration('mc-sem-entity')
    case 'gamemode':
      return enumDecoration
    default:
      return null
  }
}

// ─── ViewPlugin ───────────────────────────────────────────────────────

export const mcSemanticHighlight = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet

    constructor(view: EditorView) {
      this.decorations = buildDecorations(view)
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = buildDecorations(update.view)
      }
      // Also rebuild when AST cache field updates
      if (update.startState.field(astCacheField, false) !== update.state.field(astCacheField, false)) {
        this.decorations = buildDecorations(update.view)
      }
    }
  },
  {
    decorations: (v) => v.decorations,
  }
)
