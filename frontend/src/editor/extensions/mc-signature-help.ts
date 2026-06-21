/**
 * Signature Help — floating parameter hint tooltip (JetBrains Ctrl+P style).
 * Shows the full command syntax above the cursor with the current parameter highlighted.
 *
 * ┌─────────────────────────────────────────────────────┐
 * │ /give <player: target> «itemName: Item» [amount: int] │
 * │ itemName — 物品ID（参见 ids/items.json）              │
 * └─────────────────────────────────────────────────────┘
 */
import { StateField, type EditorState } from '@codemirror/state'
import { showTooltip, type Tooltip } from '@codemirror/view'
import { astCacheField } from '../ast/mc-ast-cache'
import type { CommandLine } from '../ast/mc-ast'
import { escapeHtml } from '../utils/tooltip-dom'

// ─── Build signature DOM ─────────────────────────────────────────────

function buildSignatureDOM(
  ast: CommandLine,
  currentParamName: string | null,
): HTMLElement {
  const def = ast.commandDef!
  const container = document.createElement('div')
  container.className = 'mc-sig-tooltip'

  // Syntax line with param highlighting
  const syntaxLine = document.createElement('div')
  syntaxLine.className = 'mc-sig-syntax'

  const cmdSpan = document.createElement('span')
  cmdSpan.className = 'mc-sig-cmd'
  cmdSpan.textContent = '/' + def.name + ' '
  syntaxLine.appendChild(cmdSpan)

  let activeParamDesc: string | null = null

  for (const p of def.parameters) {
    const span = document.createElement('span')
    const isCurrent = currentParamName !== null && p.name === currentParamName
    span.className = isCurrent ? 'mc-sig-param-active' : 'mc-sig-param'

    const bracket = p.required ? ['<', '>'] : ['[', ']']
    span.textContent = `${bracket[0]}${p.name}: ${p.type}${bracket[1]} `
    syntaxLine.appendChild(span)

    if (isCurrent && p.description) {
      activeParamDesc = `${p.name} — ${p.description}`
    }
  }

  container.appendChild(syntaxLine)

  // Current parameter description
  if (activeParamDesc) {
    const descLine = document.createElement('div')
    descLine.className = 'mc-sig-desc'
    descLine.innerHTML = escapeHtml(activeParamDesc)
    container.appendChild(descLine)
  }

  return container
}

// ─── Compute tooltips from editor state ──────────────────────────────

function getSignatureTooltips(state: EditorState): readonly Tooltip[] {
  const astMap = state.field(astCacheField, false)
  if (!astMap) return []

  const pos = state.selection.main.head
  const line = state.doc.lineAt(pos)
  const ast = astMap.get(line.number)
  if (!ast || ast.kind !== 'command') return []

  const cmdAST = ast as CommandLine
  if (!cmdAST.commandDef) return []

  // Don't show if cursor is on or before command name
  if (pos <= cmdAST.commandName.to) return []

  // Don't show on empty lines past the command
  if (cmdAST.parameters.length === 0 && pos > cmdAST.commandName.to + 1) {
    // Still show for the first expected parameter position
  }

  // Find the current parameter by cursor position
  let currentParamName: string | null = null

  for (const pn of cmdAST.parameters) {
    if (pos >= pn.token.from && pos <= pn.token.to) {
      currentParamName = pn.paramDef?.name ?? null
      break
    }
    // Cursor is in whitespace after this param and before next — highlight next param
    if (pos > pn.token.to) {
      currentParamName = pn.paramDef?.name ?? null
    }
  }

  // If cursor is past all params, try to show the next expected param
  if (!currentParamName && cmdAST.parameters.length > 0) {
    const lastPn = cmdAST.parameters[cmdAST.parameters.length - 1]
    if (pos > lastPn.token.to) {
      // Find next param in definition
      const defParams = cmdAST.commandDef.parameters
      const lastIdx = defParams.findIndex(p => p.name === lastPn.paramDef?.name)
      if (lastIdx >= 0 && lastIdx + 1 < defParams.length) {
        currentParamName = defParams[lastIdx + 1].name
      }
    }
  }

  // If we still don't have a match but cursor is after command name, show first param
  if (!currentParamName && cmdAST.parameters.length === 0 && cmdAST.commandDef.parameters.length > 0) {
    currentParamName = cmdAST.commandDef.parameters[0].name
  }

  return [{
    pos,
    above: true,
    strictSide: true,
    arrow: false,
    create() {
      return { dom: buildSignatureDOM(cmdAST, currentParamName) }
    },
  }]
}

// ─── StateField + extension ──────────────────────────────────────────

export const mcSignatureHelp = StateField.define<readonly Tooltip[]>({
  create: getSignatureTooltips,

  update(tooltips, tr) {
    if (!tr.docChanged && !tr.selection) return tooltips
    return getSignatureTooltips(tr.state)
  },

  provide: f => showTooltip.computeN([f], state => state.field(f)),
})
