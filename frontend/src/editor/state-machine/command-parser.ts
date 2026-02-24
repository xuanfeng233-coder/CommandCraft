/**
 * Command parser — analyzes cursor position to determine expected parameter type.
 *
 * Given a line of text and cursor column, tokenizes the command and maps
 * the cursor position to a CursorContext with expected type, partial input, etc.
 */
import type { CursorContext, CommandSyntaxDef, SubcommandTree, SubcommandVariant } from './types'
import { parseSelectorContext } from './selector-parser'

/**
 * Tokenize a command line into an array of string tokens.
 * Handles: quoted strings, selectors with brackets, JSON braces, relative coords.
 */
export function tokenizeLine(line: string): string[] {
  const tokens: string[] = []
  let i = 0

  while (i < line.length) {
    // Skip whitespace
    if (line[i] === ' ' || line[i] === '\t') {
      i++
      continue
    }

    // Quoted string
    if (line[i] === '"') {
      let end = i + 1
      while (end < line.length) {
        if (line[end] === '\\') { end += 2; continue }
        if (line[end] === '"') { end++; break }
        end++
      }
      tokens.push(line.slice(i, end))
      i = end
      continue
    }

    // JSON brace/bracket
    if (line[i] === '{' || line[i] === '[') {
      const open = line[i]
      const close = open === '{' ? '}' : ']'
      let depth = 1
      let end = i + 1
      while (end < line.length && depth > 0) {
        if (line[end] === open) depth++
        else if (line[end] === close) depth--
        else if (line[end] === '"') {
          end++
          while (end < line.length && line[end] !== '"') {
            if (line[end] === '\\') end++
            end++
          }
        }
        end++
      }
      tokens.push(line.slice(i, end))
      i = end
      continue
    }

    // Selector: @X or @X[...]
    if (line[i] === '@' && i + 1 < line.length) {
      let end = i + 1
      // Check for @initiator
      if (line.slice(i, i + 10) === '@initiator') {
        end = i + 10
      } else if ('aeprs'.includes(line[end])) {
        end++
      } else {
        // Not a valid selector start, treat as regular token
        end = i
      }

      if (end > i + 1) {
        // Check for optional [...]
        if (end < line.length && line[end] === '[') {
          let depth = 1
          end++
          while (end < line.length && depth > 0) {
            if (line[end] === '[') depth++
            else if (line[end] === ']') depth--
            end++
          }
        }
        tokens.push(line.slice(i, end))
        i = end
        continue
      }
    }

    // Regular token (until whitespace)
    let end = i
    while (end < line.length && line[end] !== ' ' && line[end] !== '\t') {
      end++
    }
    tokens.push(line.slice(i, end))
    i = end
  }

  return tokens
}

/**
 * Find which token index the cursor falls into.
 * Returns the token index, or tokens.length if cursor is past all tokens.
 */
function findCursorToken(line: string, col: number): { tokenIndex: number; partial: string } {
  const tokens = tokenizeLine(line.slice(0, col))
  // Check if cursor is right after a space (starting a new token)
  if (col > 0 && (line[col - 1] === ' ' || line[col - 1] === '\t')) {
    return { tokenIndex: tokens.length, partial: '' }
  }
  if (tokens.length === 0) {
    return { tokenIndex: 0, partial: '' }
  }
  return { tokenIndex: tokens.length - 1, partial: tokens[tokens.length - 1] }
}

/** Normalize parameter type string from JSON.
 *  Pass through as-is — no whitelist filtering. */
function normalizeParamType(type: string): string {
  return type || 'unknown'
}

/** Count how many tokens a parameter type consumes */
function paramTokenCount(type: string): number {
  if (type === 'x y z') return 3
  return 1
}

/**
 * Parse cursor context from a line + col + command lookup function.
 * Optionally accepts a subcommand tree getter for subcommand-aware parsing.
 */
export function parseCursorContext(
  line: string,
  col: number,
  getCommand: (name: string) => CommandSyntaxDef | undefined,
  getSubcommandTree?: (name: string) => SubcommandTree | null
): CursorContext {
  const defaultCtx: CursorContext = {
    commandName: null,
    commandDef: null,
    paramIndex: -1,
    expectedType: null,
    partialInput: '',
    inSelector: false,
    selectorParam: null,
    selectorValue: false,
    currentParam: null,
    subcommandVariant: null,
    subParamIndex: -1,
    currentSubParam: null,
    availableSubcommands: null,
  }

  const trimmed = line.trimStart()
  if (!trimmed) return defaultCtx

  const tokens = tokenizeLine(trimmed)
  if (tokens.length === 0) return defaultCtx

  // Extract command name (strip leading /)
  let cmdName = tokens[0]
  if (cmdName.startsWith('/')) cmdName = cmdName.slice(1)

  // If cursor is still on the first token, we're completing the command name
  const { tokenIndex, partial } = findCursorToken(trimmed, col - (line.length - trimmed.length))

  if (tokenIndex === 0) {
    const partialCmd = partial.startsWith('/') ? partial.slice(1) : partial
    return { ...defaultCtx, partialInput: partialCmd }
  }

  const cmdDef = getCommand(cmdName)
  if (!cmdDef) {
    return { ...defaultCtx, commandName: cmdName, partialInput: partial }
  }

  // Parameter index: token 0 is command name, token 1+ are parameters
  const paramIdx = tokenIndex - 1

  // Check if we're inside a selector
  if (partial.startsWith('@') && partial.includes('[') && !partial.endsWith(']')) {
    const selectorCtx = parseSelectorContext(partial)
    // Find correct param accounting for multi-token types
    let selectorParam = null
    let selectorParamIdx = paramIdx
    let fp = 0
    for (let pi = 0; pi < cmdDef.parameters.length; pi++) {
      const tc = paramTokenCount(cmdDef.parameters[pi].type)
      if (paramIdx >= fp && paramIdx < fp + tc) {
        selectorParam = cmdDef.parameters[pi]
        selectorParamIdx = pi
        break
      }
      fp += tc
    }
    return {
      commandName: cmdName,
      commandDef: cmdDef,
      paramIndex: selectorParamIdx,
      expectedType: selectorParam ? normalizeParamType(selectorParam.type) : null,
      partialInput: selectorCtx.partialInput,
      inSelector: true,
      selectorParam: selectorCtx.paramName,
      selectorValue: selectorCtx.isValue,
      currentParam: selectorParam,
      subcommandVariant: null,
      subParamIndex: -1,
      currentSubParam: null,
      availableSubcommands: null,
    }
  }

  // Try subcommand-aware parsing
  const subTree = getSubcommandTree?.(cmdName) ?? null
  if (subTree) {
    return parseSubcommandContext(
      cmdName, cmdDef, subTree, tokens, tokenIndex, partial,
      getCommand, getSubcommandTree
    )
  }

  // Flat parameter parsing (no subcommands)
  // Walk parameters accounting for multi-token types (e.g. x y z = 3 tokens)
  let flatPos = 0
  let flatParam = null
  let flatParamIdx = -1
  for (let pi = 0; pi < cmdDef.parameters.length; pi++) {
    const p = cmdDef.parameters[pi]
    const tc = paramTokenCount(p.type)
    if (paramIdx >= flatPos && paramIdx < flatPos + tc) {
      flatParam = p
      flatParamIdx = pi
      break
    }
    flatPos += tc
  }
  const expectedType = flatParam ? normalizeParamType(flatParam.type) : null

  return {
    commandName: cmdName,
    commandDef: cmdDef,
    paramIndex: flatParamIdx >= 0 ? flatParamIdx : paramIdx,
    expectedType,
    partialInput: partial,
    inSelector: false,
    selectorParam: null,
    selectorValue: false,
    currentParam: flatParam,
    subcommandVariant: null,
    subParamIndex: -1,
    currentSubParam: null,
    availableSubcommands: null,
  }
}

/**
 * Parse subcommand-aware cursor context.
 * Handles prefix params, keyword matching, sub-param consumption,
 * execute's chainable subcommands, and nested command parsing after "run".
 */
function parseSubcommandContext(
  cmdName: string,
  cmdDef: CommandSyntaxDef,
  subTree: SubcommandTree,
  tokens: string[],
  cursorTokenIdx: number,
  partial: string,
  getCommand?: (name: string) => CommandSyntaxDef | undefined,
  getSubcommandTree?: (name: string) => SubcommandTree | null,
): CursorContext {
  const base: CursorContext = {
    commandName: cmdName,
    commandDef: cmdDef,
    paramIndex: -1,
    expectedType: null,
    partialInput: partial,
    inSelector: false,
    selectorParam: null,
    selectorValue: false,
    currentParam: null,
    subcommandVariant: null,
    subParamIndex: -1,
    currentSubParam: null,
    availableSubcommands: null,
  }

  const isExecute = cmdName === 'execute'
  // Argument tokens (skip command name token)
  const argTokens = tokens.slice(1)
  const cursorArgIdx = cursorTokenIdx - 1

  // Phase 1: consume prefix params (non-subcommand params like tag's <entity>)
  let pos = 0
  for (let pi = 0; pi < subTree.prefixParamCount; pi++) {
    const param = cmdDef.parameters[pi]
    const tokCount = paramTokenCount(param.type)
    if (cursorArgIdx >= pos && cursorArgIdx < pos + tokCount) {
      // Cursor is on this prefix param
      return {
        ...base,
        paramIndex: pi,
        expectedType: normalizeParamType(param.type),
        currentParam: param,
      }
    }
    pos += tokCount
    if (pos > argTokens.length) return base
  }

  // Phase 2: subcommand consumption loop
  // For execute, this loops to allow chaining (as @a at @s run ...)
  // For others, it runs once
  let matchedVariant: SubcommandVariant | null = null
  let commandParamArgIdx: number | null = null

  // eslint-disable-next-line no-constant-condition
  while (true) {
    // At the start of a subcommand — cursor might be on the keyword position
    if (pos === cursorArgIdx) {
      // Cursor is at keyword position — return available subcommands for completion
      const allVariants = getAllVariants(subTree)
      return {
        ...base,
        paramIndex: pos + subTree.prefixParamCount,
        expectedType: '子命令',
        availableSubcommands: allVariants,
      }
    }

    if (pos >= argTokens.length) return base

    // Try to match keyword(s) to find which variant
    const currentToken = argTokens[pos]
    const candidates = subTree.byFirstKeyword.get(currentToken)
    if (!candidates || candidates.length === 0) {
      // No matching subcommand keyword — cursor might be on partial keyword
      if (pos === cursorArgIdx) {
        return {
          ...base,
          paramIndex: pos + subTree.prefixParamCount,
          expectedType: '子命令',
          availableSubcommands: getAllVariants(subTree),
        }
      }
      return base
    }

    // Disambiguate multi-keyword variants (e.g. "if block" vs "if entity")
    // Use longest-match: consume as many keyword tokens as possible
    matchedVariant = findBestVariant(candidates, argTokens, pos)
    if (!matchedVariant) {
      matchedVariant = candidates[0]
    }

    const kwCount = matchedVariant.keywords.length
    pos += kwCount

    // Check if cursor is on one of the keyword tokens (2nd+ keyword)
    if (cursorArgIdx > pos - kwCount && cursorArgIdx < pos) {
      // Cursor is on a disambiguating keyword — show filtered subcommands
      const partialKeywords = argTokens.slice(pos - kwCount, cursorArgIdx + 1)
      const filtered = candidates.filter((v) => {
        for (let k = 0; k < partialKeywords.length; k++) {
          if (k >= v.keywords.length) return false
          if (k === partialKeywords.length - 1) {
            return v.keywords[k].startsWith(partialKeywords[k])
          }
          if (v.keywords[k] !== partialKeywords[k]) return false
        }
        return true
      })
      return {
        ...base,
        paramIndex: pos - kwCount + subTree.prefixParamCount,
        expectedType: '子命令',
        availableSubcommands: filtered.length > 0 ? filtered : candidates,
      }
    }

    // Consume subcommand parameters
    const subParams = matchedVariant.params
    for (let si = 0; si < subParams.length; si++) {
      const sp = subParams[si]
      const tokCount = paramTokenCount(sp.type)

      // Track Command-type param position for nested parsing
      if (sp.type === 'Command') {
        commandParamArgIdx = pos
      }

      // Check if cursor falls within this param (handles multi-token params like x y z)
      if (cursorArgIdx >= pos && cursorArgIdx < pos + tokCount) {
        // Cursor is on this sub-param
        const expType = sp.type === 'literal' ? '子命令关键词' : normalizeParamType(sp.type)
        // For Command type, signal nested command completion
        if (sp.type === 'Command') {
          return {
            ...base,
            paramIndex: pos + subTree.prefixParamCount,
            expectedType: 'Command',
            subcommandVariant: matchedVariant,
            subParamIndex: si,
            currentSubParam: sp,
          }
        }
        return {
          ...base,
          paramIndex: pos + subTree.prefixParamCount,
          expectedType: sp.options ? '子命令选项' : expType,
          subcommandVariant: matchedVariant,
          subParamIndex: si,
          currentSubParam: sp,
          availableSubcommands: sp.options
            ? sp.options.map((o) => ({ keywords: [o], params: [], description: '' }))
            : null,
        }
      }

      pos += tokCount
      if (pos > argTokens.length) {
        // Ran out of tokens mid-param
        return base
      }
    }

    // After consuming a full subcommand:
    // For execute, loop back to allow another subcommand (chain)
    if (isExecute && matchedVariant.keywords[0] !== 'run') {
      continue
    }

    // For non-execute or after "run", we're done
    break
  }

  // Handle nested command after subcommand with Command type param (e.g. execute...run)
  if (commandParamArgIdx !== null && cursorArgIdx >= pos && getCommand) {
    const rawNestedName = argTokens[commandParamArgIdx]
    if (rawNestedName) {
      const nestedName = rawNestedName.startsWith('/') ? rawNestedName.slice(1) : rawNestedName
      const nestedDef = getCommand(nestedName)
      if (nestedDef) {
        const nestedParamIdx = cursorArgIdx - commandParamArgIdx - 1

        // Check if cursor is inside a selector in nested command
        if (partial.startsWith('@') && partial.includes('[') && !partial.endsWith(']')) {
          const selectorCtx = parseSelectorContext(partial)
          const param = nestedParamIdx < nestedDef.parameters.length
            ? nestedDef.parameters[nestedParamIdx] : null
          return {
            commandName: nestedName,
            commandDef: nestedDef,
            paramIndex: nestedParamIdx,
            expectedType: param ? normalizeParamType(param.type) : null,
            partialInput: selectorCtx.partialInput,
            inSelector: true,
            selectorParam: selectorCtx.paramName,
            selectorValue: selectorCtx.isValue,
            currentParam: param,
            subcommandVariant: null,
            subParamIndex: -1,
            currentSubParam: null,
            availableSubcommands: null,
          }
        }

        // Check subcommand tree for nested command (e.g. nested execute)
        const nestedSubTree = getSubcommandTree?.(nestedName) ?? null
        if (nestedSubTree) {
          const nestedTokens = argTokens.slice(commandParamArgIdx)
          const nestedCursorTokenIdx = cursorArgIdx - commandParamArgIdx
          return parseSubcommandContext(
            nestedName, nestedDef, nestedSubTree,
            nestedTokens, nestedCursorTokenIdx, partial,
            getCommand, getSubcommandTree
          )
        }

        // Flat parameter parsing for nested command (multi-token aware)
        let nfPos = 0
        let nfParam = null
        let nfIdx = nestedParamIdx
        for (let npi = 0; npi < nestedDef.parameters.length; npi++) {
          const np = nestedDef.parameters[npi]
          const ntc = paramTokenCount(np.type)
          if (nestedParamIdx >= nfPos && nestedParamIdx < nfPos + ntc) {
            nfParam = np
            nfIdx = npi
            break
          }
          nfPos += ntc
        }
        return {
          commandName: nestedName,
          commandDef: nestedDef,
          paramIndex: nfIdx,
          expectedType: nfParam ? normalizeParamType(nfParam.type) : null,
          partialInput: partial,
          inSelector: false,
          selectorParam: null,
          selectorValue: false,
          currentParam: nfParam,
          subcommandVariant: null,
          subParamIndex: -1,
          currentSubParam: null,
          availableSubcommands: null,
        }
      }
    }
  }

  // Past all subcommands — cursor is beyond known params
  if (pos === cursorArgIdx && matchedVariant) {
    return {
      ...base,
      paramIndex: pos + subTree.prefixParamCount,
      subcommandVariant: matchedVariant,
    }
  }

  return base
}

/** Get all variants from the tree as a flat list */
function getAllVariants(tree: SubcommandTree): SubcommandVariant[] {
  const all: SubcommandVariant[] = []
  for (const variants of tree.byFirstKeyword.values()) {
    all.push(...variants)
  }
  return all
}

/**
 * Find the best matching variant using longest keyword prefix match.
 * E.g. for tokens ["if", "block", "~", ...], "if block" beats "if entity".
 */
function findBestVariant(
  candidates: SubcommandVariant[],
  argTokens: string[],
  startPos: number,
): SubcommandVariant | null {
  let best: SubcommandVariant | null = null
  let bestLen = 0

  for (const v of candidates) {
    let matched = 0
    for (let k = 0; k < v.keywords.length; k++) {
      const tokenIdx = startPos + k
      if (tokenIdx >= argTokens.length) break
      if (argTokens[tokenIdx] === v.keywords[k]) {
        matched++
      } else {
        break
      }
    }
    if (matched > bestLen) {
      bestLen = matched
      best = v
    }
  }

  return best
}
