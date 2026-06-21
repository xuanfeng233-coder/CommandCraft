/**
 * NBT autocompletion for Java Edition.
 * Provides context-aware tag name and value suggestions based on NBT schemas.
 */

import type { Completion } from '@codemirror/autocomplete'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import { fetchNbtSchema } from '@/api/knowledge'
import {
  parseNbtContext,
  extractNbtFromCommand,
  extractContextType,
} from '@/editor/state-machine/nbt-parser'

// ---------------------------------------------------------------------------
// NBT Schema cache (in-memory, loaded on demand)
// ---------------------------------------------------------------------------

interface NbtTag {
  name: string
  type: string
  description?: string
  values?: (number | string)[]
  default?: number | string
  range?: string
  children?: NbtTag[]
  id_category?: string
}

interface NbtSchema {
  id?: string
  inherits?: string
  tags: NbtTag[]
}

const schemaCache = new Map<string, NbtSchema | null>()

async function loadSchema(
  nbtType: string,
  name: string,
): Promise<NbtSchema | null> {
  const key = `${nbtType}/${name}`
  if (schemaCache.has(key)) return schemaCache.get(key)!

  const schema = await fetchNbtSchema(nbtType, name, 'java')
  schemaCache.set(key, schema as NbtSchema | null)
  return schema as NbtSchema | null
}

/**
 * Resolve the tags for a given path in an NBT schema.
 * Follows the path through compound/list children.
 */
function resolveTagsAtPath(schema: NbtSchema, path: (string | number)[]): NbtTag[] {
  let tags = schema.tags
  for (const segment of path) {
    if (typeof segment === 'number') {
      // List index - stay at same level (list items share the same child schema)
      continue
    }
    // Find the tag matching this path segment
    const tag = tags.find((t) => t.name === segment)
    if (tag?.children) {
      tags = tag.children
    } else {
      return []
    }
  }
  return tags
}

/**
 * Find the tag definition for a specific key at the current path.
 */
function findTagDef(schema: NbtSchema, path: (string | number)[], key: string): NbtTag | null {
  const tags = resolveTagsAtPath(schema, path)
  return tags.find((t) => t.name === key) ?? null
}

// ---------------------------------------------------------------------------
// Completion source
// ---------------------------------------------------------------------------

/**
 * Attempt NBT completion for the current cursor position.
 * Returns completions if the cursor is inside an NBT context, null otherwise.
 */
export async function completeNbt(
  line: string,
  col: number,
  pos: number,
): Promise<{ from: number; options: Completion[] } | null> {
  // Extract NBT portion from command
  const nbtInfo = extractNbtFromCommand(line, col)
  if (!nbtInfo) return null

  // Parse cursor context within NBT
  const ctx = parseNbtContext(nbtInfo.nbtText, nbtInfo.cursorInNbt)

  // Determine entity/item/block type from command
  const contextType = extractContextType(line, nbtInfo.nbtStart)
  if (!contextType) {
    // No identifiable context - provide generic completions
    return null
  }

  // Map context to NBT type directory
  const nbtTypeMap: Record<string, string> = {
    entity: 'entities',
    item: 'items',
    block: 'blocks',
  }
  const nbtType = nbtTypeMap[contextType.context]

  // Load schema (resolved with _common inheritance)
  const schema = await loadSchema(nbtType, contextType.type)
  if (!schema) {
    // Try loading just _common
    const commonSchema = await loadSchema(nbtType, '_common')
    if (!commonSchema) return null
    return buildCompletions(commonSchema, ctx, pos, line, col)
  }

  return buildCompletions(schema, ctx, pos, line, col)
}

function buildCompletions(
  schema: NbtSchema,
  ctx: ReturnType<typeof parseNbtContext>,
  pos: number,
  line: string,
  col: number,
): { from: number; options: Completion[] } | null {
  const options: Completion[] = []
  const from = pos - ctx.partial.length

  if (ctx.isKey) {
    // Completing a tag name
    const tags = resolveTagsAtPath(schema, ctx.path)
    const partial = ctx.partial.toLowerCase()

    for (const tag of tags) {
      if (partial && !tag.name.toLowerCase().startsWith(partial)) continue
      options.push({
        label: tag.name,
        detail: tag.type,
        info: tag.description,
        type: 'property',
        apply: `${tag.name}:`,
        boost: tag.name.toLowerCase().startsWith(partial) ? 1 : 0,
      })
    }
  } else if (ctx.currentKey) {
    // Completing a tag value
    const tagDef = findTagDef(schema, ctx.path, ctx.currentKey)
    if (tagDef) {
      const valueCompletions = getValueCompletions(tagDef, ctx.partial)
      options.push(...valueCompletions)
    }
  }

  if (options.length === 0) return null
  return { from, options }
}

function getValueCompletions(tag: NbtTag, partial: string): Completion[] {
  const options: Completion[] = []

  // Specific values defined in schema
  if (tag.values && tag.values.length > 0) {
    for (const v of tag.values) {
      const label = formatNbtValue(v, tag.type)
      if (partial && !label.startsWith(partial)) continue
      options.push({
        label,
        detail: tag.type,
        info: tag.description,
        type: 'constant',
      })
    }
    return options
  }

  // Type-based suggestions
  switch (tag.type) {
    case 'byte':
      options.push(
        { label: '0b', detail: 'byte', info: 'false', type: 'constant' },
        { label: '1b', detail: 'byte', info: 'true', type: 'constant' },
      )
      break
    case 'short':
      options.push({ label: '0s', detail: 'short', type: 'constant' })
      break
    case 'int':
      options.push({ label: '0', detail: 'int', type: 'constant' })
      break
    case 'long':
      options.push({ label: '0L', detail: 'long', type: 'constant' })
      break
    case 'float':
      options.push({ label: '0.0f', detail: 'float', type: 'constant' })
      break
    case 'double':
      options.push({ label: '0.0d', detail: 'double', type: 'constant' })
      break
    case 'string':
      if (tag.id_category) {
        // Search IDs from knowledge cache
        const cache = useKnowledgeCache()
        const searchTerm = partial.replace(/^["']/, '')
        const entries = cache.searchIds(tag.id_category, searchTerm, 20)
        for (const entry of entries) {
          options.push({
            label: `"${entry.id}"`,
            detail: entry.name || entry.id,
            info: entry.description,
            type: 'text',
          })
        }
      } else {
        options.push({ label: '""', detail: 'string', type: 'text', apply: '""' })
      }
      break
    case 'compound':
      options.push({ label: '{}', detail: 'compound', type: 'keyword', apply: '{}' })
      break
    default:
      if (tag.type.startsWith('list<')) {
        options.push({ label: '[]', detail: tag.type, type: 'keyword', apply: '[]' })
        if (tag.type === 'list<compound>') {
          options.push({ label: '[{}]', detail: 'list<compound>', type: 'keyword', apply: '[{}]' })
        }
      }
      break
  }

  return options
}

function formatNbtValue(value: number | string, type: string): string {
  if (typeof value === 'string') return `"${value}"`
  switch (type) {
    case 'byte': return `${value}b`
    case 'short': return `${value}s`
    case 'long': return `${value}L`
    case 'float': return `${value}f`
    case 'double': return `${value}d`
    default: return String(value)
  }
}
