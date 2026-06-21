/**
 * Quick Fix lightbulb — shows a clickable 💡 icon in the gutter
 * on lines that have fixable diagnostics (diagnostics with actions).
 */
import { gutter, GutterMarker, type EditorView } from '@codemirror/view'
import { RangeSet } from '@codemirror/state'
import { forEachDiagnostic, type Diagnostic } from '@codemirror/lint'

// ─── Quick Fix Menu ──────────────────────────────────────────────────

function showQuickFixMenu(
  view: EditorView,
  anchor: HTMLElement,
  diagnostics: Array<{ message: string; actions: NonNullable<Diagnostic['actions']> }>,
): void {
  // Remove any existing menu
  document.querySelector('.mc-quick-fix-menu')?.remove()

  const menu = document.createElement('div')
  menu.className = 'mc-quick-fix-menu'

  for (const diag of diagnostics) {
    // Diagnostic message header
    const header = document.createElement('div')
    header.className = 'mc-quick-fix-header'
    header.textContent = diag.message
    menu.appendChild(header)

    // Action items
    for (const action of diag.actions) {
      const item = document.createElement('div')
      item.className = 'mc-quick-fix-item'
      item.textContent = action.name
      item.addEventListener('click', (e) => {
        e.stopPropagation()
        action.apply(view, diag.actions[0] as unknown as number, 0)
        menu.remove()
      })
      menu.appendChild(item)
    }
  }

  // Position near the anchor element
  const rect = anchor.getBoundingClientRect()
  menu.style.position = 'fixed'
  menu.style.left = `${rect.right + 4}px`
  menu.style.top = `${rect.top}px`
  menu.style.zIndex = '1000'

  document.body.appendChild(menu)

  // Close on click outside (delayed to avoid immediate close)
  const closeHandler = (e: MouseEvent) => {
    if (!menu.contains(e.target as Node)) {
      menu.remove()
      document.removeEventListener('mousedown', closeHandler)
    }
  }
  requestAnimationFrame(() => {
    document.addEventListener('mousedown', closeHandler)
  })
}

// ─── Gutter Marker ──────────────────────────────────────────────────

class QuickFixBulb extends GutterMarker {
  constructor(
    private diagnostics: Array<{ message: string; actions: NonNullable<Diagnostic['actions']> }>,
  ) {
    super()
  }

  toDOM(view: EditorView): HTMLElement {
    const span = document.createElement('span')
    span.className = 'mc-quick-fix-bulb'
    span.textContent = '\u{1F4A1}' // 💡
    span.title = '快速修复 (点击查看)'
    span.addEventListener('mousedown', (e) => {
      e.preventDefault()
      e.stopPropagation()
      showQuickFixMenu(view, span, this.diagnostics)
    })
    return span
  }

  eq(other: QuickFixBulb): boolean {
    return this.diagnostics.length === other.diagnostics.length
  }
}

// ─── Gutter extension ────────────────────────────────────────────────

export const mcQuickFix = gutter({
  class: 'mc-quick-fix-gutter',
  markers(view) {
    const markers: Array<{ from: number; marker: GutterMarker }> = []

    // Group fixable diagnostics by line
    const lineMap = new Map<number, Array<{ message: string; actions: NonNullable<Diagnostic['actions']> }>>()

    forEachDiagnostic(view.state, (d: Diagnostic, from: number) => {
      if (!d.actions || d.actions.length === 0) return
      const lineNo = view.state.doc.lineAt(from).number
      let list = lineMap.get(lineNo)
      if (!list) {
        list = []
        lineMap.set(lineNo, list)
      }
      list.push({ message: d.message, actions: d.actions })
    })

    for (const [lineNo, diags] of lineMap) {
      const line = view.state.doc.line(lineNo)
      markers.push({ from: line.from, marker: new QuickFixBulb(diags) })
    }

    // RangeSet requires sorted positions
    markers.sort((a, b) => a.from - b.from)
    return RangeSet.of(markers.map(m => m.marker.range(m.from)))
  },
})
