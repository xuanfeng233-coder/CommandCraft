/**
 * Extract JSON from LLM output text, trying multiple strategies.
 * Port of backend/skills/base.py BaseSkill.extract_json.
 */

export function extractJson(text: string): unknown | null {
  const trimmed = text.trim()

  // Strategy 1: direct JSON.parse
  try {
    return JSON.parse(trimmed)
  } catch {
    // continue
  }

  // Strategy 2: markdown code block extraction
  const mdMatch = trimmed.match(/```(?:json)?\s*\n?(.*?)```/s)
  if (mdMatch) {
    try {
      return JSON.parse(mdMatch[1].trim())
    } catch {
      // continue
    }
  }

  // Strategy 3: outermost braces/brackets with depth tracking
  const pairs: Array<[string, string]> = [
    ['{', '}'],
    ['[', ']'],
  ]

  for (const [openCh, closeCh] of pairs) {
    const start = trimmed.indexOf(openCh)
    if (start === -1) continue

    let depth = 0
    let inString = false
    let escape = false

    for (let i = start; i < trimmed.length; i++) {
      const ch = trimmed[i]

      if (escape) {
        escape = false
        continue
      }
      if (ch === '\\' && inString) {
        escape = true
        continue
      }
      if (ch === '"' && !escape) {
        inString = !inString
        continue
      }
      if (inString) continue

      if (ch === openCh) {
        depth++
      } else if (ch === closeCh) {
        depth--
        if (depth === 0) {
          try {
            return JSON.parse(trimmed.slice(start, i + 1))
          } catch {
            break
          }
        }
      }
    }
  }

  return null
}
