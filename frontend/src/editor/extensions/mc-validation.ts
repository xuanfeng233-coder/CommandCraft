/**
 * Real-time MC command validation (linter) for CodeMirror 6.
 * Checks command names, ID existence, and basic syntax.
 */
import { linter, type Diagnostic } from '@codemirror/lint'
import type { EditorView } from '@codemirror/view'
import { TYPE_TO_CATEGORY, getFixedOptionValues } from '../constants/type-mappings'
import { useKnowledgeCache } from '@/stores/knowledge-cache'

/**
 * Simple tokenizer for validation — splits a line into tokens,
 * returning their text and position within the line.
 */
function tokenizeForValidation(
  line: string
): Array<{ text: string; from: number; to: number }> {
  const tokens: Array<{ text: string; from: number; to: number }> = []
  let i = 0

  while (i < line.length) {
    if (line[i] === ' ' || line[i] === '\t') {
      i++
      continue
    }

    // Quoted string — skip as single token
    if (line[i] === '"') {
      const start = i
      i++
      while (i < line.length) {
        if (line[i] === '\\') { i += 2; continue }
        if (line[i] === '"') { i++; break }
        i++
      }
      tokens.push({ text: line.slice(start, i), from: start, to: i })
      continue
    }

    // JSON braces — skip
    if (line[i] === '{' || line[i] === '[') {
      const start = i
      const open = line[i]
      const close = open === '{' ? '}' : ']'
      let depth = 1
      i++
      while (i < line.length && depth > 0) {
        if (line[i] === open) depth++
        else if (line[i] === close) depth--
        else if (line[i] === '"') {
          i++
          while (i < line.length && line[i] !== '"') {
            if (line[i] === '\\') i++
            i++
          }
        }
        i++
      }
      tokens.push({ text: line.slice(start, i), from: start, to: i })
      continue
    }

    // Selector with brackets
    if (line[i] === '@' && i + 1 < line.length) {
      const start = i
      i++
      if (line.slice(i, i + 9) === 'initiator') {
        i += 9
      } else if ('aeprs'.includes(line[i])) {
        i++
      }
      if (i < line.length && line[i] === '[') {
        let depth = 1
        i++
        while (i < line.length && depth > 0) {
          if (line[i] === '[') depth++
          else if (line[i] === ']') depth--
          i++
        }
      }
      tokens.push({ text: line.slice(start, i), from: start, to: i })
      continue
    }

    // Regular token
    const start = i
    while (i < line.length && line[i] !== ' ' && line[i] !== '\t') {
      i++
    }
    tokens.push({ text: line.slice(start, i), from: start, to: i })
  }

  return tokens
}

/** The linter function */
function mcLint(view: EditorView): Diagnostic[] {
  const cache = useKnowledgeCache()
  if (!cache.loaded) return []

  const diagnostics: Diagnostic[] = []
  const doc = view.state.doc

  for (let lineNum = 1; lineNum <= doc.lines; lineNum++) {
    const line = doc.line(lineNum)
    const text = line.text.trim()

    // Skip empty lines and comments
    if (!text || text.startsWith('#')) continue

    const tokens = tokenizeForValidation(text)
    if (tokens.length === 0) continue

    // Token 0: command name
    const cmdToken = tokens[0]
    let cmdName = cmdToken.text
    if (cmdName.startsWith('/')) cmdName = cmdName.slice(1)

    const cmdDef = cache.getCommand(cmdName)
    if (!cmdDef) {
      // Unknown command
      diagnostics.push({
        from: line.from + cmdToken.from,
        to: line.from + cmdToken.to,
        severity: 'error',
        message: `未知命令: ${cmdName}`,
      })
      continue
    }

    // Validate parameter IDs
    const params = cmdDef.parameters
    for (let pi = 0; pi < params.length && pi + 1 < tokens.length; pi++) {
      const param = params[pi]
      const token = tokens[pi + 1]
      const tokenText = token.text

      // Skip selectors, numbers, quoted strings, JSON, relative coords
      if (tokenText.startsWith('@')) continue
      if (tokenText.startsWith('"')) continue
      if (tokenText.startsWith('{') || tokenText.startsWith('[')) continue
      if (tokenText.startsWith('~') || tokenText.startsWith('^')) continue
      if (/^-?\d+\.?\d*$/.test(tokenText)) continue

      // Skip subcommand type params — they have their own keyword validation
      if (param.type === '子命令') continue

      // Check fixed option types
      const fixedValues = getFixedOptionValues(param.type)
      if (fixedValues) {
        if (!fixedValues.includes(tokenText) && tokenText.length > 0) {
          // Don't warn for target type since selectors are handled above
          if (param.type !== 'target') {
            diagnostics.push({
              from: line.from + token.from,
              to: line.from + token.to,
              severity: 'warning',
              message: `无效的 ${param.type} 值: ${tokenText}`,
            })
          }
        }
        continue
      }

      // Check ID types
      const category = TYPE_TO_CATEGORY[param.type]
      if (category) {
        const ids = cache.getIds(category)
        const exists = ids.some((e) => e.id === tokenText)
        if (!exists && tokenText.length > 0) {
          diagnostics.push({
            from: line.from + token.from,
            to: line.from + token.to,
            severity: 'warning',
            message: `未知 ${param.type} ID: ${tokenText}`,
          })
        }
      }
    }

    // Check required parameter count (only for non-subcommand params)
    const requiredCount = params.filter((p) => p.required && p.type !== '子命令').length
    const providedArgs = tokens.length - 1
    if (providedArgs < requiredCount) {
      diagnostics.push({
        from: line.from + cmdToken.from,
        to: line.from + line.text.length,
        severity: 'warning',
        message: `${cmdName} 需要至少 ${requiredCount} 个参数，当前提供了 ${providedArgs} 个`,
      })
    }
  }

  return diagnostics
}

/** Export the linter extension */
export function mcValidation() {
  return linter(mcLint, { delay: 500 })
}
