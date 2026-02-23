/**
 * MC Command StreamLanguage tokenizer for CodeMirror 6.
 * Line-oriented — each line is a standalone command.
 */
import { StreamLanguage, type StreamParser } from '@codemirror/language'

interface McState {
  /** Position within the line: 'start' | 'command' | 'args' */
  phase: 'start' | 'command' | 'args'
}

const mcCommandParser: StreamParser<McState> = {
  startState(): McState {
    return { phase: 'start' }
  },

  token(stream, state): string | null {
    // Blank / whitespace
    if (stream.eatSpace()) return null

    // Comment line
    if (state.phase === 'start' && stream.match(/^#.*/)) {
      return 'lineComment'
    }

    // Start of line: expect / or command name
    if (state.phase === 'start') {
      if (stream.eat('/')) {
        state.phase = 'command'
        return 'keyword'
      }
      // Bare command without /
      if (stream.match(/^[a-zA-Z_]\w*/)) {
        state.phase = 'args'
        return 'keyword'
      }
      // Fallback: skip char
      stream.next()
      return null
    }

    // Command name after /
    if (state.phase === 'command') {
      if (stream.match(/^[a-zA-Z_]\w*/)) {
        state.phase = 'args'
        return 'keyword'
      }
      stream.next()
      state.phase = 'args'
      return null
    }

    // Arguments phase
    if (state.phase === 'args') {
      // Selector: @a, @e, @p, @r, @s, @initiator with optional [...]
      if (stream.match(/^@(?:initiator|[aeprs])(?:\[[^\]]*\])?/)) {
        return 'className'
      }

      // Double-quoted string
      if (stream.peek() === '"') {
        stream.next()
        while (!stream.eol()) {
          const ch = stream.next()
          if (ch === '"') break
          if (ch === '\\') stream.next() // skip escaped char
        }
        return 'string'
      }

      // Relative/local coordinates: ~N, ^N, ~, ^
      if (stream.match(/^[~^]-?\d*\.?\d*/)) {
        return 'atom'
      }

      // Number (int or float, possibly negative)
      if (stream.match(/^-?\d+\.?\d*/)) {
        return 'number'
      }

      // Execute sub-commands and boolean keywords
      if (stream.match(/^(?:as|at|positioned|if|unless|run|facing|rotated|in|align|anchored|store|true|false)\b/)) {
        return 'operator'
      }

      // JSON object/array — consume matching braces
      if (stream.peek() === '{' || stream.peek() === '[') {
        const open = stream.next()!
        const close = open === '{' ? '}' : ']'
        let depth = 1
        while (!stream.eol() && depth > 0) {
          const ch = stream.next()!
          if (ch === open) depth++
          else if (ch === close) depth--
          else if (ch === '"') {
            // skip string inside JSON
            while (!stream.eol()) {
              const sc = stream.next()
              if (sc === '"') break
              if (sc === '\\') stream.next()
            }
          }
        }
        return 'brace'
      }

      // Generic identifier / parameter value
      if (stream.match(/^[a-zA-Z_][\w:.]*/)) {
        return 'variableName'
      }

      // Operators: = .. ,
      if (stream.match(/^[=,!<>]+/)) {
        return 'punctuation'
      }

      // Anything else
      stream.next()
      return null
    }

    stream.next()
    return null
  },

  blankLine(state) {
    state.phase = 'start'
  },
}

/** CodeMirror Language for Minecraft Bedrock commands */
export const mcLanguage = StreamLanguage.define(mcCommandParser)
