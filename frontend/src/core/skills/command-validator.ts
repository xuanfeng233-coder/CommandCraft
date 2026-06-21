/**
 * CommandValidator — Rule-based validation of MCBE commands against the knowledge base.
 * Port of backend/skills/command_validator.py for frontend use.
 */

import { idRegistry } from '../knowledge/id-registry'
import { knowledgeLoader } from '../knowledge/loader'

const JAVA_ONLY_COMMANDS = new Set([
  'advancement',
  'attribute',
  'ban-ip',
  'bossbar',
  'data',
  'datapack',
  'debug',
  'defaultgamemode',
  'forceload',
  'item',
  'jfr',
  'pardon',
  'pardon-ip',
  'perf',
  'place',
  'publish',
  'reload',
  'save-all',
  'save-off',
  'save-on',
  'seed',
  'setidletimeout',
  'spectate',
  'team',
  'teammsg',
  'trigger',
  'worldborder',
])

const JAVA_NBT_KEYS = [
  'Enchantments',
  'display',
  'CustomName',
  'Damage',
  'Unbreakable',
  'AttributeModifiers',
  'Potion',
  'CustomPotionEffects',
  'HandItems',
  'ArmorItems',
  'Health',
]

const JAVA_ONLY_SELECTOR_ARGS = ['nbt', 'predicate', 'advancements']

interface ValidationError {
  type: string
  message: string
  suggestion: string
}

interface ValidationWarning {
  message: string
}

interface ValidationResult {
  command: string
  valid: boolean
  errors: ValidationError[]
  warnings: ValidationWarning[]
}

let knownBedrockCommands: Set<string> | null = null

async function getKnownCommands(): Promise<Set<string>> {
  if (knownBedrockCommands === null) {
    const index = await knowledgeLoader.getCommandIndex()
    knownBedrockCommands = new Set(index.map((cmd) => cmd.name))
  }
  return knownBedrockCommands
}

function extractCommandName(command: string): string | null {
  let cmd = command.trim()
  if (cmd.startsWith('/')) {
    cmd = cmd.slice(1)
  }
  const parts = cmd.split(/\s+/, 2)
  return parts[0] ? parts[0].toLowerCase() : null
}

function extractIdsFromCommand(command: string): Array<[string, string]> {
  const ids: Array<[string, string]> = []
  const parts = command.split(/\s+/)
  const cmdName = extractCommandName(command)

  if (cmdName === 'give' && parts.length >= 3) {
    ids.push([parts[2], 'items'])
  } else if (cmdName === 'summon') {
    const entityId = parts.length > 1 ? parts[1] : null
    if (entityId) {
      ids.push([entityId, 'entities'])
    }
  } else if (cmdName === 'effect' && parts.length >= 3) {
    for (let i = 2; i < parts.length; i++) {
      const p = parts[i]
      if (!p.startsWith('@') && !p.replace(/^-/, '').match(/^\d+$/)) {
        ids.push([p, 'effects'])
        break
      }
    }
  } else if ((cmdName === 'setblock' || cmdName === 'fill') && parts.length >= 5) {
    const fillKeywords = new Set(['destroy', 'hollow', 'keep', 'outline', 'replace'])
    for (const p of parts.slice(4)) {
      if (
        !p.replace(/^-/, '').match(/^\d+$/) &&
        !p.startsWith('~') &&
        !p.startsWith('^') &&
        !fillKeywords.has(p)
      ) {
        ids.push([p, 'blocks'])
        break
      }
    }
  } else if (cmdName === 'enchant' && parts.length >= 3) {
    ids.push([parts[2], 'enchantments'])
  } else if (cmdName === 'playsound' && parts.length >= 2) {
    ids.push([parts[1], 'sounds'])
  } else if (cmdName === 'particle' && parts.length >= 2) {
    ids.push([parts[1], 'particles'])
  }

  return ids
}

class CommandValidator {
  async validate(commands: string[]): Promise<ValidationResult[]> {
    const results: ValidationResult[] = []
    for (const cmd of commands) {
      results.push(await this.validateSingle(cmd))
    }
    return results
  }

  private async validateSingle(command: string): Promise<ValidationResult> {
    const errors: ValidationError[] = []
    const warnings: ValidationWarning[] = []

    const cmd = command.trim()
    if (!cmd) {
      return {
        command,
        valid: false,
        errors: [{ type: 'syntax', message: '命令为空', suggestion: '输入有效的命令' }],
        warnings: [],
      }
    }

    // Check starts with /
    if (!cmd.startsWith('/')) {
      warnings.push({ message: '命令通常以 / 开头（在命令方块中可省略）' })
    }

    // Extract command name
    const cmdName = extractCommandName(cmd)
    if (!cmdName) {
      errors.push({
        type: 'syntax',
        message: '无法解析命令名称',
        suggestion: '命令格式应为 /命令名 参数...',
      })
      return { command, valid: false, errors, warnings }
    }

    // Check if Java-only
    if (JAVA_ONLY_COMMANDS.has(cmdName)) {
      errors.push({
        type: 'version',
        message: `/${cmdName} 是 Java 版独有命令，基岩版不支持`,
        suggestion: '请使用基岩版对应的命令',
      })
    }

    // Check for execute store (Java-only subcommand)
    if (cmdName === 'execute' && cmd.includes('store ')) {
      errors.push({
        type: 'version',
        message: 'execute store 是 Java 版独有的子命令，基岩版不支持',
        suggestion: '基岩版可使用计分板配合条件执行来实现类似功能',
      })
    }

    // Check if command is known
    const known = await getKnownCommands()
    if (known.size > 0 && !known.has(cmdName) && !JAVA_ONLY_COMMANDS.has(cmdName)) {
      warnings.push({ message: `/${cmdName} 不在已收录的命令列表中（可能是合法命令但未收录）` })
    }

    // Check for execute run /command (should be without /)
    if (cmdName === 'execute' && /\brun\s+\//.test(cmd)) {
      warnings.push({
        message: 'execute run 后的命令不需要 / 前缀（如 run say Hello 而非 run /say Hello）',
      })
    }

    // Validate IDs
    const extractedIds = extractIdsFromCommand(cmd)
    for (const [idValue, category] of extractedIds) {
      const valid = await idRegistry.isValidId(idValue, category)
      if (!valid) {
        const available = await idRegistry.getAllIds(category)
        if (available.size > 0) {
          const suggestion = this.findSimilar(idValue, available)
          errors.push({
            type: 'id',
            message: `ID '${idValue}' 在 ${category} 中未找到`,
            suggestion: suggestion ? `你是否指的是: ${suggestion}` : '请检查 ID 是否正确',
          })
        }
      }
    }

    // Check for Java-only NBT syntax
    if (cmd.includes('nbt=')) {
      warnings.push({ message: '检测到 Java 版 NBT 选择器语法 (nbt=)，基岩版不支持' })
    }

    // Check for Java-style NBT in /give and /summon
    if ((cmdName === 'give' || cmdName === 'summon') && cmd.includes('{')) {
      for (const nbtKey of JAVA_NBT_KEYS) {
        if (cmd.includes(nbtKey) || cmd.includes(`"${nbtKey}"`)) {
          errors.push({
            type: 'version',
            message: `检测到 Java 版 NBT 标签 (${nbtKey})，基岩版 /${cmdName} 不支持 NBT`,
            suggestion:
              '基岩版 /give 仅支持 can_place_on/can_destroy/item_lock/keep_on_death 组件。附魔请用 /enchant，装备请用 /replaceitem',
          })
          break
        }
      }
    }

    // Check selector syntax for Java-only args
    const selectorPattern = /@[aeprs]\[([^\]]*)\]/g
    let match: RegExpExecArray | null
    while ((match = selectorPattern.exec(cmd)) !== null) {
      const selectorArgs = match[1]
      for (const ja of JAVA_ONLY_SELECTOR_ARGS) {
        if (selectorArgs.includes(`${ja}=`)) {
          errors.push({
            type: 'parameter',
            message: `选择器参数 '${ja}' 是 Java 版独有的`,
            suggestion: '基岩版选择器不支持此参数',
          })
        }
      }
    }

    return { command, valid: errors.length === 0, errors, warnings }
  }

  private findSimilar(target: string, candidates: Set<string>, maxResults = 3): string {
    const matches: string[] = []
    const targetLower = target.toLowerCase()
    const sorted = Array.from(candidates).sort()
    for (const c of sorted) {
      if (targetLower.includes(c.toLowerCase()) || c.toLowerCase().includes(targetLower)) {
        matches.push(c)
        if (matches.length >= maxResults) break
      }
    }
    return matches.join(', ')
  }
}

export const commandValidator = new CommandValidator()

export type { ValidationResult, ValidationError, ValidationWarning }
