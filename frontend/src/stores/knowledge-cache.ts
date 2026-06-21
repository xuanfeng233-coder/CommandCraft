/**
 * Knowledge cache store — loads and caches command definitions + ID data
 * from the backend for use by the editor completion system.
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchAllCommandSyntax, fetchIdsFull, fetchIdCategories } from '@/api/knowledge'
import type { CommandSyntaxDef, IdEntry, SubcommandTree } from '@/editor/state-machine/types'
import { buildSubcommandTree } from '@/editor/state-machine/subcommand-parser'

export const useKnowledgeCache = defineStore('knowledge-cache', () => {
  const commands = ref<CommandSyntaxDef[]>([])
  const commandMap = ref<Map<string, CommandSyntaxDef>>(new Map())
  const subcommandTrees = ref<Map<string, SubcommandTree>>(new Map())

  const idData = ref<Map<string, IdEntry[]>>(new Map())
  const idCategories = ref<string[]>([])

  const loaded = ref(false)
  const loading = ref(false)
  const currentEdition = ref<string>('bedrock')

  /** Load all knowledge data from backend */
  async function load(edition = 'bedrock') {
    if (loaded.value && currentEdition.value === edition) return
    if (loading.value) return
    loading.value = true
    try {
      // Fetch commands and ID categories in parallel
      const [cmds, cats] = await Promise.all([
        fetchAllCommandSyntax(edition),
        fetchIdCategories(edition),
      ])

      commands.value = cmds
      const map = new Map<string, CommandSyntaxDef>()
      const trees = new Map<string, SubcommandTree>()
      for (const cmd of cmds) {
        map.set(cmd.name, cmd)
        // Build subcommand trees for commands that have 子命令 params
        const tree = buildSubcommandTree(cmd)
        if (tree) {
          trees.set(cmd.name, tree)
        }
      }
      commandMap.value = map
      subcommandTrees.value = trees

      idCategories.value = cats

      // Fetch all ID data in parallel
      const idResults = await Promise.all(
        cats.map(async (cat) => {
          const entries = await fetchIdsFull(cat, edition)
          return { cat, entries }
        })
      )
      const idMap = new Map<string, IdEntry[]>()
      for (const { cat, entries } of idResults) {
        idMap.set(cat, entries)
      }
      idData.value = idMap

      currentEdition.value = edition
      loaded.value = true
    } catch (err) {
      console.error('Failed to load knowledge cache:', err)
    } finally {
      loading.value = false
    }
  }

  /** Reload with a different edition (clears cache first) */
  async function reload(edition: string) {
    loaded.value = false
    commands.value = []
    commandMap.value = new Map()
    subcommandTrees.value = new Map()
    idData.value = new Map()
    idCategories.value = []
    await load(edition)
  }

  /** Get a command definition by name */
  function getCommand(name: string): CommandSyntaxDef | undefined {
    return commandMap.value.get(name)
  }

  /** Get all command names */
  function getCommandNames(): string[] {
    return commands.value.map((c) => c.name)
  }

  /** Get the subcommand tree for a command, or null */
  function getSubcommandTree(name: string): SubcommandTree | null {
    return subcommandTrees.value.get(name) ?? null
  }

  /** Get IDs for a given category */
  function getIds(category: string): IdEntry[] {
    return idData.value.get(category) ?? []
  }

  /**
   * Search IDs within a category. Matches against id, name, and description (Chinese).
   * Ranking: exact match > prefix match > contains match.
   */
  function searchIds(category: string, query: string, limit = 30): IdEntry[] {
    const entries = getIds(category)
    if (!query) return entries.slice(0, limit)
    const q = query.toLowerCase()

    const exact: IdEntry[] = []
    const prefix: IdEntry[] = []
    const contains: IdEntry[] = []

    for (const entry of entries) {
      const id = entry.id.toLowerCase()
      const name = (entry.name || '').toLowerCase()
      const desc = (entry.description || '').toLowerCase()

      if (id === q || name === q || desc === q) {
        exact.push(entry)
      } else if (id.startsWith(q) || name.startsWith(q) || desc.startsWith(q)) {
        prefix.push(entry)
      } else if (id.includes(q) || name.includes(q) || desc.includes(q)) {
        contains.push(entry)
      }
    }

    const results = [...exact, ...prefix, ...contains]
    return limit > 0 ? results.slice(0, limit) : results
  }

  return {
    commands,
    commandMap,
    subcommandTrees,
    idData,
    idCategories,
    loaded,
    loading,
    currentEdition,
    load,
    reload,
    getCommand,
    getCommandNames,
    getSubcommandTree,
    getIds,
    searchIds,
  }
})
