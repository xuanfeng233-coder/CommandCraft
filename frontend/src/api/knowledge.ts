/**
 * API client for bulk knowledge endpoints.
 * Used by the editor knowledge-cache store and CommandEditor.
 */
import type { CommandSyntaxDef, IdEntry } from '@/editor/state-machine/types'
import type { CommandParamDef } from '@/types'

const API_BASE = ''

/** Fetch all command syntax definitions in bulk */
export async function fetchAllCommandSyntax(): Promise<CommandSyntaxDef[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/commands/all-syntax`)
  if (!res.ok) throw new Error(`Failed to fetch command syntax: ${res.status}`)
  const data = await res.json()
  return data.commands as CommandSyntaxDef[]
}

/** Fetch full ID entries for a category */
export async function fetchIdsFull(category: string): Promise<IdEntry[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/ids/${category}/full`)
  if (!res.ok) throw new Error(`Failed to fetch IDs for ${category}: ${res.status}`)
  const data = await res.json()
  return data.entries as IdEntry[]
}

/** Fetch all ID categories available */
export async function fetchIdCategories(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/ids`)
  if (!res.ok) throw new Error(`Failed to fetch ID categories: ${res.status}`)
  const data = await res.json()
  return data.categories as string[]
}

// --- CommandEditor support ---

const _paramCache = new Map<string, CommandParamDef[]>()

/** Fetch parameter definitions for a command (with enriched options) */
export async function fetchCommandParams(name: string): Promise<CommandParamDef[]> {
  if (_paramCache.has(name)) return _paramCache.get(name)!
  const res = await fetch(`${API_BASE}/api/knowledge/commands/${name}/params`)
  if (!res.ok) return []
  const data = await res.json()
  const params: CommandParamDef[] = data.params ?? []
  _paramCache.set(name, params)
  return params
}

/** Map parameter type/name to knowledge base category */
export function paramTypeToCategory(ptype: string, pname: string): string | null {
  const typeMap: Record<string, string> = {
    Item: 'items', Block: 'blocks', block: 'blocks',
    EntityType: 'entities', entityType: 'entities',
    Effect: 'effects', Enchant: 'enchantments', Enchantment: 'enchantments',
    Particle: 'particles', Sound: 'sounds', Biome: 'biomes',
    Fog: 'fog', Animation: 'animations',
    GameRule: 'gamerules', Structure: 'structures',
  }
  if (typeMap[ptype]) return typeMap[ptype]
  const nameMap: Record<string, string> = {
    itemName: 'items', item: 'items', entityType: 'entities',
    effect: 'effects', enchantName: 'enchantments', enchantment: 'enchantments',
    tileName: 'blocks', block: 'blocks', sound: 'sounds', particle: 'particles',
    fogId: 'fog', animationId: 'animations', rule: 'gamerules', biome: 'biomes',
  }
  return nameMap[pname] ?? null
}
