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

  /** Load all knowledge data from backend (called once on editor mount) */
  async function load() {
    if (loaded.value || loading.value) return
    loading.value = true
    try {
      // Fetch commands and ID categories in parallel
      const [cmds, cats] = await Promise.all([
        fetchAllCommandSyntax(),
        fetchIdCategories(),
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
          const entries = await fetchIdsFull(cat)
          return { cat, entries }
        })
      )
      const idMap = new Map<string, IdEntry[]>()
      for (const { cat, entries } of idResults) {
        idMap.set(cat, entries)
      }
      idData.value = idMap

      loaded.value = true
    } catch (err) {
      console.error('Failed to load knowledge cache:', err)
    } finally {
      loading.value = false
    }
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

  /** Search IDs by prefix within a category */
  function searchIds(category: string, prefix: string, limit = 30): IdEntry[] {
    const entries = getIds(category)
    if (!prefix) return entries.slice(0, limit)
    const lower = prefix.toLowerCase()
    const results: IdEntry[] = []
    for (const entry of entries) {
      if (entry.id.toLowerCase().startsWith(lower)) {
        results.push(entry)
        if (results.length >= limit) break
      }
    }
    return results
  }

  return {
    commands,
    commandMap,
    subcommandTrees,
    idData,
    idCategories,
    loaded,
    loading,
    load,
    getCommand,
    getCommandNames,
    getSubcommandTree,
    getIds,
    searchIds,
  }
})
