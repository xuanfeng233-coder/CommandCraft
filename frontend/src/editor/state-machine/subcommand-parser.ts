/**
 * Subcommand parser — parses the `name` field of "子命令" type parameters
 * into structured SubcommandVariant trees for completion and hint panels.
 *
 * Examples of name field formats:
 *   "as <origin: target>"
 *   "if block <position: x y z> <block: Block>"
 *   "objectives add <objective: string> dummy [displayName: string]"
 *   "unless ..."
 *   "run <command: Command>"
 *   "list"
 */
import type {
  CommandSyntaxDef,
  SubParamDef,
  SubcommandVariant,
  SubcommandTree,
} from './types'

/**
 * Infer parameter type from name when no explicit type is given (common in Java Edition).
 * E.g. `<pos>` → 'x y z', `<target>` → 'target', `<nbt>` → 'compound_tag'
 */
const PARAM_NAME_TYPE_MAP: Record<string, string> = {
  // Coordinates
  pos: 'x y z',
  position: 'x y z',
  begin: 'x y z',
  end: 'x y z',
  start: 'x y z',
  from: 'x y z',
  to: 'x y z',
  destination: 'x y z',
  origin: 'x y z',
  center: 'x z',
  delta: 'dx dy dz',
  rotation: 'yaw pitch',
  // Targets / entities
  target: 'target',
  targets: 'target',
  player: 'target',
  players: 'target',
  entity: 'target',
  source: 'target',
  vehicle: 'target',
  victim: 'target',
  members: 'target',
  viewers: 'target',
  // IDs
  block: 'block_id',
  item: 'item_id',
  effect: 'effect_id',
  enchantment: 'enchantment_id',
  biome: 'biome_id',
  structure: 'Structure',
  feature: 'Structure',
  particle: 'particle_id',
  sound: 'sound_id',
  attribute: 'attribute_id',
  recipe: 'resource_location',
  advancement: 'resource_location',
  id: 'resource_location',
  nbt: 'compound_tag',
  // Enums
  gamemode: 'GameMode',
  difficulty: 'Difficulty',
  dimension: 'dimension',
  anchor: 'anchor',
  slot: 'item_slot',
  operation: 'operator',
  // Strings
  name: 'string',
  path: 'string',
  objective: 'string',
  criteria: 'string',
  criterion: 'string',
  message: 'message',
  reason: 'message',
  team: 'string',
  tag: 'string',
  // Numbers
  distance: 'float',
  amount: 'int',
  count: 'int',
  scale: 'float',
  time: 'int',
  value: 'int',
  level: 'int',
  max: 'int',
  rate: 'float',
  damage: 'float',
  speed: 'float',
  volume: 'float',
  pitch: 'float',
  // Booleans
  visible: 'boolean',
  // Special
  command: 'Command',
  filter: 'block_predicate',
}

function inferParamType(name: string): string {
  return PARAM_NAME_TYPE_MAP[name.toLowerCase()] ?? 'string'
}

/** Token types from tokenizing a subcommand name field */
type NameToken =
  | { kind: 'word'; value: string }
  | { kind: 'param'; name: string; type: string; required: boolean }

/**
 * Tokenize a subcommand name string into keywords and parameter placeholders.
 * `<name: type>` → required param, `[name: type]` → optional param,
 * bare words → keyword tokens.
 */
export function tokenizeSubcommandName(name: string): NameToken[] {
  const tokens: NameToken[] = []
  let i = 0
  const s = name.trim()

  while (i < s.length) {
    // Skip whitespace
    if (s[i] === ' ' || s[i] === '\t') { i++; continue }

    // Required parameter <name: type>
    if (s[i] === '<') {
      const end = s.indexOf('>', i)
      if (end === -1) break
      const inner = s.slice(i + 1, end).trim()
      const colonIdx = inner.indexOf(':')
      if (colonIdx !== -1) {
        tokens.push({
          kind: 'param',
          name: inner.slice(0, colonIdx).trim(),
          type: inner.slice(colonIdx + 1).trim(),
          required: true,
        })
      } else {
        tokens.push({ kind: 'param', name: inner, type: inferParamType(inner), required: true })
      }
      i = end + 1
      continue
    }

    // Optional parameter [name: type]
    if (s[i] === '[') {
      const end = s.indexOf(']', i)
      if (end === -1) break
      const inner = s.slice(i + 1, end).trim()
      const colonIdx = inner.indexOf(':')
      if (colonIdx !== -1) {
        tokens.push({
          kind: 'param',
          name: inner.slice(0, colonIdx).trim(),
          type: inner.slice(colonIdx + 1).trim(),
          required: false,
        })
      } else {
        tokens.push({ kind: 'param', name: inner, type: inferParamType(inner), required: false })
      }
      i = end + 1
      continue
    }

    // Word token (keyword or literal)
    let end = i
    while (end < s.length && s[end] !== ' ' && s[end] !== '\t' && s[end] !== '<' && s[end] !== '[') {
      end++
    }
    const word = s.slice(i, end)
    if (word === '...') { i = end; continue } // skip ellipsis
    tokens.push({ kind: 'word', value: word })
    i = end
  }

  return tokens
}

/**
 * Parse a single subcommand name field into a SubcommandVariant.
 */
export function parseSubcommandName(
  name: string,
  description: string
): SubcommandVariant {
  const tokens = tokenizeSubcommandName(name)
  const keywords: string[] = []
  const params: SubParamDef[] = []
  let hitParam = false

  for (const token of tokens) {
    if (token.kind === 'word') {
      if (!hitParam) {
        // Words before any param are keywords
        // Check if it contains | (e.g. "< | <= | = | >= | >") — skip
        if (token.value.includes('|')) {
          // Literal options, treat as a param with options
          const options = token.value.split('|').map((o) => o.trim()).filter(Boolean)
          params.push({ name: token.value, type: 'literal', required: true, options })
          hitParam = true
        } else {
          keywords.push(token.value)
        }
      } else {
        // Words after params — check for pipe-separated options
        if (token.value.includes('|')) {
          const options = token.value.split('|').map((o) => o.trim()).filter(Boolean)
          params.push({ name: token.value, type: 'literal', required: true, options })
        } else {
          params.push({ name: token.value, type: 'literal', required: true, options: [token.value] })
        }
      }
    } else {
      hitParam = true
      // Check if the type contains | (e.g. "eyes|feet", "all|masked")
      const typeStr = token.type
      if (typeStr.includes('|') && !typeStr.includes(' ')) {
        const options = typeStr.split('|').map((o) => o.trim())
        params.push({ name: token.name, type: 'literal', required: token.required, options })
      } else {
        params.push({ name: token.name, type: typeStr, required: token.required })
      }
    }
  }

  return { keywords, params, description }
}

/**
 * Build a SubcommandTree from a command definition.
 * Returns null if the command has no "子命令" type parameters.
 */
export function buildSubcommandTree(cmdDef: CommandSyntaxDef): SubcommandTree | null {
  const subParams = cmdDef.parameters.filter((p) => p.type === '子命令')
  if (subParams.length === 0) {
    // Also check for pipe-separated type like "hold|query|resume"
    const pipeParam = cmdDef.parameters.find((p) => p.name === '子命令' && p.type.includes('|'))
    if (!pipeParam) return null

    // Special case: name="子命令", type="hold|query|resume"
    const options = pipeParam.type.split('|').map((o) => o.trim())
    const byFirstKeyword = new Map<string, SubcommandVariant[]>()
    for (const opt of options) {
      byFirstKeyword.set(opt, [{
        keywords: [opt],
        params: [],
        description: pipeParam.description ?? '',
      }])
    }
    return { byFirstKeyword, prefixParamCount: 0 }
  }

  // Count prefix (non-subcommand) parameters
  let prefixParamCount = 0
  for (const p of cmdDef.parameters) {
    if (p.type === '子命令') break
    prefixParamCount++
  }

  const byFirstKeyword = new Map<string, SubcommandVariant[]>()
  const ifVariants: SubcommandVariant[] = []

  for (const param of subParams) {
    // Special case: "unless ..." → will copy if variants later
    if (param.name === 'unless ...') continue

    const variant = parseSubcommandName(param.name, param.description ?? '')
    if (variant.keywords.length === 0) continue

    const firstKw = variant.keywords[0]
    if (!byFirstKeyword.has(firstKw)) {
      byFirstKeyword.set(firstKw, [])
    }
    byFirstKeyword.get(firstKw)!.push(variant)

    if (firstKw === 'if') {
      ifVariants.push(variant)
    }
  }

  // Handle "unless ..." — copy all "if" variants with "unless" as first keyword
  const unlessParam = subParams.find((p) => p.name === 'unless ...')
  if (unlessParam && ifVariants.length > 0) {
    const unlessVariants: SubcommandVariant[] = ifVariants.map((v) => ({
      keywords: ['unless', ...v.keywords.slice(1)],
      params: [...v.params],
      description: unlessParam.description ?? v.description,
    }))
    byFirstKeyword.set('unless', unlessVariants)
  }

  return { byFirstKeyword, prefixParamCount }
}
