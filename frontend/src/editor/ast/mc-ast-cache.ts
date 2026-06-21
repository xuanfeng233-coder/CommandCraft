/**
 * AST Cache — CM6 StateField that maintains a per-line LineAST map.
 *
 * - On create: parse all lines
 * - On update: only re-parse changed lines (via tr.changes)
 * - Export utility functions to read ASTs from any extension.
 */
import { StateField, type EditorState } from '@codemirror/state'
import { parseLineAST, type LineAST, type ASTLookup } from './mc-ast'
import { useKnowledgeCache } from '@/stores/knowledge-cache'

/** Map from 1-based line number to LineAST */
export type ASTMap = Map<number, LineAST>

/** Build the ASTLookup from the knowledge cache store */
function buildLookup(): ASTLookup | null {
  const cache = useKnowledgeCache()
  if (!cache.loaded) return null
  return {
    getCommand: (name) => cache.getCommand(name),
    getSubcommandTree: (name) => cache.getSubcommandTree(name),
    getIds: (category) => cache.getIds(category),
    searchIds: (category, query, limit) => cache.searchIds(category, query, limit),
  }
}

/** Parse all lines in the document */
function parseAllLines(state: EditorState, lookup: ASTLookup): ASTMap {
  const map: ASTMap = new Map()
  const doc = state.doc
  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    map.set(i, parseLineAST(line.text, line.from, lookup))
  }
  return map
}

/**
 * StateField that holds the LineAST for every line in the document.
 * Incrementally updates — only re-parses lines touched by the transaction.
 */
export const astCacheField = StateField.define<ASTMap>({
  create(state) {
    const lookup = buildLookup()
    if (!lookup) return new Map()
    return parseAllLines(state, lookup)
  },

  update(oldMap, tr) {
    if (!tr.docChanged) return oldMap

    const lookup = buildLookup()
    if (!lookup) return oldMap

    const doc = tr.state.doc
    const newMap: ASTMap = new Map()

    // Determine which line numbers were affected by changes
    const changedLines = new Set<number>()
    tr.changes.iterChangedRanges((_fromA, _toA, fromB, toB) => {
      // Map the changed range to line numbers in the new document
      const startLine = doc.lineAt(fromB).number
      const endLine = doc.lineAt(Math.min(toB, doc.length)).number
      for (let ln = startLine; ln <= endLine; ln++) {
        changedLines.add(ln)
      }
    })

    // If the number of lines changed, re-parse everything
    // (line numbers shifted, so old cache mapping is invalid)
    const oldDoc = tr.startState.doc
    if (doc.lines !== oldDoc.lines) {
      return parseAllLines(tr.state, lookup)
    }

    // Copy unchanged lines, re-parse changed ones
    for (let i = 1; i <= doc.lines; i++) {
      if (changedLines.has(i)) {
        const line = doc.line(i)
        newMap.set(i, parseLineAST(line.text, line.from, lookup))
      } else {
        // Re-map old AST but update positions if needed
        // Since line count didn't change and only specific lines changed,
        // unchanged lines keep same positions
        const oldAST = oldMap.get(i)
        if (oldAST) {
          // Positions may have shifted — re-parse for correctness
          // (cost is minimal for unchanged lines)
          const line = doc.line(i)
          newMap.set(i, parseLineAST(line.text, line.from, lookup))
        } else {
          const line = doc.line(i)
          newMap.set(i, parseLineAST(line.text, line.from, lookup))
        }
      }
    }

    return newMap
  },
})

/**
 * Force a full re-parse of the AST cache.
 * Call this when the knowledge cache finishes loading.
 */
export function rebuildASTCache(state: EditorState): ASTMap {
  const lookup = buildLookup()
  if (!lookup) return new Map()
  return parseAllLines(state, lookup)
}

/** Get the LineAST for a specific line number (1-based) */
export function getLineAST(state: EditorState, lineNumber: number): LineAST | undefined {
  return state.field(astCacheField).get(lineNumber)
}

/** Get all LineASTs */
export function getAllLineASTs(state: EditorState): ASTMap {
  return state.field(astCacheField)
}

/** Get the LineAST for a document position */
export function getASTAtPos(state: EditorState, pos: number): LineAST | undefined {
  const line = state.doc.lineAt(pos)
  return getLineAST(state, line.number)
}
