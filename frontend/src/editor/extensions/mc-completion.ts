/**
 * CodeMirror CompletionSource for MC commands.
 * Uses the state machine + knowledge cache for zero-latency completions.
 *
 * Features:
 * - Completion Info panels (JetBrains-style documentation beside dropdown)
 * - Deep JSON/Rawtext structural completion
 * - Frequency-based completion ranking
 */
import type { CompletionContext, CompletionResult, Completion } from '@codemirror/autocomplete'
import { autocompletion, pickedCompletion } from '@codemirror/autocomplete'
import { EditorView } from '@codemirror/view'
import { parseCursorContext } from '../state-machine/command-parser'
import { SELECTOR_PARAM_DEFS, SELECTOR_PARAM_MAP } from '../state-machine/selector-parser'
import type { CursorContext } from '../state-machine/types'
import { TYPE_TO_CATEGORY, FIXED_OPTIONS } from '../constants/type-mappings'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import {
  createCommandInfoDOM,
  createIdInfoDOM,
  createFixedOptionInfoDOM,
  createSelectorParamInfoDOM,
} from '../utils/tooltip-dom'
import { parseJsonCursorContext } from '../utils/json-cursor-parser'

// ─── Completion Frequency Tracking (Feature 6) ──────────────────────

const FREQ_KEY = 'mc-completion-freq'
const MAX_FREQ_ENTRIES = 200

function getFrequencies(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(FREQ_KEY) || '{}')
  } catch { return {} }
}

function recordAcceptance(label: string): void {
  const freq = getFrequencies()
  freq[label] = (freq[label] || 0) + 1
  const entries = Object.entries(freq)
  if (entries.length > MAX_FREQ_ENTRIES) {
    entries.sort((a, b) => b[1] - a[1])
    const pruned: Record<string, number> = {}
    for (const [k, v] of entries.slice(0, MAX_FREQ_ENTRIES)) {
      pruned[k] = v
    }
    localStorage.setItem(FREQ_KEY, JSON.stringify(pruned))
  } else {
    localStorage.setItem(FREQ_KEY, JSON.stringify(freq))
  }
}

function freqBoost(label: string): number {
  const freq = getFrequencies()
  return Math.min((freq[label] || 0) * 2, 50)
}

/** Update listener that tracks accepted completions */
export const completionFrequencyTracker = EditorView.updateListener.of((update) => {
  for (const tr of update.transactions) {
    const picked = tr.annotation(pickedCompletion)
    if (picked) {
      recordAcceptance(picked.label)
    }
  }
})

/** The main completion source */
function mcCompletionSource(context: CompletionContext): CompletionResult | null {
  try {
    const cache = useKnowledgeCache()
    if (!cache.loaded) return null

    const line = context.state.doc.lineAt(context.pos)
    const lineText = line.text
    const col = context.pos - line.from

    const cursorCtx = parseCursorContext(
      lineText,
      col,
      (name) => cache.getCommand(name),
      (name) => cache.getSubcommandTree(name)
    )

    // Case 1: Completing command name
    if (cursorCtx.commandName === null && cursorCtx.commandDef === null) {
      return completeCommandName(cursorCtx.partialInput, context.pos)
    }

    // Case 2: Inside a selector @e[...]
    if (cursorCtx.inSelector) {
      return completeSelectorParam(cursorCtx, context.pos)
    }

    // Case 3: Subcommand keyword completion
    if (cursorCtx.expectedType === '子命令' && cursorCtx.availableSubcommands) {
      return completeSubcommandKeyword(cursorCtx, context.pos)
    }

    // Case 4: Subcommand option (literal with options like "eyes|feet")
    if (cursorCtx.expectedType === '子命令选项' && cursorCtx.availableSubcommands) {
      return completeSubcommandKeyword(cursorCtx, context.pos)
    }

    // Case 5: Nested command after "run" (Command type)
    if (cursorCtx.expectedType === 'Command') {
      return completeCommandName(cursorCtx.partialInput, context.pos)
    }

    // Case 6: Completing a parameter value
    if (cursorCtx.expectedType) {
      return completeParameterValue(cursorCtx, context.pos)
    }

    return null
  } catch (err) {
    console.error('[MC Completion] Error in completion source:', err)
    return null
  }
}

function completeCommandName(
  partial: string,
  pos: number
): CompletionResult | null {
  const cache = useKnowledgeCache()
  const names = cache.getCommandNames()
  // Strip leading / for matching (e.g. after execute...run /give)
  const stripped = partial.startsWith('/') ? partial.slice(1) : partial
  const lower = stripped.toLowerCase()

  const options: Completion[] = []
  for (const name of names) {
    if (!lower || name.toLowerCase().startsWith(lower)) {
      const cmd = cache.getCommand(name)
      options.push({
        label: name,
        detail: cmd?.description ?? '',
        type: 'keyword',
        boost: freqBoost(name),
        info: cmd ? () => createCommandInfoDOM(cmd) : undefined,
      })
    }
  }

  if (options.length === 0) return null

  // Start replacement after the / if present
  const from = pos - stripped.length
  return { from, options, validFor: /^[a-zA-Z_]\w*$/ }
}

function completeSubcommandKeyword(
  ctx: CursorContext,
  pos: number
): CompletionResult | null {
  const variants = ctx.availableSubcommands
  if (!variants || variants.length === 0) return null

  const partial = ctx.partialInput
  const from = pos - partial.length
  const lower = partial.toLowerCase()

  // Deduplicate by first keyword (many variants share the same first keyword)
  const seen = new Set<string>()
  const options: Completion[] = []

  for (const v of variants) {
    const kw = v.keywords[0]
    if (!kw) continue
    if (seen.has(kw)) continue
    if (lower && !kw.toLowerCase().startsWith(lower)) continue
    seen.add(kw)

    // Build a syntax preview from the full variant
    const syntaxPreview = buildSyntaxPreview(v)

    options.push({
      label: kw,
      detail: syntaxPreview,
      info: v.description || undefined,
      type: 'keyword',
    })
  }

  if (options.length === 0) return null
  return { from, options, validFor: /^[a-zA-Z_><!=+\-*/%]\w*$/ }
}

/** Build a short syntax preview string from a SubcommandVariant */
function buildSyntaxPreview(v: { keywords: string[]; params: { name: string; type: string; required: boolean; options?: string[] }[] }): string {
  const parts = [...v.keywords]
  for (const p of v.params) {
    if (p.type === 'literal' && p.options) {
      parts.push(p.options.join('|'))
    } else if (p.required) {
      parts.push(`<${p.name}>`)
    } else {
      parts.push(`[${p.name}]`)
    }
  }
  return parts.join(' ')
}

function completeParameterValue(
  ctx: CursorContext,
  pos: number
): CompletionResult | null {
  const cache = useKnowledgeCache()
  const type = ctx.expectedType!
  const partial = ctx.partialInput
  const from = pos - partial.length

  // Use sub-param description if available, else fall back to currentParam
  const paramDesc = ctx.currentSubParam?.name
    ? `${ctx.currentSubParam.name}: ${ctx.currentSubParam.type}`
    : ctx.currentParam?.description

  // Check fixed options first
  const fixed = FIXED_OPTIONS[type]
  if (fixed) {
    const lower = partial.toLowerCase()
    const options: Completion[] = fixed
      .filter((opt) => !lower || opt.value.toLowerCase().startsWith(lower))
      .map((opt) => ({
        label: opt.value,
        detail: opt.description,
        type: 'enum',
        boost: freqBoost(opt.value),
        info: () => createFixedOptionInfoDOM(opt.value, opt.description, type),
      }))
    if (options.length === 0) return null
    return { from, options, validFor: /^[@a-zA-Z_]\w*$/ }
  }

  // Check ID categories
  const category = TYPE_TO_CATEGORY[type]
  if (category) {
    const entries = cache.searchIds(category, partial, 50)
    const options: Completion[] = entries.map((e) => ({
      label: e.id,
      detail: e.name ?? '',
      type: 'variable',
      boost: freqBoost(e.id),
      info: () => createIdInfoDOM(e, category),
    }))
    if (options.length === 0) return null
    return { from, options, validFor: /^[a-zA-Z_][\w:.]*$/ }
  }

  // Sub-param literal options (e.g. "eyes|feet" from subcommand parser)
  if (ctx.currentSubParam?.options) {
    const lower = partial.toLowerCase()
    const options: Completion[] = ctx.currentSubParam.options
      .filter((o) => !lower || o.toLowerCase().startsWith(lower))
      .map((o) => ({ label: o, type: 'enum' }))
    if (options.length === 0) return null
    return { from, options, validFor: /^[a-zA-Z_]\w*$/ }
  }

  // JSON type: show rawtext templates (for tellraw, titleraw, etc.)
  if (type === 'json') {
    return completeRawTextJson(partial, from)
  }

  // Int/float: show range hint or default hint
  if (type === 'int' || type === 'float') {
    const param = ctx.currentParam ?? ctx.commandDef?.parameters[ctx.paramIndex]
    const rangeStr = param?.range ? `范围: ${param.range}` : (type === 'int' ? '整数' : '小数')
    return {
      from,
      options: [{
        label: partial || '0',
        detail: rangeStr,
        info: param?.description || paramDesc || undefined,
        type: 'text',
        boost: -1,
      }],
    }
  }

  // Coordinate type: show relative/absolute hints
  if (type === 'x y z') {
    if (!partial) {
      return {
        from,
        options: [
          { label: '~ ~ ~', detail: '当前位置(相对坐标)', type: 'text' },
          { label: '~ ~1 ~', detail: '当前位置上方1格', type: 'text' },
          { label: '^ ^ ^', detail: '当前朝向(局部坐标)', type: 'text' },
          { label: '0 0 0', detail: '绝对坐标', type: 'text' },
        ],
      }
    }
    return null
  }

  // String/message/value: show type hint (non-intrusive, only when empty)
  if ((type === 'string' || type === 'message') && !partial) {
    const param = ctx.currentParam
    return {
      from,
      options: [{
        label: `<${param?.name || ctx.currentSubParam?.name || type}>`,
        detail: type === 'message' ? '聊天消息文本' : '文本值',
        info: param?.description || paramDesc || undefined,
        type: 'text',
        boost: -99,
      }],
    }
  }

  return null
}

// ─── Rawtext Deep JSON Completion (Feature 3) ───────────────────────

/** Rawtext JSON keys by path context */
const RAWTEXT_COMPONENT_KEYS = [
  { key: 'text', desc: '纯文本内容', apply: '"text":"' },
  { key: 'selector', desc: '目标选择器 (显示实体名)', apply: '"selector":"' },
  { key: 'score', desc: '计分板分数', apply: '"score":{' },
  { key: 'translate', desc: '翻译键名', apply: '"translate":"' },
  { key: 'with', desc: '翻译参数 (rawtext数组)', apply: '"with":{"rawtext":[' },
]

const SCORE_KEYS = [
  { key: 'name', desc: '目标选择器或玩家名', apply: '"name":"' },
  { key: 'objective', desc: '计分板目标名', apply: '"objective":"' },
]

const SELECTOR_VALUES = ['@a', '@e', '@p', '@r', '@s', '@initiator']

/** MC color/format codes for §X completion */
const MC_FORMAT_COMPLETIONS = [
  { code: '0', desc: '黑色' }, { code: '1', desc: '深蓝' },
  { code: '2', desc: '深绿' }, { code: '3', desc: '深青' },
  { code: '4', desc: '深红' }, { code: '5', desc: '深紫' },
  { code: '6', desc: '金色' }, { code: '7', desc: '灰色' },
  { code: '8', desc: '深灰' }, { code: '9', desc: '蓝色' },
  { code: 'a', desc: '绿色' }, { code: 'b', desc: '青色' },
  { code: 'c', desc: '红色' }, { code: 'd', desc: '粉色' },
  { code: 'e', desc: '黄色' }, { code: 'f', desc: '白色' },
  { code: 'g', desc: '硬币金' }, { code: 'k', desc: '混淆(乱码)' },
  { code: 'l', desc: '粗体' }, { code: 'o', desc: '斜体' },
  { code: 'r', desc: '重置格式' },
]

/** Rawtext JSON completion (templates + deep structural) */
function completeRawTextJson(
  partial: string,
  from: number,
): CompletionResult | null {
  // Empty or very short — show templates
  if (!partial || partial.length <= 1) {
    return showRawTextTemplates(partial, from)
  }

  // Try deep JSON completion
  const ctx = parseJsonCursorContext(partial, partial.length)
  const cursorPos = from + partial.length
  const completionFrom = cursorPos - ctx.partialInput.length

  // Inside a string literal
  if (ctx.inString) {
    // Color/format code completion after §
    const lastSect = ctx.partialInput.lastIndexOf('\u00A7') // §
    if (lastSect >= 0) {
      const afterSect = ctx.partialInput.slice(lastSect + 1)
      const codeFrom = cursorPos - afterSect.length
      const lower = afterSect.toLowerCase()
      const options: Completion[] = MC_FORMAT_COMPLETIONS
        .filter(c => !lower || c.code.startsWith(lower))
        .map(c => ({
          label: c.code,
          detail: c.desc,
          type: 'enum',
        }))
      if (options.length > 0) return { from: codeFrom, options }
    }

    // Selector value completion
    if (ctx.currentKey === 'selector') {
      const lower = ctx.partialInput.toLowerCase()
      const options: Completion[] = SELECTOR_VALUES
        .filter(s => !lower || s.startsWith(lower))
        .map(s => ({ label: s, detail: s === '@a' ? '所有玩家' : s === '@e' ? '所有实体' : s === '@p' ? '最近玩家' : s === '@r' ? '随机玩家' : s === '@s' ? '执行者' : 'NPC交互者', type: 'enum' }))
      if (options.length > 0) return { from: completionFrom, options }
    }

    // Key name completion (typing inside quotes for an object key)
    if (ctx.expectingKey) {
      const keyDefs = getKeysForPath(ctx.path)
      if (keyDefs) {
        const lower = ctx.partialInput.toLowerCase()
        const options: Completion[] = keyDefs
          .filter(k => !lower || k.key.startsWith(lower))
          .map(k => ({
            label: k.key,
            detail: k.desc,
            apply: k.key + '":"',
            type: 'property',
          }))
        if (options.length > 0) return { from: completionFrom, options }
      }
    }

    return null
  }

  // Expecting object key (after { or ,) — not inside a string
  if (ctx.expectingKey) {
    const keyDefs = getKeysForPath(ctx.path)
    if (keyDefs) {
      const options: Completion[] = keyDefs.map(k => ({
        label: k.key,
        detail: k.desc,
        apply: k.apply,
        type: 'property',
      }))
      if (options.length > 0) return { from: completionFrom, options }
    }
  }

  // Expecting value in rawtext array — suggest component objects
  if (ctx.expectingValue && pathEndsWithRawtextArray(ctx.path)) {
    return {
      from: completionFrom,
      options: [
        { label: '{"text":""}', detail: '文本组件', type: 'text' },
        { label: '{"selector":"@a"}', detail: '选择器组件', type: 'text' },
        { label: '{"score":{"name":"@s","objective":""}}', detail: '分数组件', type: 'text' },
        { label: '{"translate":""}', detail: '翻译组件', type: 'text' },
      ],
    }
  }

  // Fallback to templates
  return showRawTextTemplates(partial, from)
}

/** Determine which keys are valid for the given path */
function getKeysForPath(path: (string | number)[]): typeof RAWTEXT_COMPONENT_KEYS | null {
  // Path like ["rawtext", <number>] → inside a rawtext array item
  if (path.length >= 2 && path[path.length - 2] === 'rawtext' && typeof path[path.length - 1] === 'number') {
    return RAWTEXT_COMPONENT_KEYS
  }
  // Path like ["rawtext", <number>, "score"] → inside score object
  if (path.length >= 3 && path[path.length - 1] === 'score') {
    return SCORE_KEYS
  }
  // At root level → suggest "rawtext"
  if (path.length === 0) {
    return [{ key: 'rawtext', desc: 'rawtext 数组', apply: '"rawtext":[' }]
  }
  return null
}

/** Check if path ends inside a rawtext array */
function pathEndsWithRawtextArray(path: (string | number)[]): boolean {
  return path.length >= 1 && path[path.length - 1] === 'rawtext'
}

/** Show rawtext templates (for empty or very short JSON input) */
function showRawTextTemplates(
  partial: string,
  from: number,
): CompletionResult | null {
  const templates = [
    { label: 'rawtext: 纯文本', apply: '{"rawtext":[{"text":""}]}', detail: '基本文本组件' },
    { label: 'rawtext: 带颜色文本', apply: '{"rawtext":[{"text":"§e在此输入§r"}]}', detail: '带颜色代码的文本' },
    { label: 'rawtext: 选择器', apply: '{"rawtext":[{"selector":"@a"}]}', detail: '显示实体/玩家名称' },
    { label: 'rawtext: 分数', apply: '{"rawtext":[{"score":{"name":"@s","objective":""}}]}', detail: '显示计分板分数' },
    { label: 'rawtext: 翻译文本', apply: '{"rawtext":[{"translate":"","with":{"rawtext":[{"selector":"@s"}]}}]}', detail: '翻译键 + 参数替换' },
    { label: 'rawtext: 组合', apply: '{"rawtext":[{"text":""},{"selector":"@s"},{"text":" 的分数: "},{"score":{"name":"@s","objective":""}}]}', detail: '多组件组合示例' },
  ]

  const lower = partial.toLowerCase()
  const options: Completion[] = templates
    .filter(t => !lower || t.apply.toLowerCase().startsWith(lower) || t.label.toLowerCase().includes(lower))
    .map(t => ({ label: t.label, apply: t.apply, detail: t.detail, type: 'text' as const }))

  if (options.length === 0) return null
  return { from, options }
}

/** Common entity family names in Bedrock Edition */
const ENTITY_FAMILIES = [
  { value: 'player', desc: '玩家' },
  { value: 'mob', desc: '生物' },
  { value: 'monster', desc: '怪物' },
  { value: 'undead', desc: '亡灵' },
  { value: 'skeleton', desc: '骷髅类' },
  { value: 'zombie', desc: '僵尸类' },
  { value: 'arthropod', desc: '节肢类' },
  { value: 'animal', desc: '动物' },
  { value: 'villager', desc: '村民' },
  { value: 'inanimate', desc: '非生物实体' },
  { value: 'illager', desc: '灾厄村民' },
  { value: 'hoglin', desc: '疣猪兽' },
  { value: 'piglin', desc: '猪灵' },
  { value: 'aquatic', desc: '水生生物' },
  { value: 'fish', desc: '鱼类' },
  { value: 'bat', desc: '蝙蝠' },
  { value: 'wolf', desc: '狼' },
  { value: 'cat', desc: '猫' },
  { value: 'iron_golem', desc: '铁傀儡' },
  { value: 'ocelot', desc: '豹猫' },
  { value: 'horse', desc: '马' },
  { value: 'creeper', desc: '苦力怕' },
  { value: 'enderman', desc: '末影人' },
  { value: 'breeze', desc: '旋风人' },
  { value: 'bogged', desc: '沼骸' },
]

/** haspermission valid permission names */
const HASPERMISSION_NAMES = [
  { value: 'camera', desc: '摄像机/视角控制' },
  { value: 'movement', desc: '所有移动' },
  { value: 'lateral_movement', desc: '横向移动' },
  { value: 'jump', desc: '跳跃' },
  { value: 'sneak', desc: '潜行' },
  { value: 'mount', desc: '骑乘' },
  { value: 'dismount', desc: '下坐骑' },
  { value: 'move_forward', desc: '向前移动' },
  { value: 'move_backward', desc: '向后移动' },
  { value: 'move_left', desc: '向左移动' },
  { value: 'move_right', desc: '向右移动' },
]

/** hasitem location slot types */
const HASITEM_LOCATIONS = [
  { value: 'slot.weapon.mainhand', desc: '主手' },
  { value: 'slot.weapon.offhand', desc: '副手' },
  { value: 'slot.armor.head', desc: '头盔槽' },
  { value: 'slot.armor.chest', desc: '胸甲槽' },
  { value: 'slot.armor.legs', desc: '护腿槽' },
  { value: 'slot.armor.feet', desc: '靴子槽' },
  { value: 'slot.hotbar', desc: '快捷栏 (0-8)' },
  { value: 'slot.inventory', desc: '物品栏' },
  { value: 'slot.enderchest', desc: '末影箱 (0-26)' },
  { value: 'slot.saddle', desc: '鞍槽' },
  { value: 'slot.armor', desc: '马铠槽' },
  { value: 'slot.chest', desc: '箱子栏(驴/骡/羊驼)' },
  { value: 'slot.equippable', desc: '可装备槽' },
]

function completeSelectorParam(
  ctx: CursorContext,
  pos: number
): CompletionResult | null {
  const cache = useKnowledgeCache()
  const partial = ctx.partialInput
  const from = pos - partial.length

  if (!ctx.selectorValue) {
    // Completing parameter name — with descriptions and info panels
    const lower = partial.toLowerCase()
    const options: Completion[] = SELECTOR_PARAM_DEFS
      .filter((d) => !lower || d.name.startsWith(lower))
      .map((d) => ({
        label: d.name,
        detail: d.description,
        type: 'property',
        apply: d.name + '=',
        boost: freqBoost(d.name),
        info: () => createSelectorParamInfoDOM(d.name, d.valueType, d.description),
      }))
    if (options.length === 0) return null
    return { from, options, validFor: /^[a-zA-Z_]\w*$/ }
  }

  // Completing parameter value
  const paramName = ctx.selectorParam
  const paramDef = paramName ? SELECTOR_PARAM_MAP.get(paramName) : null

  // --- type: entity ID search ---
  if (paramName === 'type') {
    const searchTerm = partial.startsWith('!') ? partial.slice(1) : partial
    const entries = cache.searchIds('entities', searchTerm, 50)
    const prefix = partial.startsWith('!') ? '!' : ''
    const options: Completion[] = entries.map((e) => ({
      label: prefix + e.id,
      detail: e.name ?? '',
      type: 'variable',
    }))
    // Also offer negation hint if empty
    if (!partial) {
      options.unshift({
        label: '!',
        detail: '排除指定类型 (取反)',
        type: 'keyword',
        boost: -1,
      })
    }
    if (options.length === 0) return null
    return { from, options, validFor: /^!?[a-zA-Z_][\w:.]*$/ }
  }

  // --- m: game mode ---
  if (paramName === 'm') {
    const modes = [
      { value: 'survival', desc: '生存模式 (0/s)' },
      { value: 'creative', desc: '创造模式 (1/c)' },
      { value: 'adventure', desc: '冒险模式 (2/a)' },
      { value: 'spectator', desc: '旁观模式' },
      { value: 'default', desc: '默认模式 (5/d)' },
      { value: '!survival', desc: '排除生存模式' },
      { value: '!creative', desc: '排除创造模式' },
      { value: '!adventure', desc: '排除冒险模式' },
      { value: '!spectator', desc: '排除旁观模式' },
    ]
    const lower = partial.toLowerCase()
    const options: Completion[] = modes
      .filter((m) => !lower || m.value.startsWith(lower))
      .map((m) => ({ label: m.value, detail: m.desc, type: 'enum' }))
    return { from, options, validFor: /^!?[a-zA-Z]\w*$/ }
  }

  // --- family: entity family ---
  if (paramName === 'family') {
    const searchTerm = partial.startsWith('!') ? partial.slice(1) : partial
    const prefix = partial.startsWith('!') ? '!' : ''
    const lower = searchTerm.toLowerCase()
    const options: Completion[] = ENTITY_FAMILIES
      .filter((f) => !lower || f.value.startsWith(lower))
      .map((f) => ({ label: prefix + f.value, detail: f.desc, type: 'enum' }))
    if (!partial) {
      options.unshift({
        label: '!',
        detail: '排除指定族 (取反)',
        type: 'keyword',
        boost: -1,
      })
    }
    if (options.length === 0) return null
    return { from, options, validFor: /^!?[a-zA-Z_]\w*$/ }
  }

  // --- tag / name: string with negation support ---
  if (paramName === 'tag' || paramName === 'name') {
    if (!partial) {
      const hint = paramName === 'tag' ? '标签名' : '实体名称'
      return {
        from,
        options: [
          { label: '!', detail: `排除指定${hint} (取反)`, type: 'keyword', boost: -1 },
          ...(paramName === 'tag'
            ? [{ label: '', detail: '匹配无标签实体 (tag=空)', type: 'text' as const, boost: -2 }]
            : []),
        ],
      }
    }
    return null
  }

  // --- scores: compound template ---
  if (paramName === 'scores') {
    if (!partial || partial === '{') {
      return {
        from,
        options: [
          { label: '{objective=值}', apply: '{objective=0}', detail: '精确匹配分数', type: 'text' },
          { label: '{obj=最小..最大}', apply: '{objective=0..10}', detail: '分数范围', type: 'text' },
          { label: '{obj=最小..}', apply: '{objective=1..}', detail: '大于等于', type: 'text' },
          { label: '{obj=..最大}', apply: '{objective=..5}', detail: '小于等于', type: 'text' },
          { label: '{obj=!值}', apply: '{objective=!0}', detail: '不等于', type: 'text' },
          { label: '{a=值,b=值}', apply: '{obj1=1,obj2=2}', detail: '多目标(AND)', type: 'text' },
        ],
      }
    }
    return null
  }

  // --- hasitem: compound template ---
  if (paramName === 'hasitem') {
    if (!partial || partial === '{' || partial === '[') {
      return {
        from,
        options: [
          { label: '单物品检测', apply: '{item=diamond}', detail: '检测是否有指定物品', type: 'text' },
          { label: '指定数量', apply: '{item=diamond,quantity=5..}', detail: '物品+数量范围', type: 'text' },
          { label: '指定位置', apply: '{item=diamond_sword,location=slot.weapon.mainhand}', detail: '物品+装备槽', type: 'text' },
          { label: '无此物品', apply: '{item=diamond,quantity=0}', detail: 'quantity=0 检测无物品', type: 'text' },
          { label: '多物品(AND)', apply: '[{item=apple},{item=stick}]', detail: '同时拥有多种物品', type: 'text' },
          { label: '完整语法', apply: '{item=,data=-1,quantity=1..,location=,slot=}', detail: '所有子参数', type: 'text' },
        ],
      }
    }
    // Inside hasitem compound — detect sub-parameter context
    return completeHasitemSubParam(partial, from, cache)
  }

  // --- haspermission: compound template ---
  if (paramName === 'haspermission') {
    if (!partial || partial === '{') {
      const options: Completion[] = HASPERMISSION_NAMES.map((p) => ({
        label: `{${p.value}=enabled}`,
        apply: `{${p.value}=enabled}`,
        detail: p.desc,
        type: 'text',
      }))
      options.push({
        label: '{权限=disabled}',
        apply: '{camera=disabled}',
        detail: '检测权限被禁用',
        type: 'text',
      })
      return { from, options }
    }
    // Inside haspermission compound — offer permission names and enabled/disabled
    return completeHaspermissionSubParam(partial, from)
  }

  // --- has_property: compound template ---
  if (paramName === 'has_property') {
    if (!partial || partial === '{') {
      return {
        from,
        options: [
          { label: '{属性=值}', apply: '{minecraft:has_nectar=true}', detail: '布尔属性检测', type: 'text' },
          { label: '{属性="字符串"}', apply: '{minecraft:climate_variant="warm"}', detail: '字符串属性检测', type: 'text' },
          { label: '{属性=范围}', apply: '{minecraft:creaking_swaying_ticks=1..5}', detail: '数值范围检测', type: 'text' },
          { label: '{属性=!值}', apply: '{minecraft:climate_variant=!"cold"}', detail: '取反检测', type: 'text' },
        ],
      }
    }
    return null
  }

  // --- r/rm: distance ---
  if (paramName === 'r' || paramName === 'rm') {
    if (!partial) {
      const hint = paramName === 'r' ? '最大距离(方块数)' : '最小距离(方块数)'
      return {
        from,
        options: [
          { label: '5', detail: hint, type: 'text' },
          { label: '10', detail: hint, type: 'text' },
          { label: '50', detail: hint, type: 'text' },
          { label: '100', detail: hint, type: 'text' },
        ],
      }
    }
    return null
  }

  // --- l/lm: experience level ---
  if (paramName === 'l' || paramName === 'lm') {
    if (!partial) {
      const hint = paramName === 'l' ? '最大经验等级' : '最小经验等级'
      return {
        from,
        options: [
          { label: '0', detail: hint, type: 'text' },
          { label: '10', detail: hint, type: 'text' },
          { label: '30', detail: hint, type: 'text' },
        ],
      }
    }
    return null
  }

  // --- c: count/limit ---
  if (paramName === 'c') {
    if (!partial) {
      return {
        from,
        options: [
          { label: '1', detail: '最近的1个目标', type: 'text' },
          { label: '5', detail: '最近的5个目标', type: 'text' },
          { label: '-1', detail: '最远的1个目标(反转排序)', type: 'text' },
        ],
      }
    }
    return null
  }

  // --- x/y/z: coordinates ---
  if (paramName === 'x' || paramName === 'y' || paramName === 'z') {
    if (!partial) {
      return {
        from,
        options: [
          { label: '~', detail: '相对当前位置', type: 'text' },
          { label: '0', detail: '绝对坐标', type: 'text' },
        ],
      }
    }
    return null
  }

  // --- dx/dy/dz: volume extent ---
  if (paramName === 'dx' || paramName === 'dy' || paramName === 'dz') {
    if (!partial) {
      return {
        from,
        options: [
          { label: '5', detail: '区域范围(方块数)', type: 'text' },
          { label: '10', detail: '区域范围(方块数)', type: 'text' },
        ],
      }
    }
    return null
  }

  // --- rx/rxm: vertical rotation (pitch) ---
  if (paramName === 'rx' || paramName === 'rxm') {
    if (!partial) {
      const hint = paramName === 'rx' ? '最大俯仰角' : '最小俯仰角'
      return {
        from,
        options: [
          { label: '-90', detail: `${hint} (正上方)`, type: 'text' },
          { label: '-45', detail: `${hint} (仰视)`, type: 'text' },
          { label: '0', detail: `${hint} (平视)`, type: 'text' },
          { label: '45', detail: `${hint} (俯视)`, type: 'text' },
          { label: '90', detail: `${hint} (正下方)`, type: 'text' },
        ],
      }
    }
    return null
  }

  // --- ry/rym: horizontal rotation (yaw) ---
  if (paramName === 'ry' || paramName === 'rym') {
    if (!partial) {
      const hint = paramName === 'ry' ? '最大偏航角' : '最小偏航角'
      return {
        from,
        options: [
          { label: '0', detail: `${hint} (南)`, type: 'text' },
          { label: '90', detail: `${hint} (西)`, type: 'text' },
          { label: '180', detail: `${hint} (北)`, type: 'text' },
          { label: '-90', detail: `${hint} (东)`, type: 'text' },
          { label: '-180', detail: `${hint} (北)`, type: 'text' },
        ],
      }
    }
    return null
  }

  // Fallback: show value type hint from param definition
  if (paramDef && !partial) {
    const typeHints: Record<string, string> = {
      'int': '整数值',
      'float': '小数值',
      'string': '文本值',
      'boolean': 'true 或 false',
      'compound': '复合参数 {...}',
    }
    const hint = typeHints[paramDef.valueType]
    if (hint) {
      return {
        from,
        options: [{ label: `<${paramDef.name}>`, detail: hint, type: 'text', boost: -99 }],
      }
    }
  }

  return null
}

/** Complete sub-parameters inside hasitem={...} */
function completeHasitemSubParam(
  partial: string,
  from: number,
  cache: ReturnType<typeof useKnowledgeCache>,
): CompletionResult | null {
  // Find the last sub-parameter being typed inside the braces
  // e.g. partial = "{item=diamond,location=" → we're completing "location" value
  const lastComma = partial.lastIndexOf(',')
  const lastBrace = partial.lastIndexOf('{')
  const start = Math.max(lastComma, lastBrace)
  const currentPart = partial.slice(start + 1)
  const eqIdx = currentPart.indexOf('=')

  if (eqIdx === -1) {
    // Typing sub-parameter name
    const lower = currentPart.toLowerCase()
    const subParams = [
      { name: 'item', desc: '物品ID (必填)' },
      { name: 'data', desc: '物品数据值 (默认-1=任意)' },
      { name: 'quantity', desc: '数量 (支持范围, 0=没有此物品)' },
      { name: 'location', desc: '装备槽类型' },
      { name: 'slot', desc: '槽位编号 (需配合location)' },
    ]
    const subFrom = from + start + 1
    const options: Completion[] = subParams
      .filter((p) => !lower || p.name.startsWith(lower))
      .map((p) => ({
        label: p.name,
        detail: p.desc,
        type: 'property',
        apply: p.name + '=',
      }))
    if (options.length === 0) return null
    return { from: subFrom, options, validFor: /^[a-zA-Z_]\w*$/ }
  }

  // Typing sub-parameter value
  const subParamName = currentPart.slice(0, eqIdx)
  const subValue = currentPart.slice(eqIdx + 1)
  const valueFrom = from + start + 1 + eqIdx + 1

  if (subParamName === 'item') {
    const entries = cache.searchIds('items', subValue, 50)
    const options: Completion[] = entries.map((e) => ({
      label: e.id,
      detail: e.name ?? '',
      type: 'variable',
    }))
    if (options.length === 0) return null
    return { from: valueFrom, options, validFor: /^[a-zA-Z_][\w:.]*$/ }
  }

  if (subParamName === 'location') {
    const lower = subValue.toLowerCase()
    const options: Completion[] = HASITEM_LOCATIONS
      .filter((l) => !lower || l.value.toLowerCase().startsWith(lower))
      .map((l) => ({ label: l.value, detail: l.desc, type: 'enum' }))
    if (options.length === 0) return null
    return { from: valueFrom, options, validFor: /^[a-zA-Z_.]\w*$/ }
  }

  if (subParamName === 'quantity') {
    if (!subValue) {
      return {
        from: valueFrom,
        options: [
          { label: '0', detail: '没有此物品', type: 'text' },
          { label: '1..', detail: '至少1个(默认)', type: 'text' },
          { label: '5..', detail: '至少5个', type: 'text' },
          { label: '1..64', detail: '1到64个', type: 'text' },
          { label: '..10', detail: '最多10个', type: 'text' },
        ],
      }
    }
    return null
  }

  return null
}

/** Complete sub-parameters inside haspermission={...} */
function completeHaspermissionSubParam(
  partial: string,
  from: number,
): CompletionResult | null {
  const lastComma = partial.lastIndexOf(',')
  const lastBrace = partial.lastIndexOf('{')
  const start = Math.max(lastComma, lastBrace)
  const currentPart = partial.slice(start + 1)
  const eqIdx = currentPart.indexOf('=')

  if (eqIdx === -1) {
    // Typing permission name
    const lower = currentPart.toLowerCase()
    const subFrom = from + start + 1
    const options: Completion[] = HASPERMISSION_NAMES
      .filter((p) => !lower || p.value.startsWith(lower))
      .map((p) => ({
        label: p.value,
        detail: p.desc,
        type: 'property',
        apply: p.value + '=',
      }))
    if (options.length === 0) return null
    return { from: subFrom, options, validFor: /^[a-zA-Z_]\w*$/ }
  }

  // Typing enabled/disabled
  const subValue = currentPart.slice(eqIdx + 1)
  const valueFrom = from + start + 1 + eqIdx + 1
  const lower = subValue.toLowerCase()
  const states = [
    { value: 'enabled', desc: '权限已启用' },
    { value: 'disabled', desc: '权限已禁用' },
  ]
  const options: Completion[] = states
    .filter((s) => !lower || s.value.startsWith(lower))
    .map((s) => ({ label: s.value, detail: s.desc, type: 'enum' }))
  if (options.length === 0) return null
  return { from: valueFrom, options, validFor: /^[a-zA-Z]\w*$/ }
}

/** Export the autocompletion extension configured for MC commands */
export function mcCompletion() {
  return autocompletion({
    override: [mcCompletionSource],
    activateOnTyping: true,
    maxRenderedOptions: 50,
  })
}
