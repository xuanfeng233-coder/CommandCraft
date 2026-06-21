/**
 * Line AST — unified semantic layer for MC commands.
 *
 * Single parse per line, consumed by validation, hover, semantic highlight,
 * and inline decorations. Reuses tokenizeLine() from command-parser.ts
 * for initial tokenization, then matches tokens against CommandSyntaxDef.
 */
import { SELECTOR_PARAM_MAP, type SelectorParamDef } from '../state-machine/selector-parser'
import { TYPE_TO_CATEGORY, getFixedOptionValues } from '../constants/type-mappings'
import type { CommandSyntaxDef, CommandParamDef, SubcommandTree, SubcommandVariant } from '../state-machine/types'

// ─── Token ────────────────────────────────────────────────────────────

export type TokenType =
  | 'command' | 'selector' | 'string' | 'number' | 'coord'
  | 'json' | 'identifier' | 'keyword' | 'operator' | 'unknown'

export interface Token {
  text: string
  from: number  // absolute offset within the document
  to: number
  tokenType: TokenType
}

// ─── AST Nodes ────────────────────────────────────────────────────────

export interface ASTDiagnostic {
  from: number
  to: number
  severity: 'error' | 'warning' | 'info'
  message: string
  quickFix?: QuickFix[]
}

export interface QuickFix {
  label: string
  from: number
  to: number
  replacement: string
}

export interface SelectorParamNode {
  key: Token
  eq: Token | null        // the '=' sign
  value: Token | null
  paramDef: SelectorParamDef | null
}

export interface SelectorNode {
  base: Token             // @a, @e, etc.
  params: SelectorParamNode[]
  unclosed: boolean       // bracket not closed
  openBracket: number     // absolute position of [
  closeBracket: number    // absolute position of ] or end
}

export interface ParameterNode {
  token: Token
  paramDef: CommandParamDef | null
  expectedType: string | null
  resolvedCategory: string | null   // 'items', 'blocks', 'entities', etc.
  isValid: boolean | null           // null=not checked, true/false=checked
  selector?: SelectorNode
}

export interface ExecuteChainNode {
  variant: SubcommandVariant | null
  keywordTokens: Token[]
  paramNodes: ParameterNode[]
}

export interface CommandLine {
  kind: 'command'
  slash: Token | null
  commandName: Token
  commandDef: CommandSyntaxDef | null
  parameters: ParameterNode[]
  executeChain: ExecuteChainNode[] | null
  diagnostics: ASTDiagnostic[]
}

export interface EmptyLine {
  kind: 'empty'
  diagnostics: ASTDiagnostic[]
}

export interface CommentLine {
  kind: 'comment'
  token: Token
  diagnostics: ASTDiagnostic[]
}

export interface ErrorLine {
  kind: 'error'
  tokens: Token[]
  diagnostics: ASTDiagnostic[]
}

export type LineAST = EmptyLine | CommentLine | CommandLine | ErrorLine

// ─── AST Lookup interfaces ───────────────────────────────────────────

export interface ASTLookup {
  getCommand: (name: string) => CommandSyntaxDef | undefined
  getSubcommandTree: (name: string) => SubcommandTree | null
  getIds: (category: string) => Array<{ id: string; name?: string; description?: string; category?: string }>
  searchIds: (category: string, query: string, limit: number) => Array<{ id: string; name?: string; description?: string }>
}

// ─── Token classification ─────────────────────────────────────────────

function classifyToken(text: string): TokenType {
  if (text.startsWith('@')) return 'selector'
  if (text.startsWith('"')) return 'string'
  if (text.startsWith('{') || text.startsWith('[')) return 'json'
  if (text.startsWith('~') || text.startsWith('^')) return 'coord'
  if (/^-?\d+\.?\d*$/.test(text)) return 'number'
  return 'identifier'
}

/** Count how many tokens a parameter type consumes */
function paramTokenCount(type: string): number {
  if (type === 'x y z') return 3
  return 1
}

// ─── Tokenize with positions ──────────────────────────────────────────

export interface PositionedToken {
  text: string
  from: number  // offset within the line text
  to: number
}

/**
 * Tokenize a line and return tokens with positions within that line.
 * Uses the same logic as command-parser's tokenizeLine but tracks offsets.
 */
function tokenizeLineWithPositions(line: string): PositionedToken[] {
  const tokens: PositionedToken[] = []
  let i = 0

  while (i < line.length) {
    if (line[i] === ' ' || line[i] === '\t') { i++; continue }

    const start = i

    // Quoted string
    if (line[i] === '"') {
      i++
      while (i < line.length) {
        if (line[i] === '\\') { i += 2; continue }
        if (line[i] === '"') { i++; break }
        i++
      }
      tokens.push({ text: line.slice(start, i), from: start, to: i })
      continue
    }

    // JSON brace/bracket
    if (line[i] === '{' || line[i] === '[') {
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

    // Selector
    if (line[i] === '@' && i + 1 < line.length) {
      let end = i + 1
      if (line.slice(i, i + 10) === '@initiator') {
        end = i + 10
      } else if ('aeprs'.includes(line[end])) {
        end++
      } else {
        end = i
      }
      if (end > i + 1) {
        if (end < line.length && line[end] === '[') {
          let depth = 1
          end++
          while (end < line.length && depth > 0) {
            if (line[end] === '[') depth++
            else if (line[end] === ']') depth--
            end++
          }
        }
        tokens.push({ text: line.slice(i, end), from: i, to: end })
        i = end
        continue
      }
    }

    // Regular token
    while (i < line.length && line[i] !== ' ' && line[i] !== '\t') i++
    tokens.push({ text: line.slice(start, i), from: start, to: i })
  }

  return tokens
}

// ─── Selector parsing ─────────────────────────────────────────────────

function parseSelector(text: string, absFrom: number): SelectorNode {
  const bracketIdx = text.indexOf('[')
  let baseText: string
  let baseEnd: number

  if (bracketIdx === -1) {
    baseText = text
    baseEnd = text.length
  } else {
    baseText = text.slice(0, bracketIdx)
    baseEnd = bracketIdx
  }

  const base: Token = {
    text: baseText,
    from: absFrom,
    to: absFrom + baseEnd,
    tokenType: 'selector',
  }

  if (bracketIdx === -1) {
    return { base, params: [], unclosed: false, openBracket: -1, closeBracket: -1 }
  }

  const openBracket = absFrom + bracketIdx
  const unclosed = !text.endsWith(']')
  const closeBracket = unclosed ? absFrom + text.length : absFrom + text.length - 1

  // Parse inside brackets
  const inside = text.slice(bracketIdx + 1, unclosed ? text.length : text.length - 1)
  const params: SelectorParamNode[] = []

  // Split by commas respecting nested braces
  const parts: Array<{ text: string; from: number }> = []
  let current = ''
  let currentStart = bracketIdx + 1
  let braceDepth = 0
  let bracketDepth = 0

  for (let ci = 0; ci < inside.length; ci++) {
    const ch = inside[ci]
    if (ch === '{') braceDepth++
    else if (ch === '}') braceDepth--
    else if (ch === '[') bracketDepth++
    else if (ch === ']') bracketDepth--

    if (ch === ',' && braceDepth === 0 && bracketDepth === 0) {
      parts.push({ text: current, from: currentStart })
      current = ''
      currentStart = bracketIdx + 1 + ci + 1
    } else {
      current += ch
    }
  }
  if (current) parts.push({ text: current, from: currentStart })

  for (const part of parts) {
    const eqIdx = part.text.indexOf('=')
    if (eqIdx === -1) {
      // Partial param name (no = yet)
      const keyToken: Token = {
        text: part.text,
        from: absFrom + part.from,
        to: absFrom + part.from + part.text.length,
        tokenType: 'identifier',
      }
      params.push({
        key: keyToken,
        eq: null,
        value: null,
        paramDef: SELECTOR_PARAM_MAP.get(part.text) ?? null,
      })
    } else {
      const keyText = part.text.slice(0, eqIdx)
      const valText = part.text.slice(eqIdx + 1)
      const keyToken: Token = {
        text: keyText,
        from: absFrom + part.from,
        to: absFrom + part.from + eqIdx,
        tokenType: 'identifier',
      }
      const eqToken: Token = {
        text: '=',
        from: absFrom + part.from + eqIdx,
        to: absFrom + part.from + eqIdx + 1,
        tokenType: 'operator',
      }
      const valToken: Token = {
        text: valText,
        from: absFrom + part.from + eqIdx + 1,
        to: absFrom + part.from + part.text.length,
        tokenType: classifyToken(valText),
      }
      params.push({
        key: keyToken,
        eq: eqToken,
        value: valToken,
        paramDef: SELECTOR_PARAM_MAP.get(keyText) ?? null,
      })
    }
  }

  return { base, params, unclosed, openBracket, closeBracket }
}

// ─── Main parse function ──────────────────────────────────────────────

/**
 * Parse a single line into a LineAST node.
 * @param lineText - raw line text
 * @param lineFrom - absolute document offset of line start
 * @param lookup - knowledge base lookup functions
 */
export function parseLineAST(
  lineText: string,
  lineFrom: number,
  lookup: ASTLookup
): LineAST {
  const trimmed = lineText.trim()

  // Empty line
  if (!trimmed) {
    return { kind: 'empty', diagnostics: [] }
  }

  // Comment line
  if (trimmed.startsWith('#')) {
    const commentStart = lineText.indexOf('#')
    return {
      kind: 'comment',
      token: {
        text: trimmed,
        from: lineFrom + commentStart,
        to: lineFrom + lineText.length,
        tokenType: 'keyword',
      },
      diagnostics: [],
    }
  }

  // Tokenize
  const posTokens = tokenizeLineWithPositions(lineText)
  if (posTokens.length === 0) {
    return { kind: 'empty', diagnostics: [] }
  }

  // First token = command name (possibly with /)
  const firstToken = posTokens[0]
  let cmdText = firstToken.text
  let slash: Token | null = null

  if (cmdText.startsWith('/')) {
    slash = {
      text: '/',
      from: lineFrom + firstToken.from,
      to: lineFrom + firstToken.from + 1,
      tokenType: 'operator',
    }
    cmdText = cmdText.slice(1)
  }

  const commandNameToken: Token = {
    text: cmdText,
    from: lineFrom + firstToken.from + (slash ? 1 : 0),
    to: lineFrom + firstToken.to,
    tokenType: 'command',
  }

  const commandDef = lookup.getCommand(cmdText) ?? null
  const diagnostics: ASTDiagnostic[] = []

  // Build the command line AST
  const ast: CommandLine = {
    kind: 'command',
    slash,
    commandName: commandNameToken,
    commandDef,
    parameters: [],
    executeChain: null,
    diagnostics,
  }

  if (!commandDef) {
    // Unknown command — will be diagnosed by validation phase
    // Still produce parameter tokens for highlighting
    for (let i = 1; i < posTokens.length; i++) {
      const pt = posTokens[i]
      const tok: Token = {
        text: pt.text,
        from: lineFrom + pt.from,
        to: lineFrom + pt.to,
        tokenType: classifyToken(pt.text),
      }
      const pn: ParameterNode = {
        token: tok,
        paramDef: null,
        expectedType: null,
        resolvedCategory: null,
        isValid: null,
      }
      if (tok.tokenType === 'selector') {
        pn.selector = parseSelector(pt.text, lineFrom + pt.from)
      }
      ast.parameters.push(pn)
    }
    return ast
  }

  // Check if command has subcommand tree (execute, scoreboard, etc.)
  const subTree = lookup.getSubcommandTree(cmdText)

  if (cmdText === 'execute' && subTree) {
    ast.executeChain = parseExecuteChain(posTokens, lineFrom, subTree, lookup)
    // Flatten chain params into ast.parameters for highlights
    for (const chain of ast.executeChain) {
      ast.parameters.push(...chain.paramNodes)
    }
  } else if (subTree) {
    // Non-execute subcommand commands (scoreboard, tag, etc.)
    parseSubcommandParams(ast, posTokens, lineFrom, subTree, lookup)
  } else {
    // Flat parameter commands
    parseFlatParams(ast, posTokens, lineFrom, lookup)
  }

  return ast
}

// ─── Flat parameter parsing ───────────────────────────────────────────

function parseFlatParams(
  ast: CommandLine,
  posTokens: PositionedToken[],
  lineFrom: number,
  lookup: ASTLookup,
): void {
  const params = ast.commandDef!.parameters

  for (let i = 1; i < posTokens.length; i++) {
    const pt = posTokens[i]
    const tok: Token = {
      text: pt.text,
      from: lineFrom + pt.from,
      to: lineFrom + pt.to,
      tokenType: classifyToken(pt.text),
    }

    // Map token index to parameter definition
    const matchedParam = findParamForTokenIndex(params, i - 1)

    const category = matchedParam ? TYPE_TO_CATEGORY[matchedParam.type] ?? null : null
    let isValid: boolean | null = null

    // Validate IDs
    if (category && tok.tokenType === 'identifier') {
      const ids = lookup.getIds(category)
      const cleanText = tok.text.replace(/^minecraft:/, '')
      isValid = ids.some(e => e.id === cleanText || e.id === tok.text)
    }

    // Validate fixed options
    if (matchedParam && !category && tok.tokenType === 'identifier') {
      const fixedVals = getFixedOptionValues(matchedParam.type)
      if (fixedVals) {
        isValid = fixedVals.includes(tok.text)
      }
    }

    const pn: ParameterNode = {
      token: tok,
      paramDef: matchedParam,
      expectedType: matchedParam?.type ?? null,
      resolvedCategory: category,
      isValid,
    }

    if (tok.tokenType === 'selector') {
      pn.selector = parseSelector(pt.text, lineFrom + pt.from)
    }

    ast.parameters.push(pn)
  }
}

/** Find which CommandParamDef a flat token index maps to */
function findParamForTokenIndex(params: CommandParamDef[], tokenIdx: number): CommandParamDef | null {
  let pos = 0
  for (const p of params) {
    const tc = paramTokenCount(p.type)
    if (tokenIdx >= pos && tokenIdx < pos + tc) return p
    pos += tc
  }
  return null
}

// ─── Execute chain parsing ────────────────────────────────────────────

function parseExecuteChain(
  posTokens: PositionedToken[],
  lineFrom: number,
  subTree: SubcommandTree,
  lookup: ASTLookup,
): ExecuteChainNode[] {
  const chain: ExecuteChainNode[] = []
  let pos = 1 // skip command name token

  while (pos < posTokens.length) {
    const kwToken = posTokens[pos]
    const kwText = kwToken.text

    // Look up subcommand variant
    const candidates = subTree.byFirstKeyword.get(kwText)
    if (!candidates || candidates.length === 0) {
      // Not a recognized subcommand keyword — treat rest as params
      const node: ExecuteChainNode = {
        variant: null,
        keywordTokens: [{
          text: kwText,
          from: lineFrom + kwToken.from,
          to: lineFrom + kwToken.to,
          tokenType: 'keyword',
        }],
        paramNodes: [],
      }
      chain.push(node)
      pos++
      break
    }

    // Find best variant (longest keyword match)
    const variant = findBestVariantFromTokens(candidates, posTokens, pos)
    const kwCount = variant.keywords.length
    const keywordTokens: Token[] = []

    for (let k = 0; k < kwCount && pos + k < posTokens.length; k++) {
      const kt = posTokens[pos + k]
      keywordTokens.push({
        text: kt.text,
        from: lineFrom + kt.from,
        to: lineFrom + kt.to,
        tokenType: 'keyword',
      })
    }
    pos += kwCount

    // Parse subcommand params
    const paramNodes: ParameterNode[] = []
    for (const sp of variant.params) {
      if (sp.type === 'Command') {
        // After "run": parse the rest as a nested command
        // Remaining tokens become a nested command
        const remainingTokens = posTokens.slice(pos)
        if (remainingTokens.length > 0) {
          const nestedParams = parseNestedCommandParams(remainingTokens, lineFrom, lookup)
          paramNodes.push(...nestedParams)
          pos = posTokens.length // consumed everything
        }
        break
      }

      const tc = paramTokenCount(sp.type)
      for (let t = 0; t < tc && pos < posTokens.length; t++) {
        const pt = posTokens[pos]
        const tok: Token = {
          text: pt.text,
          from: lineFrom + pt.from,
          to: lineFrom + pt.to,
          tokenType: classifyToken(pt.text),
        }

        const category = TYPE_TO_CATEGORY[sp.type] ?? null
        let isValid: boolean | null = null
        if (category && tok.tokenType === 'identifier') {
          const ids = lookup.getIds(category)
          isValid = ids.some(e => e.id === tok.text)
        }

        const pn: ParameterNode = {
          token: tok,
          paramDef: { name: sp.name, type: sp.type, required: sp.required },
          expectedType: sp.type,
          resolvedCategory: category,
          isValid,
        }
        if (tok.tokenType === 'selector') {
          pn.selector = parseSelector(pt.text, lineFrom + pt.from)
        }
        paramNodes.push(pn)
        pos++
      }
    }

    chain.push({ variant, keywordTokens, paramNodes })

    // If we hit "run", rest was consumed by nested command parsing
    if (variant.keywords[0] === 'run') break
  }

  return chain
}

function parseNestedCommandParams(
  tokens: PositionedToken[],
  lineFrom: number,
  lookup: ASTLookup,
): ParameterNode[] {
  const params: ParameterNode[] = []
  if (tokens.length === 0) return params

  // First token is the nested command name
  const cmdToken = tokens[0]
  let cmdText = cmdToken.text
  if (cmdText.startsWith('/')) cmdText = cmdText.slice(1)

  const cmdTok: Token = {
    text: cmdText,
    from: lineFrom + cmdToken.from + (cmdToken.text.startsWith('/') ? 1 : 0),
    to: lineFrom + cmdToken.to,
    tokenType: 'command',
  }
  params.push({
    token: cmdTok,
    paramDef: null,
    expectedType: 'Command',
    resolvedCategory: null,
    isValid: lookup.getCommand(cmdText) ? true : null,
  })

  const nestedDef = lookup.getCommand(cmdText)
  for (let i = 1; i < tokens.length; i++) {
    const pt = tokens[i]
    const tok: Token = {
      text: pt.text,
      from: lineFrom + pt.from,
      to: lineFrom + pt.to,
      tokenType: classifyToken(pt.text),
    }

    const matchedParam = nestedDef ? findParamForTokenIndex(nestedDef.parameters, i - 1) : null
    const category = matchedParam ? TYPE_TO_CATEGORY[matchedParam.type] ?? null : null
    let isValid: boolean | null = null

    if (category && tok.tokenType === 'identifier') {
      const ids = lookup.getIds(category)
      const cleanText = tok.text.replace(/^minecraft:/, '')
      isValid = ids.some(e => e.id === cleanText || e.id === tok.text)
    }
    if (matchedParam && !category && tok.tokenType === 'identifier') {
      const fixedVals = getFixedOptionValues(matchedParam.type)
      if (fixedVals) isValid = fixedVals.includes(tok.text)
    }

    const pn: ParameterNode = {
      token: tok,
      paramDef: matchedParam,
      expectedType: matchedParam?.type ?? null,
      resolvedCategory: category,
      isValid,
    }
    if (tok.tokenType === 'selector') {
      pn.selector = parseSelector(pt.text, lineFrom + pt.from)
    }
    params.push(pn)
  }

  return params
}

// ─── Subcommand parsing (non-execute) ─────────────────────────────────

function parseSubcommandParams(
  ast: CommandLine,
  posTokens: PositionedToken[],
  lineFrom: number,
  subTree: SubcommandTree,
  lookup: ASTLookup,
): void {
  let pos = 1 // skip command name

  // Consume prefix params
  for (let pi = 0; pi < subTree.prefixParamCount && pos < posTokens.length; pi++) {
    const param = ast.commandDef!.parameters[pi]
    const tc = paramTokenCount(param.type)
    for (let t = 0; t < tc && pos < posTokens.length; t++) {
      const pt = posTokens[pos]
      const tok: Token = {
        text: pt.text,
        from: lineFrom + pt.from,
        to: lineFrom + pt.to,
        tokenType: classifyToken(pt.text),
      }
      const category = TYPE_TO_CATEGORY[param.type] ?? null
      let isValid: boolean | null = null
      if (category && tok.tokenType === 'identifier') {
        const ids = lookup.getIds(category)
        isValid = ids.some(e => e.id === tok.text)
      }
      const pn: ParameterNode = {
        token: tok,
        paramDef: param,
        expectedType: param.type,
        resolvedCategory: category,
        isValid,
      }
      if (tok.tokenType === 'selector') {
        pn.selector = parseSelector(pt.text, lineFrom + pt.from)
      }
      ast.parameters.push(pn)
      pos++
    }
  }

  if (pos >= posTokens.length) return

  // Try to match subcommand keyword
  const kwToken = posTokens[pos]
  const candidates = subTree.byFirstKeyword.get(kwToken.text)
  if (!candidates) {
    // Unknown subcommand keyword - push remaining as unknown
    for (let i = pos; i < posTokens.length; i++) {
      const pt = posTokens[i]
      ast.parameters.push({
        token: {
          text: pt.text,
          from: lineFrom + pt.from,
          to: lineFrom + pt.to,
          tokenType: classifyToken(pt.text),
        },
        paramDef: null,
        expectedType: null,
        resolvedCategory: null,
        isValid: null,
      })
    }
    return
  }

  const variant = findBestVariantFromTokens(candidates, posTokens, pos)
  const kwCount = variant.keywords.length

  // Push keyword tokens
  for (let k = 0; k < kwCount && pos < posTokens.length; k++) {
    const pt = posTokens[pos]
    ast.parameters.push({
      token: {
        text: pt.text,
        from: lineFrom + pt.from,
        to: lineFrom + pt.to,
        tokenType: 'keyword',
      },
      paramDef: null,
      expectedType: '子命令',
      resolvedCategory: null,
      isValid: true,
    })
    pos++
  }

  // Push subcommand params
  for (const sp of variant.params) {
    const tc = paramTokenCount(sp.type)
    for (let t = 0; t < tc && pos < posTokens.length; t++) {
      const pt = posTokens[pos]
      const tok: Token = {
        text: pt.text,
        from: lineFrom + pt.from,
        to: lineFrom + pt.to,
        tokenType: classifyToken(pt.text),
      }
      const category = TYPE_TO_CATEGORY[sp.type] ?? null
      let isValid: boolean | null = null
      if (category && tok.tokenType === 'identifier') {
        const ids = lookup.getIds(category)
        isValid = ids.some(e => e.id === tok.text)
      }
      if (!category && tok.tokenType === 'identifier') {
        const fixedVals = getFixedOptionValues(sp.type)
        if (fixedVals) isValid = fixedVals.includes(tok.text)
      }
      const pn: ParameterNode = {
        token: tok,
        paramDef: { name: sp.name, type: sp.type, required: sp.required },
        expectedType: sp.type,
        resolvedCategory: category,
        isValid,
      }
      if (tok.tokenType === 'selector') {
        pn.selector = parseSelector(pt.text, lineFrom + pt.from)
      }
      ast.parameters.push(pn)
      pos++
    }
  }
}

// ─── Variant matching helper ──────────────────────────────────────────

function findBestVariantFromTokens(
  candidates: SubcommandVariant[],
  tokens: PositionedToken[],
  startPos: number,
): SubcommandVariant {
  let best: SubcommandVariant = candidates[0]
  let bestLen = 0

  for (const v of candidates) {
    let matched = 0
    for (let k = 0; k < v.keywords.length; k++) {
      const idx = startPos + k
      if (idx >= tokens.length) break
      if (tokens[idx].text === v.keywords[k]) matched++
      else break
    }
    if (matched > bestLen) {
      bestLen = matched
      best = v
    }
  }

  return best
}

// ─── Utility: find AST node at position ───────────────────────────────

/**
 * Find the ParameterNode at a given absolute document position.
 * Returns null if position is on the command name or outside tokens.
 */
export function findNodeAtPosition(ast: LineAST, pos: number): ParameterNode | null {
  if (ast.kind !== 'command') return null
  for (const p of ast.parameters) {
    if (pos >= p.token.from && pos <= p.token.to) return p
  }
  return null
}

/**
 * Find the Token at a given absolute document position.
 * Checks command name, slash, and all parameter tokens.
 */
export function findTokenAtPosition(ast: LineAST, pos: number): { token: Token; node: ParameterNode | null; isCommandName: boolean } | null {
  if (ast.kind !== 'command') return null

  // Check command name
  if (pos >= ast.commandName.from && pos <= ast.commandName.to) {
    return { token: ast.commandName, node: null, isCommandName: true }
  }

  // Check parameters
  for (const p of ast.parameters) {
    if (pos >= p.token.from && pos <= p.token.to) {
      return { token: p.token, node: p, isCommandName: false }
    }
    // Check inside selector
    if (p.selector) {
      if (pos >= p.selector.base.from && pos <= p.selector.base.to) {
        return { token: p.selector.base, node: p, isCommandName: false }
      }
      for (const sp of p.selector.params) {
        if (pos >= sp.key.from && pos <= sp.key.to) {
          return { token: sp.key, node: p, isCommandName: false }
        }
        if (sp.value && pos >= sp.value.from && pos <= sp.value.to) {
          return { token: sp.value, node: p, isCommandName: false }
        }
      }
    }
  }

  return null
}
