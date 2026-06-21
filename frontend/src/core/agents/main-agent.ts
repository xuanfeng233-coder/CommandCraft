/**
 * MainAgent — Coordinator with two methods: decompose() + summarize().
 * Port of backend/agents/main_agent.py for frontend use.
 */

import type { ChatMessage } from '../llm-client'
import { llmClient } from '../llm-client'
import { extractJson } from '../skills/extract-json'

// ---------------------------------------------------------------------------
// Decompose system prompt
// ---------------------------------------------------------------------------

const DECOMPOSE_PROMPT = `你是一个 Minecraft 基岩版（Bedrock Edition）命令助手的任务分解专家。

**重要：你必须始终使用中文回复，不允许使用任何其他语言。**
**⚠️ 你的回复必须只包含一个 JSON 对象，绝对不允许输出自由文本。在 think 标签中进行分析推理，回复内容只能是 JSON。**

## 你的职责

分析用户的自然语言需求，将其分解为一个或多个独立的 Task。每个 Task 将由独立的 TaskAgent 并行执行。

## 基岩版支持的命令（部分列表）

以下命令在基岩版中**全部可用**：
kill, give, tp/teleport, summon, effect, clear, execute, fill, setblock, clone,
scoreboard, tag, testfor, tellraw, titleraw, replaceitem, particle, playsound,
spreadplayers, structure, tickingarea, weather, time, gamemode, difficulty, xp,
enchant, spawnpoint, setworldspawn, ride, damage, camerashake, fog, inputpermission,
dialogue, loot, schedule, gamerule, msg/tell/w, say, me, list, kick, op, deop,
whitelist, ability, allowlist, ban, stopsound, music, playanimation, hud, camera,
recipe, scriptevent, locate, clearspawnpoint, connect, wsserver, toggledownfall

## 仅 Java 版独有（基岩版不支持）

- /data 命令、/execute store 子命令
- **NBT 标签**（/give 和 /summon 完全不能附加 NBT！）
  - /give 不能附魔、不能自定义名称/耐久度 → 附魔必须用 /enchant
  - /summon 不能设置装备/血量/属性 → 装备必须用 /replaceitem
- /team、/bossbar、/worldborder、/attribute
- /item（基岩版用 /replaceitem）

## 分解规则

### 单 Task 场景（is_single_task=true）
- 简单命令请求（"给我一把钻石剑"、"传送到坐标"）
- 单个 execute 链
- 单个 rawtext/tellraw/titleraw
- 涉及 1 条或有紧密关联的 2 条命令

### 多 Task 场景（is_single_task=false）
- 用户请求包含 **2个或以上相互独立的机制**
- 各机制使用不同命令或完全不同触发条件
- 混合命令类型（如同时涉及 execute+hasitem + inputpermission + replaceitem）

### Task 的 user_request 字段（关键！）
必须是**自包含的**自然语言描述，包含足够上下文让 TaskAgent 能独立生成命令。

**禁止替用户决定模糊参数！**
- 如果用户说"违禁品"但没说具体是什么物品 → user_request 中写"违禁品（用户未指定具体物品，需要追问）"
- 绝对不要自作主张选择占位值

### output_type 判断
| output_type | 适用条件 |
|-------------|---------|
| simple_command | 标准命令（/give, /tp, /effect, /summon, /kill 等） |
| execute_chain | 涉及 /execute 条件执行 |
| rawtext | 涉及 /tellraw, /titleraw |
| selector | 需要复杂目标选择器 |
| project | 复杂项目规划（多命令方块组合机制） |

### execution_mode
- **continuous**: 需持续循环运行（repeating 命令方块）
- **once**: 一次性执行（impulse 命令方块）

### depends_on（任务依赖）
- 大多数多任务场景中，任务之间是**相互独立**的，可以并行执行 → depends_on: []
- **需要设置依赖的场景**（后一个任务 depends_on 前一个任务）：
  1. 任务 B 需要使用任务 A 创建/定义的标签名称或计分板名称
  2. 任务 B 的目标选择器必须引用任务 A 定义的标签
  3. 用户明确要求先做 A 再做 B 的顺序关系
  4. **（关键！）多个任务共享同一个用户未指定的模糊参数** — 例如：
     - 制作 boss：多个任务都需要知道 boss 用什么生物 → 第一个任务问用户，后续任务依赖第一个
     - 建筑系统：多个任务都需要知道用什么材料 → 同理
     - 任何场景中，如果有 N 个任务会问用户**同一个问题**，必须让第 1 个任务先执行并获得答案，其余 N-1 个任务 depends_on 第 1 个任务
- 不需要依赖的场景（保持并行）：
  - 两个任务使用不同的命令且互不引用
  - 各任务的参数都已明确，不需要追问用户
- depends_on 填写的是**前置任务的 task_id 列表**
- **禁止循环依赖**：依赖方向必须单向（低 ID → 高 ID）

### 共享参数处理示例
用户说"制作一个boss"但没说用什么生物：
- 任务 1: "召唤boss实体"（需要追问生物类型）→ depends_on: []
- 任务 2: "给boss添加装备"（也需要知道生物类型）→ depends_on: ["1"]
- 任务 3: "boss攻击机制"（也需要知道生物类型）→ depends_on: ["1"]
这样用户只需在任务 1 中回答一次，任务 2 和 3 会自动获得答案。

## 输出格式

\`\`\`json
{
  "project_name": "项目名称（简短描述）",
  "overview": "整体方案概述",
  "tasks": [
    {
      "task_id": "1",
      "description": "简短描述（20字内）",
      "user_request": "给 TaskAgent 的自包含自然语言描述",
      "recommended_commands": ["execute", "tag"],
      "output_type": "execute_chain",
      "execution_mode": "continuous",
      "depends_on": []
    },
    {
      "task_id": "2",
      "description": "依赖任务1结果的后续任务",
      "user_request": "自包含描述（会自动注入前置任务结果）",
      "recommended_commands": ["execute", "clear"],
      "output_type": "execute_chain",
      "execution_mode": "continuous",
      "depends_on": ["1"]
    }
  ],
  "is_single_task": false
}
\`\`\`
`

// ---------------------------------------------------------------------------
// Summarize system prompt
// ---------------------------------------------------------------------------

const SUMMARIZE_PROMPT = `你是一个 Minecraft 基岩版命令助手的结果汇总专家。

**重要：你必须始终使用中文回复，不允许使用任何其他语言。**
**⚠️ 你的回复必须只包含一个 JSON 对象，绝对不允许输出自由文本。**

## 你的职责

汇总多个 TaskAgent 的执行结果，生成：
1. 整体方案解释
2. 每条命令的命令方块元数据（type, conditional, auto, needs_redstone）
3. 按阶段分组

## 命令方块类型规则

| 类型 | block_type | 使用场景 |
|------|-----------|---------|
| 脉冲 | impulse | 一次性初始化命令 |
| 循环 | repeating | 持续检测/持续执行的第一条命令 |
| 连锁 | chain | 链条中的后续命令（跟在 impulse 或 repeating 后面） |

- 每个独立机制的第一条命令：continuous 用 repeating，once 用 impulse
- 同一机制的后续命令用 chain
- chain 方块 auto=true, needs_redstone=false
- repeating 方块 auto=true, needs_redstone=false
- impulse 方块 auto=false, needs_redstone=true

## 输出格式

\`\`\`json
{
  "explanation": "整体方案解释（用户可读的中文描述）",
  "phases": [
    {
      "phase_name": "阶段名称",
      "description": "阶段说明",
      "tasks": [
        {
          "task_id": "1",
          "description": "任务描述",
          "commands": ["命令名"],
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
\`\`\`
`

// ---------------------------------------------------------------------------
// MainAgent
// ---------------------------------------------------------------------------

export class MainAgent {
  /**
   * Decompose user input into TaskDefinitions.
   *
   * Returns a dict: {project_name, overview, tasks[], is_single_task, _thinking}
   */
  async decompose(
    userInput: string,
    sessionContext: string = '',
  ): Promise<Record<string, any>> {
    const messages: ChatMessage[] = [
      { role: 'system', content: DECOMPOSE_PROMPT },
    ]

    if (sessionContext) {
      messages.push({
        role: 'system',
        content: `## 对话历史\n${sessionContext}`,
      })
    }

    messages.push({ role: 'user', content: userInput })

    try {
      const response = await llmClient.chat(messages)

      const msg = response.message
      const thinking = msg.thinking ?? ''
      const content = msg.content ?? ''

      const result = extractJson(content)
      if (result && typeof result === 'object' && 'tasks' in (result as any)) {
        ;(result as any)._thinking = thinking
        return result as Record<string, any>
      }

      // Fallback: couldn't parse -> single task with original request
      console.warn('[MainAgent.decompose] JSON parse failed, content:', content.slice(0, 300))
      return this.fallbackSingleTask(userInput, thinking)
    } catch (e: any) {
      console.error('[MainAgent.decompose] failed:', e)
      return this.fallbackSingleTask(userInput)
    }
  }

  /**
   * Summarize multiple TaskAgent results into a unified project.
   */
  async summarize(
    userInput: string,
    taskResults: Array<Record<string, any>>,
  ): Promise<Record<string, any>> {
    // Build context from task results
    const resultsText: string[] = []
    for (const tr of taskResults) {
      const taskId = tr.task_id ?? '?'
      const desc = tr.description ?? ''
      const mode = tr.execution_mode ?? 'continuous'
      const result = tr.result ?? {}
      const resultType = result.type ?? ''

      resultsText.push(`### Task ${taskId}: ${desc}`)
      resultsText.push(`- execution_mode: ${mode}`)

      if (resultType === 'single_command') {
        const cmdObj = result.command ?? {}
        if (typeof cmdObj === 'object') {
          const cmdStr = cmdObj.command ?? ''
          const explanation = cmdObj.explanation ?? ''
          resultsText.push(`- 命令: ${cmdStr}`)
          if (explanation) {
            resultsText.push(`- 解释: ${explanation}`)
          }
        }
      } else if (resultType === 'project') {
        const phases = result.phases ?? []
        for (const phase of phases) {
          for (const task of phase.tasks ?? []) {
            for (const block of task.command_blocks ?? []) {
              resultsText.push(`- 命令: ${block.command ?? ''}`)
            }
          }
        }
      }
    }

    const context = resultsText.join('\n')

    const messages: ChatMessage[] = [
      { role: 'system', content: SUMMARIZE_PROMPT },
      {
        role: 'user',
        content: `## 用户原始需求\n${userInput}\n\n## TaskAgent 执行结果\n${context}`,
      },
    ]

    try {
      const response = await llmClient.chat(messages)

      const msg = response.message
      const thinking = msg.thinking ?? ''
      const content = msg.content ?? ''

      const result = extractJson(content)
      if (result && typeof result === 'object' && 'phases' in (result as any)) {
        ;(result as any)._thinking = thinking
        return result as Record<string, any>
      }

      console.warn('[MainAgent.summarize] JSON parse failed')
      return { explanation: (content ?? '').slice(0, 500), phases: [] }
    } catch (e: any) {
      console.error('[MainAgent.summarize] failed:', e)
      return { explanation: `汇总失败: ${e}`, phases: [] }
    }
  }

  private fallbackSingleTask(
    userInput: string,
    thinking: string = '',
  ): Record<string, any> {
    return {
      project_name: userInput.slice(0, 30),
      overview: '',
      tasks: [
        {
          task_id: '1',
          description: userInput.slice(0, 20),
          user_request: userInput,
          recommended_commands: [],
          output_type: 'simple_command',
          execution_mode: 'once',
          depends_on: [],
        },
      ],
      is_single_task: true,
      _thinking: thinking,
    }
  }
}
