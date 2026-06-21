/**
 * API client for bulk knowledge endpoints.
 * Used by the editor knowledge-cache store and CommandEditor.
 */
import type { CommandSyntaxDef, IdEntry } from '@/editor/state-machine/types'
import type { CommandParamDef } from '@/types'

const API_BASE = ''

/** Fetch all command syntax definitions in bulk */
export async function fetchAllCommandSyntax(edition = 'bedrock'): Promise<CommandSyntaxDef[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/commands/all-syntax`)
  if (!res.ok) throw new Error(`Failed to fetch command syntax: ${res.status}`)
  const data = await res.json()
  return data.commands as CommandSyntaxDef[]
}

/** Fetch full ID entries for a category */
export async function fetchIdsFull(category: string, edition = 'bedrock'): Promise<IdEntry[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/ids/${category}/full`)
  if (!res.ok) throw new Error(`Failed to fetch IDs for ${category}: ${res.status}`)
  const data = await res.json()
  return data.entries as IdEntry[]
}

/** Fetch all ID categories available */
export async function fetchIdCategories(edition = 'bedrock'): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/ids`)
  if (!res.ok) throw new Error(`Failed to fetch ID categories: ${res.status}`)
  const data = await res.json()
  return data.categories as string[]
}

/** Fetch NBT schema for an entity/item/block type (Java Edition) */
export async function fetchNbtSchema(
  nbtType: string,
  name: string,
  edition = 'java',
): Promise<Record<string, any> | null> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/nbt/${nbtType}/${name}`)
  if (!res.ok) return null
  const data = await res.json()
  return data.schema ?? null
}

/** List available NBT schema names for a type */
export async function fetchNbtSchemaNames(
  nbtType: string,
  edition = 'java',
): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/nbt/${nbtType}`)
  if (!res.ok) return []
  const data = await res.json()
  return data.names ?? []
}

/** Fetch data component definitions (Java 1.20.5+) */
export async function fetchDataComponents(edition = 'java'): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/data-components`)
  if (!res.ok) return {}
  return res.json()
}

/** Fetch JSON text component schema */
export async function fetchTextComponents(edition = 'java'): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/api/knowledge/${edition}/text-components`)
  if (!res.ok) return {}
  return res.json()
}

// --- CommandEditor support ---

const _paramCache = new Map<string, CommandParamDef[]>()

/** Fetch parameter definitions for a command (with enriched options) */
export async function fetchCommandParams(name: string, edition = 'bedrock'): Promise<CommandParamDef[]> {
  const key = `${edition}:${name}`
  if (_paramCache.has(key)) return _paramCache.get(key)!
  const res = await fetch(`${API_BASE}/api/knowledge/commands/${name}/params?edition=${edition}`)
  if (!res.ok) return []
  const data = await res.json()
  const params: CommandParamDef[] = data.params ?? []
  _paramCache.set(key, params)
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
    Attribute: 'attributes',
  }
  if (typeMap[ptype]) return typeMap[ptype]
  const nameMap: Record<string, string> = {
    itemName: 'items', item: 'items', entityType: 'entities',
    effect: 'effects', enchantName: 'enchantments', enchantment: 'enchantments',
    tileName: 'blocks', block: 'blocks', sound: 'sounds', particle: 'particles',
    fogId: 'fog', animationId: 'animations', rule: 'gamerules', biome: 'biomes',
    attribute: 'attributes',
  }
  return nameMap[pname] ?? null
}
