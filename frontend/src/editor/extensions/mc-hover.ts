/**
 * MC Command Hover Tooltips — shows contextual information
 * when hovering over commands, IDs, selectors, and parameters.
 *
 * Uses the AST cache for semantic understanding of what's under the cursor.
 */
import { hoverTooltip } from '@codemirror/view'
import { astCacheField } from '../ast/mc-ast-cache'
import { findTokenAtPosition, type CommandLine, type ParameterNode, type Token } from '../ast/mc-ast'
import { FIXED_OPTIONS } from '../constants/type-mappings'
import { SELECTOR_PARAM_MAP } from '../state-machine/selector-parser'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import { escapeHtml, createTooltipDOM } from '../utils/tooltip-dom'

// ─── Selector base descriptions ───────────────────────────────────────

const SELECTOR_DESC: Record<string, { label: string; desc: string }> = {
  '@a': { label: '所有玩家', desc: '选择世界中的所有玩家' },
  '@e': { label: '所有实体', desc: '选择所有实体（包括玩家和非玩家）' },
  '@p': { label: '最近玩家', desc: '选择距离最近的玩家' },
  '@r': { label: '随机玩家', desc: '随机选择一个玩家' },
  '@s': { label: '执行者自身', desc: '选择命令执行者自身' },
  '@initiator': { label: 'NPC交互者', desc: '选择与NPC交互的玩家' },
}

// ─── Execute subcommand descriptions ──────────────────────────────────

const EXECUTE_SUBCMD_DESC: Record<string, { syntax: string; desc: string }> = {
  as: { syntax: 'as <目标>', desc: '改变命令的执行实体（who）' },
  at: { syntax: 'at <目标>', desc: '改变命令的执行位置和朝向（where）' },
  positioned: { syntax: 'positioned <x y z>', desc: '改变命令的执行坐标' },
  if: { syntax: 'if <条件>', desc: '仅当条件为真时继续执行' },
  unless: { syntax: 'unless <条件>', desc: '仅当条件为假时继续执行' },
  run: { syntax: 'run <命令>', desc: '执行后续命令' },
  facing: { syntax: 'facing <x y z>', desc: '改变执行朝向为指定坐标方向' },
  rotated: { syntax: 'rotated <y> <x>', desc: '改变执行的旋转角度' },
  in: { syntax: 'in <维度>', desc: '改变执行的维度' },
  align: { syntax: 'align <轴>', desc: '将坐标对齐到方块网格' },
  anchored: { syntax: 'anchored <eyes|feet>', desc: '改变坐标锚点（眼睛或脚部）' },
}

// ─── Build tooltip for command name ───────────────────────────────────

function commandTooltip(ast: CommandLine): HTMLElement {
  const def = ast.commandDef!
  const sections: Array<{ cls: string; html: string }> = []

  // Title
  sections.push({
    cls: 'mc-hover-title',
    html: `<span class="mc-hover-cmd">/${escapeHtml(def.name)}</span>` +
      `<span class="mc-hover-badge">${escapeHtml(def.category)}</span>`,
  })

  // Syntax
  sections.push({
    cls: 'mc-hover-syntax',
    html: escapeHtml(def.syntax),
  })

  // Description
  sections.push({
    cls: 'mc-hover-desc',
    html: escapeHtml(def.description),
  })

  // Parameters overview
  if (def.parameters.length > 0) {
    const paramLines = def.parameters.map(p => {
      const req = p.required ? '<span class="mc-hover-req">必填</span>' : '<span class="mc-hover-opt">可选</span>'
      return `<div class="mc-hover-param-item">${req} <code>${escapeHtml(p.name)}</code>: ${escapeHtml(p.type)}${p.description ? ' — ' + escapeHtml(p.description) : ''}</div>`
    })
    sections.push({
      cls: 'mc-hover-params',
      html: paramLines.join(''),
    })
  }

  return createTooltipDOM(sections)
}

// ─── Build tooltip for ID parameters ──────────────────────────────────

function idTooltip(pn: ParameterNode): HTMLElement | null {
  const cache = useKnowledgeCache()
  const category = pn.resolvedCategory
  if (!category) return null

  const text = pn.token.text.replace(/^minecraft:/, '')
  const ids = cache.getIds(category)
  const entry = ids.find(e => e.id === text)

  const sections: Array<{ cls: string; html: string }> = []

  if (entry) {
    sections.push({
      cls: 'mc-hover-title',
      html: `<code>${escapeHtml(text)}</code>` +
        (entry.name ? ` <span class="mc-hover-name">${escapeHtml(entry.name)}</span>` : '') +
        ` <span class="mc-hover-badge">${escapeHtml(category)}</span>`,
    })
    if (entry.description) {
      sections.push({ cls: 'mc-hover-desc', html: escapeHtml(entry.description) })
    }
    if (entry.category) {
      sections.push({ cls: 'mc-hover-meta', html: `分类: ${escapeHtml(entry.category)}` })
    }
  } else {
    // Unknown ID
    const allIds = ids.map(e => e.id)
    let suggestion = ''
    const lower = text.toLowerCase()
    for (const id of allIds.slice(0, 200)) {
      if (id.toLowerCase().includes(lower) || lower.includes(id.toLowerCase())) {
        suggestion = id
        break
      }
    }

    sections.push({
      cls: 'mc-hover-error',
      html: `<span class="mc-hover-invalid">未知 ID: ${escapeHtml(text)}</span>` +
        (suggestion ? `<br>你是不是想用 <code>${escapeHtml(suggestion)}</code>？` : ''),
    })
  }

  return createTooltipDOM(sections)
}

// ─── Build tooltip for selector base ──────────────────────────────────

function selectorBaseTooltip(text: string): HTMLElement | null {
  const info = SELECTOR_DESC[text]
  if (!info) return null

  return createTooltipDOM([
    { cls: 'mc-hover-title', html: `<code>${escapeHtml(text)}</code> <span class="mc-hover-name">${escapeHtml(info.label)}</span>` },
    { cls: 'mc-hover-desc', html: escapeHtml(info.desc) },
  ])
}

// ─── Build tooltip for selector param key ─────────────────────────────

function selectorParamTooltip(paramName: string): HTMLElement | null {
  const def = SELECTOR_PARAM_MAP.get(paramName)
  if (!def) return null

  return createTooltipDOM([
    { cls: 'mc-hover-title', html: `<code>${escapeHtml(paramName)}</code> <span class="mc-hover-badge">${escapeHtml(def.valueType)}</span>` },
    { cls: 'mc-hover-desc', html: escapeHtml(def.description) },
  ])
}

// ─── Build tooltip for execute keywords ───────────────────────────────

function executeKeywordTooltip(keyword: string): HTMLElement | null {
  const info = EXECUTE_SUBCMD_DESC[keyword]
  if (!info) return null

  return createTooltipDOM([
    { cls: 'mc-hover-title', html: `<code>${escapeHtml(keyword)}</code> <span class="mc-hover-badge">execute 子命令</span>` },
    { cls: 'mc-hover-syntax', html: escapeHtml(info.syntax) },
    { cls: 'mc-hover-desc', html: escapeHtml(info.desc) },
  ])
}

// ─── Build tooltip for fixed option values ────────────────────────────

function fixedOptionTooltip(pn: ParameterNode): HTMLElement | null {
  if (!pn.paramDef) return null

  const opts = FIXED_OPTIONS[pn.paramDef.type]
  if (!opts) return null

  const match = opts.find(o => o.value === pn.token.text)
  if (!match) return null

  return createTooltipDOM([
    { cls: 'mc-hover-title', html: `<code>${escapeHtml(match.value)}</code> <span class="mc-hover-badge">${escapeHtml(pn.paramDef.type)}</span>` },
    { cls: 'mc-hover-desc', html: escapeHtml(match.description) },
  ])
}

// ─── Build tooltip for coordinates ────────────────────────────────────

function coordTooltip(token: Token): HTMLElement | null {
  const text = token.text
  let desc: string

  if (text.startsWith('~')) {
    const offset = text.slice(1) || '0'
    desc = `相对坐标: 相对当前位置偏移 ${offset} 格`
  } else if (text.startsWith('^')) {
    const offset = text.slice(1) || '0'
    desc = `局部坐标: 相对视线方向偏移 ${offset} 格 (左/上/前)`
  } else {
    desc = `绝对坐标: ${text}`
  }

  return createTooltipDOM([
    { cls: 'mc-hover-title', html: `<code>${escapeHtml(text)}</code> <span class="mc-hover-badge">坐标</span>` },
    { cls: 'mc-hover-desc', html: escapeHtml(desc) },
  ])
}

// ─── Hover tooltip extension ──────────────────────────────────────────

export function mcHoverTooltip() {
  return hoverTooltip((view, pos) => {
    const cache = useKnowledgeCache()
    if (!cache.loaded) return null

    const astMap = view.state.field(astCacheField, false)
    if (!astMap) return null

    const line = view.state.doc.lineAt(pos)
    const ast = astMap.get(line.number)
    if (!ast || ast.kind !== 'command') return null

    const cmdAST = ast as CommandLine
    const hit = findTokenAtPosition(ast, pos)
    if (!hit) return null

    const { token, node, isCommandName } = hit

    // Command name hover
    if (isCommandName && cmdAST.commandDef) {
      return {
        pos: token.from,
        end: token.to,
        above: true,
        create() {
          return { dom: commandTooltip(cmdAST) }
        },
      }
    }

    if (!node) return null

    // Selector base hover (@a, @e, etc.)
    if (node.selector && pos >= node.selector.base.from && pos <= node.selector.base.to) {
      const baseText = node.selector.base.text
      const dom = selectorBaseTooltip(baseText)
      if (dom) {
        return {
          pos: node.selector.base.from,
          end: node.selector.base.to,
          above: true,
          create() { return { dom } },
        }
      }
    }

    // Selector parameter key/value hover
    if (node.selector) {
      for (const sp of node.selector.params) {
        if (pos >= sp.key.from && pos <= sp.key.to) {
          const dom = selectorParamTooltip(sp.key.text)
          if (dom) {
            return {
              pos: sp.key.from,
              end: sp.key.to,
              above: true,
              create() { return { dom } },
            }
          }
        }
      }
    }

    // Execute subcommand keyword hover
    if (token.tokenType === 'keyword' && node.expectedType === '子命令') {
      const dom = executeKeywordTooltip(token.text)
      if (dom) {
        return {
          pos: token.from,
          end: token.to,
          above: true,
          create() { return { dom } },
        }
      }
    }

    // ID hover (items, blocks, entities, effects, etc.)
    if (node.resolvedCategory && token.tokenType === 'identifier') {
      const dom = idTooltip(node)
      if (dom) {
        return {
          pos: token.from,
          end: token.to,
          above: true,
          create() { return { dom } },
        }
      }
    }

    // Fixed option hover (gamemode, difficulty, etc.)
    if (node.paramDef && FIXED_OPTIONS[node.paramDef.type]) {
      const dom = fixedOptionTooltip(node)
      if (dom) {
        return {
          pos: token.from,
          end: token.to,
          above: true,
          create() { return { dom } },
        }
      }
    }

    // Coordinate hover
    if (token.tokenType === 'coord') {
      const dom = coordTooltip(token)
      if (dom) {
        return {
          pos: token.from,
          end: token.to,
          above: true,
          create() { return { dom } },
        }
      }
    }

    return null
  }, { hoverTime: 300 })
}
