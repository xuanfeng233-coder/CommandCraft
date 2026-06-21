/**
 * NBT context parser for Java Edition.
 * Parses cursor position within NBT `{...}` syntax to determine:
 * - Current path in the NBT tree
 * - Whether cursor is at a key or value position
 * - Partial input being typed
 */

export interface NbtCursorContext {
  /** NBT path from root, e.g. ["tag", "Enchantments", 0, "id"] */
  path: (string | number)[]
  /** Whether cursor is at key position (tag name) or value position */
  isKey: boolean
  /** Partial text typed */
  partial: string
  /** Current compound depth */
  depth: number
  /** Whether we're inside a list */
  inList: boolean
  /** The current key name if at value position */
  currentKey: string | null
}

/**
 * Parse cursor context within an NBT string.
 *
 * @param nbtText The NBT text (everything inside the outermost {})
 * @param cursorOffset The cursor position within nbtText
 */
export function parseNbtContext(nbtText: string, cursorOffset: number): NbtCursorContext {
  const path: (string | number)[] = []
  let isKey = true
  let partial = ''
  let depth = 0
  let inList = false
  let currentKey: string | null = null

  // Track state
  let inString = false
  let stringChar = ''
  let escaped = false
  let currentToken = ''
  let afterColon = false
  const listCountStack: number[] = [] // track list index at each depth

  for (let i = 0; i < cursorOffset && i < nbtText.length; i++) {
    const ch = nbtText[i]

    if (escaped) {
      escaped = false
      currentToken += ch
      continue
    }

    if (ch === '\\') {
      escaped = true
      currentToken += ch
      continue
    }

    if (inString) {
      if (ch === stringChar) {
        inString = false
        currentToken += ch
      } else {
        currentToken += ch
      }
      continue
    }

    if (ch === '"' || ch === "'") {
      inString = true
      stringChar = ch
      currentToken += ch
      continue
    }

    switch (ch) {
      case '{':
        if (afterColon && currentKey) {
          path.push(currentKey)
        }
        depth++
        currentToken = ''
        isKey = true
        afterColon = false
        currentKey = null
        break

      case '}':
        if (afterColon) {
          // We were at a value position
        }
        depth--
        if (path.length > 0 && typeof path[path.length - 1] === 'string') {
          path.pop()
        }
        currentToken = ''
        isKey = false
        afterColon = false
        currentKey = null
        break

      case '[':
        if (afterColon && currentKey) {
          path.push(currentKey)
        }
        inList = true
        listCountStack.push(0)
        currentToken = ''
        isKey = false
        afterColon = false
        break

      case ']':
        inList = listCountStack.length > 1
        listCountStack.pop()
        if (path.length > 0) {
          path.pop()
        }
        currentToken = ''
        break

      case ':':
        // Key:value separator
        currentKey = currentToken.trim().replace(/^["']|["']$/g, '')
        afterColon = true
        isKey = false
        currentToken = ''
        break

      case ',':
        // Next entry
        if (inList && listCountStack.length > 0) {
          listCountStack[listCountStack.length - 1]++
        }
        afterColon = false
        currentKey = null
        isKey = !inList // In compound: next is key. In list: next is value.
        currentToken = ''
        break

      case ' ':
      case '\t':
      case '\n':
      case '\r':
        // Whitespace - don't add to token
        break

      default:
        currentToken += ch
        break
    }
  }

  partial = currentToken.trim().replace(/^["']/, '')

  return {
    path,
    isKey,
    partial,
    depth,
    inList,
    currentKey: afterColon ? currentKey : null,
  }
}

/**
 * Extract the NBT portion from a command string.
 * Returns the NBT text and the cursor offset within it.
 *
 * For example, in `/summon minecraft:zombie ~ ~ ~ {IsBa|`
 * returns { nbtText: "{IsBa", cursorInNbt: 5, nbtStart: 36 }
 */
export function extractNbtFromCommand(
  line: string,
  cursorCol: number,
): { nbtText: string; cursorInNbt: number; nbtStart: number } | null {
  // Find the last unmatched { before cursor
  let braceDepth = 0
  let nbtStart = -1

  for (let i = cursorCol - 1; i >= 0; i--) {
    const ch = line[i]
    if (ch === '}') braceDepth++
    else if (ch === '{') {
      if (braceDepth === 0) {
        nbtStart = i
        break
      }
      braceDepth--
    }
  }

  if (nbtStart === -1) return null

  const nbtText = line.substring(nbtStart, cursorCol)
  return {
    nbtText,
    cursorInNbt: cursorCol - nbtStart,
    nbtStart,
  }
}

/**
 * Try to determine the entity/item type from the command context.
 * For `/summon minecraft:zombie ~ ~ ~ {` returns "zombie"
 * For `/give @s minecraft:diamond_sword{` returns "diamond_sword" (item context)
 */
export function extractContextType(
  line: string,
  nbtStart: number,
): { type: string; context: 'entity' | 'item' | 'block' } | null {
  const before = line.substring(0, nbtStart).trim()
  const parts = before.split(/\s+/)

  const cmdName = parts[0]?.replace(/^\//, '').toLowerCase()

  if (cmdName === 'summon' && parts.length >= 2) {
    const entityId = parts[1].replace(/^minecraft:/, '')
    return { type: entityId, context: 'entity' }
  }

  if (cmdName === 'give' && parts.length >= 3) {
    const itemId = parts[2].replace(/^minecraft:/, '').replace(/\[.*$/, '')
    return { type: itemId, context: 'item' }
  }

  if (cmdName === 'data' && before.includes('block')) {
    return { type: '_common', context: 'block' }
  }

  if (cmdName === 'data' && before.includes('entity')) {
    // Try to find entity type from selector
    const selectorMatch = before.match(/@e\[.*?type=(?:minecraft:)?(\w+)/)
    if (selectorMatch) {
      return { type: selectorMatch[1], context: 'entity' }
    }
  }

  return null
}
