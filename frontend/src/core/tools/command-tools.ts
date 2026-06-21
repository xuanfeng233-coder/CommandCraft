/**
 * Tool definitions and execution for LLM tool calling.
 * Port of backend/tools/command_tools.py for frontend use.
 */

import { knowledgeLoader } from '../knowledge/loader'

// ---------------------------------------------------------------------------
// Tool schemas (OpenAI function calling format)
// ---------------------------------------------------------------------------

export const TOOL_DEFINITIONS = [
  {
    type: 'function' as const,
    function: {
      name: 'get_command_usage',
      description:
        '获取指定基岩版命令的完整用法文档，包括语法、参数说明和示例。当你不确定命令的具体语法或参数时调用此工具。',
      parameters: {
        type: 'object',
        properties: {
          command_name: {
            type: 'string',
            description: '命令名称（不含/前缀），如 give, execute, tellraw',
          },
        },
        required: ['command_name'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'get_parameter_options',
      description:
        '获取指定类别的有效参数值列表。可用类别: blocks, items, entities, effects, enchantments, particles, sounds, biomes, structures, fog, gamerules, animations。当你需要确认某个ID是否有效或查找正确的ID名称时调用。',
      parameters: {
        type: 'object',
        properties: {
          category: {
            type: 'string',
            description: 'ID 类别名称，如 items, entities, effects, enchantments, blocks',
          },
          search_term: {
            type: 'string',
            description: '可选的搜索关键词，用于过滤结果（支持中英文）',
          },
        },
        required: ['category'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'get_formatting_codes',
      description:
        '获取基岩版 § 颜色代码和格式修饰符的完整参考表。当任务涉及 tellraw、titleraw、say、title 等文本显示命令且需要颜色/格式美化时调用。',
      parameters: {
        type: 'object',
        properties: {},
      },
    },
  },
]

// ---------------------------------------------------------------------------
// Tool execution
// ---------------------------------------------------------------------------

export async function executeTool(name: string, args: Record<string, any>): Promise<string> {
  if (name === 'get_command_usage') {
    return getCommandUsage(args.command_name ?? '')
  } else if (name === 'get_parameter_options') {
    return getParameterOptions(args.category ?? '', args.search_term)
  } else if (name === 'get_formatting_codes') {
    return getFormattingCodes()
  }
  return `未知工具: ${name}`
}

async function getCommandUsage(commandName: string): Promise<string> {
  const name = commandName.trim().replace(/^\/+/, '').toLowerCase()
  const doc = await knowledgeLoader.getCommandDoc(name)
  if (!doc) {
    return `未找到命令 '${name}' 的文档。请检查命令名称是否正确。`
  }
  return knowledgeLoader.formatCommandDocsCompact([name])
}

async function getParameterOptions(
  category: string,
  searchTerm?: string,
): Promise<string> {
  category = category.trim().toLowerCase()
  let entries = await knowledgeLoader.getIdFile(category)
  if (!entries || entries.length === 0) {
    const available = await knowledgeLoader.getIdCategories()
    return `未找到类别 '${category}'。可用类别: ${available.join(', ')}`
  }

  // Filter by search term if provided
  if (searchTerm) {
    const term = searchTerm.toLowerCase()
    const filtered = entries.filter((entry) => {
      const searchable = JSON.stringify(entry).toLowerCase()
      return searchable.includes(term)
    })
    if (filtered.length === 0) {
      return `在 '${category}' 中未找到与 '${searchTerm}' 匹配的条目。共 ${entries.length} 个条目。`
    }
    entries = filtered
  }

  // Format entries compactly
  const MAX_ENTRIES = 50
  const lines: string[] = []
  for (const entry of entries.slice(0, MAX_ENTRIES)) {
    if (typeof entry === 'object' && entry !== null) {
      const entryId = (entry as any).id ?? (entry as any).name ?? ''
      const desc =
        (entry as any).description ??
        (entry as any).name_cn ??
        (entry as any).name ??
        ''
      if (desc && desc.toLowerCase().replace(/ /g, '_') !== entryId.toLowerCase()) {
        lines.push(`- ${entryId}: ${desc}`)
      } else {
        lines.push(`- ${entryId}`)
      }
    } else if (typeof entry === 'string') {
      lines.push(`- ${entry}`)
    }
  }

  let result = `## ${category} (${entries.length} 条`
  if (entries.length > MAX_ENTRIES) {
    result += `，显示前 ${MAX_ENTRIES} 条`
  }
  result += ')\n' + lines.join('\n')
  return result
}

async function getFormattingCodes(): Promise<string> {
  const text = await knowledgeLoader.formatFormattingCodesForPrompt()
  if (!text) {
    return '格式代码数据不可用。基本颜色: §0-§f (16色), §g-§u (基岩版材质色), §k混淆 §l加粗 §o斜体 §r重置'
  }
  return text
}

// ---------------------------------------------------------------------------
// Command directory (injected into system prompt)
// ---------------------------------------------------------------------------

const CAT_NAMES: Record<string, string> = {
  item_management: '物品管理',
  teleportation: '传送',
  execution: '条件执行',
  scoreboard: '计分板',
  effects: '效果/附魔',
  entity: '实体',
  world_editing: '世界编辑',
  display: '文本显示',
  entity_management: '实体管理',
  game_settings: '游戏设置',
  multimedia: '多媒体',
  spawn: '出生点',
  communication: '通信',
  server_admin: '服务器管理',
  world_management: '世界管理',
  player_management: '玩家管理',
  testing: '检测/测试',
  advanced: '高级',
}

export async function buildCommandDirectoryText(): Promise<string> {
  const index = await knowledgeLoader.getCommandIndex()
  if (!index || index.length === 0) {
    return ''
  }

  const lines = [
    '## 基岩版命令目录\n以下是所有可用的基岩版命令。如需确认具体语法，请调用 get_command_usage 工具。\n',
  ]

  // Group by category
  const categories: Record<string, string[]> = {}
  for (const cmd of index) {
    const cat = cmd.category ?? 'other'
    const name = cmd.name ?? ''
    const desc = cmd.description ?? ''
    const entry = desc ? `${name}: ${desc}` : name
    if (!categories[cat]) categories[cat] = []
    categories[cat].push(entry)
  }

  for (const [cat, entries] of Object.entries(categories)) {
    const displayName = CAT_NAMES[cat] ?? cat
    lines.push(`### ${displayName}`)
    for (const e of entries) {
      lines.push(`- ${e}`)
    }
    lines.push('')
  }

  return lines.join('\n')
}
