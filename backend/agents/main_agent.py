"""Main Agent — Coordinator with two methods: decompose() + summarize().

Replaces the old Tool Calling loop architecture. Now uses a single LLM call
for task decomposition and another for result summarization.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.config import DECOMPOSE_MAX_TOKENS, SUMMARY_MAX_TOKENS
from backend.skills.base import BaseSkill
from backend.subscription.llm_context import get_llm_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decompose system prompt
# ---------------------------------------------------------------------------

_DECOMPOSE_PROMPT = """\
你是一个 Minecraft 基岩版（Bedrock Edition）命令助手的任务分解专家。

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
- 大多数多任务场景中，任务之间是**相互独立**的，可以并行执行 → `depends_on: []`
- **仅当后一个任务的命令生成必须依赖前一个任务的结果（如标签名、计分板名）时**，才设置依赖
- 常见依赖场景：
  - 任务 B 需要使用任务 A 创建/定义的标签名称或计分板名称
  - 任务 B 的目标选择器必须引用任务 A 定义的标签
  - 用户明确要求先做 A 再做 B 的顺序关系
- 不需要依赖的场景（保持并行）：
  - 两个任务使用不同的命令且互不引用
  - 命令生成本身不需要等待另一个任务的具体参数值
- depends_on 填写的是**前置任务的 task_id 列表**
- **禁止循环依赖**：依赖方向必须单向（低 ID → 高 ID）

## 输出格式

```json
{{
  "project_name": "项目名称（简短描述）",
  "overview": "整体方案概述",
  "tasks": [
    {{
      "task_id": "1",
      "description": "简短描述（20字内）",
      "user_request": "给 TaskAgent 的自包含自然语言描述",
      "recommended_commands": ["execute", "tag"],
      "output_type": "execute_chain",
      "execution_mode": "continuous",
      "depends_on": []
    }},
    {{
      "task_id": "2",
      "description": "依赖任务1结果的后续任务",
      "user_request": "自包含描述（会自动注入前置任务结果）",
      "recommended_commands": ["execute", "clear"],
      "output_type": "execute_chain",
      "execution_mode": "continuous",
      "depends_on": ["1"]
    }}
  ],
  "is_single_task": false
}}
```

"""

# ---------------------------------------------------------------------------
# Summarize system prompt
# ---------------------------------------------------------------------------

_SUMMARIZE_PROMPT = """\
你是一个 Minecraft 基岩版命令助手的结果汇总专家。

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

```json
{{
  "explanation": "整体方案解释（用户可读的中文描述）",
  "phases": [
    {{
      "phase_name": "阶段名称",
      "description": "阶段说明",
      "tasks": [
        {{
          "task_id": "1",
          "description": "任务描述",
          "commands": ["命令名"],
          "command_blocks": [
            {{
              "type": "repeating",
              "conditional": false,
              "needs_redstone": false,
              "command": "/具体命令",
              "comment": "作用说明"
            }}
          ],
          "dependencies": []
        }}
      ]
    }}
  ]
}}
```
"""


class MainAgent:
    """Coordinator that decomposes user requests and summarizes results."""

    async def decompose(
        self,
        user_input: str,
        session_context: str = "",
    ) -> dict[str, Any]:
        """Decompose user input into TaskDefinitions.

        Returns a DecompositionResult-like dict:
            {"project_name": "...", "overview": "...", "tasks": [...], "is_single_task": bool}
        """
        system_prompt = _DECOMPOSE_PROMPT

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if session_context:
            messages.append({
                "role": "system",
                "content": f"## 对话历史\n{session_context}",
            })
        messages.append({"role": "user", "content": user_input})

        try:
            response = await get_llm_client().chat(
                messages,
                max_tokens=DECOMPOSE_MAX_TOKENS,
                think=True,
            )

            msg = response.get("message", {})
            thinking = msg.get("thinking", "")
            content = msg.get("content", "")

            logger.info(
                "MainAgent.decompose: thinking=%d chars, content=%d chars",
                len(thinking), len(content),
            )

            result = BaseSkill.extract_json(content)
            if isinstance(result, dict) and "tasks" in result:
                result["_thinking"] = thinking
                return result

            # Fallback: couldn't parse → single task with original request
            logger.warning("MainAgent.decompose: JSON parse failed, content=%s", content[:300])
            return self._fallback_single_task(user_input, thinking)

        except Exception as e:
            logger.error("MainAgent.decompose failed: %s", e)
            return self._fallback_single_task(user_input)

    async def summarize(
        self,
        user_input: str,
        task_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Summarize multiple TaskAgent results into a unified project.

        Args:
            user_input: Original user request.
            task_results: List of {"task_id", "description", "execution_mode", "result"}.

        Returns:
            Dict with explanation, phases, command_blocks metadata.
        """
        # Build context from task results
        results_text = []
        for tr in task_results:
            task_id = tr.get("task_id", "?")
            desc = tr.get("description", "")
            mode = tr.get("execution_mode", "continuous")
            result = tr.get("result", {})
            result_type = result.get("type", "")

            results_text.append(f"### Task {task_id}: {desc}")
            results_text.append(f"- execution_mode: {mode}")

            if result_type == "single_command":
                cmd_obj = result.get("command", {})
                if isinstance(cmd_obj, dict):
                    cmd_str = cmd_obj.get("command", "")
                    explanation = cmd_obj.get("explanation", "")
                    results_text.append(f"- 命令: {cmd_str}")
                    if explanation:
                        results_text.append(f"- 解释: {explanation}")
            elif result_type == "project":
                phases = result.get("phases", [])
                for phase in phases:
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            results_text.append(f"- 命令: {block.get('command', '')}")

        context = "\n".join(results_text)

        messages = [
            {"role": "system", "content": _SUMMARIZE_PROMPT},
            {
                "role": "user",
                "content": f"## 用户原始需求\n{user_input}\n\n## TaskAgent 执行结果\n{context}",
            },
        ]

        try:
            response = await get_llm_client().chat(
                messages,
                max_tokens=SUMMARY_MAX_TOKENS,
                think=True,
            )

            msg = response.get("message", {})
            thinking = msg.get("thinking", "")
            content = msg.get("content", "")

            result = BaseSkill.extract_json(content)
            if isinstance(result, dict) and "phases" in result:
                result["_thinking"] = thinking
                return result

            logger.warning("MainAgent.summarize: JSON parse failed")
            return {"explanation": content[:500], "phases": []}

        except Exception as e:
            logger.error("MainAgent.summarize failed: %s", e)
            return {"explanation": f"汇总失败: {e}", "phases": []}

    @staticmethod
    def _fallback_single_task(
        user_input: str,
        thinking: str = "",
    ) -> dict[str, Any]:
        """Create a single-task decomposition as fallback."""
        return {
            "project_name": user_input[:30],
            "overview": "",
            "tasks": [
                {
                    "task_id": "1",
                    "description": user_input[:20],
                    "user_request": user_input,
                    "recommended_commands": [],
                    "output_type": "simple_command",
                    "execution_mode": "once",
                    "depends_on": [],
                }
            ],
            "is_single_task": True,
            "_thinking": thinking,
        }
