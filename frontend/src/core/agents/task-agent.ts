/**
 * TaskAgent — self-contained agent for executing a single TaskDefinition.
 * Port of backend/agents/task_agent.py for frontend use.
 *
 * Each TaskAgent independently: builds prompt -> LLM generates (with tool calling) -> validates.
 */

import type { ChatMessage } from '../llm-client'
import { llmClient } from '../llm-client'
import { extractJson } from '../skills/extract-json'
import { commandValidator } from '../skills/command-validator'
import { getProvider } from '../providers'
import {
  TOOL_DEFINITIONS,
  buildCommandDirectoryText,
  executeTool,
} from '../tools/command-tools'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TOOL_ROUNDS = 5

// ---------------------------------------------------------------------------
// Base template — shared across all output types
// ---------------------------------------------------------------------------

const BASE_TEMPLATE = `你是一个 Minecraft 基岩版（Bedrock Edition）命令生成专家。基于提供的命令目录和工具，生成准确的基岩版命令。

**重要：你必须始终使用中文回复，不允许使用任何其他语言。**

## 基岩版 vs Java 版关键差异（你必须严格遵守）

### ID 与命名空间
- 基岩版物品/实体/效果等 ID **不加 minecraft: 前缀**：用 \`diamond_sword\` 而非 \`minecraft:diamond_sword\`

### 方块状态语法
- 基岩版使用 \`["state_name"=value]\` 格式
- 示例：\`/setblock ~ ~ ~ stone ["stone_type"="granite"]\`

### 基岩版不支持的功能（仅以下功能不支持，其他命令均可正常使用）
- **无 NBT 标签**：/give 和 /summon 完全不支持 NBT 标签！
  - /give 不能附加附魔、自定义名称、耐久度等任何 NBT 数据
  - /give 仅支持 4 种组件：can_place_on, can_destroy, item_lock, keep_on_death
  - /summon 不能设置实体装备、血量、属性等任何 NBT 数据
  - **绝对不要生成类似 /give @s diamond_sword 1 0 {"Enchantments":[...]} 这样的 Java 版语法！**
- **无 /data 命令**、**无 /execute store**
- **计分板仅 dummy 类型**（无法自动追踪，但 /scoreboard 命令本身完全可用）
- **无 /team**、无 /bossbar、无 /worldborder、无 /attribute、无 /item（用 /replaceitem）

### 基岩版独有选择器参数（所有使用目标选择器的命令都适用！）
- **hasitem** — 检测背包/装备物品（⚠️参数名是 \`hasitem\` 不是 \`item\`！\`item=\` 不是有效选择器参数）
  - 基本: \`@a[hasitem={item=diamond_sword,quantity=1..}]\`
  - 无物品: \`@a[hasitem={item=bow,quantity=0}]\`
  - 指定槽位: \`@a[hasitem={item=diamond_helmet,location=slot.armor.head}]\`
  - 多物品(AND): \`@a[hasitem=[{item=diamond_sword},{item=shield}]]\`
  - 槽位: \`slot.weapon.mainhand\`(主手), \`slot.weapon.offhand\`(副手), \`slot.armor.head/chest/legs/feet\`(装备)
- **haspermission** — 检测权限: \`@a[haspermission={camera=enabled,movement=disabled}]\`
- **has_property** — 检测实体属性: \`@e[has_property={minecraft:variant=2}]\`

### 需要多条命令的常见场景（不能用单条命令实现！）
| 用户想做的 | 错误做法 | 正确做法 |
|-----------|---------|---------|
| 给附魔物品 | /give + NBT 附魔 ❌ | /give 获得物品 → /enchant 附魔 |
| 召唤穿装备的实体 | /summon + NBT 装备 ❌ | /summon 生成 → /replaceitem 穿装备 |
| 给命名物品 | /give + NBT 名称 ❌ | 基岩版无法通过命令实现 |
| 自定义耐久度 | /give + NBT 耐久 ❌ | 基岩版无法通过命令实现 |

### 基岩版完全支持的常用命令（不要误判为不存在）
/kill, /give, /tp, /summon, /effect, /clear, /execute, /fill, /setblock, /clone,
/scoreboard, /tag, /testfor, /tellraw, /titleraw, /replaceitem, /particle,
/playsound, /enchant, /xp, /weather, /time, /gamemode, /gamerule, /ride, /damage

## 命令选择复查（安全网）

| 用户想做的 | 正确命令 | 不可误用 |
|-----------|---------|---------|
| 清除地上的掉落物/箭矢/经验球 | /kill @e[type=item] | 不要用 /clear（仅作用于背包） |
| 清除玩家背包里的物品 | /clear @s <item> | 不要用 /kill（杀死实体） |
| 清空一片区域的方块 | /fill ... air | 不要用 /clear 或 /kill |
| 清除状态效果 | /effect <target> clear | 不要用 /clear |

{type_specific_section}

{command_directory}

## 追问格式（所有输出类型通用）

当参数不足或需求存在歧义、需要用户补充信息时，**必须**使用以下 JSON 格式进行追问，而不是直接用自然语言提问：
\`\`\`json
{
  "type": "conversation",
  "questions": [
    {
      "param": "参数名称",
      "question": "面向用户的自然语言提问",
      "options": [{"value": "选项值", "label": "显示文本"}],
      "default": "默认值建议（可为null）"
    }
  ],
  "current_progress": "当前已确定的参数摘要"
}
\`\`\`

## ⚠️ 输出约束（严格遵守）

**你的回复必须只包含一个 JSON 对象，不允许有任何其他文字、解释或 Markdown 格式。**
直接输出 JSON，不要用 \`\`\`json \`\`\` 代码块包裹。`

// ---------------------------------------------------------------------------
// Type-specific sections
// ---------------------------------------------------------------------------

const SIMPLE_COMMAND_SECTION = `## 命令生成规则

### 常见命令语法差异
- \`/give <player> <itemName> [amount] [data] [components]\` — components 仅支持 can_place_on, can_destroy, item_lock, keep_on_death
- \`/summon <entityType> [pos] [yRot] [xRot] [spawnEvent] [nameTag]\` — 无 NBT 数据
- \`/effect <target> <effect> [seconds] [amplifier] [hideParticles]\` — 清除用 \`effect <target> clear\`
- \`/enchant <target> <enchantName> [level]\` — 不需要命名空间
- \`/xp <amount>[L] [player]\` — 用 L 后缀表示等级
- \`/particle <effect> [position]\` — 极简版
- \`/playsound <sound> [player] [position] [volume] [pitch] [minVolume]\`
- \`/replaceitem\` — 基岩版用这个，Java 版用 \`/item\`
- \`/fill <from> <to> <block> [blockStates] [oldBlockHandling]\`
- \`/setblock <pos> <block> [blockStates] [destroy|keep|replace]\`
- \`/clear <player> [itemName] [data] [maxCount]\`

### 颜色美化提示
当命令涉及文本显示（say、title、me、tellraw、titleraw 等）时，**主动使用 § 颜色代码和特殊符号美化输出**：
- 标签加颜色和加粗: \`§c§l[警告]§r\`, \`§a§l[成功]§r\`, \`§6§l[公告]§r\`
- 数值用醒目颜色: \`§7击杀数: §a§l42\`
- 利用特殊符号增加美感: \`§6★ §e任务完成 §6★\`, \`§c♥ §f生命值: §a20\`
（如需完整颜色参考表，请调用 get_formatting_codes 工具）

### 规则
1. 严格遵循基岩版语法，ID 不加命名空间前缀
2. 参数完整且无歧义时直接生成命令
3. 参数不足但可用合理默认值时，使用默认值并说明
4. **参数不足或存在多种有效实现方式时**，输出 conversation 类型的追问

### 必须追问的场景（不要直接猜测用户意图）
- **附魔物品**：用户想要附魔物品时，基岩版 /give 不能附加附魔！正确方案：先 /give 再 /enchant
- **需要 NBT 的自定义**：用户想要自定义名称/耐久度/属性的物品或实体 → 说明基岩版限制
- **召唤带装备的实体**：需要 /summon + /replaceitem 两步
- **"清除/清理"类需求**：目标不明确时
- **目标选择不明确**：用户说"给玩家..."但未说明是自己还是所有玩家
- **影响范围不确定**：如 /fill 没给坐标
- **单条命令无法实现**：任何需要多条命令配合的需求

## 输出格式

### 格式1: 命令生成（参数充分且无歧义时）
\`\`\`json
{
  "type": "single_command",
  "command": {
    "command": "/完整命令字符串",
    "explanation": "命令各部分的详细解释",
    "variants": ["可选的变体写法"],
    "warnings": ["注意事项"]
  }
}
\`\`\`

### 格式2: 参数追问（参数不足或有歧义时）
\`\`\`json
{
  "type": "conversation",
  "questions": [
    {
      "param": "参数名",
      "question": "面向用户的自然语言提问",
      "options": [{"value": "选项值", "label": "显示文本"}],
      "default": "默认值建议"
    }
  ],
  "current_progress": "当前已确定的参数摘要"
}
\`\`\``

const EXECUTE_CHAIN_SECTION = `## 基岩版 execute 完整子命令参考（1.19.50+ 新语法）

### 修饰子命令
| 子命令 | 语法 | 说明 |
|--------|------|------|
| \`align\` | \`align <axes>\` | 对齐到方块网格 |
| \`anchored\` | \`anchored <eyes｜feet>\` | 设置执行锚点 |
| \`as\` | \`as <目标选择器>\` | 改变执行者身份 |
| \`at\` | \`at <目标选择器>\` | 改变执行位置/旋转/维度 |
| \`facing\` | \`facing <x y z>\` 或 \`facing entity <目标> <eyes｜feet>\` | 设置朝向 |
| \`in\` | \`in <dimension>\` | 切换维度 |
| \`positioned\` | \`positioned <x y z>\` 或 \`positioned as <目标>\` | 更新位置 |
| \`rotated\` | \`rotated <yaw> <pitch>\` 或 \`rotated as <目标>\` | 设置旋转 |

### 条件子命令（if/unless）
| 条件 | 语法 | 说明 |
|------|------|------|
| 方块检测 | \`if/unless block <x y z> <方块ID> [方块状态]\` | 方块状态: \`["state"=value]\` |
| 区域比较 | \`if/unless blocks <begin> <end> <dest> <all/masked>\` | 比较两个区域 |
| 实体存在 | \`if/unless entity <目标选择器>\` | 检测实体 |
| 分数比较 | \`if/unless score <目标1> <obj1> <运算符> <目标2> <obj2>\` | \`<\`, \`<=\`, \`=\`, \`>=\`, \`>\` |
| 分数范围 | \`if/unless score <目标> <obj> matches <范围>\` | \`5\`, \`1..10\`, \`10..\`, \`..20\` |

### 执行子命令
\`run <命令>\` — **命令不加 / 前缀！**

### Java 版独有（基岩版不支持！）
- **\`store\`** — 基岩版完全没有此功能
- \`on\`, \`summon\`, \`positioned over\`, \`if/unless biome|data|loaded|predicate|items|function\`

### 常用模式
- 在所有玩家位置执行: \`execute as @a at @s run <命令>\`
- 条件检测: \`execute if entity @e[type=zombie,r=10] run say 附近有僵尸\`
- 组合条件: \`execute as @a at @s if block ~ ~-1 ~ gold_block run effect @s speed 1 1\`
- 检测持有物品: \`execute as @a[hasitem={item=tnt}] run tag @s add WARN\`（⚠️用 hasitem 不是 item）

### 规则
1. 严格使用基岩版 execute 新语法（1.19.50+）
2. **绝对不要使用 store 子命令**
3. **\`run\` 后面的命令不加 \`/\` 前缀**

## 输出格式
\`\`\`json
{
  "type": "single_command",
  "command": {
    "command": "/execute ... run 命令",
    "explanation": "命令链逐段解释",
    "chain_breakdown": [
      {"subcommand": "as", "value": "@a", "purpose": "以每个玩家身份执行"}
    ],
    "variants": [],
    "warnings": []
  }
}
\`\`\``

const RAWTEXT_SECTION = `## 基岩版 rawtext 完整格式规范

### 根结构
基岩版 rawtext 根**必须**是 \`{"rawtext": [组件1, 组件2, ...]}\`

### 4 种组件类型
1. **text**: \`{"text": "§c红色文字§r 普通文字"}\`
2. **selector**: \`{"selector": "@s"}\`
3. **score**: \`{"score": {"name": "@s", "objective": "kills"}}\`
4. **translate**: \`{"translate": "Hello %%1", "with": {"rawtext": [{"text": "Steve"}]}}\`

### 不支持的功能（Java 版独有）
clickEvent, hoverEvent, color 属性, bold/italic 属性, font, insertion, keybind, nbt 组件

### 颜色与格式代码（§）
- 标准16色: §0黑 §1深蓝 §2深绿 §3深青 §4深红 §5深紫 §6金 §7灰 §8深灰 §9蓝 §a绿 §b青 §c红 §d粉 §e黄 §f白
- 基岩版材质色: §g硬币金 §h石英白 §i铁灰 §j下界合金 §p金 §q绿宝石 §s钻石青 §t青金石蓝 §u紫水晶
- **§m §n 在基岩版是材质色（红石红/铜色），不是删除线/下划线！**
- 修饰符: §k混淆 | §l加粗 | §o斜体 | §r重置
- 组合规则: 先颜色后样式（§c§l = 红色加粗），切换前用 §r 重置
- 善用颜色和特殊符号（★♥◆➤✔✘━等）让输出更美观，尤其是标签、标题、状态信息

（如需完整颜色表和特殊符号列表，请调用 get_formatting_codes 工具）

### 使用命令
- \`/tellraw <目标> <rawtext JSON>\` — 聊天消息
- \`/titleraw <目标> title|subtitle|actionbar <rawtext JSON>\` — 标题/副标题/动作栏

### 规则
1. JSON 根结构必须是 \`{"rawtext": [...]}\`
2. 颜色用 § 代码，不用 JSON 属性
3. 不要用 clickEvent, hoverEvent 等 Java 版属性

## 输出格式
\`\`\`json
{
  "type": "single_command",
  "command": {
    "command": "/tellraw @a {...rawtext JSON...}",
    "explanation": "rawtext 各组件解释",
    "preview": "模拟的显示效果纯文本",
    "variants": [],
    "warnings": []
  }
}
\`\`\``

const SELECTOR_SECTION = `## 基岩版选择器完整参考

### 选择器类型
| 选择器 | 选择目标 |
|--------|---------|
| \`@a\` | 所有在线玩家（含死亡） |
| \`@e\` | 所有存活实体+在线玩家 |
| \`@p\` | 最近的存活玩家 |
| \`@r\` | 随机存活玩家 |
| \`@s\` | 命令执行者自身 |
| \`@initiator\` | NPC对话发起者（基岩版独有） |

### 全部选择器参数

#### 基岩版独有参数（重要！）

**hasitem — 物品检测:**
- 基本: \`@a[hasitem={item=diamond_sword,quantity=1..}]\`
- 无物品: \`@a[hasitem={item=bow,quantity=0}]\`
- 特定槽位: \`@a[hasitem={item=diamond_helmet,location=slot.armor.head}]\`
- 多物品(AND): \`@a[hasitem=[{item=diamond_sword},{item=shield}]]\`

**haspermission — 权限检测:**
- \`@a[haspermission={camera=enabled,movement=disabled}]\`

**has_property — 实体属性检测:**
- \`@e[has_property={minecraft:variant=2}]\`

### 规则
1. 使用基岩版语法（r=/rm= 而非 distance=, c= 而非 limit=）
2. 输出完整命令（不仅是选择器）
3. ID 不加 minecraft: 前缀

## 输出格式
\`\`\`json
{
  "type": "single_command",
  "command": {
    "command": "/完整命令（含选择器）",
    "explanation": "选择器各部分解释",
    "selector_breakdown": {
      "base": "@e",
      "conditions": [
        {"key": "type", "value": "zombie", "explanation": "仅选择僵尸"}
      ]
    },
    "variants": [],
    "warnings": []
  }
}
\`\`\``

const PROJECT_SECTION = `## 命令方块项目规划

### 三种命令方块
| 类型 | 行为 | 典型用途 |
|------|------|---------|
| 脉冲 (impulse) | 红石信号时执行一次 | 初始化 |
| 循环 (repeating) | 每tick持续执行 | 持续检测 |
| 连锁 (chain) | 前一个成功后执行 | 顺序逻辑链 |

### 命令方块链规则
1. 链条起点必须是脉冲或循环方块
2. 方块必须物理相连且朝向一致
3. 连锁方块必须设 auto=true
4. \`execute ... run\` 后面的命令不加 \`/\` 前缀

### 常见模式
- **定时器**: 计分板每tick+1，达到目标值触发动作
- **标签状态机**: tag管理实体多状态

### 参考示例

**用户需求**: 制作一个限时挑战系统，60秒倒计时，期间击杀僵尸获得积分

\`\`\`json
{
  "type": "project",
  "project_name": "限时击杀挑战",
  "overview": "使用计分板追踪倒计时和积分，循环命令方块持续检测",
  "phases": [
    {
      "phase_name": "初始化",
      "description": "创建计分板并初始化数值",
      "tasks": [
        {
          "task_id": "1",
          "description": "创建计分板",
          "commands": ["scoreboard"],
          "command_blocks": [
            {
              "type": "impulse",
              "conditional": false,
              "needs_redstone": true,
              "command": "/scoreboard objectives add timer dummy 倒计时",
              "comment": "创建倒计时计分板"
            },
            {
              "type": "chain",
              "conditional": false,
              "needs_redstone": false,
              "command": "/scoreboard objectives add kills dummy 击杀数",
              "comment": "创建击杀计分板"
            },
            {
              "type": "chain",
              "conditional": false,
              "needs_redstone": false,
              "command": "/scoreboard players set @a timer 1200",
              "comment": "设置60秒（1200tick）"
            }
          ],
          "dependencies": []
        }
      ]
    },
    {
      "phase_name": "持续运行",
      "description": "倒计时和击杀检测",
      "tasks": [
        {
          "task_id": "2",
          "description": "倒计时递减",
          "commands": ["scoreboard", "execute"],
          "command_blocks": [
            {
              "type": "repeating",
              "conditional": false,
              "needs_redstone": false,
              "command": "/execute as @a if score @s timer matches 1.. run scoreboard players remove @s timer 1",
              "comment": "每tick减少1"
            },
            {
              "type": "chain",
              "conditional": false,
              "needs_redstone": false,
              "command": "/execute as @a if score @s timer matches 0 run titleraw @s actionbar {\\"rawtext\\":[{\\"text\\":\\"§c§l时间到！\\"}]}",
              "comment": "倒计时结束提示"
            }
          ],
          "dependencies": []
        }
      ]
    }
  ]
}
\`\`\`

## 输出格式
\`\`\`json
{
  "type": "project",
  "project_name": "项目名称",
  "overview": "整体方案概述",
  "phases": [
    {
      "phase_name": "阶段名称",
      "description": "阶段说明",
      "tasks": [
        {
          "task_id": "1",
          "description": "任务描述",
          "commands": ["涉及的命令名称"],
          "command_blocks": [
            {
              "type": "repeating",
              "conditional": false,
              "needs_redstone": false,
              "command": "/具体命令",
              "comment": "作用说明"
            }
          ],
          "dependencies": []
        }
      ]
    }
  ]
}
\`\`\``

// Map output_type to section
const TYPE_SECTIONS: Record<string, string> = {
  simple_command: SIMPLE_COMMAND_SECTION,
  execute_chain: EXECUTE_CHAIN_SECTION,
  rawtext: RAWTEXT_SECTION,
  selector: SELECTOR_SECTION,
  project: PROJECT_SECTION,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function providerSupportsTools(): boolean {
  const providerId = (llmClient as any).config?.providerId ?? ''
  if (!providerId) return true // unknown provider — try optimistically
  const provider = getProvider(providerId)
  if (!provider) return true
  return provider.supports_tools
}

function taskEvent(
  taskId: string,
  status: string,
  result?: Record<string, any>,
  error?: string,
): Record<string, any> {
  const data: Record<string, any> = { task_id: taskId, status }
  if (result !== undefined) data.result = result
  if (error !== undefined) data.error = error
  return { event: 'task_update', data }
}

// ---------------------------------------------------------------------------
// TaskAgent
// ---------------------------------------------------------------------------

export class TaskAgent {
  /**
   * Execute a task definition, yielding SSE events.
   *
   * Yields:
   *   {event: "task_update", data: {task_id, status: "generating|validating|paused|completed|failed", ...}}
   *   {event: "task_thinking", data: {task_id, text}}
   */
  async *execute(
    taskDef: Record<string, any>,
    ambiguous: boolean = false,
  ): AsyncGenerator<Record<string, any>> {
    const taskId: string = taskDef.task_id ?? '1'
    const userRequest: string = taskDef.user_request ?? ''
    const recommendedCommands: string[] = taskDef.recommended_commands ?? []
    const outputType: string = taskDef.output_type ?? 'simple_command'

    // Step 1: Build prompt
    yield taskEvent(taskId, 'generating')

    let commandDirectory = await buildCommandDirectoryText()
    if (ambiguous) {
      commandDirectory +=
        '\n\n## 歧义提示\n此需求存在歧义，请优先输出 conversation 类型进行追问。'
    }

    let content: string
    let thinking: string
    let result: Record<string, any>

    try {
      const systemPrompt = this.buildPrompt(outputType, commandDirectory)
      const messages: ChatMessage[] = [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userRequest },
      ]

      if (providerSupportsTools()) {
        // Path A: Tool calling loop
        ;[content, thinking] = await this.executeWithTools(messages, taskId)
      } else {
        // Path B: Fallback — inject recommended command docs directly
        ;[content, thinking] = await this.executeWithFallback(messages, recommendedCommands)
      }

      if (thinking) {
        yield {
          event: 'task_thinking',
          data: { task_id: taskId, text: thinking },
        }
      }

      result = this.parseOutput(content, outputType)
      if (thinking) {
        result.thinking = thinking
      }
    } catch (e: any) {
      console.error(`[TaskAgent ${taskId}] LLM generation failed:`, e)
      yield taskEvent(taskId, 'failed', undefined, String(e))
      return
    }

    // Step 2: Check if conversation (pause)
    if (result.type === 'conversation') {
      console.info(`[TaskAgent ${taskId}] needs user input — pausing`)
      yield taskEvent(taskId, 'paused', result)
      return
    }

    // Step 3: Validate
    yield taskEvent(taskId, 'validating')
    await this.runValidation(result)

    yield taskEvent(taskId, 'completed', result)
  }

  private async executeWithTools(
    messages: ChatMessage[],
    taskId: string,
  ): Promise<[string, string]> {
    let thinking = ''

    for (let roundIdx = 0; roundIdx < MAX_TOOL_ROUNDS; roundIdx++) {
      const response = await llmClient.chatWithTools(messages, TOOL_DEFINITIONS as any)
      const msg = response.message

      // Accumulate thinking from all rounds
      const roundThinking = msg.thinking ?? ''
      if (roundThinking) {
        thinking += (thinking ? '\n---\n' : '') + roundThinking
      }

      const toolCalls = msg.tool_calls
      if (!toolCalls || toolCalls.length === 0) {
        // No more tool calls — model is done
        return [msg.content ?? '', thinking]
      }

      // Append assistant message with tool calls
      messages.push({
        role: 'assistant',
        content: msg.content,
        tool_calls: toolCalls,
      })

      // Execute each tool call
      for (const tc of toolCalls) {
        const funcName = tc.function.name
        const funcArgs = tc.function.arguments
        console.info(
          `[TaskAgent ${taskId}] tool call [${roundIdx + 1}] ${funcName}(${JSON.stringify(funcArgs)})`,
        )
        const resultText = await executeTool(funcName, funcArgs)
        messages.push({
          role: 'tool',
          content: resultText,
          tool_call_id: tc.id,
        })
      }
    }

    // Exhausted MAX_TOOL_ROUNDS — do one final call without tools
    console.warn(
      `[TaskAgent ${taskId}] exhausted ${MAX_TOOL_ROUNDS} tool rounds, final call`,
    )
    const response = await llmClient.chat(messages)
    const msg = response.message
    const finalThinking = msg.thinking ?? ''
    if (finalThinking) {
      thinking += (thinking ? '\n---\n' : '') + finalThinking
    }
    return [msg.content ?? '', thinking]
  }

  private async executeWithFallback(
    messages: ChatMessage[],
    recommendedCommands: string[],
  ): Promise<[string, string]> {
    if (recommendedCommands.length > 0) {
      const { knowledgeLoader } = await import('../knowledge/loader')
      const docsText = await knowledgeLoader.formatCommandDocsCompact(recommendedCommands)
      if (docsText) {
        messages[0].content += `\n\n## 相关命令文档\n${docsText}`
      }
    }

    const response = await llmClient.chat(messages)
    const msg = response.message
    return [msg.content ?? '', msg.thinking ?? '']
  }

  private buildPrompt(outputType: string, commandDirectory: string): string {
    const typeSection = TYPE_SECTIONS[outputType] ?? SIMPLE_COMMAND_SECTION
    return BASE_TEMPLATE.replace('{type_specific_section}', typeSection).replace(
      '{command_directory}',
      commandDirectory,
    )
  }

  private parseOutput(raw: string, outputType: string): Record<string, any> {
    const data = extractJson(raw)

    if (data && typeof data === 'object' && 'type' in (data as any)) {
      return this.normalizeOutput(data as Record<string, any>)
    }

    // JSON extraction failed — detect if this is a conversational response
    if (raw && this.looksLikeConversation(raw)) {
      console.info(
        '[TaskAgent._parseOutput] JSON failed but detected conversational text, wrapping as conversation type',
      )
      return {
        type: 'conversation',
        questions: [
          {
            param: 'user_clarification',
            question: raw.trim(),
            options: [],
            default: null,
          },
        ],
        current_progress: '',
      }
    }

    if (outputType === 'project') {
      return {
        type: 'project',
        project_name: '解析失败',
        overview: raw ? raw.slice(0, 500) : '',
        phases: [],
      }
    }

    return {
      type: 'single_command',
      command: {
        command: '',
        explanation: raw ? raw.slice(0, 500) : '',
        variants: [],
        warnings: ['JSON 解析失败，请查看原始输出'],
      },
    }
  }

  private looksLikeConversation(text: string): boolean {
    const hasQuestion = text.includes('？') || text.includes('?')
    const strongKeywords = [
      '请提供',
      '请指定',
      '请选择',
      '请确认',
      '请告诉',
      '需要您',
      '需要你',
      '以下信息',
    ]
    const hasStrongKeyword = strongKeywords.some((kw) => text.includes(kw))
    const weakKeywords = ['哪种', '哪个', '什么类型', '什么物品', '什么方块', '什么实体']
    const hasWeakKeyword = weakKeywords.some((kw) => text.includes(kw))
    const hasNumberedList = [1, 2, 3, 4, 5].some(
      (i) => text.includes(`${i}.`) || text.includes(`${i}、`) || text.includes(`${i}. `),
    )
    const startsWithCommand = text.trim().startsWith('/')

    if (startsWithCommand) return false
    if (hasStrongKeyword) return true
    if (hasWeakKeyword && hasQuestion) return true
    if (hasQuestion && hasNumberedList) return true
    return false
  }

  private normalizeOutput(data: Record<string, any>): Record<string, any> {
    const resultType = data.type ?? ''

    if (['execute_chain', 'selector', 'rawtext'].includes(resultType)) {
      let cmdObj = data.command
      const commandsArr = data.commands

      if (cmdObj === undefined && Array.isArray(commandsArr)) {
        const cmdStrs: string[] = []
        for (const item of commandsArr) {
          if (typeof item === 'string') {
            cmdStrs.push(item)
          } else if (typeof item === 'object' && item !== null && 'command' in item) {
            cmdStrs.push(item.command)
          }
        }
        const mergedCmd = cmdStrs.join('\n')
        cmdObj = {
          command: mergedCmd,
          explanation: data.explanation ?? '',
          variants: data.variants ?? [],
          warnings: data.warnings ?? [],
        }
      } else if (typeof cmdObj === 'string') {
        cmdObj = {
          command: cmdObj,
          explanation: data.explanation ?? '',
          variants: data.variants ?? [],
          warnings: data.warnings ?? [],
        }
      }

      if (typeof cmdObj === 'object' && cmdObj !== null) {
        for (const key of ['chain_breakdown', 'selector_breakdown', 'preview']) {
          if (key in data && !(key in cmdObj)) {
            cmdObj[key] = data[key]
          }
        }
      }

      data.type = 'single_command'
      data.command = cmdObj ?? {
        command: '',
        explanation: '',
        variants: [],
        warnings: [],
      }
      delete data.commands
    }

    return data
  }

  private async runValidation(contentData: Record<string, any>): Promise<void> {
    const commandObj = contentData.command
    if (!commandObj || typeof commandObj !== 'object') return
    const cmdStr: string = commandObj.command ?? ''
    if (!cmdStr) return

    const cmdLines = cmdStr
      .split('\n')
      .map((l: string) => l.trim())
      .filter((l: string) => l.length > 0)

    try {
      const results = await commandValidator.validate(cmdLines)
      if (!results || results.length === 0) return

      const allErrors: string[] = []
      const allWarnings: string[] = []
      let allValid = true

      for (const validation of results) {
        const errors = validation.errors ?? []
        const warningsList = (validation.warnings ?? []).map((w: any) => w.message)
        if (errors.length > 0) {
          allValid = false
          for (const err of errors) {
            allErrors.push(`[${err.type}] ${err.message} — ${err.suggestion ?? ''}`)
          }
        }
        allWarnings.push(...warningsList)
      }

      const existing: string[] = commandObj.warnings ?? []
      existing.push(...allErrors)
      existing.push(...allWarnings)
      if (existing.length > 0) {
        commandObj.warnings = existing
      }

      commandObj.validation = {
        valid: allValid,
        error_count: allErrors.length,
      }
    } catch (e: any) {
      console.warn('[CommandValidator] failed:', e)
    }
  }
}
