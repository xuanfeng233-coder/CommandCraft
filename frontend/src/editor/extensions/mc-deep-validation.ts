/**
 * Deep semantic validation (linter) for MC commands.
 *
 * Replaces the shallow mc-validation.ts with AST-driven diagnostics.
 * Reads LineAST from the AST cache for each line and produces
 * CM6 Diagnostics with Quick Fix actions.
 */
import { linter, type Diagnostic } from '@codemirror/lint'
import type { EditorView } from '@codemirror/view'
import { astCacheField } from '../ast/mc-ast-cache'
import type { CommandLine, ParameterNode, SelectorNode } from '../ast/mc-ast'
import { getFixedOptionValues } from '../constants/type-mappings'
import { SELECTOR_PARAM_MAP, SELECTOR_PARAM_DEFS } from '../state-machine/selector-parser'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import type { CommandParamDef } from '../state-machine/types'

// ─── Levenshtein distance ─────────────────────────────────────────────

function levenshtein(a: string, b: string): number {
  const la = a.length
  const lb = b.length
  if (la === 0) return lb
  if (lb === 0) return la

  // Optimization: if length difference > maxDist commonly used (3), skip
  if (Math.abs(la - lb) > 5) return Math.abs(la - lb)

  const matrix: number[][] = []
  for (let i = 0; i <= la; i++) {
    matrix[i] = [i]
    for (let j = 1; j <= lb; j++) {
      matrix[i][j] = i === 0
        ? j
        : Math.min(
            matrix[i - 1][j] + 1,
            matrix[i][j - 1] + 1,
            matrix[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
          )
    }
  }
  return matrix[la][lb]
}

/**
 * Find the closest match from a list of candidates.
 * Uses prefix pre-filtering for performance on large lists.
 */
function findClosestMatch(
  target: string,
  candidates: string[],
  maxDist = 3,
): string | null {
  if (candidates.length === 0 || !target) return null

  const lower = target.toLowerCase()

  // Phase 1: prefix filter — candidates sharing first 1-2 chars
  const prefixCandidates = candidates.filter(c => {
    const cl = c.toLowerCase()
    return cl[0] === lower[0] || cl.startsWith(lower.slice(0, 2)) || lower.startsWith(cl.slice(0, 2))
  })

  // If prefix filter is too restrictive, fall back to full list but cap size
  const searchSet = prefixCandidates.length > 0 ? prefixCandidates : candidates.slice(0, 200)

  let best: string | null = null
  let bestDist = maxDist + 1

  for (const c of searchSet) {
    const d = levenshtein(lower, c.toLowerCase())
    if (d < bestDist) {
      bestDist = d
      best = c
    }
    if (d === 0) return c // exact match
  }

  return bestDist <= maxDist ? best : null
}

// ─── Coordinate mixing check ─────────────────────────────────────────

type CoordType = 'relative' | 'local' | 'absolute'

function classifyCoord(text: string): CoordType {
  if (text.startsWith('~')) return 'relative'
  if (text.startsWith('^')) return 'local'
  return 'absolute'
}

// ─── Execute chain validation ─────────────────────────────────────────

function validateExecuteChain(ast: CommandLine, diagnostics: Diagnostic[]): void {
  if (!ast.executeChain || ast.executeChain.length === 0) return

  const lastChain = ast.executeChain[ast.executeChain.length - 1]

  // Check if there's a "run" subcommand
  const hasRun = ast.executeChain.some(c => c.variant?.keywords[0] === 'run')

  if (!hasRun) {
    // Warning: execute chain without run
    const lastToken = lastChain.keywordTokens[lastChain.keywordTokens.length - 1]
      ?? lastChain.paramNodes[lastChain.paramNodes.length - 1]?.token
    if (lastToken) {
      diagnostics.push({
        from: ast.commandName.from,
        to: lastToken.to,
        severity: 'warning',
        message: 'execute 链缺少 run 子命令',
        actions: [{
          name: '在末尾插入 run',
          apply(view, _from, to) {
            view.dispatch({ changes: { from: to, insert: ' run ' } })
          },
        }],
      })
    }
  } else {
    // Check if "run" has a command after it
    const runChain = ast.executeChain.find(c => c.variant?.keywords[0] === 'run')
    if (runChain && runChain.paramNodes.length === 0) {
      const runKw = runChain.keywordTokens[0]
      diagnostics.push({
        from: runKw.from,
        to: runKw.to,
        severity: 'warning',
        message: 'run 后面缺少要执行的命令',
      })
    }
  }
}

// ─── Selector validation ──────────────────────────────────────────────

function validateSelector(selector: SelectorNode, diagnostics: Diagnostic[]): void {
  // Unclosed bracket
  if (selector.unclosed) {
    diagnostics.push({
      from: selector.openBracket,
      to: selector.closeBracket,
      severity: 'error',
      message: '选择器参数括号未闭合',
      actions: [{
        name: '添加 ]',
        apply(view) {
          view.dispatch({ changes: { from: selector.closeBracket, insert: ']' } })
        },
      }],
    })
  }

  const seenParams = new Map<string, number>()

  for (const param of selector.params) {
    const keyText = param.key.text.replace(/^!/, '')

    // Unknown selector parameter
    if (keyText && !SELECTOR_PARAM_MAP.has(keyText)) {
      const closest = findClosestMatch(
        keyText,
        SELECTOR_PARAM_DEFS.map(d => d.name),
        2,
      )
      diagnostics.push({
        from: param.key.from,
        to: param.key.to,
        severity: 'error',
        message: `未知选择器参数: ${keyText}` + (closest ? `，你是不是想用 \`${closest}\`？` : ''),
        actions: closest ? [{
          name: `替换为 ${closest}`,
          apply(view) {
            const negated = param.key.text.startsWith('!') ? '!' : ''
            view.dispatch({ changes: { from: param.key.from, to: param.key.to, insert: negated + closest } })
          },
        }] : undefined,
      })
      continue
    }

    // Duplicate parameter check (some params like tag can repeat)
    const repeatableParams = new Set(['tag', 'scores', 'hasitem', 'haspermission', 'has_property', 'family', 'type', 'name'])
    if (!repeatableParams.has(keyText)) {
      const prev = seenParams.get(keyText)
      if (prev !== undefined) {
        diagnostics.push({
          from: param.key.from,
          to: param.key.to,
          severity: 'warning',
          message: `重复的选择器参数: ${keyText}`,
        })
      }
    }
    seenParams.set(keyText, (seenParams.get(keyText) ?? 0) + 1)

    // Validate parameter value type
    if (param.value && param.paramDef && param.value.text) {
      const valText = param.value.text.replace(/^!/, '')
      const vt = param.paramDef.valueType

      if (vt === 'int' && valText && !/^-?\d+$/.test(valText)) {
        diagnostics.push({
          from: param.value.from,
          to: param.value.to,
          severity: 'warning',
          message: `\`${keyText}\` 期望整数值，当前: ${valText}`,
        })
      }
      if (vt === 'float' && valText && !/^-?\d+\.?\d*$/.test(valText)) {
        diagnostics.push({
          from: param.value.from,
          to: param.value.to,
          severity: 'warning',
          message: `\`${keyText}\` 期望数值，当前: ${valText}`,
        })
      }
      if (vt === 'gamemode' && valText) {
        const gamemodes = ['survival', 'creative', 'adventure', 'spectator', 's', 'c', 'a', 'sp',
          '0', '1', '2', '6']
        if (!gamemodes.includes(valText)) {
          diagnostics.push({
            from: param.value.from,
            to: param.value.to,
            severity: 'warning',
            message: `无效的游戏模式: ${valText}`,
          })
        }
      }
    }
  }
}

// ─── Main lint function ───────────────────────────────────────────────

function mcDeepLint(view: EditorView): Diagnostic[] {
  const cache = useKnowledgeCache()
  if (!cache.loaded) return []

  const diagnostics: Diagnostic[] = []
  const astMap = view.state.field(astCacheField, false)

  // If AST cache is not available yet, return empty
  if (!astMap || astMap.size === 0) return []

  const commandNames = cache.getCommandNames()

  for (const [_lineNum, ast] of astMap) {
    if (ast.kind !== 'command') continue

    const cmdAST = ast as CommandLine

    // ─── Rule: Unknown command ──────────────────────────────

    if (!cmdAST.commandDef) {
      const cmdText = cmdAST.commandName.text
      const closest = findClosestMatch(cmdText, commandNames, 3)

      // Check if it's a Java Edition command
      const javaOnlyCommands = new Set([
        'data', 'datapack', 'bossbar', 'forceload', 'advancement',
        'attribute', 'debug', 'item', 'jfr', 'perf', 'publish',
        'recipe', 'seed', 'spectate', 'team', 'trigger', 'worldborder',
      ])
      const isJavaOnly = javaOnlyCommands.has(cmdText)

      const msg = isJavaOnly
        ? `\`${cmdText}\` 是 Java 版专属命令，基岩版不支持`
        : `未知命令: ${cmdText}` + (closest ? `，你是不是想用 \`${closest}\`？` : '')

      diagnostics.push({
        from: cmdAST.commandName.from,
        to: cmdAST.commandName.to,
        severity: 'error',
        message: msg,
        actions: closest ? [{
          name: `替换为 ${closest}`,
          apply(v: EditorView) {
            v.dispatch({
              changes: { from: cmdAST.commandName.from, to: cmdAST.commandName.to, insert: closest }
            })
          },
        }] : undefined,
      })
      continue
    }

    // ─── Rule: Required parameter count ─────────────────────

    const params = cmdAST.commandDef.parameters
    const requiredParams = params.filter(p => p.required && p.type !== '子命令')
    const providedCount = cmdAST.parameters.length

    // Count required tokens (accounting for multi-token params)
    let requiredTokens = 0
    for (const p of requiredParams) {
      requiredTokens += p.type === 'x y z' ? 3 : 1
    }

    if (providedCount < requiredTokens) {
      // Find which params are missing
      const missingNames = getMissingParamNames(params, providedCount)
      const missingMsg = missingNames.length > 0
        ? `缺少必填参数: ${missingNames.join(', ')}`
        : `${cmdAST.commandName.text} 需要至少 ${requiredTokens} 个参数，当前提供了 ${providedCount} 个`

      diagnostics.push({
        from: cmdAST.commandName.from,
        to: cmdAST.parameters.length > 0
          ? cmdAST.parameters[cmdAST.parameters.length - 1].token.to
          : cmdAST.commandName.to,
        severity: 'warning',
        message: missingMsg,
      })
    }

    // ─── Rule: Too many parameters ──────────────────────────

    const totalTokenCapacity = getTotalTokenCapacity(params)
    if (providedCount > totalTokenCapacity && totalTokenCapacity > 0 && !hasSubcommand(params)) {
      diagnostics.push({
        from: cmdAST.parameters[totalTokenCapacity].token.from,
        to: cmdAST.parameters[cmdAST.parameters.length - 1].token.to,
        severity: 'warning',
        message: `参数过多: ${cmdAST.commandName.text} 最多接受 ${totalTokenCapacity} 个参数`,
      })
    }

    // ─── Per-parameter validation ───────────────────────────

    for (const pn of cmdAST.parameters) {
      validateParameterNode(pn, cmdAST, diagnostics, cache)
    }

    // ─── Execute chain validation ───────────────────────────

    if (cmdAST.executeChain) {
      validateExecuteChain(cmdAST, diagnostics)
    }

    // ─── Coordinate mixing validation ───────────────────────

    validateCoordinateMixing(cmdAST, diagnostics)
  }

  return diagnostics
}

// ─── Per-parameter validation ─────────────────────────────────────────

function validateParameterNode(
  pn: ParameterNode,
  _ast: CommandLine,
  diagnostics: Diagnostic[],
  cache: ReturnType<typeof useKnowledgeCache>,
): void {
  const { token, paramDef, expectedType, resolvedCategory, isValid } = pn

  // Skip keyword tokens, selectors (handled separately), JSON, strings
  if (token.tokenType === 'keyword' && expectedType === '子命令') return
  if (token.tokenType === 'json') return
  if (token.tokenType === 'string') return
  if (token.tokenType === 'coord') return

  // Validate selectors
  if (pn.selector) {
    validateSelector(pn.selector, diagnostics)
    return
  }

  if (token.tokenType === 'selector') return

  // ─── Rule: minecraft: namespace prefix ──────────────────

  if (resolvedCategory && token.text.startsWith('minecraft:')) {
    const cleanId = token.text.replace(/^minecraft:/, '')
    diagnostics.push({
      from: token.from,
      to: token.to,
      severity: 'warning',
      message: '基岩版不使用 minecraft: 命名空间前缀',
      actions: [{
        name: '移除 minecraft: 前缀',
        apply(view) {
          view.dispatch({ changes: { from: token.from, to: token.to, insert: cleanId } })
        },
      }],
    })
    return
  }

  // ─── Rule: Invalid ID with fuzzy suggestion ─────────────

  if (resolvedCategory && isValid === false && token.tokenType === 'identifier') {
    const allIds = cache.getIds(resolvedCategory).map(e => e.id)
    const closest = findClosestMatch(token.text, allIds, 3)

    diagnostics.push({
      from: token.from,
      to: token.to,
      severity: 'warning',
      message: `未知 ${expectedType} ID: ${token.text}` +
        (closest ? `，你是不是想用 \`${closest}\`？` : ''),
      actions: closest ? [{
        name: `替换为 ${closest}`,
        apply(view) {
          view.dispatch({ changes: { from: token.from, to: token.to, insert: closest } })
        },
      }] : undefined,
    })
    return
  }

  // ─── Rule: Invalid fixed option ─────────────────────────

  if (paramDef && !resolvedCategory && token.tokenType === 'identifier') {
    const fixedVals = getFixedOptionValues(paramDef.type)
    if (fixedVals && !fixedVals.includes(token.text) && token.text.length > 0) {
      // Don't warn for target type (selectors handled above)
      if (paramDef.type === 'target') return

      const closest = findClosestMatch(token.text, fixedVals, 2)
      diagnostics.push({
        from: token.from,
        to: token.to,
        severity: 'warning',
        message: `无效的 ${paramDef.type} 值: ${token.text}` +
          (closest ? `，你是不是想用 \`${closest}\`？` : ''),
        actions: closest ? [{
          name: `替换为 ${closest}`,
          apply(view) {
            view.dispatch({ changes: { from: token.from, to: token.to, insert: closest } })
          },
        }] : undefined,
      })
      return
    }
  }

  // ─── Rule: Type mismatch (int, float) ───────────────────

  if (paramDef && token.tokenType === 'identifier') {
    const type = paramDef.type
    if (type === 'int' && token.text.length > 0) {
      if (/^-?\d+\.\d+$/.test(token.text)) {
        // Float where int expected
        const intVal = Math.trunc(parseFloat(token.text)).toString()
        diagnostics.push({
          from: token.from,
          to: token.to,
          severity: 'warning',
          message: `期望整数，当前为浮点数: ${token.text}`,
          actions: [{
            name: `截断为 ${intVal}`,
            apply(view) {
              view.dispatch({ changes: { from: token.from, to: token.to, insert: intVal } })
            },
          }],
        })
      } else if (!/^-?\d+$/.test(token.text) && !token.text.startsWith('@')) {
        diagnostics.push({
          from: token.from,
          to: token.to,
          severity: 'error',
          message: `期望整数类型，当前: ${token.text}`,
        })
      }
    }

    if (type === 'float' && token.text.length > 0) {
      if (!/^-?\d+\.?\d*$/.test(token.text) && !token.text.startsWith('@')) {
        diagnostics.push({
          from: token.from,
          to: token.to,
          severity: 'error',
          message: `期望数值类型，当前: ${token.text}`,
        })
      }
    }
  }

  // ─── Rule: Number in range ──────────────────────────────

  if (paramDef?.range && token.tokenType === 'number') {
    const numVal = parseFloat(token.text)
    const rangeMatch = paramDef.range.match(/^(-?\d+)-(-?\d+)$/)
    if (rangeMatch && !isNaN(numVal)) {
      const min = parseInt(rangeMatch[1])
      const max = parseInt(rangeMatch[2])
      if (numVal < min || numVal > max) {
        const clamped = Math.max(min, Math.min(max, Math.round(numVal))).toString()
        diagnostics.push({
          from: token.from,
          to: token.to,
          severity: 'warning',
          message: `数值 ${token.text} 超出范围 ${paramDef.range}`,
          actions: [{
            name: `限制为 ${clamped}`,
            apply(view) {
              view.dispatch({ changes: { from: token.from, to: token.to, insert: clamped } })
            },
          }],
        })
      }
    }
  }
}

// ─── Coordinate mixing validation ─────────────────────────────────────

function validateCoordinateMixing(ast: CommandLine, diagnostics: Diagnostic[]): void {
  // Find groups of 3 consecutive coordinate tokens
  const params = ast.parameters

  for (let i = 0; i <= params.length - 3; i++) {
    const p1 = params[i]
    const p2 = params[i + 1]
    const p3 = params[i + 2]

    // Only check if all three are coordinate type or the param expects x y z
    const isCoordGroup =
      (p1.expectedType === 'x y z') ||
      (p1.token.tokenType === 'coord' && p2.token.tokenType === 'coord' && p3.token.tokenType === 'coord') ||
      (p1.token.tokenType === 'coord' && p2.token.tokenType === 'coord' && p3.token.tokenType === 'number') ||
      (p1.token.tokenType === 'coord' && p2.token.tokenType === 'number' && p3.token.tokenType === 'coord') ||
      (p1.token.tokenType === 'number' && p2.token.tokenType === 'coord' && p3.token.tokenType === 'coord')

    if (!isCoordGroup) continue

    const types = new Set<CoordType>()
    for (const p of [p1, p2, p3]) {
      if (p.token.text.startsWith('~') || p.token.text.startsWith('^')) {
        types.add(classifyCoord(p.token.text))
      }
    }

    if (types.has('relative') && types.has('local')) {
      diagnostics.push({
        from: p1.token.from,
        to: p3.token.to,
        severity: 'error',
        message: '不能混用相对坐标(~)和局部坐标(^)',
        actions: [
          {
            name: '统一为相对坐标(~)',
            apply(view) {
              const changes: Array<{ from: number; to: number; insert: string }> = []
              for (const p of [p1, p2, p3]) {
                if (p.token.text.startsWith('^')) {
                  const num = p.token.text.slice(1)
                  changes.push({ from: p.token.from, to: p.token.to, insert: '~' + num })
                }
              }
              view.dispatch({ changes })
            },
          },
          {
            name: '统一为局部坐标(^)',
            apply(view) {
              const changes: Array<{ from: number; to: number; insert: string }> = []
              for (const p of [p1, p2, p3]) {
                if (p.token.text.startsWith('~')) {
                  const num = p.token.text.slice(1)
                  changes.push({ from: p.token.from, to: p.token.to, insert: '^' + num })
                }
              }
              view.dispatch({ changes })
            },
          },
        ],
      })

      // Skip to next group after this coordinate set
      i += 2
    }
  }
}

// ─── Helper functions ─────────────────────────────────────────────────

/** Get names of missing required parameters */
function getMissingParamNames(params: CommandParamDef[], providedCount: number): string[] {
  const names: string[] = []
  let pos = 0
  for (const p of params) {
    const tc = p.type === 'x y z' ? 3 : 1
    if (p.required && p.type !== '子命令' && pos >= providedCount) {
      names.push(p.name)
    }
    pos += tc
  }
  return names
}

/** Get total token capacity for a command's parameters */
function getTotalTokenCapacity(params: CommandParamDef[]): number {
  let total = 0
  for (const p of params) {
    if (p.type === '子命令') return 0 // can't predict subcommand length
    total += p.type === 'x y z' ? 3 : 1
  }
  return total
}

/** Check if params include subcommand type */
function hasSubcommand(params: CommandParamDef[]): boolean {
  return params.some(p => p.type === '子命令')
}

// ─── Export ───────────────────────────────────────────────────────────

/** Deep validation linter extension (replaces mcValidation) */
export function mcDeepValidation() {
  return linter(mcDeepLint, { delay: 400 })
}
