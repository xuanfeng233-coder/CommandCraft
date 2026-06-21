<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { McButton, McInput, McTag, McScrollbar } from '@/components/mc-ui'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import { TYPE_TO_CATEGORY, FIXED_OPTIONS } from './constants/type-mappings'
import type { CommandSyntaxDef, CommandParamDef } from './state-machine/types'

const emit = defineEmits<{
  command: [cmd: string]
}>()

const knowledgeCache = useKnowledgeCache()

// ─── Types ───
interface ParsedSubParam {
  name: string
  type: string
  required: boolean
  description?: string
  options?: string[] // for pipe-separated options like "eyes|feet"
}

interface SubcommandVariant {
  label: string        // display: first keyword or full keywords
  keywords: string[]   // literal tokens to insert
  subParams: ParsedSubParam[]
  description: string  // from original CommandParamDef
  raw: string          // original param name for reference
}

interface RawtextSegment {
  type: 'text' | 'selector' | 'score' | 'translate'
  value: string       // text content, selector, or translate key
  objective?: string  // for score type
  name?: string       // for score type (player name/selector)
  with?: string[]     // for translate args
}

/** Item component state for give command */
interface ItemComponents {
  canPlaceOn: string[]
  canDestroy: string[]
  itemLock: '' | 'lock_in_slot' | 'lock_in_inventory'
  keepOnDeath: boolean
}

const COLOR_CODES = [
  { code: '§0', color: '#000', label: '黑' }, { code: '§1', color: '#0000AA', label: '深蓝' },
  { code: '§2', color: '#00AA00', label: '深绿' }, { code: '§3', color: '#00AAAA', label: '深青' },
  { code: '§4', color: '#AA0000', label: '深红' }, { code: '§5', color: '#AA00AA', label: '紫' },
  { code: '§6', color: '#FFAA00', label: '金' }, { code: '§7', color: '#AAA', label: '灰' },
  { code: '§8', color: '#555', label: '深灰' }, { code: '§9', color: '#5555FF', label: '蓝' },
  { code: '§a', color: '#55FF55', label: '绿' }, { code: '§b', color: '#55FFFF', label: '青' },
  { code: '§c', color: '#FF5555', label: '红' }, { code: '§d', color: '#FF55FF', label: '粉' },
  { code: '§e', color: '#FFFF55', label: '黄' }, { code: '§f', color: '#FFF', label: '白' },
  { code: '§l', color: '', label: '粗体' }, { code: '§o', color: '', label: '斜体' },
  { code: '§r', color: '', label: '重置' },
]

// ─── Subcommand Parser ───

/**
 * Tokenize a subcommand param name, handling nested brackets correctly.
 * e.g. "[ease <easeTime: float> <easeType: Easing>]" → single token
 *      "<scan mode: all|masked>" → single token (space in name)
 */
function tokenizeParamName(raw: string): string[] {
  const tokens: string[] = []
  let i = 0
  while (i < raw.length) {
    if (raw[i] === ' ') { i++; continue }
    if (raw[i] === '<' || raw[i] === '[') {
      const close = raw[i] === '<' ? '>' : ']'
      let depth = 1
      let j = i + 1
      while (j < raw.length && depth > 0) {
        if (raw[j] === raw[i]) depth++
        else if (raw[j] === close) depth--
        j++
      }
      tokens.push(raw.slice(i, j))
      i = j
    } else {
      let j = i
      while (j < raw.length && raw[j] !== ' ' && raw[j] !== '<' && raw[j] !== '[') j++
      tokens.push(raw.slice(i, j))
      i = j
    }
  }
  return tokens
}

function parseSingleParam(tok: string, required: boolean): ParsedSubParam | null {
  // Strip outer brackets: <...> or [...]
  const inner = tok.slice(1, -1).trim()

  // Check for nested sub-group: "ease <easeTime: float> <easeType: Easing>"
  // Only trigger if there are actual nested bracket patterns (keyword + <param>)
  // NOT for literal < in type values like "< | <= | = | >= | >"
  const hasNestedBrackets = /\w\s+<\w+:/.test(inner) || /\w\s+\[\w+/.test(inner)
  if (hasNestedBrackets) {
    return null // signal caller to flatten
  }

  // Bare pipe options without name: "append|replace" or "daytime|gametime|day"
  if (!inner.includes(':') && inner.includes('|')) {
    const opts = inner.split('|').map((s) => s.trim())
    return { name: opts.join('/'), type: 'enum_inline', required, options: opts }
  }

  // Simple name: "default" → flag
  if (!inner.includes(':')) {
    return { name: inner, type: 'flag', required: false }
  }

  // "name: type" — name may contain spaces or hyphens
  const colonIdx = inner.indexOf(':')
  const name = inner.slice(0, colonIdx).trim()
  const type = inner.slice(colonIdx + 1).trim()

  // Pipe options in type: "all|masked", "eyes|feet"
  if (type.includes('|')) {
    const opts = type.split('|').map((s) => s.trim())
    return { name, type: 'enum_inline', required, options: opts }
  }

  return { name, type, required }
}

function parseSubcommandVariant(param: CommandParamDef): SubcommandVariant | null {
  const raw = param.name
  // Skip meta-references like "unless ..." — expanded separately
  if (raw.includes('...')) return null

  const tokens = tokenizeParamName(raw)
  const keywords: string[] = []
  const subParams: ParsedSubParam[] = []

  for (const tok of tokens) {
    if (tok.startsWith('<')) {
      // Required param
      const p = parseSingleParam(tok, true)
      if (p) {
        subParams.push(p)
      } else {
        // Nested group — flatten: first word is keyword, inner <> are params
        const inner = tok.slice(1, -1).trim()
        const nested = tokenizeParamName(inner)
        for (const nt of nested) {
          if (nt.startsWith('<')) {
            const np = parseSingleParam(nt, true)
            if (np) subParams.push(np)
          } else if (nt.startsWith('[')) {
            const np = parseSingleParam(nt, false)
            if (np) subParams.push(np)
          } else {
            keywords.push(nt)
          }
        }
      }
    } else if (tok.startsWith('[')) {
      // Optional param or optional group
      const inner = tok.slice(1, -1).trim()
      // Check if it's a nested group: [ease <easeTime:...> ...]
      if (inner.includes('<') || inner.includes('[')) {
        const nested = tokenizeParamName(inner)
        for (const nt of nested) {
          if (nt.startsWith('<')) {
            const np = parseSingleParam(nt, false)
            if (np) subParams.push(np)
          } else if (nt.startsWith('[')) {
            const np = parseSingleParam(nt, false)
            if (np) subParams.push(np)
          } else {
            keywords.push(nt)
          }
        }
      } else {
        const p = parseSingleParam(tok, false)
        if (p) subParams.push(p)
      }
    } else {
      // Literal keyword
      keywords.push(tok)
    }
  }

  return {
    label: keywords.join(' ') || raw,
    keywords,
    subParams,
    description: param.description || '',
    raw,
  }
}

// ─── Chaining support ───
interface ChainedSub {
  variant: SubcommandVariant
  values: string[]
}

/** Whether a command supports chaining subcommands (like execute) */
function isChainable(cmd: CommandSyntaxDef): boolean {
  return cmd.name === 'execute'
}

// ─── State Machine ───
type Phase = 'select' | 'fill' | 'pick_variant' | 'fill_sub' | 'complete'
const phase = ref<Phase>('select')
const selectedCommand = ref<CommandSyntaxDef | null>(null)
// Normal params
const currentStep = ref(0)
const paramValues = ref<string[]>([])
// Subcommand
const subcommandVariants = ref<SubcommandVariant[]>([])
const selectedVariant = ref<SubcommandVariant | null>(null)
const subStep = ref(0)
const subParamValues = ref<string[]>([])
// Chaining (for execute)
const chain = ref<ChainedSub[]>([])
// JSON builder
const rawtextSegments = ref<RawtextSegment[]>([])

// ─── Phase 1: Command Selection ───
const searchQuery = ref('')

const CATEGORY_LABELS: Record<string, string> = {
  item_management: '物品管理', teleportation: '传送', execution: '执行',
  scoreboard: '计分板', effects: '效果', entity: '实体',
  world_editing: '世界编辑', display: '显示', entity_management: '实体管理',
  game_settings: '游戏设置', multimedia: '多媒体', player_management: '玩家管理',
  server_admin: '服务器', communication: '聊天', world_management: '世界管理',
  testing: '测试', spawn: '出生点', advanced: '高级', camera: '相机',
  scripting: '脚本', agent: '代理', education: '教育版', websocket: 'WebSocket',
  info: '信息', editor: '编辑器',
}

/** Split params into normal + subcommand groups */
function getNormalParams(cmd: CommandSyntaxDef): CommandParamDef[] {
  return cmd.parameters.filter((p) => !p.name.includes(' ') && !p.name.includes('<'))
}

function getSubcommandParams(cmd: CommandSyntaxDef): CommandParamDef[] {
  return cmd.parameters.filter((p) => p.name.includes(' ') || (p.name.includes('<') && p.name.includes(':')))
}

function hasSubcommands(cmd: CommandSyntaxDef): boolean {
  return getSubcommandParams(cmd).length > 0
}

const filteredCommands = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  const groups = new Map<string, CommandSyntaxDef[]>()
  for (const cmd of knowledgeCache.commands) {
    if (cmd.name.endsWith('old')) continue
    if (q && !cmd.name.includes(q) && !cmd.description.includes(q)) continue
    const cat = cmd.category || 'other'
    if (!groups.has(cat)) groups.set(cat, [])
    groups.get(cat)!.push(cmd)
  }
  return groups
})

function selectCommand(cmd: CommandSyntaxDef) {
  selectedCommand.value = cmd
  const normals = getNormalParams(cmd)
  paramValues.value = normals.map((p) => p.default ?? '')
  currentStep.value = 0

  // Parse subcommands
  const subParams = getSubcommandParams(cmd)
  const parsed: SubcommandVariant[] = []
  const ifVariants: SubcommandVariant[] = []

  for (const sp of subParams) {
    const v = parseSubcommandVariant(sp)
    if (!v) continue // skip "..." references
    parsed.push(v)
    // Collect "if ..." variants to duplicate for "unless"
    if (v.keywords[0] === 'if') ifVariants.push(v)
  }

  // Expand "unless ..." by duplicating all "if" variants
  if (subParams.some((p) => p.name.includes('unless ...'))) {
    for (const ifV of ifVariants) {
      parsed.push({
        ...ifV,
        label: 'unless ' + ifV.keywords.slice(1).join(' '),
        keywords: ['unless', ...ifV.keywords.slice(1)],
        description: ifV.description.replace(/如果/g, '除非').replace(/if/gi, 'unless'),
        raw: ifV.raw.replace(/^if/, 'unless'),
      })
    }
  }

  subcommandVariants.value = parsed
  selectedVariant.value = null
  subStep.value = 0
  subParamValues.value = []
  chain.value = []
  rawtextSegments.value = []

  if (normals.length > 0) {
    phase.value = 'fill'
  } else if (parsed.length > 0) {
    phase.value = 'pick_variant'
  } else {
    phase.value = 'complete'
  }
}

// ─── Phase 2: Normal param fill ───
const fillSearchQuery = ref('')
const fillSearchInputRef = ref<HTMLElement | null>(null)

const normalParams = computed(() =>
  selectedCommand.value ? getNormalParams(selectedCommand.value) : []
)

const currentParam = computed<CommandParamDef | null>(() =>
  normalParams.value[currentStep.value] ?? null
)

/** Detect if a json param is rawtext or item components */
function isRawtextParam(paramName: string, cmdName: string): boolean {
  const n = paramName.toLowerCase()
  if (n.includes('rawjson') || n.includes('message') || n.includes('text')) return true
  if (cmdName === 'tellraw' || cmdName === 'titleraw') return true
  return false
}

const inputMode = computed<'buttons' | 'search' | 'number' | 'text' | 'coord' | 'rawtext' | 'components'>(() => {
  const p = currentParam.value
  if (!p) return 'text'
  const t = p.type
  if (t === 'x y z') return 'coord'
  if (t === 'json') {
    const cmd = selectedCommand.value?.name || ''
    return isRawtextParam(p.name, cmd) ? 'rawtext' : 'components'
  }
  if (FIXED_OPTIONS[t]) return 'buttons'
  if (TYPE_TO_CATEGORY[t]) return 'search'
  if (t === 'int' || t === 'float' || t === 'value') return 'number'
  return 'text'
})

const buttonOptions = computed(() => {
  const p = currentParam.value
  if (!p) return []
  return FIXED_OPTIONS[p.type] ?? []
})

// ─── Entity → SpawnEvent relevance (reused from before) ───
const ENTITY_TO_EVENT_CATS: Record<string, string[]> = {
  creeper: ['creeper'], zombie: ['zombie'], drowned: ['zombie', 'drowned'],
  husk: ['zombie', 'husk'], zombie_villager: ['zombie_villager'],
  zombie_villager_v2: ['zombie_villager'], skeleton: ['skeleton'],
  stray: ['skeleton'], wither_skeleton: ['skeleton'],
  skeleton_horse: ['skeleton_horse'], spider: ['spider', 'neutral_mob'],
  cave_spider: ['spider', 'neutral_mob'], enderman: ['neutral_mob'],
  bee: ['neutral_mob'], wolf: ['wolf', 'neutral_mob', 'tameable'],
  cat: ['cat', 'tameable'], ocelot: ['tameable'], parrot: ['tameable'],
  horse: ['horse', 'tameable'], donkey: ['horse', 'tameable'],
  mule: ['horse', 'tameable'], zombie_horse: ['horse', 'skeleton_horse'],
  llama: ['tameable'], trader_llama: ['tameable'],
  villager: ['villager'], villager_v2: ['villager'],
  iron_golem: ['iron_golem'], sheep: ['sheep', 'shearable'],
  snow_golem: ['shearable'], slime: ['slime'], magma_cube: ['slime'],
  pillager: ['raid'], vindicator: ['raid', 'vindicator'], evoker: ['raid'],
  ravager: ['raid'], witch: ['raid'], warden: ['warden'], frog: ['frog'],
  fox: ['fox'], panda: ['panda'], hoglin: ['nether'],
  piglin: ['nether', 'piglin'], piglin_brute: ['nether'],
  zoglin: ['nether'], strider: ['nether', 'strider'],
  mooshroom: ['mooshroom'], ender_dragon: ['ender_dragon'],
  armadillo: ['armadillo'], shulker: ['shulker'], goat: ['goat'],
  turtle: ['turtle'], bogged: ['skeleton'],
}

const selectedEntityType = computed<string>(() => {
  if (!selectedCommand.value) return ''
  const params = getNormalParams(selectedCommand.value)
  const entityIdx = params.findIndex((p) => p.type === 'EntityType')
  if (entityIdx < 0) return ''
  return paramValues.value[entityIdx] || ''
})

const relevantEventCats = computed<Set<string>>(() => {
  const entity = selectedEntityType.value
  if (!entity) return new Set()
  return new Set([...(ENTITY_TO_EVENT_CATS[entity] || []), 'common'])
})

function isRelevantEvent(entry: { id: string; category?: string }): boolean {
  if (relevantEventCats.value.size === 0) return false
  return relevantEventCats.value.has(entry.category || '')
}

const searchOptions = computed(() => {
  const p = currentParam.value
  if (!p) return []
  const cat = TYPE_TO_CATEGORY[p.type]
  if (!cat) return []
  const q = fillSearchQuery.value.toLowerCase().trim()
  let entries = q ? knowledgeCache.searchIds(cat, q, 100) : knowledgeCache.getIds(cat)
  if (p.type === 'SpawnEvent' && selectedEntityType.value) {
    const relevant: typeof entries = []
    const rest: typeof entries = []
    for (const e of entries) {
      if (isRelevantEvent(e)) relevant.push(e)
      else rest.push(e)
    }
    entries = [...relevant, ...rest]
  }
  return entries
})

// Coordinate sub-fields
const coordX = ref('~')
const coordY = ref('~')
const coordZ = ref('~')

watch(currentStep, () => {
  fillSearchQuery.value = ''
  if (currentParam.value?.type === 'x y z') {
    const existing = paramValues.value[currentStep.value]
    if (existing) {
      const parts = existing.split(' ')
      coordX.value = parts[0] || '~'; coordY.value = parts[1] || '~'; coordZ.value = parts[2] || '~'
    } else {
      coordX.value = '~'; coordY.value = '~'; coordZ.value = '~'
    }
  }
  if (inputMode.value === 'rawtext') {
    rawtextSegments.value = [{ type: 'text', value: '' }]
  }
  if (inputMode.value === 'components') {
    itemComp.value = { canPlaceOn: [], canDestroy: [], itemLock: '', keepOnDeath: false }
    compBlockInput.value = ''
    compDestroyInput.value = ''
  }
  nextTick(() => {
    const el = fillSearchInputRef.value
    if (el) { const input = el.querySelector?.('input') ?? el; (input as HTMLElement).focus?.() }
  })
})

function setParamValue(val: string) {
  paramValues.value[currentStep.value] = val
  goNextNormal()
}

function setCoordValue() {
  paramValues.value[currentStep.value] = `${coordX.value} ${coordY.value} ${coordZ.value}`
  goNextNormal()
}

function goNextNormal() {
  if (currentStep.value < normalParams.value.length - 1) {
    currentStep.value++
  } else if (subcommandVariants.value.length > 0) {
    phase.value = 'pick_variant'
  } else {
    phase.value = 'complete'
  }
}

function goPrevNormal() {
  if (currentStep.value > 0) currentStep.value--
}

function skipNormalParam() {
  paramValues.value[currentStep.value] = ''
  goNextNormal()
}

// ─── JSON / Rawtext builder ───
// ─── Rawtext builder ───
function addRawtextSegment(type: 'text' | 'selector' | 'score' | 'translate') {
  if (type === 'score') {
    rawtextSegments.value.push({ type: 'score', value: '', objective: '', name: '@s' })
  } else if (type === 'translate') {
    rawtextSegments.value.push({ type: 'translate', value: '', with: [''] })
  } else {
    rawtextSegments.value.push({ type, value: '' })
  }
}

function removeRawtextSegment(i: number) {
  rawtextSegments.value.splice(i, 1)
}

function insertColorCode(segIndex: number, code: string) {
  const seg = rawtextSegments.value[segIndex]
  if (seg && seg.type === 'text') {
    seg.value += code
  }
}

function addTranslateArg(segIndex: number) {
  const seg = rawtextSegments.value[segIndex]
  if (seg?.with) seg.with.push('')
}

function removeTranslateArg(segIndex: number, argIndex: number) {
  const seg = rawtextSegments.value[segIndex]
  if (seg?.with && seg.with.length > 1) seg.with.splice(argIndex, 1)
}

function buildRawtextJson(): string {
  const parts: Record<string, unknown>[] = []
  for (const s of rawtextSegments.value) {
    if (s.type === 'text' && s.value) parts.push({ text: s.value })
    else if (s.type === 'selector') parts.push({ selector: s.value || '@s' })
    else if (s.type === 'score') parts.push({ score: { name: s.name || '@s', objective: s.objective || 'dummy' } })
    else if (s.type === 'translate' && s.value) {
      const entry: Record<string, unknown> = { translate: s.value }
      if (s.with && s.with.some((a) => a)) entry.with = { rawtext: s.with.filter(Boolean).map((a) => ({ text: a })) }
      parts.push(entry)
    }
  }
  return JSON.stringify({ rawtext: parts.length ? parts : [{ text: '' }] })
}

function confirmRawtext() {
  paramValues.value[currentStep.value] = buildRawtextJson()
  goNextNormal()
}

// ─── Item components builder (give) ───
const itemComp = ref<ItemComponents>({
  canPlaceOn: [], canDestroy: [], itemLock: '', keepOnDeath: false,
})
const compBlockInput = ref('')
const compDestroyInput = ref('')

const compBlockResults = computed(() =>
  compBlockInput.value
    ? knowledgeCache.searchIds('blocks', compBlockInput.value, 15)
    : knowledgeCache.getIds('blocks')
)
const compDestroyResults = computed(() =>
  compDestroyInput.value
    ? knowledgeCache.searchIds('blocks', compDestroyInput.value, 15)
    : knowledgeCache.getIds('blocks')
)

function addCompBlock(list: 'canPlaceOn' | 'canDestroy', val: string) {
  const v = val.trim()
  if (!v) return
  if (!itemComp.value[list].includes(v)) itemComp.value[list].push(v)
}

function removeCompBlock(list: 'canPlaceOn' | 'canDestroy', i: number) {
  itemComp.value[list].splice(i, 1)
}

function buildComponentsJson(): string {
  const obj: Record<string, unknown> = {}
  if (itemComp.value.canPlaceOn.length) {
    obj['minecraft:can_place_on'] = { blocks: itemComp.value.canPlaceOn }
  }
  if (itemComp.value.canDestroy.length) {
    obj['minecraft:can_destroy'] = { blocks: itemComp.value.canDestroy }
  }
  if (itemComp.value.itemLock) {
    obj['minecraft:item_lock'] = { mode: itemComp.value.itemLock }
  }
  if (itemComp.value.keepOnDeath) {
    obj['minecraft:keep_on_death'] = {}
  }
  return Object.keys(obj).length ? JSON.stringify(obj) : ''
}

function confirmComponents() {
  paramValues.value[currentStep.value] = buildComponentsJson()
  goNextNormal()
}

// ─── Selector Builder ───
interface SelectorCondition {
  param: string
  value: string
  negated: boolean
  _open?: boolean
}

const SELECTOR_PARAM_LIST = [
  { name: 'type', label: '实体类型', valueType: 'search' as const, category: 'entities' },
  { name: 'name', label: '名称', valueType: 'text' as const },
  { name: 'tag', label: '标签', valueType: 'text' as const },
  { name: 'family', label: '族', valueType: 'text' as const },
  { name: 'r', label: '最大半径', valueType: 'number' as const },
  { name: 'rm', label: '最小半径', valueType: 'number' as const },
  { name: 'c', label: '数量', valueType: 'number' as const },
  { name: 'l', label: '最大等级', valueType: 'number' as const },
  { name: 'lm', label: '最小等级', valueType: 'number' as const },
  { name: 'm', label: '游戏模式', valueType: 'select' as const, options: ['survival', 'creative', 'adventure', 'spectator'] },
  { name: 'x', label: 'X坐标', valueType: 'number' as const },
  { name: 'y', label: 'Y坐标', valueType: 'number' as const },
  { name: 'z', label: 'Z坐标', valueType: 'number' as const },
  { name: 'dx', label: 'X范围', valueType: 'number' as const },
  { name: 'dy', label: 'Y范围', valueType: 'number' as const },
  { name: 'dz', label: 'Z范围', valueType: 'number' as const },
  { name: 'rx', label: '最大俯仰角', valueType: 'number' as const },
  { name: 'rxm', label: '最小俯仰角', valueType: 'number' as const },
  { name: 'ry', label: '最大水平角', valueType: 'number' as const },
  { name: 'rym', label: '最小水平角', valueType: 'number' as const },
  { name: 'scores', label: '计分板', valueType: 'text' as const },
  { name: 'hasitem', label: '持有物品', valueType: 'text' as const },
  { name: 'has_property', label: '属性', valueType: 'text' as const },
]

type SelectorBuilderCtx = 'normal' | 'sub' | 'run' | 'run_sub' | null
const selectorBuilderCtx = ref<SelectorBuilderCtx>(null)
const selectorBase = ref('@e')
const selectorConditions = ref<SelectorCondition[]>([])
const selectorConditionSearch = ref<Record<number, string>>({})

function selectorParamDef(name: string) {
  return SELECTOR_PARAM_LIST.find(p => p.name === name)
}

function openSelectorBuilder(ctx: Exclude<SelectorBuilderCtx, null>, existingValue?: string) {
  selectorBuilderCtx.value = ctx
  selectorConditions.value = []
  selectorConditionSearch.value = {}
  if (existingValue && existingValue.startsWith('@')) {
    selectorBase.value = existingValue.slice(0, 2)
    const bracketMatch = existingValue.match(/\[(.+)\]/)
    if (bracketMatch) {
      // Split by commas respecting nested braces
      const inner = bracketMatch[1]
      const conditions: SelectorCondition[] = []
      let depth = 0, start = 0
      for (let i = 0; i <= inner.length; i++) {
        if (i < inner.length) {
          if (inner[i] === '{' || inner[i] === '[') depth++
          else if (inner[i] === '}' || inner[i] === ']') depth--
          else if (inner[i] === ',' && depth === 0) {
            const seg = inner.slice(start, i).trim()
            if (seg) conditions.push(parseSelectorSeg(seg))
            start = i + 1
            continue
          }
        } else {
          const seg = inner.slice(start).trim()
          if (seg) conditions.push(parseSelectorSeg(seg))
        }
      }
      selectorConditions.value = conditions
    }
  } else {
    selectorBase.value = '@e'
  }
}

function parseSelectorSeg(seg: string): SelectorCondition {
  const eqIdx = seg.indexOf('=')
  if (eqIdx > 0) {
    const param = seg.slice(0, eqIdx).trim()
    let value = seg.slice(eqIdx + 1).trim()
    const negated = value.startsWith('!')
    if (negated) value = value.slice(1)
    return { param, value, negated }
  }
  return { param: seg, value: '', negated: false }
}

function addSelectorCondition() {
  selectorConditions.value.push({ param: 'type', value: '', negated: false })
}

function removeSelectorCondition(i: number) {
  selectorConditions.value.splice(i, 1)
  delete selectorConditionSearch.value[i]
}

function selectorSearchResults(condIndex: number) {
  const cond = selectorConditions.value[condIndex]
  if (!cond) return []
  const def = selectorParamDef(cond.param)
  if (!def || def.valueType !== 'search') return []
  const q = (selectorConditionSearch.value[condIndex] || '').toLowerCase().trim()
  const cat = (def as any).category as string
  return q ? knowledgeCache.searchIds(cat, q, 30) : knowledgeCache.getIds(cat).slice(0, 30)
}

const builtSelector = computed(() => {
  const base = selectorBase.value
  const parts: string[] = []
  for (const c of selectorConditions.value) {
    if (!c.value && c.param !== 'tag') continue
    const val = c.negated ? `!${c.value}` : c.value
    parts.push(`${c.param}=${val}`)
  }
  return parts.length ? `${base}[${parts.join(',')}]` : base
})

function confirmSelectorBuilder() {
  const val = builtSelector.value
  const ctx = selectorBuilderCtx.value
  selectorBuilderCtx.value = null
  if (ctx === 'normal') {
    paramValues.value[currentStep.value] = val
    goNextNormal()
  } else if (ctx === 'sub') {
    subParamValues.value[subStep.value] = val
    goNextSub()
  } else if (ctx === 'run') {
    runSetParam(val)
  } else if (ctx === 'run_sub') {
    runSetSubParam(val)
  }
}

function closeSelectorBuilder() {
  selectorBuilderCtx.value = null
}

// ─── Phase: Pick subcommand variant ───
function pickVariant(v: SubcommandVariant) {
  selectedVariant.value = v
  subParamValues.value = v.subParams.map(() => '')
  subStep.value = 0
  rawtextSegments.value = []
  if (v.subParams.length > 0) {
    phase.value = 'fill_sub'
  } else {
    finishCurrentSub()
  }
}

/** Commit current subcommand to chain and decide next step */
function finishCurrentSub() {
  const cmd = selectedCommand.value
  const variant = selectedVariant.value
  if (!variant) return

  // Save current sub to chain
  chain.value.push({ variant, values: [...subParamValues.value] })

  // For chainable commands (execute): after non-terminal subs, pick next
  if (cmd && isChainable(cmd) && variant.keywords[0] !== 'run') {
    selectedVariant.value = null
    subParamValues.value = []
    subStep.value = 0
    phase.value = 'pick_variant'
  } else {
    phase.value = 'complete'
  }
}

// ─── Phase: Fill sub-params ───
const currentSubParam = computed<ParsedSubParam | null>(() =>
  selectedVariant.value?.subParams[subStep.value] ?? null
)

const subInputMode = computed<'buttons' | 'search' | 'number' | 'text' | 'coord' | 'rawtext' | 'inline_enum' | 'command'>(() => {
  const p = currentSubParam.value
  if (!p) return 'text'
  const t = p.type
  if (t === 'Command') return 'command'
  if (t === 'x y z') return 'coord'
  if (t === 'json' || t === 'message') return 'rawtext'
  if (t === 'enum_inline') return 'inline_enum'
  if (FIXED_OPTIONS[t]) return 'buttons'
  if (TYPE_TO_CATEGORY[t]) return 'search'
  if (t === 'int' || t === 'float' || t === 'value') return 'number'
  return 'text'
})

// ─── Nested command picker (for execute ... run) ───
const runCommandSearch = ref('')
const runSelectedCommand = ref<CommandSyntaxDef | null>(null)
const runNormalParams = ref<CommandParamDef[]>([])
const runParamValues = ref<string[]>([])
const runStep = ref(0)
const runSubVariants = ref<SubcommandVariant[]>([])
const runSelectedVariant = ref<SubcommandVariant | null>(null)
const runSubValues = ref<string[]>([])
const runSubStep = ref(0)
type RunPhase = 'pick' | 'fill' | 'pick_sub' | 'fill_sub'
const runPhase = ref<RunPhase>('pick')

const runFilteredCommands = computed(() => {
  const q = runCommandSearch.value.toLowerCase().trim()
  const list: CommandSyntaxDef[] = []
  for (const cmd of knowledgeCache.commands) {
    if (cmd.name.endsWith('old') || cmd.name === 'execute') continue
    if (q && !cmd.name.includes(q) && !cmd.description.includes(q)) continue
    list.push(cmd)
  }
  return list
})

function runSelectCommand(cmd: CommandSyntaxDef) {
  runSelectedCommand.value = cmd
  const normals = getNormalParams(cmd)
  runNormalParams.value = normals
  runParamValues.value = normals.map((p) => p.default ?? '')
  runStep.value = 0
  // Parse subcommands for the run target
  const subParams = getSubcommandParams(cmd)
  const parsed: SubcommandVariant[] = []
  for (const sp of subParams) {
    const v = parseSubcommandVariant(sp)
    if (v) parsed.push(v)
  }
  runSubVariants.value = parsed
  runSelectedVariant.value = null
  runSubValues.value = []
  runSubStep.value = 0
  runPhase.value = normals.length > 0 ? 'fill' : parsed.length > 0 ? 'pick_sub' : 'fill' // at least show something
}

const runCurrentParam = computed(() => runNormalParams.value[runStep.value] ?? null)
const runInputMode = computed<'buttons' | 'search' | 'number' | 'text' | 'coord' | 'rawtext' | 'components'>(() => {
  const p = runCurrentParam.value
  if (!p) return 'text'
  const t = p.type
  if (t === 'x y z') return 'coord'
  if (t === 'json') {
    const cmd = runSelectedCommand.value?.name || ''
    return isRawtextParam(p.name, cmd) ? 'rawtext' : 'components'
  }
  if (t === 'message') return 'rawtext'
  if (FIXED_OPTIONS[t]) return 'buttons'
  if (TYPE_TO_CATEGORY[t]) return 'search'
  if (t === 'int' || t === 'float' || t === 'value') return 'number'
  return 'text'
})

const runSearchQuery = ref('')
const runCoordX = ref('~')
const runCoordY = ref('~')
const runCoordZ = ref('~')

const runSearchOptions = computed(() => {
  const p = runCurrentParam.value
  if (!p) return []
  const cat = TYPE_TO_CATEGORY[p.type]
  if (!cat) return []
  const q = runSearchQuery.value.toLowerCase().trim()
  return q ? knowledgeCache.searchIds(cat, q, 100) : knowledgeCache.getIds(cat)
})

watch(runStep, () => {
  runSearchQuery.value = ''
  if (runCurrentParam.value?.type === 'x y z') {
    runCoordX.value = '~'; runCoordY.value = '~'; runCoordZ.value = '~'
  }
  if (runInputMode.value === 'rawtext') {
    rawtextSegments.value = [{ type: 'text', value: '' }]
  }
  if (runInputMode.value === 'components') {
    itemComp.value = { canPlaceOn: [], canDestroy: [], itemLock: '', keepOnDeath: false }
    compBlockInput.value = ''
    compDestroyInput.value = ''
  }
})

function runSetParam(val: string) {
  runParamValues.value[runStep.value] = val
  runGoNext()
}

function runSetCoord() {
  runSetParam(`${runCoordX.value} ${runCoordY.value} ${runCoordZ.value}`)
}

function runSkipParam() {
  runParamValues.value[runStep.value] = ''
  runGoNext()
}

function runGoNext() {
  if (runStep.value < runNormalParams.value.length - 1) {
    runStep.value++
  } else if (runSubVariants.value.length > 0) {
    runPhase.value = 'pick_sub'
  } else {
    commitRunCommand()
  }
}

function runPickSub(v: SubcommandVariant) {
  runSelectedVariant.value = v
  runSubValues.value = v.subParams.map(() => '')
  runSubStep.value = 0
  if (v.subParams.length > 0) {
    runPhase.value = 'fill_sub'
  } else {
    commitRunCommand()
  }
}

const runSubSearchQuery = ref('')
const runSubCoordX = ref('~')
const runSubCoordY = ref('~')
const runSubCoordZ = ref('~')

const runSubCurrentParam = computed(() => runSelectedVariant.value?.subParams[runSubStep.value] ?? null)
const runSubInputMode = computed<'buttons' | 'search' | 'number' | 'text' | 'coord' | 'rawtext' | 'inline_enum'>(() => {
  const p = runSubCurrentParam.value
  if (!p) return 'text'
  const t = p.type
  if (t === 'enum_inline') return 'inline_enum'
  if (t === 'x y z') return 'coord'
  if (t === 'json' || t === 'message') return 'rawtext'
  if (FIXED_OPTIONS[t]) return 'buttons'
  if (TYPE_TO_CATEGORY[t]) return 'search'
  if (t === 'int' || t === 'float' || t === 'value') return 'number'
  return 'text'
})

const runSubSearchOptions = computed(() => {
  const p = runSubCurrentParam.value
  if (!p) return []
  const cat = TYPE_TO_CATEGORY[p.type]
  if (!cat) return []
  const q = runSubSearchQuery.value.toLowerCase().trim()
  return q ? knowledgeCache.searchIds(cat, q, 100) : knowledgeCache.getIds(cat)
})

watch(runSubStep, () => {
  runSubSearchQuery.value = ''
  if (runSubCurrentParam.value?.type === 'x y z') {
    runSubCoordX.value = '~'; runSubCoordY.value = '~'; runSubCoordZ.value = '~'
  }
  if (runSubInputMode.value === 'rawtext') {
    rawtextSegments.value = [{ type: 'text', value: '' }]
  }
})

function runSetSubParam(val: string) {
  runSubValues.value[runSubStep.value] = val
  if (runSubStep.value < (runSelectedVariant.value?.subParams.length ?? 0) - 1) {
    runSubStep.value++
  } else {
    commitRunCommand()
  }
}

function runSetSubCoord() {
  runSetSubParam(`${runSubCoordX.value} ${runSubCoordY.value} ${runSubCoordZ.value}`)
}

function runSkipSubParam() {
  runSubValues.value[runSubStep.value] = ''
  if (runSubStep.value < (runSelectedVariant.value?.subParams.length ?? 0) - 1) {
    runSubStep.value++
  } else {
    commitRunCommand()
  }
}

function runConfirmRawtext() {
  runSetParam(buildRawtextJson())
}

function runConfirmComponents() {
  runSetParam(buildComponentsJson())
}

function runSubConfirmRawtext() {
  runSetSubParam(buildRawtextJson())
}

function commitRunCommand() {
  if (!runSelectedCommand.value) return
  const parts = [runSelectedCommand.value.name]
  for (let i = 0; i < runNormalParams.value.length; i++) {
    const val = runParamValues.value[i]
    if (val) parts.push(val)
    else break
  }
  if (runSelectedVariant.value) {
    parts.push(...runSelectedVariant.value.keywords)
    for (let i = 0; i < runSelectedVariant.value.subParams.length; i++) {
      const val = runSubValues.value[i]
      if (val) parts.push(val)
      else break
    }
  }
  subParamValues.value[subStep.value] = parts.join(' ')
  goNextSub()
}

const subButtonOptions = computed(() => {
  const p = currentSubParam.value
  if (!p) return []
  if (p.options) return p.options.map((o) => ({ value: o, description: '' }))
  return FIXED_OPTIONS[p.type] ?? []
})

const subSearchQuery = ref('')
const subSearchOptions = computed(() => {
  const p = currentSubParam.value
  if (!p) return []
  const cat = TYPE_TO_CATEGORY[p.type]
  if (!cat) return []
  const q = subSearchQuery.value.toLowerCase().trim()
  return q ? knowledgeCache.searchIds(cat, q, 100) : knowledgeCache.getIds(cat)
})

// Sub-param coordinate fields
const subCoordX = ref('~')
const subCoordY = ref('~')
const subCoordZ = ref('~')

watch(subStep, () => {
  subSearchQuery.value = ''
  if (currentSubParam.value?.type === 'x y z') {
    subCoordX.value = '~'; subCoordY.value = '~'; subCoordZ.value = '~'
  }
  if (currentSubParam.value?.type === 'json' || currentSubParam.value?.type === 'message') {
    rawtextSegments.value = [{ type: 'text', value: '' }]
  }
  if (currentSubParam.value?.type === 'Command') {
    runPhase.value = 'pick'
    runCommandSearch.value = ''
    runSelectedCommand.value = null
  }
})

function setSubParamValue(val: string) {
  subParamValues.value[subStep.value] = val
  goNextSub()
}

function setSubCoordValue() {
  subParamValues.value[subStep.value] = `${subCoordX.value} ${subCoordY.value} ${subCoordZ.value}`
  goNextSub()
}

function confirmSubJson() {
  subParamValues.value[subStep.value] = buildRawtextJson()
  goNextSub()
}

function goNextSub() {
  const variant = selectedVariant.value
  if (!variant) return
  if (subStep.value < variant.subParams.length - 1) {
    subStep.value++
  } else {
    finishCurrentSub()
  }
}

function goPrevSub() {
  if (subStep.value > 0) {
    subStep.value--
  } else {
    phase.value = 'pick_variant'
  }
}

function skipSubParam() {
  subParamValues.value[subStep.value] = ''
  goNextSub()
}

// ─── Phase 3: Complete ───
const copied = ref(false)

const builtCommand = computed(() => {
  if (!selectedCommand.value) return ''
  const parts = [`/${selectedCommand.value.name}`]
  // Normal params
  for (let i = 0; i < normalParams.value.length; i++) {
    const val = paramValues.value[i]
    if (val) parts.push(val)
    else if (normalParams.value[i].required) parts.push('')
    else break
  }
  // All chained subcommands
  for (const link of chain.value) {
    parts.push(...link.variant.keywords)
    for (let i = 0; i < link.variant.subParams.length; i++) {
      const val = link.values[i]
      if (val) parts.push(val)
      else if (link.variant.subParams[i].required) parts.push('')
      else break
    }
  }
  return parts.filter(Boolean).join(' ')
})

const commandSegments = computed(() => {
  if (!selectedCommand.value) return []
  const segments: { text: string; type: string; idx: number }[] = []
  segments.push({ text: '/' + selectedCommand.value.name, type: 'command', idx: -1 })
  for (let i = 0; i < normalParams.value.length; i++) {
    const val = paramValues.value[i]
    if (!val) break
    segments.push({ text: val, type: getSegType(normalParams.value[i].type), idx: i })
  }
  // All chained subcommands
  for (let c = 0; c < chain.value.length; c++) {
    const link = chain.value[c]
    if (link.variant.keywords.length) {
      segments.push({ text: link.variant.keywords.join(' '), type: 'enum', idx: -2 })
    }
    for (let i = 0; i < link.variant.subParams.length; i++) {
      const val = link.values[i]
      if (!val) break
      segments.push({ text: val, type: getSegType(link.variant.subParams[i].type), idx: 1000 + c * 100 + i })
    }
  }
  return segments
})

function getSegType(type: string): string {
  if (type === 'target') return 'selector'
  if (type === 'int' || type === 'float' || type === 'value') return 'number'
  if (type === 'x y z') return 'coord'
  if (TYPE_TO_CATEGORY[type]) return 'id'
  if (FIXED_OPTIONS[type] || type === 'enum_inline') return 'enum'
  if (type === 'json' || type === 'message') return 'string'
  return 'text'
}

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(builtCommand.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = builtCommand.value
    document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  }
  emit('command', builtCommand.value)
}

function editParam(index: number) {
  if (index < normalParams.value.length) {
    currentStep.value = index
    phase.value = 'fill'
  }
}

function resetWizard() {
  phase.value = 'select'
  selectedCommand.value = null
  paramValues.value = []
  currentStep.value = 0
  searchQuery.value = ''
  fillSearchQuery.value = ''
  selectedVariant.value = null
  subParamValues.value = []
  subStep.value = 0
  chain.value = []
  rawtextSegments.value = []
}

// Preview bar for normal param phase
function previewNormalSegments() {
  if (!selectedCommand.value) return []
  const segs: { text: string; state: 'done' | 'current' | 'pending'; idx: number }[] = []
  for (let i = 0; i < normalParams.value.length; i++) {
    const p = normalParams.value[i]
    const val = paramValues.value[i]
    const state = i < currentStep.value ? 'done' : i === currentStep.value ? 'current' : 'pending'
    segs.push({
      text: val || (p.required ? `<${p.name}>` : `[${p.name}]`),
      state, idx: i,
    })
  }
  if (subcommandVariants.value.length > 0) {
    segs.push({ text: '<...>', state: 'pending', idx: -1 })
  }
  return segs
}

onMounted(() => { knowledgeCache.load(localStorage.getItem('mc-edition') || 'bedrock') })
</script>

<template>
  <div class="wizard">
    <!-- ═══ Phase 1: Command Selection ═══ -->
    <template v-if="phase === 'select'">
      <div class="wizard-header">
        <span class="wizard-title">选择命令</span>
      </div>
      <div class="search-bar">
        <McInput :model-value="searchQuery" placeholder="搜索命令..." @update:model-value="searchQuery = $event" />
      </div>
      <McScrollbar class="command-list">
        <template v-if="knowledgeCache.loaded">
          <div v-for="[cat, cmds] of filteredCommands" :key="cat" class="command-group">
            <div class="group-label">{{ CATEGORY_LABELS[cat] || cat }}</div>
            <div class="group-items">
              <button v-for="cmd in cmds" :key="cmd.name" class="command-item" @click="selectCommand(cmd)">
                <span class="cmd-name">/{{ cmd.name }}</span>
                <span class="cmd-desc">{{ cmd.description }}</span>
                <McTag v-if="hasSubcommands(cmd)" type="info" size="tiny">子命令</McTag>
              </button>
            </div>
          </div>
          <div v-if="filteredCommands.size === 0" class="empty-hint">没有找到匹配的命令</div>
        </template>
        <div v-else class="empty-hint">加载中...</div>
      </McScrollbar>
    </template>

    <!-- ═══ Phase 2: Normal Parameter Fill ═══ -->
    <template v-if="phase === 'fill' && selectedCommand && currentParam">
      <div class="wizard-header">
        <McButton size="small" @click="resetWizard">返回</McButton>
        <span class="wizard-title">/{{ selectedCommand.name }}</span>
        <span class="step-indicator">{{ currentStep + 1 }} / {{ normalParams.length }}{{ subcommandVariants.length ? '+' : '' }}</span>
      </div>

      <!-- Preview -->
      <div class="preview-bar">
        <span class="preview-cmd">/{{ selectedCommand.name }}</span>
        <span v-for="seg in previewNormalSegments()" :key="seg.idx" class="preview-seg" :class="`preview-${seg.state}`"
          @click="seg.state === 'done' && (currentStep = seg.idx)">{{ seg.text }}</span>
      </div>

      <!-- Progress -->
      <div class="progress-dots">
        <span v-for="(p, i) in normalParams" :key="i" class="dot"
          :class="{ 'dot-done': i < currentStep || (i === currentStep && paramValues[i]), 'dot-current': i === currentStep, 'dot-optional': !p.required }"
          @click="currentStep = i" />
      </div>

      <!-- Param info -->
      <div class="param-info">
        <div class="param-header">
          <span class="param-name">{{ currentParam.name }}</span>
          <McTag :type="currentParam.required ? 'error' : 'default'" size="tiny">{{ currentParam.required ? '必填' : '可选' }}</McTag>
          <McTag type="info" size="tiny">{{ currentParam.type }}</McTag>
        </div>
        <div v-if="currentParam.description" class="param-desc">{{ currentParam.description }}</div>
        <div v-if="currentParam.range" class="param-range">范围: {{ currentParam.range }}</div>
        <div v-if="currentParam.default" class="param-default">默认值: {{ currentParam.default }}</div>
      </div>

      <!-- Input area -->
      <div class="input-area">
        <!-- Buttons -->
        <div v-if="inputMode === 'buttons'" class="btn-grid">
          <button v-for="opt in buttonOptions" :key="opt.value" class="option-btn"
            :class="{ 'option-selected': paramValues[currentStep] === opt.value }" @click="setParamValue(opt.value)">
            <span class="opt-value">{{ opt.value }}</span>
            <span class="opt-desc">{{ opt.description }}</span>
          </button>
          <div v-if="currentParam.type === 'target'" class="custom-input-row">
            <McInput :model-value="paramValues[currentStep]" placeholder="或输入玩家名/选择器..."
              @update:model-value="paramValues[currentStep] = $event" @keydown.enter="goNextNormal" />
            <McButton size="small" class="selector-builder-btn" @click="openSelectorBuilder('normal', paramValues[currentStep])">自定义选择器</McButton>
          </div>
        </div>

        <!-- Search (IDs) -->
        <div v-else-if="inputMode === 'search'" class="search-panel">
          <div ref="fillSearchInputRef" class="search-input-wrap">
            <McInput :model-value="fillSearchQuery" :placeholder="`搜索${currentParam.name}...`" @update:model-value="fillSearchQuery = $event" />
          </div>
          <div v-if="currentParam.type === 'SpawnEvent' && selectedEntityType" class="relevant-hint">
            <McTag type="success" size="tiny">{{ selectedEntityType }}</McTag>
            <span>相关事件已置顶高亮</span>
          </div>
          <McScrollbar class="id-list">
            <button v-for="entry in searchOptions" :key="entry.id" class="id-item"
              :class="{ 'id-selected': paramValues[currentStep] === entry.id, 'id-relevant': currentParam.type === 'SpawnEvent' && isRelevantEvent(entry) }"
              @click="setParamValue(entry.id)">
              <span class="id-value">{{ entry.id }}</span>
              <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
            </button>
            <div v-if="searchOptions.length === 0" class="empty-hint">无结果</div>
          </McScrollbar>
        </div>

        <!-- Number -->
        <div v-else-if="inputMode === 'number'" class="number-input">
          <McInput :model-value="paramValues[currentStep]" :placeholder="currentParam.default ? `默认 ${currentParam.default}` : '输入数值...'"
            @update:model-value="paramValues[currentStep] = $event" @keydown.enter="goNextNormal" />
        </div>

        <!-- Coordinate -->
        <div v-else-if="inputMode === 'coord'" class="coord-input">
          <div class="coord-fields">
            <div class="coord-field"><label class="coord-label">X</label><McInput :model-value="coordX" placeholder="~" @update:model-value="coordX = $event" @keydown.enter="setCoordValue" /></div>
            <div class="coord-field"><label class="coord-label">Y</label><McInput :model-value="coordY" placeholder="~" @update:model-value="coordY = $event" @keydown.enter="setCoordValue" /></div>
            <div class="coord-field"><label class="coord-label">Z</label><McInput :model-value="coordZ" placeholder="~" @update:model-value="coordZ = $event" @keydown.enter="setCoordValue" /></div>
          </div>
          <div class="coord-presets">
            <McButton size="small" @click="coordX = '~'; coordY = '~'; coordZ = '~'">相对 ~</McButton>
            <McButton size="small" @click="coordX = '^'; coordY = '^'; coordZ = '^'">局部 ^</McButton>
          </div>
        </div>

        <!-- JSON / Rawtext builder -->
        <!-- Rawtext JSON builder (tellraw/titleraw) -->
        <div v-else-if="inputMode === 'rawtext'" class="json-builder">
          <div class="json-hint">可视化编辑 rawtext JSON：</div>
          <div v-for="(seg, i) in rawtextSegments" :key="i" class="rawtext-row">
            <McTag :type="seg.type === 'text' ? 'default' : seg.type === 'selector' ? 'warning' : seg.type === 'translate' ? 'success' : 'info'" size="tiny">
              {{ { text: '文本', selector: '选择器', score: '计分板', translate: '翻译' }[seg.type] }}
            </McTag>
            <template v-if="seg.type === 'text'">
              <McInput :model-value="seg.value" placeholder="输入文本（可含§颜色代码）..."
                @update:model-value="seg.value = $event" class="rawtext-input" />
              <div class="color-picker">
                <button v-for="cc in COLOR_CODES" :key="cc.code" class="color-dot"
                  :style="cc.color ? { background: cc.color } : {}" :title="`${cc.code} ${cc.label}`"
                  @click="insertColorCode(i, cc.code)">
                  {{ cc.color ? '' : cc.label[0] }}
                </button>
              </div>
            </template>
            <McInput v-else-if="seg.type === 'selector'" :model-value="seg.value" placeholder="@a, @p, @s..."
              @update:model-value="seg.value = $event" class="rawtext-input" />
            <template v-else-if="seg.type === 'score'">
              <McInput :model-value="seg.name" placeholder="玩家 @s" @update:model-value="seg.name = $event" class="rawtext-input-sm" />
              <McInput :model-value="seg.objective" placeholder="计分项名称" @update:model-value="seg.objective = $event" class="rawtext-input-sm" />
            </template>
            <template v-else-if="seg.type === 'translate'">
              <McInput :model-value="seg.value" placeholder="翻译键 (如 chat.type.text)"
                @update:model-value="seg.value = $event" class="rawtext-input" />
              <div class="translate-args">
                <span class="translate-label">参数:</span>
                <div v-for="(arg, ai) in seg.with" :key="ai" class="translate-arg-row">
                  <McInput :model-value="arg" placeholder="参数值" @update:model-value="seg.with![ai] = $event" class="rawtext-input-sm" />
                  <button v-if="seg.with!.length > 1" class="rawtext-remove" @click="removeTranslateArg(i, ai)">×</button>
                </div>
                <McButton size="small" @click="addTranslateArg(i)">+ 参数</McButton>
              </div>
            </template>
            <button class="rawtext-remove" @click="removeRawtextSegment(i)">×</button>
          </div>
          <div class="rawtext-actions">
            <McButton size="small" @click="addRawtextSegment('text')">+ 文本</McButton>
            <McButton size="small" @click="addRawtextSegment('selector')">+ 选择器</McButton>
            <McButton size="small" @click="addRawtextSegment('score')">+ 计分板</McButton>
            <McButton size="small" @click="addRawtextSegment('translate')">+ 翻译键</McButton>
          </div>
          <div class="json-preview"><code>{{ buildRawtextJson() }}</code></div>
        </div>

        <!-- Item components builder (give) -->
        <div v-else-if="inputMode === 'components'" class="json-builder">
          <div class="json-hint">物品组件编辑器（基岩版仅支持以下4种组件）：</div>

          <!-- can_place_on -->
          <div class="comp-section">
            <div class="comp-label">can_place_on 可放置方块</div>
            <div class="comp-tags">
              <McTag v-for="(b, i) in itemComp.canPlaceOn" :key="i" type="info" size="tiny">
                {{ b }} <button class="rawtext-remove" @click="removeCompBlock('canPlaceOn', i)">×</button>
              </McTag>
            </div>
            <McInput :model-value="compBlockInput" placeholder="搜索方块..." @update:model-value="compBlockInput = $event" />
            <McScrollbar class="comp-id-list">
              <button v-for="entry in compBlockResults" :key="entry.id" class="id-item"
                :class="{ 'id-selected': itemComp.canPlaceOn.includes(entry.id) }"
                @click="addCompBlock('canPlaceOn', entry.id)">
                <span class="id-value">{{ entry.id }}</span>
                <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
              </button>
            </McScrollbar>
          </div>

          <!-- can_destroy -->
          <div class="comp-section">
            <div class="comp-label">can_destroy 可破坏方块</div>
            <div class="comp-tags">
              <McTag v-for="(b, i) in itemComp.canDestroy" :key="i" type="warning" size="tiny">
                {{ b }} <button class="rawtext-remove" @click="removeCompBlock('canDestroy', i)">×</button>
              </McTag>
            </div>
            <McInput :model-value="compDestroyInput" placeholder="搜索方块..." @update:model-value="compDestroyInput = $event" />
            <McScrollbar class="comp-id-list">
              <button v-for="entry in compDestroyResults" :key="entry.id" class="id-item"
                :class="{ 'id-selected': itemComp.canDestroy.includes(entry.id) }"
                @click="addCompBlock('canDestroy', entry.id)">
                <span class="id-value">{{ entry.id }}</span>
                <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
              </button>
            </McScrollbar>
          </div>

          <!-- item_lock -->
          <div class="comp-section">
            <div class="comp-label">item_lock 物品锁定</div>
            <div class="btn-grid">
              <button class="option-btn" :class="{ 'option-selected': itemComp.itemLock === '' }" @click="itemComp.itemLock = ''">
                <span class="opt-value">无</span>
              </button>
              <button class="option-btn" :class="{ 'option-selected': itemComp.itemLock === 'lock_in_slot' }" @click="itemComp.itemLock = 'lock_in_slot'">
                <span class="opt-value">lock_in_slot</span><span class="opt-desc">锁定在槽位</span>
              </button>
              <button class="option-btn" :class="{ 'option-selected': itemComp.itemLock === 'lock_in_inventory' }" @click="itemComp.itemLock = 'lock_in_inventory'">
                <span class="opt-value">lock_in_inventory</span><span class="opt-desc">锁定在背包</span>
              </button>
            </div>
          </div>

          <!-- keep_on_death -->
          <div class="comp-section">
            <div class="comp-label">keep_on_death 死亡保留</div>
            <div class="btn-grid">
              <button class="option-btn" :class="{ 'option-selected': !itemComp.keepOnDeath }" @click="itemComp.keepOnDeath = false">
                <span class="opt-value">否</span>
              </button>
              <button class="option-btn" :class="{ 'option-selected': itemComp.keepOnDeath }" @click="itemComp.keepOnDeath = true">
                <span class="opt-value">是</span><span class="opt-desc">死亡不掉落</span>
              </button>
            </div>
          </div>

          <div class="json-preview"><code>{{ buildComponentsJson() || '(空，跳过即可)' }}</code></div>
        </div>

        <!-- Text fallback -->
        <div v-else class="text-input">
          <McInput :model-value="paramValues[currentStep]" :placeholder="`输入${currentParam.name}...`"
            @update:model-value="paramValues[currentStep] = $event" @keydown.enter="goNextNormal" />
        </div>
      </div>

      <!-- Actions -->
      <div class="fill-actions">
        <McButton size="small" :disabled="currentStep === 0" @click="goPrevNormal">上一步</McButton>
        <McButton v-if="!currentParam.required" size="small" @click="skipNormalParam">跳过</McButton>
        <McButton v-if="inputMode !== 'buttons' || currentParam.type === 'target'" variant="primary" size="small"
          :disabled="currentParam.required && inputMode !== 'coord' && inputMode !== 'rawtext' && inputMode !== 'components' && !paramValues[currentStep]"
          @click="inputMode === 'coord' ? setCoordValue() : inputMode === 'rawtext' ? confirmRawtext() : inputMode === 'components' ? confirmComponents() : goNextNormal()">
          {{ currentStep === normalParams.length - 1 && !subcommandVariants.length ? '完成' : '下一步' }}
        </McButton>
      </div>
    </template>

    <!-- ═══ Phase: Pick Subcommand Variant ═══ -->
    <template v-if="phase === 'pick_variant' && selectedCommand">
      <div class="wizard-header">
        <McButton size="small" @click="chain.length > 0 ? (chain.pop(), phase = 'pick_variant') : normalParams.length > 0 ? (phase = 'fill', currentStep = normalParams.length - 1) : resetWizard()">返回</McButton>
        <span class="wizard-title">/{{ selectedCommand.name }} — {{ chain.length > 0 ? '添加子命令' : '选择子命令' }}</span>
      </div>

      <!-- Preview of chain built so far -->
      <div class="preview-bar">
        <span class="preview-cmd">/{{ selectedCommand.name }}</span>
        <span v-for="(p, i) in normalParams" :key="'n'+i" class="preview-seg preview-done"
          @click="currentStep = i; phase = 'fill'">{{ paramValues[i] || `<${p.name}>` }}</span>
        <template v-for="(link, c) in chain" :key="'c'+c">
          <span class="preview-seg preview-done">{{ link.variant.keywords.join(' ') }}</span>
          <span v-for="(val, vi) in link.values" :key="'cv'+vi" class="preview-seg preview-done">{{ val }}</span>
        </template>
        <span class="preview-seg preview-current">&lt;...&gt;</span>
      </div>

      <McScrollbar class="command-list">
        <div class="group-items" style="padding: 8px 12px;">
          <button v-for="v in subcommandVariants" :key="v.raw" class="command-item" @click="pickVariant(v)">
            <span class="cmd-name">{{ v.label }}</span>
            <span class="cmd-desc">{{ v.description }}</span>
            <McTag v-if="v.subParams.length > 0" type="default" size="tiny">{{ v.subParams.length }}个参数</McTag>
          </button>
        </div>
      </McScrollbar>

      <!-- Chain actions for execute -->
      <div v-if="isChainable(selectedCommand) && chain.length > 0" class="fill-actions">
        <span class="chain-count">已添加 {{ chain.length }} 个子命令</span>
        <McButton variant="primary" size="small" @click="phase = 'complete'">完成命令</McButton>
      </div>
      <div v-if="isChainable(selectedCommand)" class="execute-hint">
        execute 子命令可链式组合，选择 run 结束链并执行命令
      </div>
    </template>

    <!-- ═══ Phase: Fill Sub-params ═══ -->
    <template v-if="phase === 'fill_sub' && selectedVariant && currentSubParam">
      <div class="wizard-header">
        <McButton size="small" @click="phase = 'pick_variant'">返回</McButton>
        <span class="wizard-title">/{{ selectedCommand?.name }} {{ selectedVariant.label }}</span>
        <span class="step-indicator">{{ subStep + 1 }} / {{ selectedVariant.subParams.length }}</span>
      </div>

      <!-- Preview -->
      <div class="preview-bar">
        <span class="preview-cmd">/{{ selectedCommand?.name }}</span>
        <span v-for="(_p, i) in normalParams" :key="'n'+i" class="preview-seg preview-done"
          @click="currentStep = i; phase = 'fill'">{{ paramValues[i] }}</span>
        <template v-for="(link, c) in chain" :key="'pc'+c">
          <span class="preview-seg preview-done">{{ link.variant.keywords.join(' ') }}</span>
          <span v-for="(val, vi) in link.values" :key="'pv'+vi" class="preview-seg preview-done">{{ val }}</span>
        </template>
        <span class="preview-seg preview-done">{{ selectedVariant.keywords.join(' ') }}</span>
        <span v-for="(sp, i) in selectedVariant.subParams" :key="'s'+i" class="preview-seg"
          :class="i < subStep ? 'preview-done' : i === subStep ? 'preview-current' : 'preview-pending'"
          @click="i < subStep && (subStep = i)">
          {{ subParamValues[i] || (sp.required ? `<${sp.name}>` : `[${sp.name}]`) }}
        </span>
      </div>

      <!-- Param info -->
      <div class="param-info">
        <div class="param-header">
          <span class="param-name">{{ currentSubParam.name }}</span>
          <McTag :type="currentSubParam.required ? 'error' : 'default'" size="tiny">{{ currentSubParam.required ? '必填' : '可选' }}</McTag>
          <McTag type="info" size="tiny">{{ currentSubParam.options ? currentSubParam.options.join('|') : currentSubParam.type }}</McTag>
        </div>
      </div>

      <!-- Input area -->
      <div class="input-area">
        <!-- Inline enum (pipe options like eyes|feet) -->
        <div v-if="subInputMode === 'inline_enum'" class="btn-grid">
          <button v-for="opt in currentSubParam.options" :key="opt" class="option-btn"
            :class="{ 'option-selected': subParamValues[subStep] === opt }" @click="setSubParamValue(opt)">
            <span class="opt-value">{{ opt }}</span>
          </button>
        </div>

        <!-- Buttons -->
        <div v-else-if="subInputMode === 'buttons'" class="btn-grid">
          <button v-for="opt in subButtonOptions" :key="opt.value" class="option-btn"
            :class="{ 'option-selected': subParamValues[subStep] === opt.value }" @click="setSubParamValue(opt.value)">
            <span class="opt-value">{{ opt.value }}</span>
            <span v-if="opt.description" class="opt-desc">{{ opt.description }}</span>
          </button>
          <div v-if="currentSubParam.type === 'target'" class="custom-input-row">
            <McInput :model-value="subParamValues[subStep]" placeholder="或输入玩家名/选择器..."
              @update:model-value="subParamValues[subStep] = $event" @keydown.enter="goNextSub" />
            <McButton size="small" class="selector-builder-btn" @click="openSelectorBuilder('sub', subParamValues[subStep])">自定义选择器</McButton>
          </div>
        </div>

        <!-- Search (IDs) -->
        <div v-else-if="subInputMode === 'search'" class="search-panel">
          <div class="search-input-wrap">
            <McInput :model-value="subSearchQuery" :placeholder="`搜索${currentSubParam.name}...`" @update:model-value="subSearchQuery = $event" />
          </div>
          <McScrollbar class="id-list">
            <button v-for="entry in subSearchOptions" :key="entry.id" class="id-item"
              :class="{ 'id-selected': subParamValues[subStep] === entry.id }" @click="setSubParamValue(entry.id)">
              <span class="id-value">{{ entry.id }}</span>
              <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
            </button>
            <div v-if="subSearchOptions.length === 0" class="empty-hint">无结果</div>
          </McScrollbar>
        </div>

        <!-- Number -->
        <div v-else-if="subInputMode === 'number'" class="number-input">
          <McInput :model-value="subParamValues[subStep]" placeholder="输入数值..."
            @update:model-value="subParamValues[subStep] = $event" @keydown.enter="goNextSub" />
        </div>

        <!-- Coordinate -->
        <div v-else-if="subInputMode === 'coord'" class="coord-input">
          <div class="coord-fields">
            <div class="coord-field"><label class="coord-label">X</label><McInput :model-value="subCoordX" placeholder="~" @update:model-value="subCoordX = $event" @keydown.enter="setSubCoordValue" /></div>
            <div class="coord-field"><label class="coord-label">Y</label><McInput :model-value="subCoordY" placeholder="~" @update:model-value="subCoordY = $event" @keydown.enter="setSubCoordValue" /></div>
            <div class="coord-field"><label class="coord-label">Z</label><McInput :model-value="subCoordZ" placeholder="~" @update:model-value="subCoordZ = $event" @keydown.enter="setSubCoordValue" /></div>
          </div>
          <div class="coord-presets">
            <McButton size="small" @click="subCoordX = '~'; subCoordY = '~'; subCoordZ = '~'">相对 ~</McButton>
            <McButton size="small" @click="subCoordX = '^'; subCoordY = '^'; subCoordZ = '^'">局部 ^</McButton>
          </div>
        </div>

        <!-- JSON / Rawtext builder -->
        <div v-else-if="subInputMode === 'rawtext'" class="json-builder">
          <div class="json-hint">可视化编辑 rawtext JSON：</div>
          <div v-for="(seg, i) in rawtextSegments" :key="i" class="rawtext-row">
            <McTag :type="seg.type === 'text' ? 'default' : seg.type === 'selector' ? 'warning' : seg.type === 'translate' ? 'success' : 'info'" size="tiny">
              {{ { text: '文本', selector: '选择器', score: '计分板', translate: '翻译' }[seg.type] }}
            </McTag>
            <template v-if="seg.type === 'text'">
              <McInput :model-value="seg.value" placeholder="输入文本（可含§颜色代码）..." @update:model-value="seg.value = $event" class="rawtext-input" />
              <div class="color-picker">
                <button v-for="cc in COLOR_CODES" :key="cc.code" class="color-dot"
                  :style="cc.color ? { background: cc.color } : {}" :title="`${cc.code} ${cc.label}`"
                  @click="insertColorCode(i, cc.code)">{{ cc.color ? '' : cc.label[0] }}</button>
              </div>
            </template>
            <McInput v-else-if="seg.type === 'selector'" :model-value="seg.value" placeholder="@a, @p, @s..." @update:model-value="seg.value = $event" class="rawtext-input" />
            <template v-else-if="seg.type === 'score'">
              <McInput :model-value="seg.name" placeholder="玩家 @s" @update:model-value="seg.name = $event" class="rawtext-input-sm" />
              <McInput :model-value="seg.objective" placeholder="计分项名称" @update:model-value="seg.objective = $event" class="rawtext-input-sm" />
            </template>
            <template v-else-if="seg.type === 'translate'">
              <McInput :model-value="seg.value" placeholder="翻译键 (如 chat.type.text)" @update:model-value="seg.value = $event" class="rawtext-input" />
              <div class="translate-args">
                <span class="translate-label">参数:</span>
                <div v-for="(arg, ai) in seg.with" :key="ai" class="translate-arg-row">
                  <McInput :model-value="arg" placeholder="参数值" @update:model-value="seg.with![ai] = $event" class="rawtext-input-sm" />
                  <button v-if="seg.with!.length > 1" class="rawtext-remove" @click="removeTranslateArg(i, ai)">×</button>
                </div>
                <McButton size="small" @click="addTranslateArg(i)">+ 参数</McButton>
              </div>
            </template>
            <button class="rawtext-remove" @click="removeRawtextSegment(i)">×</button>
          </div>
          <div class="rawtext-actions">
            <McButton size="small" @click="addRawtextSegment('text')">+ 文本</McButton>
            <McButton size="small" @click="addRawtextSegment('selector')">+ 选择器</McButton>
            <McButton size="small" @click="addRawtextSegment('score')">+ 计分板</McButton>
            <McButton size="small" @click="addRawtextSegment('translate')">+ 翻译键</McButton>
          </div>
          <div class="json-preview"><code>{{ buildRawtextJson() }}</code></div>
        </div>

        <!-- Nested command picker (for execute run) -->
        <div v-else-if="subInputMode === 'command'" class="run-command-panel">
          <!-- Pick command -->
          <template v-if="runPhase === 'pick'">
            <div class="search-input-wrap">
              <McInput :model-value="runCommandSearch" placeholder="搜索要执行的命令..." @update:model-value="runCommandSearch = $event" />
            </div>
            <McScrollbar class="id-list">
              <button v-for="cmd in runFilteredCommands" :key="cmd.name" class="id-item" @click="runSelectCommand(cmd)">
                <span class="id-value">/{{ cmd.name }}</span>
                <span class="id-desc">{{ cmd.description }}</span>
              </button>
            </McScrollbar>
          </template>
          <!-- Fill run command params -->
          <template v-else-if="runPhase === 'fill' && runCurrentParam">
            <div class="run-sub-header">
              <McButton size="small" @click="runPhase = 'pick'; runSelectedCommand = null">换命令</McButton>
              <span class="run-cmd-label">/{{ runSelectedCommand?.name }}</span>
              <McTag type="info" size="tiny">{{ runStep + 1 }}/{{ runNormalParams.length }}</McTag>
            </div>
            <div class="param-info" style="padding:6px 0">
              <div class="param-header">
                <span class="param-name">{{ runCurrentParam.name }}</span>
                <McTag :type="runCurrentParam.required ? 'error' : 'default'" size="tiny">{{ runCurrentParam.required ? '必填' : '可选' }}</McTag>
                <McTag type="info" size="tiny">{{ runCurrentParam.type }}</McTag>
              </div>
              <div v-if="runCurrentParam.description" class="param-desc">{{ runCurrentParam.description }}</div>
            </div>
            <!-- Buttons -->
            <div v-if="runInputMode === 'buttons'" class="btn-grid">
              <button v-for="opt in FIXED_OPTIONS[runCurrentParam.type]" :key="opt.value" class="option-btn"
                :class="{ 'option-selected': runParamValues[runStep] === opt.value }" @click="runSetParam(opt.value)">
                <span class="opt-value">{{ opt.value }}</span><span class="opt-desc">{{ opt.description }}</span>
              </button>
              <div v-if="runCurrentParam.type === 'target'" class="custom-input-row">
                <McInput :model-value="runParamValues[runStep]" placeholder="或输入玩家名/选择器..."
                  @update:model-value="runParamValues[runStep] = $event" @keydown.enter="runGoNext" />
                <McButton size="small" class="selector-builder-btn" @click="openSelectorBuilder('run', runParamValues[runStep])">自定义选择器</McButton>
              </div>
            </div>
            <!-- Search (IDs) -->
            <div v-else-if="runInputMode === 'search'" class="search-panel" style="max-height:220px">
              <div class="search-input-wrap">
                <McInput :model-value="runSearchQuery" :placeholder="`搜索${runCurrentParam.name}...`" @update:model-value="runSearchQuery = $event" />
              </div>
              <McScrollbar class="id-list">
                <button v-for="entry in runSearchOptions" :key="entry.id" class="id-item"
                  :class="{ 'id-selected': runParamValues[runStep] === entry.id }" @click="runSetParam(entry.id)">
                  <span class="id-value">{{ entry.id }}</span>
                  <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
                </button>
                <div v-if="runSearchOptions.length === 0" class="empty-hint">无结果</div>
              </McScrollbar>
            </div>
            <!-- Coordinate -->
            <div v-else-if="runInputMode === 'coord'" class="coord-input">
              <div class="coord-fields">
                <div class="coord-field"><label class="coord-label">X</label><McInput :model-value="runCoordX" placeholder="~" @update:model-value="runCoordX = $event" @keydown.enter="runSetCoord" /></div>
                <div class="coord-field"><label class="coord-label">Y</label><McInput :model-value="runCoordY" placeholder="~" @update:model-value="runCoordY = $event" @keydown.enter="runSetCoord" /></div>
                <div class="coord-field"><label class="coord-label">Z</label><McInput :model-value="runCoordZ" placeholder="~" @update:model-value="runCoordZ = $event" @keydown.enter="runSetCoord" /></div>
              </div>
              <div class="coord-presets">
                <McButton size="small" @click="runCoordX = '~'; runCoordY = '~'; runCoordZ = '~'">相对 ~</McButton>
                <McButton size="small" @click="runCoordX = '^'; runCoordY = '^'; runCoordZ = '^'">局部 ^</McButton>
              </div>
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" @click="runSetCoord">确认坐标</McButton>
              </div>
            </div>
            <!-- Rawtext JSON builder -->
            <div v-else-if="runInputMode === 'rawtext'" class="json-builder">
              <div class="json-hint">可视化编辑 rawtext JSON：</div>
              <div v-for="(seg, i) in rawtextSegments" :key="i" class="rawtext-row">
                <McTag :type="seg.type === 'text' ? 'default' : seg.type === 'selector' ? 'warning' : seg.type === 'translate' ? 'success' : 'info'" size="tiny">
                  {{ { text: '文本', selector: '选择器', score: '计分板', translate: '翻译' }[seg.type] }}
                </McTag>
                <template v-if="seg.type === 'text'">
                  <McInput :model-value="seg.value" placeholder="输入文本（可含§颜色代码）..." @update:model-value="seg.value = $event" class="rawtext-input" />
                  <div class="color-picker">
                    <button v-for="cc in COLOR_CODES" :key="cc.code" class="color-dot"
                      :style="cc.color ? { background: cc.color } : {}" :title="`${cc.code} ${cc.label}`"
                      @click="insertColorCode(i, cc.code)">{{ cc.color ? '' : cc.label[0] }}</button>
                  </div>
                </template>
                <McInput v-else-if="seg.type === 'selector'" :model-value="seg.value" placeholder="@a, @p, @s..." @update:model-value="seg.value = $event" class="rawtext-input" />
                <template v-else-if="seg.type === 'score'">
                  <McInput :model-value="seg.name" placeholder="玩家 @s" @update:model-value="seg.name = $event" class="rawtext-input-sm" />
                  <McInput :model-value="seg.objective" placeholder="计分项名称" @update:model-value="seg.objective = $event" class="rawtext-input-sm" />
                </template>
                <template v-else-if="seg.type === 'translate'">
                  <McInput :model-value="seg.value" placeholder="翻译键 (如 chat.type.text)" @update:model-value="seg.value = $event" class="rawtext-input" />
                  <div class="translate-args">
                    <span class="translate-label">参数:</span>
                    <div v-for="(arg, ai) in seg.with" :key="ai" class="translate-arg-row">
                      <McInput :model-value="arg" placeholder="参数值" @update:model-value="seg.with![ai] = $event" class="rawtext-input-sm" />
                      <button v-if="seg.with!.length > 1" class="rawtext-remove" @click="removeTranslateArg(i, ai)">×</button>
                    </div>
                    <McButton size="small" @click="addTranslateArg(i)">+ 参数</McButton>
                  </div>
                </template>
                <button class="rawtext-remove" @click="removeRawtextSegment(i)">×</button>
              </div>
              <div class="rawtext-actions">
                <McButton size="small" @click="addRawtextSegment('text')">+ 文本</McButton>
                <McButton size="small" @click="addRawtextSegment('selector')">+ 选择器</McButton>
                <McButton size="small" @click="addRawtextSegment('score')">+ 计分板</McButton>
                <McButton size="small" @click="addRawtextSegment('translate')">+ 翻译键</McButton>
              </div>
              <div class="json-preview"><code>{{ buildRawtextJson() }}</code></div>
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" @click="runConfirmRawtext">确认 JSON</McButton>
              </div>
            </div>
            <!-- Item components builder -->
            <div v-else-if="runInputMode === 'components'" class="json-builder">
              <div class="json-hint">物品组件编辑器（基岩版仅支持以下4种组件）：</div>
              <div class="comp-section">
                <div class="comp-label">can_place_on 可放置方块</div>
                <div class="comp-tags">
                  <McTag v-for="(b, i) in itemComp.canPlaceOn" :key="i" type="info" size="tiny">
                    {{ b }} <button class="rawtext-remove" @click="removeCompBlock('canPlaceOn', i)">×</button>
                  </McTag>
                </div>
                <McInput :model-value="compBlockInput" placeholder="搜索方块..." @update:model-value="compBlockInput = $event" />
                <McScrollbar class="comp-id-list">
                  <button v-for="entry in compBlockResults" :key="entry.id" class="id-item"
                    :class="{ 'id-selected': itemComp.canPlaceOn.includes(entry.id) }"
                    @click="addCompBlock('canPlaceOn', entry.id)">
                    <span class="id-value">{{ entry.id }}</span>
                    <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
                  </button>
                </McScrollbar>
              </div>
              <div class="comp-section">
                <div class="comp-label">can_destroy 可破坏方块</div>
                <div class="comp-tags">
                  <McTag v-for="(b, i) in itemComp.canDestroy" :key="i" type="warning" size="tiny">
                    {{ b }} <button class="rawtext-remove" @click="removeCompBlock('canDestroy', i)">×</button>
                  </McTag>
                </div>
                <McInput :model-value="compDestroyInput" placeholder="搜索方块..." @update:model-value="compDestroyInput = $event" />
                <McScrollbar class="comp-id-list">
                  <button v-for="entry in compDestroyResults" :key="entry.id" class="id-item"
                    :class="{ 'id-selected': itemComp.canDestroy.includes(entry.id) }"
                    @click="addCompBlock('canDestroy', entry.id)">
                    <span class="id-value">{{ entry.id }}</span>
                    <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
                  </button>
                </McScrollbar>
              </div>
              <div class="comp-section">
                <div class="comp-label">item_lock 物品锁定</div>
                <div class="btn-grid">
                  <button class="option-btn" :class="{ 'option-selected': itemComp.itemLock === '' }" @click="itemComp.itemLock = ''"><span class="opt-value">无</span></button>
                  <button class="option-btn" :class="{ 'option-selected': itemComp.itemLock === 'lock_in_slot' }" @click="itemComp.itemLock = 'lock_in_slot'"><span class="opt-value">lock_in_slot</span><span class="opt-desc">锁定在槽位</span></button>
                  <button class="option-btn" :class="{ 'option-selected': itemComp.itemLock === 'lock_in_inventory' }" @click="itemComp.itemLock = 'lock_in_inventory'"><span class="opt-value">lock_in_inventory</span><span class="opt-desc">锁定在背包</span></button>
                </div>
              </div>
              <div class="comp-section">
                <div class="comp-label">keep_on_death 死亡保留</div>
                <div class="btn-grid">
                  <button class="option-btn" :class="{ 'option-selected': !itemComp.keepOnDeath }" @click="itemComp.keepOnDeath = false"><span class="opt-value">否</span></button>
                  <button class="option-btn" :class="{ 'option-selected': itemComp.keepOnDeath }" @click="itemComp.keepOnDeath = true"><span class="opt-value">是</span><span class="opt-desc">死亡不掉落</span></button>
                </div>
              </div>
              <div class="json-preview"><code>{{ buildComponentsJson() || '(空，跳过即可)' }}</code></div>
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" @click="runConfirmComponents">确认组件</McButton>
              </div>
            </div>
            <!-- Number -->
            <div v-else-if="runInputMode === 'number'" class="number-input">
              <McInput :model-value="runParamValues[runStep]" :placeholder="runCurrentParam.default ? `默认 ${runCurrentParam.default}` : '输入数值...'"
                @update:model-value="runParamValues[runStep] = $event" @keydown.enter="runGoNext" />
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" :disabled="runCurrentParam.required && !runParamValues[runStep]" @click="runGoNext">
                  {{ runStep === runNormalParams.length - 1 ? (runSubVariants.length ? '选子命令' : '确认') : '下一步' }}
                </McButton>
                <McButton v-if="!runCurrentParam.required" size="small" style="margin-left:6px" @click="runSkipParam">跳过</McButton>
              </div>
            </div>
            <!-- Text fallback -->
            <div v-else>
              <McInput :model-value="runParamValues[runStep]" :placeholder="`输入${runCurrentParam.name}...`"
                @update:model-value="runParamValues[runStep] = $event" @keydown.enter="runGoNext" />
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" :disabled="runCurrentParam.required && !runParamValues[runStep]" @click="runGoNext">
                  {{ runStep === runNormalParams.length - 1 ? (runSubVariants.length ? '选子命令' : '确认') : '下一步' }}
                </McButton>
                <McButton v-if="!runCurrentParam.required" size="small" style="margin-left:6px" @click="runSkipParam">跳过</McButton>
              </div>
            </div>
          </template>
          <!-- Pick sub-variant for run command -->
          <template v-else-if="runPhase === 'pick_sub'">
            <div class="run-sub-header">
              <span class="run-cmd-label">/{{ runSelectedCommand?.name }} — 选择子命令</span>
            </div>
            <McScrollbar class="id-list">
              <button v-for="v in runSubVariants" :key="v.raw" class="id-item" @click="runPickSub(v)">
                <span class="id-value">{{ v.label }}</span>
                <span class="id-desc">{{ v.description }}</span>
              </button>
            </McScrollbar>
          </template>
          <!-- Fill sub-variant params for run command -->
          <template v-else-if="runPhase === 'fill_sub' && runSelectedVariant && runSubCurrentParam">
            <div class="run-sub-header">
              <span class="run-cmd-label">/{{ runSelectedCommand?.name }} {{ runSelectedVariant.label }}</span>
              <McTag type="info" size="tiny">{{ runSubStep + 1 }}/{{ runSelectedVariant.subParams.length }}</McTag>
            </div>
            <div class="param-info" style="padding:6px 0">
              <div class="param-header">
                <span class="param-name">{{ runSubCurrentParam.name }}</span>
                <McTag :type="runSubCurrentParam.required ? 'error' : 'default'" size="tiny">{{ runSubCurrentParam.required ? '必填' : '可选' }}</McTag>
                <McTag type="info" size="tiny">{{ runSubCurrentParam.options ? runSubCurrentParam.options.join('|') : runSubCurrentParam.type }}</McTag>
              </div>
            </div>
            <!-- Inline enum (pipe options) -->
            <div v-if="runSubInputMode === 'inline_enum'" class="btn-grid">
              <button v-for="opt in runSubCurrentParam.options" :key="opt" class="option-btn"
                :class="{ 'option-selected': runSubValues[runSubStep] === opt }" @click="runSetSubParam(opt)">
                <span class="opt-value">{{ opt }}</span>
              </button>
            </div>
            <!-- Buttons -->
            <div v-else-if="runSubInputMode === 'buttons'" class="btn-grid">
              <button v-for="opt in FIXED_OPTIONS[runSubCurrentParam.type]" :key="opt.value" class="option-btn"
                :class="{ 'option-selected': runSubValues[runSubStep] === opt.value }" @click="runSetSubParam(opt.value)">
                <span class="opt-value">{{ opt.value }}</span><span class="opt-desc">{{ opt.description }}</span>
              </button>
              <div v-if="runSubCurrentParam.type === 'target'" class="custom-input-row">
                <McInput :model-value="runSubValues[runSubStep]" placeholder="或输入玩家名/选择器..."
                  @update:model-value="runSubValues[runSubStep] = $event" @keydown.enter="runSetSubParam(runSubValues[runSubStep])" />
                <McButton size="small" class="selector-builder-btn" @click="openSelectorBuilder('run_sub', runSubValues[runSubStep])">自定义选择器</McButton>
              </div>
            </div>
            <!-- Search (IDs) -->
            <div v-else-if="runSubInputMode === 'search'" class="search-panel" style="max-height:200px">
              <div class="search-input-wrap">
                <McInput :model-value="runSubSearchQuery" :placeholder="`搜索${runSubCurrentParam.name}...`" @update:model-value="runSubSearchQuery = $event" />
              </div>
              <McScrollbar class="id-list">
                <button v-for="entry in runSubSearchOptions" :key="entry.id" class="id-item"
                  :class="{ 'id-selected': runSubValues[runSubStep] === entry.id }" @click="runSetSubParam(entry.id)">
                  <span class="id-value">{{ entry.id }}</span>
                  <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
                </button>
                <div v-if="runSubSearchOptions.length === 0" class="empty-hint">无结果</div>
              </McScrollbar>
            </div>
            <!-- Coordinate -->
            <div v-else-if="runSubInputMode === 'coord'" class="coord-input">
              <div class="coord-fields">
                <div class="coord-field"><label class="coord-label">X</label><McInput :model-value="runSubCoordX" placeholder="~" @update:model-value="runSubCoordX = $event" @keydown.enter="runSetSubCoord" /></div>
                <div class="coord-field"><label class="coord-label">Y</label><McInput :model-value="runSubCoordY" placeholder="~" @update:model-value="runSubCoordY = $event" @keydown.enter="runSetSubCoord" /></div>
                <div class="coord-field"><label class="coord-label">Z</label><McInput :model-value="runSubCoordZ" placeholder="~" @update:model-value="runSubCoordZ = $event" @keydown.enter="runSetSubCoord" /></div>
              </div>
              <div class="coord-presets">
                <McButton size="small" @click="runSubCoordX = '~'; runSubCoordY = '~'; runSubCoordZ = '~'">相对 ~</McButton>
                <McButton size="small" @click="runSubCoordX = '^'; runSubCoordY = '^'; runSubCoordZ = '^'">局部 ^</McButton>
              </div>
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" @click="runSetSubCoord">确认坐标</McButton>
              </div>
            </div>
            <!-- Rawtext JSON builder -->
            <div v-else-if="runSubInputMode === 'rawtext'" class="json-builder">
              <div class="json-hint">可视化编辑 rawtext JSON：</div>
              <div v-for="(seg, i) in rawtextSegments" :key="i" class="rawtext-row">
                <McTag :type="seg.type === 'text' ? 'default' : seg.type === 'selector' ? 'warning' : seg.type === 'translate' ? 'success' : 'info'" size="tiny">
                  {{ { text: '文本', selector: '选择器', score: '计分板', translate: '翻译' }[seg.type] }}
                </McTag>
                <template v-if="seg.type === 'text'">
                  <McInput :model-value="seg.value" placeholder="输入文本（可含§颜色代码）..." @update:model-value="seg.value = $event" class="rawtext-input" />
                  <div class="color-picker">
                    <button v-for="cc in COLOR_CODES" :key="cc.code" class="color-dot"
                      :style="cc.color ? { background: cc.color } : {}" :title="`${cc.code} ${cc.label}`"
                      @click="insertColorCode(i, cc.code)">{{ cc.color ? '' : cc.label[0] }}</button>
                  </div>
                </template>
                <McInput v-else-if="seg.type === 'selector'" :model-value="seg.value" placeholder="@a, @p, @s..." @update:model-value="seg.value = $event" class="rawtext-input" />
                <template v-else-if="seg.type === 'score'">
                  <McInput :model-value="seg.name" placeholder="玩家 @s" @update:model-value="seg.name = $event" class="rawtext-input-sm" />
                  <McInput :model-value="seg.objective" placeholder="计分项名称" @update:model-value="seg.objective = $event" class="rawtext-input-sm" />
                </template>
                <template v-else-if="seg.type === 'translate'">
                  <McInput :model-value="seg.value" placeholder="翻译键" @update:model-value="seg.value = $event" class="rawtext-input" />
                  <div class="translate-args">
                    <span class="translate-label">参数:</span>
                    <div v-for="(arg, ai) in seg.with" :key="ai" class="translate-arg-row">
                      <McInput :model-value="arg" placeholder="参数值" @update:model-value="seg.with![ai] = $event" class="rawtext-input-sm" />
                      <button v-if="seg.with!.length > 1" class="rawtext-remove" @click="removeTranslateArg(i, ai)">×</button>
                    </div>
                    <McButton size="small" @click="addTranslateArg(i)">+ 参数</McButton>
                  </div>
                </template>
                <button class="rawtext-remove" @click="removeRawtextSegment(i)">×</button>
              </div>
              <div class="rawtext-actions">
                <McButton size="small" @click="addRawtextSegment('text')">+ 文本</McButton>
                <McButton size="small" @click="addRawtextSegment('selector')">+ 选择器</McButton>
                <McButton size="small" @click="addRawtextSegment('score')">+ 计分板</McButton>
                <McButton size="small" @click="addRawtextSegment('translate')">+ 翻译键</McButton>
              </div>
              <div class="json-preview"><code>{{ buildRawtextJson() }}</code></div>
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" @click="runSubConfirmRawtext">确认 JSON</McButton>
              </div>
            </div>
            <!-- Number -->
            <div v-else-if="runSubInputMode === 'number'" class="number-input">
              <McInput :model-value="runSubValues[runSubStep]" placeholder="输入数值..."
                @update:model-value="runSubValues[runSubStep] = $event" @keydown.enter="runSetSubParam(runSubValues[runSubStep])" />
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" :disabled="runSubCurrentParam.required && !runSubValues[runSubStep]" @click="runSetSubParam(runSubValues[runSubStep])">
                  {{ runSubStep === runSelectedVariant.subParams.length - 1 ? '确认' : '下一步' }}
                </McButton>
                <McButton v-if="!runSubCurrentParam.required" size="small" style="margin-left:6px" @click="runSkipSubParam">跳过</McButton>
              </div>
            </div>
            <!-- Text fallback -->
            <div v-else>
              <McInput :model-value="runSubValues[runSubStep]" :placeholder="`输入${runSubCurrentParam.name}...`"
                @update:model-value="runSubValues[runSubStep] = $event" @keydown.enter="runSetSubParam(runSubValues[runSubStep])" />
              <div style="margin-top:6px">
                <McButton variant="primary" size="small" :disabled="runSubCurrentParam.required && !runSubValues[runSubStep]" @click="runSetSubParam(runSubValues[runSubStep])">
                  {{ runSubStep === runSelectedVariant.subParams.length - 1 ? '确认' : '下一步' }}
                </McButton>
                <McButton v-if="!runSubCurrentParam.required" size="small" style="margin-left:6px" @click="runSkipSubParam">跳过</McButton>
              </div>
            </div>
          </template>
        </div>

        <!-- Text fallback -->
        <div v-else class="text-input">
          <McInput :model-value="subParamValues[subStep]" :placeholder="`输入${currentSubParam.name}...`"
            @update:model-value="subParamValues[subStep] = $event" @keydown.enter="goNextSub" />
        </div>
      </div>

      <!-- Actions -->
      <div class="fill-actions">
        <McButton size="small" @click="goPrevSub">上一步</McButton>
        <McButton v-if="!currentSubParam.required" size="small" @click="skipSubParam">跳过</McButton>
        <McButton v-if="subInputMode !== 'buttons' && subInputMode !== 'inline_enum'" variant="primary" size="small"
          :disabled="currentSubParam.required && subInputMode !== 'coord' && subInputMode !== 'rawtext' && !subParamValues[subStep]"
          @click="subInputMode === 'coord' ? setSubCoordValue() : subInputMode === 'rawtext' ? confirmSubJson() : goNextSub()">
          {{ subStep === selectedVariant.subParams.length - 1 ? '完成' : '下一步' }}
        </McButton>
      </div>
    </template>

    <!-- ═══ Phase: Complete ═══ -->
    <template v-if="phase === 'complete' && selectedCommand">
      <div class="wizard-header">
        <McButton size="small" @click="resetWizard">新命令</McButton>
        <span class="wizard-title">命令已生成</span>
      </div>
      <div class="complete-content">
        <div class="command-display">
          <code class="command-line">
            <span v-for="(seg, i) in commandSegments" :key="i" class="seg" :class="`seg-${seg.type}`"
              @click="seg.idx >= 0 && seg.idx < 100 && editParam(seg.idx)">{{ seg.text }}</span>
          </code>
        </div>
        <div class="complete-actions">
          <McButton variant="primary" @click="copyCommand">{{ copied ? '已复制' : '复制命令' }}</McButton>
          <McButton v-if="normalParams.length" @click="editParam(0)">编辑参数</McButton>
          <McButton v-if="subcommandVariants.length" @click="chain = []; phase = 'pick_variant'">换子命令</McButton>
          <McButton @click="resetWizard">新命令</McButton>
        </div>
        <div class="param-summary">
          <div v-for="(p, i) in normalParams" :key="'n'+i" class="param-row" @click="editParam(i)">
            <span class="param-row-name">{{ p.name }}</span>
            <span class="param-row-value" :class="{ 'param-empty': !paramValues[i] }">{{ paramValues[i] || '(空)' }}</span>
            <span class="param-row-edit">编辑</span>
          </div>
          <template v-for="(link, c) in chain" :key="'chain'+c">
            <div class="param-row">
              <span class="param-row-name">子命令 {{ chain.length > 1 ? c + 1 : '' }}</span>
              <span class="param-row-value">{{ link.variant.label }}</span>
            </div>
            <div v-for="(sp, i) in link.variant.subParams" :key="'s'+c+'-'+i" class="param-row">
              <span class="param-row-name" style="padding-left:12px">{{ sp.name }}</span>
              <span class="param-row-value" :class="{ 'param-empty': !link.values[i] }">{{ link.values[i] || '(空)' }}</span>
            </div>
          </template>
        </div>
      </div>
    </template>
    <!-- ═══ Selector Builder Overlay ═══ -->
    <div v-if="selectorBuilderCtx" class="selector-overlay">
      <div class="selector-builder">
        <div class="wizard-header">
          <McButton size="small" @click="closeSelectorBuilder">取消</McButton>
          <span class="wizard-title">自定义选择器</span>
        </div>
        <!-- Base selector -->
        <div class="selector-base-row">
          <span class="selector-label">基础选择器</span>
          <div class="btn-grid">
            <button v-for="base in ['@p', '@a', '@e', '@r', '@s']" :key="base" class="option-btn option-btn-sm"
              :class="{ 'option-selected': selectorBase === base }" @click="selectorBase = base">
              <span class="opt-value">{{ base }}</span>
            </button>
          </div>
        </div>
        <!-- Conditions -->
        <McScrollbar class="selector-conditions">
          <span class="selector-label">筛选条件</span>
          <div v-for="(cond, ci) in selectorConditions" :key="ci" class="selector-cond-row">
            <!-- Param picker: MC-styled button grid -->
            <div class="selector-param-picker">
              <span class="selector-param-current" @click="cond._open = !cond._open">{{ cond.param }} <span class="selector-param-arrow">{{ cond._open ? '▲' : '▼' }}</span></span>
              <div v-if="cond._open" class="selector-param-dropdown">
                <button v-for="sp in SELECTOR_PARAM_LIST" :key="sp.name" class="selector-param-option"
                  :class="{ 'selector-param-active': cond.param === sp.name }"
                  @click="cond.param = sp.name; cond.value = ''; delete selectorConditionSearch[ci]; cond._open = false">
                  <span class="selector-param-option-name">{{ sp.name }}</span>
                  <span class="selector-param-option-label">{{ sp.label }}</span>
                </button>
              </div>
            </div>
            <span class="selector-eq">=</span>
            <!-- Negate toggle -->
            <button v-if="selectorParamDef(cond.param)?.valueType !== 'number' && selectorParamDef(cond.param)?.valueType !== 'select'"
              class="selector-negate-btn" :class="{ 'selector-negated': cond.negated }" @click="cond.negated = !cond.negated" title="取反">!</button>
            <!-- Value input by type -->
            <template v-if="selectorParamDef(cond.param)?.valueType === 'search'">
              <div class="selector-search-wrap">
                <McInput :model-value="selectorConditionSearch[ci] || ''" placeholder="搜索..."
                  @update:model-value="selectorConditionSearch[ci] = $event" />
                <McScrollbar class="selector-search-list">
                  <button v-for="entry in selectorSearchResults(ci)" :key="entry.id" class="id-item"
                    :class="{ 'id-selected': cond.value === entry.id }" @click="cond.value = entry.id">
                    <span class="id-value">{{ entry.id }}</span>
                    <span v-if="entry.description" class="id-desc">{{ entry.description }}</span>
                  </button>
                </McScrollbar>
              </div>
            </template>
            <template v-else-if="selectorParamDef(cond.param)?.valueType === 'select'">
              <div class="selector-select-grid">
                <button v-for="opt in (selectorParamDef(cond.param) as any)?.options" :key="opt"
                  class="option-btn option-btn-sm" :class="{ 'option-selected': cond.value === opt }" @click="cond.value = opt">
                  <span class="opt-value">{{ opt }}</span>
                </button>
              </div>
            </template>
            <template v-else-if="selectorParamDef(cond.param)?.valueType === 'number'">
              <McInput :model-value="cond.value" placeholder="数值..." style="width:80px"
                @update:model-value="cond.value = $event" />
            </template>
            <template v-else>
              <McInput :model-value="cond.value" :placeholder="cond.param === 'scores' ? '{obj=1..5}' : cond.param === 'hasitem' ? '{item=diamond}' : '输入值...'"
                @update:model-value="cond.value = $event" style="flex:1;min-width:100px" />
            </template>
            <button class="selector-remove-btn" @click="removeSelectorCondition(ci)">×</button>
          </div>
          <McButton size="small" @click="addSelectorCondition">+ 添加条件</McButton>
        </McScrollbar>
        <!-- Preview -->
        <div class="selector-preview">
          <span class="selector-label">预览</span>
          <code class="selector-preview-code">{{ builtSelector }}</code>
        </div>
        <!-- Actions -->
        <div class="fill-actions">
          <McButton variant="primary" @click="confirmSelectorBuilder">确认选择器</McButton>
          <McButton @click="closeSelectorBuilder">取消</McButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wizard { display: flex; flex-direction: column; height: 100%; background: var(--mc-bg-main); overflow: hidden; }
.wizard-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 2px solid var(--mc-border); background: rgba(0,0,0,0.15); flex-shrink: 0; }
.wizard-title { font-family: var(--mc-font-title); font-size: 14px; color: var(--mc-text-primary); }
.step-indicator { margin-left: auto; font-family: var(--mc-font-mono); font-size: 12px; color: var(--mc-text-dim); }

.search-bar { padding: 8px 12px; flex-shrink: 0; }
.command-list { flex: 1; overflow-y: auto; }
.command-group { padding: 0 12px 8px; }
.group-label { font-family: var(--mc-font-title); font-size: 11px; color: var(--mc-text-dim); padding: 6px 0 4px; letter-spacing: 1px; }
.group-items { display: flex; flex-direction: column; gap: 2px; }
.command-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: transparent; border: 2px solid transparent; color: var(--mc-text-primary); font-family: var(--mc-font-body); font-size: 13px; cursor: pointer; text-align: left; transition: background 100ms; }
.command-item:hover { background: var(--mc-bg-card); border-color: var(--mc-border-light); }
.cmd-name { font-family: var(--mc-font-mono); color: var(--mc-syn-command); min-width: 120px; flex-shrink: 0; }
.cmd-desc { color: var(--mc-text-dim); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }

.preview-bar { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px; background: var(--mc-bg-deep); border-bottom: 2px solid var(--mc-border); font-family: var(--mc-font-mono); font-size: 13px; flex-shrink: 0; }
.preview-cmd { color: var(--mc-syn-command); }
.preview-seg { transition: color 100ms; }
.preview-done { color: var(--mc-text-primary); cursor: pointer; }
.preview-done:hover { color: var(--mc-gold); text-decoration: underline; }
.preview-current { color: var(--mc-gold); border-bottom: 2px solid var(--mc-gold); animation: blink 1s step-end infinite; }
.preview-pending { color: var(--mc-text-dim); opacity: 0.5; }
@keyframes blink { 50% { border-color: transparent; } }

.progress-dots { display: flex; gap: 6px; padding: 8px 12px; justify-content: center; flex-shrink: 0; }
.dot { width: 8px; height: 8px; border: 2px solid var(--mc-border-light); background: transparent; cursor: pointer; transition: all 100ms; }
.dot-done { background: var(--mc-green); border-color: var(--mc-green); }
.dot-current { border-color: var(--mc-gold); background: var(--mc-gold); box-shadow: 0 0 6px var(--mc-gold); }
.dot-optional { border-style: dashed; }

.param-info { padding: 8px 12px; border-bottom: 2px solid var(--mc-border); flex-shrink: 0; }
.param-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.param-name { font-family: var(--mc-font-title); font-size: 14px; color: var(--mc-gold); }
.param-desc { font-size: 12px; color: var(--mc-text-secondary); line-height: 1.5; }
.param-range, .param-default { font-size: 11px; color: var(--mc-text-dim); margin-top: 2px; }

.input-area { flex: 1; overflow-y: auto; padding: 8px 12px; }

.btn-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.option-btn { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 12px; min-width: 80px; background: var(--mc-bg-card); border: 2px solid var(--mc-border); box-shadow: var(--mc-shadow-raised-sm); color: var(--mc-text-primary); font-family: var(--mc-font-body); cursor: pointer; transition: all 100ms; }
.option-btn:hover { background: var(--mc-bg-hover); border-color: var(--mc-gold); }
.option-btn:active { box-shadow: var(--mc-shadow-sunken-sm); transform: translateY(1px); }
.option-selected { border-color: var(--mc-green); background: rgba(58,151,30,0.15); }
.opt-value { font-family: var(--mc-font-mono); font-size: 13px; color: var(--mc-syn-command); }
.opt-desc { font-size: 10px; color: var(--mc-text-dim); }
.custom-input-row { width: 100%; margin-top: 6px; }

.search-panel { display: flex; flex-direction: column; height: 100%; }
.search-input-wrap { flex-shrink: 0; margin-bottom: 6px; }
.id-list { flex: 1; min-height: 0; }
.id-item { display: flex; align-items: center; gap: 8px; width: 100%; padding: 5px 8px; background: transparent; border: 2px solid transparent; color: var(--mc-text-primary); font-family: var(--mc-font-body); font-size: 13px; cursor: pointer; text-align: left; transition: background 100ms; overflow: hidden; }
.id-item:hover { background: var(--mc-bg-card); border-color: var(--mc-border-light); }
.id-selected { border-color: var(--mc-green) !important; background: rgba(58,151,30,0.1); }
.id-relevant { background: rgba(226,199,20,0.08); border-left: 3px solid var(--mc-gold) !important; }
.id-relevant .id-value { color: var(--mc-gold); }
.id-relevant:hover { background: rgba(226,199,20,0.15); }
.relevant-hint { display: flex; align-items: center; gap: 6px; padding: 4px 8px; margin-bottom: 4px; font-size: 11px; color: var(--mc-text-dim); background: rgba(226,199,20,0.06); border-bottom: 1px solid rgba(226,199,20,0.2); }
.id-value { font-family: var(--mc-font-mono); color: var(--mc-sem-item); min-width: 80px; max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 1; }
.id-desc { color: var(--mc-text-dim); font-size: 12px; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 45%; }

.number-input { max-width: 200px; }
.coord-input { display: flex; flex-direction: column; gap: 8px; }
.coord-fields { display: flex; gap: 8px; }
.coord-field { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.coord-label { font-family: var(--mc-font-mono); font-size: 12px; color: var(--mc-text-dim); text-align: center; }
.coord-presets { display: flex; gap: 6px; }
.text-input { max-width: 400px; }

/* JSON / Rawtext builder */
.json-builder { display: flex; flex-direction: column; gap: 8px; }
.json-hint { font-size: 12px; color: var(--mc-text-dim); }
.rawtext-row { display: flex; align-items: flex-start; gap: 6px; padding: 4px 0; flex-wrap: wrap; }
.rawtext-input { flex: 1; min-width: 120px; }
.rawtext-input-sm { width: 100px; }
.rawtext-remove { background: none; border: none; color: var(--mc-red); font-size: 16px; cursor: pointer; padding: 2px 6px; font-family: var(--mc-font-mono); flex-shrink: 0; }
.rawtext-remove:hover { color: var(--mc-red-hover); }
.rawtext-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.json-preview { background: var(--mc-bg-deep); border: 2px solid var(--mc-border); padding: 8px; font-family: var(--mc-font-mono); font-size: 11px; color: var(--mc-syn-string); word-break: break-all; max-height: 60px; overflow-y: auto; }

/* Color picker for § codes */
.color-picker { display: flex; flex-wrap: wrap; gap: 2px; width: 100%; margin-top: 4px; }
.color-dot { width: 18px; height: 18px; border: 1px solid var(--mc-border-light); cursor: pointer; font-size: 8px; display: flex; align-items: center; justify-content: center; color: var(--mc-text-primary); font-family: var(--mc-font-mono); }
.color-dot:hover { border-color: var(--mc-gold); transform: scale(1.2); }

/* Translate args */
.translate-args { width: 100%; margin-top: 4px; display: flex; flex-direction: column; gap: 4px; padding-left: 8px; }
.translate-label { font-size: 11px; color: var(--mc-text-dim); }
.translate-arg-row { display: flex; align-items: center; gap: 4px; }

/* Item components builder */
.comp-section { padding: 6px 0; border-bottom: 1px solid var(--mc-border-light); }
.comp-label { font-family: var(--mc-font-mono); font-size: 12px; color: var(--mc-text-secondary); margin-bottom: 4px; }
.comp-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px; }
.comp-add-row { display: flex; gap: 6px; align-items: flex-start; }
.comp-id-list { max-height: 120px; overflow-y: auto; margin-top: 4px; border: 1px solid var(--mc-border-light); }

.fill-actions { display: flex; gap: 8px; padding: 8px 12px; border-top: 2px solid var(--mc-border); flex-shrink: 0; }

.execute-hint { padding: 8px 12px; font-size: 12px; color: var(--mc-text-dim); background: rgba(226,199,20,0.06); border-top: 1px solid rgba(226,199,20,0.2); flex-shrink: 0; }
.run-command-panel { display: flex; flex-direction: column; height: 100%; }
.run-sub-header { display: flex; align-items: center; gap: 6px; padding: 4px 0 8px; flex-shrink: 0; }
.run-cmd-label { font-family: var(--mc-font-mono); font-size: 13px; color: var(--mc-syn-command); }
.chain-count { font-size: 12px; color: var(--mc-text-secondary); flex: 1; }

.complete-content { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 16px; }
.command-display { background: var(--mc-bg-deep); border: 2px solid var(--mc-border); padding: 16px; box-shadow: var(--mc-shadow-sunken); }
.command-line { font-family: var(--mc-font-mono); font-size: 15px; line-height: 1.6; word-break: break-all; }
.seg { cursor: default; transition: opacity 100ms; }
.seg + .seg::before { content: ' '; }
.seg-command { color: var(--mc-syn-command); }
.seg-selector { color: var(--mc-syn-selector); }
.seg-number { color: var(--mc-syn-number); }
.seg-coord { color: var(--mc-syn-optional); }
.seg-id { color: var(--mc-sem-item); }
.seg-enum { color: var(--mc-sem-enum); }
.seg-string { color: var(--mc-syn-string); }
.seg-text { color: var(--mc-text-primary); }

.complete-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.param-summary { display: flex; flex-direction: column; gap: 2px; }
.param-row { display: flex; align-items: center; gap: 8px; padding: 6px 8px; cursor: pointer; border: 2px solid transparent; transition: background 100ms; }
.param-row:hover { background: var(--mc-bg-card); border-color: var(--mc-border-light); }
.param-row-name { font-family: var(--mc-font-mono); font-size: 12px; color: var(--mc-text-dim); min-width: 100px; }
.param-row-value { font-family: var(--mc-font-mono); font-size: 13px; color: var(--mc-text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.param-empty { color: var(--mc-text-dim); opacity: 0.5; }
.param-row-edit { font-size: 11px; color: var(--mc-gold); opacity: 0; transition: opacity 100ms; }
.param-row:hover .param-row-edit { opacity: 1; }

.empty-hint { padding: 20px; text-align: center; color: var(--mc-text-dim); font-size: 13px; }

/* Selector builder */
.selector-builder-btn { margin-top: 6px; }
.selector-overlay { position: absolute; inset: 0; z-index: 10; display: flex; flex-direction: column; background: var(--mc-bg-main); }
.selector-builder { display: flex; flex-direction: column; height: 100%; }
.selector-base-row { padding: 8px 12px; border-bottom: 2px solid var(--mc-border); flex-shrink: 0; }
.selector-label { font-family: var(--mc-font-title); font-size: 12px; color: var(--mc-text-dim); display: block; margin-bottom: 6px; }
.option-btn-sm { min-width: 48px; padding: 6px 8px; }
.selector-conditions { padding: 8px 12px; flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.selector-cond-row { display: flex; align-items: flex-start; gap: 6px; flex-wrap: wrap; padding: 8px; border: 2px solid var(--mc-border-light); background: rgba(0,0,0,0.08); box-shadow: var(--mc-shadow-sunken-sm); }
/* Param picker dropdown */
.selector-param-picker { position: relative; min-width: 100px; }
.selector-param-current { display: flex; align-items: center; gap: 4px; padding: 5px 10px; background: var(--mc-bg-card); border: 2px solid var(--mc-border); box-shadow: var(--mc-shadow-raised-sm); font-family: var(--mc-font-mono); font-size: 12px; color: var(--mc-syn-selector); cursor: pointer; transition: border-color 100ms, box-shadow 100ms; }
.selector-param-current:hover { border-color: var(--mc-gold); }
.selector-param-current:active { box-shadow: var(--mc-shadow-sunken-sm); transform: translateY(1px); }
.selector-param-arrow { font-size: 8px; color: var(--mc-text-dim); margin-left: auto; transition: color 100ms; }
.selector-param-current:hover .selector-param-arrow { color: var(--mc-gold); }
.selector-param-dropdown { position: absolute; top: calc(100% + 2px); left: 0; z-index: 5; width: 220px; max-height: 200px; overflow-y: auto; background: var(--mc-bg-card); border: 2px solid var(--mc-border); box-shadow: var(--mc-shadow-raised); }
.selector-param-option { display: flex; align-items: center; gap: 6px; width: 100%; padding: 5px 8px; background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--mc-text-primary); font-family: var(--mc-font-body); font-size: 12px; cursor: pointer; text-align: left; transition: background 80ms, border-color 80ms; }
.selector-param-option:last-child { border-bottom: none; }
.selector-param-option:hover { background: var(--mc-bg-hover); }
.selector-param-active { background: rgba(58,151,30,0.15); border-left: 3px solid var(--mc-green); }
.selector-param-option-name { font-family: var(--mc-font-mono); color: var(--mc-syn-selector); min-width: 60px; }
.selector-param-option-label { color: var(--mc-text-dim); font-size: 11px; }
/* Eq sign */
.selector-eq { font-family: var(--mc-font-mono); font-size: 14px; color: var(--mc-text-dim); line-height: 30px; flex-shrink: 0; }
/* Negate button */
.selector-negate-btn { width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; background: var(--mc-bg-card); border: 2px solid var(--mc-border); font-family: var(--mc-font-mono); font-size: 14px; color: var(--mc-text-dim); cursor: pointer; transition: all 100ms; flex-shrink: 0; }
.selector-negate-btn:hover { border-color: var(--mc-red); color: var(--mc-red); }
.selector-negated { background: rgba(170,0,0,0.2); border-color: var(--mc-red); color: var(--mc-red); }
/* Select grid (for gamemode etc) */
.selector-select-grid { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; }
/* Search area */
.selector-search-wrap { flex: 1; min-width: 140px; }
.selector-search-list { max-height: 150px; border: 2px solid var(--mc-border-light); margin-top: 2px; }
/* Remove button */
.selector-remove-btn { width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; background: none; border: 2px solid transparent; font-family: var(--mc-font-mono); font-size: 16px; color: var(--mc-text-dim); cursor: pointer; transition: all 100ms; flex-shrink: 0; }
.selector-remove-btn:hover { color: var(--mc-red); border-color: var(--mc-red); background: rgba(170,0,0,0.1); }
/* Preview */
.selector-preview { padding: 8px 12px; border-top: 2px solid var(--mc-border); flex-shrink: 0; }
.selector-preview-code { display: block; font-family: var(--mc-font-mono); font-size: 14px; color: var(--mc-syn-selector); background: var(--mc-bg-deep); padding: 8px; margin-top: 4px; word-break: break-all; border: 2px solid var(--mc-border); box-shadow: var(--mc-shadow-sunken-sm); }
</style>
