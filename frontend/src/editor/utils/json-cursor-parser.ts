/**
 * JSON cursor context parser for deep completion inside JSON values.
 * Parses (potentially incomplete) JSON up to the cursor position
 * and determines what kind of completion is expected.
 */

export interface JsonCursorContext {
  /** Key path from root, e.g. ["rawtext", 0, "score"] */
  path: (string | number)[]
  /** Cursor is at a position expecting an object key */
  expectingKey: boolean
  /** Cursor is at a position expecting a value */
  expectingValue: boolean
  /** The key whose value we're filling (when expectingValue inside an object) */
  currentKey: string | null
  /** Partial text typed at cursor */
  partialInput: string
  /** Cursor is inside a string literal */
  inString: boolean
}

/**
 * Parse JSON text up to cursor position and determine context.
 * @param json The JSON string (complete or incomplete)
 * @param cursorOffset Cursor position within the JSON string (0-based)
 */
export function parseJsonCursorContext(json: string, cursorOffset: number): JsonCursorContext {
  const result: JsonCursorContext = {
    path: [],
    expectingKey: false,
    expectingValue: false,
    currentKey: null,
    partialInput: '',
    inString: false,
  }

  interface Frame {
    type: 'object' | 'array'
    key: string | null
    index: number
    afterColon: boolean
  }

  const stack: Frame[] = []
  const text = json.slice(0, cursorOffset)
  let i = 0

  while (i < text.length) {
    const ch = text[i]

    // Skip whitespace
    if (ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r') {
      i++
      continue
    }

    // Open object
    if (ch === '{') {
      stack.push({ type: 'object', key: null, index: 0, afterColon: false })
      i++
      continue
    }

    // Close object
    if (ch === '}') {
      if (stack.length > 0) stack.pop()
      i++
      continue
    }

    // Open array
    if (ch === '[') {
      stack.push({ type: 'array', key: null, index: 0, afterColon: false })
      i++
      continue
    }

    // Close array
    if (ch === ']') {
      if (stack.length > 0) stack.pop()
      i++
      continue
    }

    // Colon (key-value separator in object)
    if (ch === ':') {
      const frame = stack[stack.length - 1]
      if (frame) frame.afterColon = true
      i++
      continue
    }

    // Comma (element separator)
    if (ch === ',') {
      const frame = stack[stack.length - 1]
      if (frame) {
        frame.afterColon = false
        frame.key = null
        if (frame.type === 'array') frame.index++
      }
      i++
      continue
    }

    // String literal
    if (ch === '"') {
      const start = i
      i++ // skip opening quote
      let str = ''
      let closed = false
      while (i < text.length) {
        if (text[i] === '\\') {
          str += text[i] + (i + 1 < text.length ? text[i + 1] : '')
          i += 2
          continue
        }
        if (text[i] === '"') {
          i++ // skip closing quote
          closed = true
          break
        }
        str += text[i]
        i++
      }

      // If this is an object key (before colon)
      const frame = stack[stack.length - 1]
      if (frame && frame.type === 'object' && !frame.afterColon) {
        frame.key = str
      }

      // Check if cursor is inside this string
      if (cursorOffset > start && cursorOffset <= i) {
        if (!closed || cursorOffset < i) {
          result.inString = true
          result.partialInput = json.slice(start + 1, cursorOffset)
        }
      }
      continue
    }

    // Other values (numbers, true, false, null)
    while (i < text.length && !',}]: \t\n\r'.includes(text[i])) {
      i++
    }
  }

  // Build path from stack
  for (const frame of stack) {
    if (frame.type === 'array') {
      result.path.push(frame.index)
    } else if (frame.key !== null) {
      result.path.push(frame.key)
    }
  }

  // Determine expectation from top frame
  const topFrame = stack[stack.length - 1]
  if (topFrame) {
    if (topFrame.type === 'object') {
      if (topFrame.afterColon) {
        result.expectingValue = true
        result.currentKey = topFrame.key
      } else {
        result.expectingKey = true
      }
    } else {
      // Array: always expecting a value element
      result.expectingValue = true
    }
  }

  return result
}
