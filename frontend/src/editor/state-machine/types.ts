/** Types for the MC command state machine & editor */

/**
 * Parameter type as declared in command JSON definitions.
 * Open string type — any type string from command JSONs is passed through as-is.
 * Well-known types include: target, Item, Block, EntityType, Effect, Enchantment,
 * Enchant, Particle, Sound, Biome, Fog, Animation, GameRule, Structure,
 * int, float, boolean, Boolean, string, json, x y z, gamemode, GameMode,
 * difficulty, Difficulty, DamageCause, MaskMode, CloneMode, FillMode,
 * SetBlockMode, Ability, EaseType, InputPermission, HudElement,
 * EntityEquipmentSlot, CameraPreset, MobEvent, Dimension, operator, message
 */
export type ParameterType = string

/** A parameter definition from command JSON */
export interface CommandParamDef {
  name: string
  type: ParameterType
  required: boolean
  description?: string
  default?: string
  range?: string
}

/** Minimal command syntax definition (loaded from knowledge base) */
export interface CommandSyntaxDef {
  name: string
  syntax: string
  description: string
  category: string
  parameters: CommandParamDef[]
}

/** A sub-parameter within a subcommand variant */
export interface SubParamDef {
  name: string
  type: string
  required: boolean
  /** Fixed literal options for this param (e.g. "eyes|feet") */
  options?: string[]
}

/** A single subcommand variant parsed from the name field */
export interface SubcommandVariant {
  /** Leading keywords (e.g. ["if", "block"] or ["objectives", "add"]) */
  keywords: string[]
  /** Parameters after the keywords */
  params: SubParamDef[]
  /** Description from the original CommandParamDef */
  description: string
}

/** Tree structure grouping subcommand variants by first keyword */
export interface SubcommandTree {
  /** Variants grouped by their first keyword */
  byFirstKeyword: Map<string, SubcommandVariant[]>
  /** Number of non-subcommand parameters before the subcommand begins */
  prefixParamCount: number
}

/** Context at cursor position, produced by the state machine */
export interface CursorContext {
  /** The command name (without /) if recognized, null otherwise */
  commandName: string | null
  /** The full command definition, if found */
  commandDef: CommandSyntaxDef | null
  /** Index of the parameter the cursor is in (0-based) */
  paramIndex: number
  /** Expected parameter type at cursor */
  expectedType: ParameterType | null
  /** Partial text already typed for the current parameter */
  partialInput: string
  /** Whether we're inside a selector bracket @e[...] */
  inSelector: boolean
  /** Selector parameter name being typed (when inSelector) */
  selectorParam: string | null
  /** Whether we're typing the value side of selector param=value */
  selectorValue: boolean
  /** Current parameter definition (for hint panel) */
  currentParam: CommandParamDef | null
  /** Matched subcommand variant */
  subcommandVariant: SubcommandVariant | null
  /** Parameter index within the subcommand variant */
  subParamIndex: number
  /** Current sub-parameter definition */
  currentSubParam: SubParamDef | null
  /** Available subcommand variants at cursor (for completion) */
  availableSubcommands: SubcommandVariant[] | null
}

/** An ID entry from the knowledge base */
export interface IdEntry {
  id: string
  name?: string
  category?: string
  description?: string
}
