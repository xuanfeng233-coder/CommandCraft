/**
 * Knowledge base loader — fetches command docs and ID files via HTTP.
 * Port of backend/knowledge/loader.py for frontend use.
 */

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const resp = await fetch(url)
    if (!resp.ok) return null
    return (await resp.json()) as T
  } catch {
    return null
  }
}

interface CommandIndexEntry {
  name: string
  description: string
  category?: string
  common_use_cases?: string[]
}

interface CommandParam {
  name: string
  required?: boolean
  type?: string
  range?: string
  default?: string
}

interface CommandExample {
  input: string
  description: string
}

interface CommandDoc {
  name: string
  description?: string
  syntax?: string
  parameters?: CommandParam[]
  examples?: CommandExample[]
  bedrock_specific_notes?: string
  [key: string]: unknown
}

interface ColorEntry {
  code: string
  name: string
  hex: string
  usage: string
}

interface ModifierEntry {
  code: string
  name: string
  description: string
}

interface PatternEntry {
  name: string
  example: string
  description: string
}

interface SymbolEntry {
  symbol: string
  name: string
}

interface FormattingCodesData {
  colors?: {
    standard_16?: ColorEntry[]
    bedrock_exclusive_material?: ColorEntry[]
  }
  java_vs_bedrock_warning?: { description?: string }
  modifiers?: ModifierEntry[]
  best_practices?: string[]
  common_patterns?: PatternEntry[]
  special_symbols?: SymbolEntry[]
}

interface IdEntry {
  id: string
  [key: string]: unknown
}

class KnowledgeLoader {
  // 数据已按版本分目录（bedrock/java）；客户端命令工具默认使用基岩版数据。
  // 旧的根目录布局（/knowledge_base/ids 等）已于 2026-06-21 清理。
  private basePath = '/knowledge_base/bedrock'
  private commandIndex: CommandIndexEntry[] | null = null
  private categories: Record<string, string[]> | null = null
  private commandCache: Map<string, CommandDoc> = new Map()
  private idCache: Map<string, IdEntry[]> = new Map()
  private formattingCodes: FormattingCodesData | null = null
  private formattingPrompt: string | null = null

  // --- Command index ---

  async getCommandIndex(): Promise<CommandIndexEntry[]> {
    if (this.commandIndex === null) {
      this.commandIndex =
        (await fetchJson<CommandIndexEntry[]>(`${this.basePath}/commands/index.json`)) ?? []
    }
    return this.commandIndex
  }

  async getCategories(): Promise<Record<string, string[]>> {
    if (this.categories === null) {
      this.categories =
        (await fetchJson<Record<string, string[]>>(`${this.basePath}/commands/_categories.json`)) ??
        {}
    }
    return this.categories
  }

  // --- Individual command docs ---

  async getCommandDoc(name: string): Promise<CommandDoc | null> {
    if (this.commandCache.has(name)) {
      return this.commandCache.get(name)!
    }
    const doc = await fetchJson<CommandDoc>(`${this.basePath}/commands/${name}.json`)
    if (doc) {
      this.commandCache.set(name, doc)
    }
    return doc
  }

  async getCommandDocs(names: string[]): Promise<CommandDoc[]> {
    const docs: CommandDoc[] = []
    for (const name of names) {
      const doc = await this.getCommandDoc(name)
      if (doc !== null) {
        docs.push(doc)
      }
    }
    return docs
  }

  // --- ID files ---

  async getIdFile(category: string): Promise<IdEntry[]> {
    if (this.idCache.has(category)) {
      return this.idCache.get(category)!
    }
    const entries = (await fetchJson<IdEntry[]>(`${this.basePath}/ids/${category}.json`)) ?? []
    this.idCache.set(category, entries)
    return entries
  }

  async getIdCategories(): Promise<string[]> {
    // Since we can't list directory contents via fetch, maintain a known list.
    // This mirrors the files present in knowledge_base/bedrock/ids/ (synced 2026-06-21).
    return [
      'animations',
      'attributes',
      'banner_patterns',
      'biomes',
      'blocks',
      'camera_presets',
      'damage_causes',
      'effects',
      'enchantments',
      'entities',
      'equipment_slots',
      'fog',
      'gamerules',
      'items',
      'mob_events',
      'note_block_instruments',
      'paintings',
      'particles',
      'potions',
      'sounds',
      'spawn_events',
      'structures',
      'villager_professions',
    ]
  }

  // --- Formatting codes ---

  async getFormattingCodes(): Promise<FormattingCodesData> {
    if (this.formattingCodes === null) {
      this.formattingCodes =
        (await fetchJson<FormattingCodesData>(`${this.basePath}/formatting_codes.json`)) ?? {}
    }
    return this.formattingCodes
  }

  async formatFormattingCodesForPrompt(): Promise<string> {
    if (this.formattingPrompt !== null) {
      return this.formattingPrompt
    }

    const data = await this.getFormattingCodes()
    if (!data || Object.keys(data).length === 0) {
      this.formattingPrompt = ''
      return ''
    }

    const lines: string[] = ['## 颜色代码与格式参考\n']

    // Standard 16 colors
    const std = data.colors?.standard_16 ?? []
    if (std.length > 0) {
      lines.push('### 标准 16 色')
      for (const c of std) {
        lines.push(`- \`${c.code}\` ${c.name} (${c.hex}) — ${c.usage}`)
      }
    }

    // Bedrock exclusive material colors
    const mat = data.colors?.bedrock_exclusive_material ?? []
    if (mat.length > 0) {
      lines.push('\n### 基岩版独有材质色')
      for (const c of mat) {
        lines.push(`- \`${c.code}\` ${c.name} (${c.hex}) — ${c.usage}`)
      }
    }

    // Java vs Bedrock warning
    const warning = data.java_vs_bedrock_warning?.description ?? ''
    if (warning) {
      lines.push(`\n**注意**: ${warning}`)
    }

    // Modifiers
    const mods = data.modifiers ?? []
    if (mods.length > 0) {
      lines.push('\n### 格式修饰符')
      for (const m of mods) {
        lines.push(`- \`${m.code}\` ${m.name}: ${m.description}`)
      }
    }

    // Best practices
    const practices = data.best_practices ?? []
    if (practices.length > 0) {
      lines.push('\n### 使用规范')
      for (const p of practices) {
        lines.push(`- ${p}`)
      }
    }

    // Common patterns
    const patterns = data.common_patterns ?? []
    if (patterns.length > 0) {
      lines.push('\n### 常用配色模式')
      for (const p of patterns) {
        lines.push(`- **${p.name}**: \`${p.example}\` — ${p.description}`)
      }
    }

    // Special symbols
    const symbols = data.special_symbols ?? []
    if (symbols.length > 0) {
      lines.push('\n### 特殊符号（可直接用于命令文本）')
      const symParts = symbols.map((s) => `${s.symbol}(${s.name})`)
      lines.push(symParts.join('  '))
    }

    this.formattingPrompt = lines.join('\n')
    return this.formattingPrompt
  }

  // --- Formatted summaries for prompts ---

  async formatCommandDocsCompact(commandNames: string[]): Promise<string> {
    const docs = await this.getCommandDocs(commandNames)
    if (docs.length === 0) {
      return '（无匹配的命令文档）'
    }

    const sections: string[] = []
    for (const doc of docs) {
      const name = doc.name ?? '?'
      const syntax = doc.syntax ?? ''
      const desc = doc.description ?? ''

      // Compact parameter summary
      const params = doc.parameters ?? []
      const paramParts: string[] = []
      for (const p of params) {
        const req = p.required ? '必填' : '可选'
        let info = `${p.name}(${req},${p.type ?? '?'}`
        if (p.range) {
          info += `,范围${p.range}`
        }
        if (p.default) {
          info += `,默认${p.default}`
        }
        info += ')'
        paramParts.push(info)
      }

      // Examples (1-2 max)
      const examples = (doc.examples ?? []).slice(0, 2)
      const exampleLines = examples.map((ex) => `  ${ex.input} → ${ex.description}`)

      // Bedrock notes
      const notes = doc.bedrock_specific_notes ?? ''

      let section = `### /${name}\n描述: ${desc}\n语法: ${syntax}\n参数: ${paramParts.join(' | ')}`
      if (exampleLines.length > 0) {
        section += '\n示例:\n' + exampleLines.join('\n')
      }
      if (notes) {
        section += `\n基岩版注意: ${notes}`
      }

      sections.push(section)
    }

    return sections.join('\n\n')
  }

  // --- Cache management ---

  reload(): void {
    this.commandIndex = null
    this.categories = null
    this.commandCache.clear()
    this.idCache.clear()
    this.formattingCodes = null
    this.formattingPrompt = null
  }
}

export const knowledgeLoader = new KnowledgeLoader()

export type { CommandIndexEntry, CommandDoc, CommandParam, CommandExample, IdEntry }
