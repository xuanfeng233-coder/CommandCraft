/**
 * Inline Decorations for MC commands:
 *
 * 1. Color code preview (§e, §a, etc.) — small colored squares
 * 2. Selector bracket matching — highlight matching [ ]
 * 3. Coordinate axis labels — X Y Z above coordinate groups
 * 4. Command separator lines — subtle dividers between command groups
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
import type { CommandLine, ParameterNode } from '../ast/mc-ast'

// ─── MC Color Codes ───────────────────────────────────────────────────

/** Minecraft formatting code colors (§0-§9, §a-§f, §g-§j) */
const MC_COLORS: Record<string, string> = {
  '0': '#000000', // Black
  '1': '#0000AA', // Dark Blue
  '2': '#00AA00', // Dark Green
  '3': '#00AAAA', // Dark Aqua
  '4': '#AA0000', // Dark Red
  '5': '#AA00AA', // Dark Purple
  '6': '#FFAA00', // Gold
  '7': '#AAAAAA', // Gray
  '8': '#555555', // Dark Gray
  '9': '#5555FF', // Blue
  a: '#55FF55',   // Green
  b: '#55FFFF',   // Aqua
  c: '#FF5555',   // Red
  d: '#FF55FF',   // Light Purple
  e: '#FFFF55',   // Yellow
  f: '#FFFFFF',   // White
  g: '#DDD605',   // Minecoin Gold
  h: '#E3D4D1',   // Material Quartz
  i: '#CECACA',   // Material Iron
  j: '#443A3B',   // Material Netherite
}

/** MC format codes (non-color) */
const MC_FORMAT_CODES: Record<string, string> = {
  k: '混淆',
  l: '粗体',
  m: '删除线',
  n: '下划线',
  o: '斜体',
  r: '重置',
}

// ─── Color Code Widget ────────────────────────────────────────────────

class ColorCodeWidget extends WidgetType {
  constructor(
    private color: string,
    private code: string,
    private isFormat: boolean,
    private formatDesc: string,
  ) {
    super()
  }

  toDOM(): HTMLElement {
    const span = document.createElement('span')
    span.className = 'mc-deco-color-swatch'

    if (this.isFormat) {
      span.textContent = this.code
      span.title = this.formatDesc
      span.style.color = '#AAAAAA'
      span.style.fontSize = '9px'
      span.style.border = '1px solid #555'
      span.style.borderRadius = '2px'
      span.style.padding = '0 2px'
      span.style.marginLeft = '1px'
      span.style.verticalAlign = 'middle'
      span.style.lineHeight = '1'
    } else {
      span.style.backgroundColor = this.color
      span.title = `§${this.code} (${this.color})`
    }

    return span
  }

  eq(other: ColorCodeWidget): boolean {
    return this.color === other.color && this.code === other.code
  }

  get estimatedHeight(): number { return -1 }
  ignoreEvent(): boolean { return true }
}

// ─── Coordinate Axis Label Widget ─────────────────────────────────────

class CoordAxisWidget extends WidgetType {
  constructor(private axis: string) {
    super()
  }

  toDOM(): HTMLElement {
    const span = document.createElement('span')
    span.className = 'mc-deco-coord-axis'
    span.textContent = this.axis
    return span
  }

  eq(other: CoordAxisWidget): boolean {
    return this.axis === other.axis
  }

  get estimatedHeight(): number { return -1 }
  ignoreEvent(): boolean { return true }
}

// ─── Build all inline decorations ─────────────────────────────────────

function buildInlineDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const doc = view.state.doc
  const decos: Array<{ from: number; to: number; deco: Decoration }> = []

  // Visible lines
  for (const { from, to } of view.visibleRanges) {
    const startLine = doc.lineAt(from).number
    const endLine = doc.lineAt(to).number

    for (let ln = startLine; ln <= endLine; ln++) {
      const line = doc.line(ln)
      const text = line.text

      // ─── 1. Color code preview ──────────────────────────

      findColorCodes(text, line.from, decos)

      // ─── 4. Command separator line (empty line between commands) ──

      if (text.trim() === '' && ln > 1 && ln < doc.lines) {
        const prevLine = doc.line(ln - 1).text.trim()
        const nextLine = doc.line(ln + 1).text.trim()
        if (prevLine && !prevLine.startsWith('#') && nextLine && !nextLine.startsWith('#')) {
          decos.push({
            from: line.from,
            to: line.from,
            deco: Decoration.line({ class: 'mc-deco-separator' }),
          })
        }
      }
    }
  }

  // ─── 3. Coordinate axis labels (based on AST) ──────────

  const astMap = view.state.field(astCacheField, false)
  if (astMap) {
    // Only show for the line the cursor is on
    const cursorPos = view.state.selection.main.head
    const cursorLine = doc.lineAt(cursorPos).number
    const ast = astMap.get(cursorLine)

    if (ast && ast.kind === 'command') {
      findCoordGroups(ast as CommandLine, decos)
    }
  }

  // ─── 2. Selector bracket matching ──────────────────────

  buildBracketMatchDecorations(view, decos)

  // Sort by position
  decos.sort((a, b) => a.from - b.from || a.to - b.to)

  for (const { from, to, deco } of decos) {
    if (from <= to) {
      builder.add(from, to, deco)
    }
  }

  return builder.finish()
}

// ─── Color code finder ────────────────────────────────────────────────

function findColorCodes(
  text: string,
  lineFrom: number,
  decos: Array<{ from: number; to: number; deco: Decoration }>,
): void {
  // Match §X patterns (inside strings or rawtext)
  const regex = /§([0-9a-fk-or]|[g-j])/gi
  let match: RegExpExecArray | null

  while ((match = regex.exec(text)) !== null) {
    const code = match[1].toLowerCase()
    const color = MC_COLORS[code]
    const formatDesc = MC_FORMAT_CODES[code]

    if (color) {
      // Insert color swatch widget after the §X
      const pos = lineFrom + match.index + match[0].length
      decos.push({
        from: pos,
        to: pos,
        deco: Decoration.widget({
          widget: new ColorCodeWidget(color, code, false, ''),
          side: 1,
        }),
      })
    } else if (formatDesc) {
      const pos = lineFrom + match.index + match[0].length
      decos.push({
        from: pos,
        to: pos,
        deco: Decoration.widget({
          widget: new ColorCodeWidget('', code, true, formatDesc),
          side: 1,
        }),
      })
    }
  }
}

// ─── Coordinate group finder ──────────────────────────────────────────

function findCoordGroups(
  ast: CommandLine,
  decos: Array<{ from: number; to: number; deco: Decoration }>,
): void {
  const params = ast.parameters

  for (let i = 0; i <= params.length - 3; i++) {
    const p1 = params[i]
    const p2 = params[i + 1]
    const p3 = params[i + 2]

    // Check if this is a coordinate group (param expects x y z, or tokens are coords/numbers)
    const isCoord = (pn: ParameterNode) =>
      pn.token.tokenType === 'coord' || pn.token.tokenType === 'number'

    const isXYZParam = p1.expectedType === 'x y z'
    const allCoords = isCoord(p1) && isCoord(p2) && isCoord(p3)

    if (isXYZParam || allCoords) {
      const axes = ['X', 'Y', 'Z']
      for (let j = 0; j < 3; j++) {
        const p = [p1, p2, p3][j]
        decos.push({
          from: p.token.from,
          to: p.token.from,
          deco: Decoration.widget({
            widget: new CoordAxisWidget(axes[j]),
            side: -1, // before the token
          }),
        })
      }

      i += 2 // skip past this group
    }
  }
}

// ─── Bracket matching ─────────────────────────────────────────────────

const matchBracketDeco = Decoration.mark({ class: 'mc-deco-bracket-match' })

function buildBracketMatchDecorations(
  view: EditorView,
  decos: Array<{ from: number; to: number; deco: Decoration }>,
): void {
  const pos = view.state.selection.main.head
  const doc = view.state.doc
  const line = doc.lineAt(pos)
  const text = line.text
  const col = pos - line.from

  if (col < 0 || col > text.length) return

  // Check character at cursor and before cursor
  const charAt = col < text.length ? text[col] : ''
  const charBefore = col > 0 ? text[col - 1] : ''

  let bracketPos: number = -1
  let isOpen: boolean = false

  if (charAt === '[') {
    bracketPos = pos
    isOpen = true
  } else if (charBefore === '[') {
    bracketPos = pos - 1
    isOpen = true
  } else if (charAt === ']') {
    bracketPos = pos
    isOpen = false
  } else if (charBefore === ']') {
    bracketPos = pos - 1
    isOpen = false
  }

  if (bracketPos === -1) return

  // Find matching bracket within the same line
  const relPos = bracketPos - line.from

  if (isOpen) {
    // Find matching ]
    let depth = 0
    for (let i = relPos; i < text.length; i++) {
      if (text[i] === '[') depth++
      else if (text[i] === ']') {
        depth--
        if (depth === 0) {
          // Highlight both brackets
          decos.push({ from: bracketPos, to: bracketPos + 1, deco: matchBracketDeco })
          decos.push({ from: line.from + i, to: line.from + i + 1, deco: matchBracketDeco })
          return
        }
      }
    }
  } else {
    // Find matching [
    let depth = 0
    for (let i = relPos; i >= 0; i--) {
      if (text[i] === ']') depth++
      else if (text[i] === '[') {
        depth--
        if (depth === 0) {
          decos.push({ from: line.from + i, to: line.from + i + 1, deco: matchBracketDeco })
          decos.push({ from: bracketPos, to: bracketPos + 1, deco: matchBracketDeco })
          return
        }
      }
    }
  }
}

// ─── ViewPlugin ───────────────────────────────────────────────────────

export const mcInlineDecorations = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet

    constructor(view: EditorView) {
      this.decorations = buildInlineDecorations(view)
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged || update.selectionSet) {
        this.decorations = buildInlineDecorations(update.view)
      }
    }
  },
  {
    decorations: (v) => v.decorations,
  }
)
