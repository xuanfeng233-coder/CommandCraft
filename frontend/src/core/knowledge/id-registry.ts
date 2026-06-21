/**
 * ID Registry — validates entity/item/block/effect IDs against the knowledge base.
 * Port of backend/knowledge/id_registry.py for frontend use.
 */

import { knowledgeLoader } from './loader'

class IDRegistry {
  private idSets: Map<string, Set<string>> = new Map()

  async ensureLoaded(category: string): Promise<void> {
    if (this.idSets.has(category)) return
    const entries = await knowledgeLoader.getIdFile(category)
    const ids = new Set<string>()
    for (const entry of entries) {
      if (entry.id) {
        ids.add(entry.id)
      }
    }
    this.idSets.set(category, ids)
  }

  async isValidId(idValue: string, category: string): Promise<boolean> {
    await this.ensureLoaded(category)
    const ids = this.idSets.get(category)
    if (!ids || ids.size === 0) {
      return true // Skip validation if category not available
    }
    return ids.has(idValue)
  }

  async getAllIds(category: string): Promise<Set<string>> {
    await this.ensureLoaded(category)
    return this.idSets.get(category) ?? new Set()
  }

  async getAvailableCategories(): Promise<string[]> {
    return knowledgeLoader.getIdCategories()
  }

  reload(): void {
    this.idSets.clear()
  }
}

export const idRegistry = new IDRegistry()
