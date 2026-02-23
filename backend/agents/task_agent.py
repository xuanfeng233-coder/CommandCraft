"""TaskAgent — self-contained agent for executing a single TaskDefinition.

Each TaskAgent independently: RAG retrieves → LLM generates → validates.
Migrated prompt templates from command_generator.py.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from backend.config import TASK_AGENT_MAX_TOKENS
from backend.rag.retriever import rag_retriever
from backend.skills.base import BaseSkill
from backend.skills.command_validator import command_validator
from backend.subscription.llm_context import get_llm_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base template (~300 tokens) — shared across all output types
# ---------------------------------------------------------------------------

_BASE_TEMPLATE = """\
你是一个 Minecraft 基岩版（Bedrock Edition）命令生成专家。基于提供的命令文档和上下文，生成准确的基岩版命令。

**重要：你必须始终使用中文回复，不允许使用任何其他语言。**

## 基岩版 vs Java 版关键差异（你必须严格遵守）

### ID 与命名空间
- 基岩版物品/实体/效果等 ID **不加 minecraft: 前缀**：用 `diamond_sword` 而非 `minecraft:diamond_sword`

### 方块状态语法
- 基岩版使用 `["state_name"=value]` 格式
- 示例：`/setblock ~ ~ ~ stone ["stone_type"="granite"]`

### 基岩版不支持的功能（仅以下功能不支持，其他命令均可正常使用）
- **无 NBT 标签**：/give 和 /summon 完全不支持 NBT 标签！
  - /give 不能附加附魔、自定义名称、耐久度等任何 NBT 数据
  - /give 仅支持 4 种组件：can_place_on, can_destroy, item_lock, keep_on_death
  - /summon 不能设置实体装备、血量、属性等任何 NBT 数据
  - **绝对不要生成类似 /give @s diamond_sword 1 0 {{"Enchantments":[...]}} 这样的 Java 版语法！**
- **无 /data 命令**、**无 /execute store**
- **计分板仅 dummy 类型**（无法自动追踪，但 /scoreboard 命令本身完全可用）
- **无 /team**、无 /bossbar、无 /worldborder、无 /attribute、无 /item（用 /replaceitem）

### 基岩版独有选择器参数（所有使用目标选择器的命令都适用！）
- **hasitem** — 检测背包/装备物品（⚠️参数名是 `hasitem` 不是 `item`！`item=` 不是有效选择器参数）
  - 基本: `@a[hasitem={{item=diamond_sword,quantity=1..}}]`
  - 无物品: `@a[hasitem={{item=bow,quantity=0}}]`
  - 指定槽位: `@a[hasitem={{item=diamond_helmet,location=slot.armor.head}}]`
  - 多物品(AND): `@a[hasitem=[{{item=diamond_sword}},{{item=shield}}]]`
  - 槽位: `slot.weapon.mainhand`(主手), `slot.weapon.offhand`(副手), `slot.armor.head/chest/legs/feet`(装备)
- **haspermission** — 检测权限: `@a[haspermission={{camera=enabled,movement=disabled}}]`
- **has_property** — 检测实体属性: `@e[has_property={{minecraft:variant=2}}]`

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

{retrieved_context}

## 追问格式（所有输出类型通用）

当参数不足或需求存在歧义、需要用户补充信息时，**必须**使用以下 JSON 格式进行追问，而不是直接用自然语言提问：
```json
{{
  "type": "conversation",
  "questions": [
    {{
      "param": "参数名称",
      "question": "面向用户的自然语言提问",
      "options": [{{"value": "选项值", "label": "显示文本"}}],
      "default": "默认值建议（可为null）"
    }}
  ],
  "current_progress": "当前已确定的参数摘要"
}}
```

## ⚠️ 输出约束（严格遵守）

**你的回复必须只包含一个 JSON 对象，不允许有任何其他文字、解释或 Markdown 格式。**
直接输出 JSON，不要用 ```json ``` 代码块包裹。
"""

# ---------------------------------------------------------------------------
# Type-specific sections (migrated from command_generator.py)
# ---------------------------------------------------------------------------

_SIMPLE_COMMAND_SECTION = """\
## 命令生成规则

### 常见命令语法差异
- `/give <player> <itemName> [amount] [data] [components]` — components 仅支持 can_place_on, can_destroy, item_lock, keep_on_death
- `/summon <entityType> [pos] [yRot] [xRot] [spawnEvent] [nameTag]` — 无 NBT 数据
- `/effect <target> <effect> [seconds] [amplifier] [hideParticles]` — 清除用 `effect <target> clear`
- `/enchant <target> <enchantName> [level]` — 不需要命名空间
- `/xp <amount>[L] [player]` — 用 L 后缀表示等级
- `/particle <effect> [position]` — 极简版
- `/playsound <sound> [player] [position] [volume] [pitch] [minVolume]`
- `/replaceitem` — 基岩版用这个，Java 版用 `/item`
- `/fill <from> <to> <block> [blockStates] [oldBlockHandling]`
- `/setblock <pos> <block> [blockStates] [destroy|keep|replace]`
- `/clear <player> [itemName] [data] [maxCount]`

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
```json
{{
  "type": "single_command",
  "command": {{
    "command": "/完整命令字符串",
    "explanation": "命令各部分的详细解释",
    "variants": ["可选的变体写法"],
    "warnings": ["注意事项"]
  }}
}}
```

### 格式2: 参数追问（参数不足或有歧义时）
```json
{{
  "type": "conversation",
  "questions": [
    {{
      "param": "参数名",
      "question": "面向用户的自然语言提问",
      "options": [{{"value": "选项值", "label": "显示文本"}}],
      "default": "默认值建议"
    }}
  ],
  "current_progress": "当前已确定的参数摘要"
}}
```
"""

_EXECUTE_CHAIN_SECTION = """\
## 基岩版 execute 完整子命令参考（1.19.50+ 新语法）

### 修饰子命令
| 子命令 | 语法 | 说明 |
|--------|------|------|
| `align` | `align <axes>` | 对齐到方块网格 |
| `anchored` | `anchored <eyes｜feet>` | 设置执行锚点 |
| `as` | `as <目标选择器>` | 改变执行者身份 |
| `at` | `at <目标选择器>` | 改变执行位置/旋转/维度 |
| `facing` | `facing <x y z>` 或 `facing entity <目标> <eyes｜feet>` | 设置朝向 |
| `in` | `in <dimension>` | 切换维度 |
| `positioned` | `positioned <x y z>` 或 `positioned as <目标>` | 更新位置 |
| `rotated` | `rotated <yaw> <pitch>` 或 `rotated as <目标>` | 设置旋转 |

### 条件子命令（if/unless）
| 条件 | 语法 | 说明 |
|------|------|------|
| 方块检测 | `if/unless block <x y z> <方块ID> [方块状态]` | 方块状态: `["state"=value]` |
| 区域比较 | `if/unless blocks <begin> <end> <dest> <all/masked>` | 比较两个区域 |
| 实体存在 | `if/unless entity <目标选择器>` | 检测实体 |
| 分数比较 | `if/unless score <目标1> <obj1> <运算符> <目标2> <obj2>` | `<`, `<=`, `=`, `>=`, `>` |
| 分数范围 | `if/unless score <目标> <obj> matches <范围>` | `5`, `1..10`, `10..`, `..20` |

### 执行子命令
`run <命令>` — **命令不加 / 前缀！**

### Java 版独有（基岩版不支持！）
- **`store`** — 基岩版完全没有此功能
- `on`, `summon`, `positioned over`, `if/unless biome|data|loaded|predicate|items|function`

### 常用模式
- 在所有玩家位置执行: `execute as @a at @s run <命令>`
- 条件检测: `execute if entity @e[type=zombie,r=10] run say 附近有僵尸`
- 组合条件: `execute as @a at @s if block ~ ~-1 ~ gold_block run effect @s speed 1 1`
- 检测持有物品: `execute as @a[hasitem={{item=tnt}}] run tag @s add WARN`（⚠️用 hasitem 不是 item）

### 规则
1. 严格使用基岩版 execute 新语法（1.19.50+）
2. **绝对不要使用 store 子命令**
3. **`run` 后面的命令不加 `/` 前缀**

## 输出格式
```json
{{
  "type": "single_command",
  "command": {{
    "command": "/execute ... run 命令",
    "explanation": "命令链逐段解释",
    "chain_breakdown": [
      {{"subcommand": "as", "value": "@a", "purpose": "以每个玩家身份执行"}}
    ],
    "variants": [],
    "warnings": []
  }}
}}
```
"""

_RAWTEXT_SECTION = """\
## 基岩版 rawtext 完整格式规范

### 根结构
基岩版 rawtext 根**必须**是 `{{"rawtext": [组件1, 组件2, ...]}}`

### 4 种组件类型
1. **text**: `{{"text": "§c红色文字§r 普通文字"}}`
2. **selector**: `{{"selector": "@s"}}`
3. **score**: `{{"score": {{"name": "@s", "objective": "kills"}}}}`
4. **translate**: `{{"translate": "Hello %%1", "with": {{"rawtext": [{{"text": "Steve"}}]}}}}`

### 不支持的功能（Java 版独有）
clickEvent, hoverEvent, color 属性, bold/italic 属性, font, insertion, keybind, nbt 组件

### 颜色代码（§）
§0-§f 标准16色 | §g-§v 基岩版独有材质色
§k 混淆 | §l 加粗 | §o 斜体 | §r 重置

### 使用命令
- `/tellraw <目标> <rawtext JSON>` — 聊天消息
- `/titleraw <目标> title|subtitle|actionbar <rawtext JSON>` — 标题/副标题/动作栏

### 规则
1. JSON 根结构必须是 `{{"rawtext": [...]}}`
2. 颜色用 § 代码，不用 JSON 属性
3. 不要用 clickEvent, hoverEvent 等 Java 版属性

## 输出格式
```json
{{
  "type": "single_command",
  "command": {{
    "command": "/tellraw @a {{...rawtext JSON...}}",
    "explanation": "rawtext 各组件解释",
    "preview": "模拟的显示效果纯文本",
    "variants": [],
    "warnings": []
  }}
}}
```
"""

_SELECTOR_SECTION = """\
## 基岩版选择器完整参考

### 选择器类型
| 选择器 | 选择目标 |
|--------|---------|
| `@a` | 所有在线玩家（含死亡） |
| `@e` | 所有存活实体+在线玩家 |
| `@p` | 最近的存活玩家 |
| `@r` | 随机存活玩家 |
| `@s` | 命令执行者自身 |
| `@initiator` | NPC对话发起者（基岩版独有） |

### 全部选择器参数

#### 基岩版独有参数（重要！）

**hasitem — 物品检测:**
- 基本: `@a[hasitem={{item=diamond_sword,quantity=1..}}]`
- 无物品: `@a[hasitem={{item=bow,quantity=0}}]`
- 特定槽位: `@a[hasitem={{item=diamond_helmet,location=slot.armor.head}}]`
- 多物品(AND): `@a[hasitem=[{{item=diamond_sword}},{{item=shield}}]]`

**haspermission — 权限检测:**
- `@a[haspermission={{camera=enabled,movement=disabled}}]`

**has_property — 实体属性检测:**
- `@e[has_property={{minecraft:variant=2}}]`

### 规则
1. 使用基岩版语法（r=/rm= 而非 distance=, c= 而非 limit=）
2. 输出完整命令（不仅是选择器）
3. ID 不加 minecraft: 前缀

## 输出格式
```json
{{
  "type": "single_command",
  "command": {{
    "command": "/完整命令（含选择器）",
    "explanation": "选择器各部分解释",
    "selector_breakdown": {{
      "base": "@e",
      "conditions": [
        {{"key": "type", "value": "zombie", "explanation": "仅选择僵尸"}}
      ]
    }},
    "variants": [],
    "warnings": []
  }}
}}
```
"""

_PROJECT_SECTION = """\
## 命令方块项目规划

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
4. `execute ... run` 后面的命令不加 `/` 前缀

### 常见模式
- **定时器**: 计分板每tick+1，达到目标值触发动作
- **标签状态机**: tag管理实体多状态

## 输出格式
```json
{{
  "type": "project",
  "project_name": "项目名称",
  "overview": "整体方案概述",
  "phases": [
    {{
      "phase_name": "阶段名称",
      "description": "阶段说明",
      "tasks": [
        {{
          "task_id": "1",
          "description": "任务描述",
          "commands": ["涉及的命令名称"],
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

# Map output_type to section
_TYPE_SECTIONS: dict[str, str] = {
    "simple_command": _SIMPLE_COMMAND_SECTION,
    "execute_chain": _EXECUTE_CHAIN_SECTION,
    "rawtext": _RAWTEXT_SECTION,
    "selector": _SELECTOR_SECTION,
    "project": _PROJECT_SECTION,
}


class TaskAgent:
    """Self-contained agent that executes a single TaskDefinition.

    Flow:
    1. RAG retrieve context (smart: common cmds exact-only, no intents)
    2. LLM generate with type-specific prompt
    3. Detect parameter-missing (conversation type) → pause
    4. Validate result
    """

    async def execute(
        self,
        task_def: dict[str, Any],
        ambiguous: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a task definition, yielding SSE events.

        Yields:
            {"event": "task_update", "data": {"task_id": ..., "status": "retrieving|generating|validating|paused|completed|failed", ...}}
            {"event": "task_thinking", "data": {"task_id": ..., "text": ...}}
        """
        task_id = task_def.get("task_id", "1")
        user_request = task_def.get("user_request", "")
        recommended_commands = task_def.get("recommended_commands", [])
        output_type = task_def.get("output_type", "simple_command")

        # Step 1: RAG retrieve (with output_type for smart retrieval)
        yield _task_event(task_id, "retrieving")

        retrieved_context = ""
        try:
            ctx = await rag_retriever.retrieve_context(
                query=user_request,
                exact_command_names=recommended_commands or None,
                output_type=output_type,
            )
            retrieved_context = ctx.to_prompt_text_compact()
        except Exception as e:
            logger.warning("TaskAgent %s: RAG retrieval failed: %s", task_id, e)

        # Step 2: LLM generate
        yield _task_event(task_id, "generating")

        if ambiguous:
            retrieved_context += "\n\n## 歧义提示\n此需求存在歧义，请优先输出 conversation 类型进行追问。"

        try:
            system_prompt = self._build_prompt(output_type, retrieved_context)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_request},
            ]

            response = await get_llm_client().chat(
                messages,
                max_tokens=TASK_AGENT_MAX_TOKENS,
            )

            msg = response.get("message", {})
            thinking = msg.get("thinking", "")
            content = msg.get("content", "")

            if thinking:
                yield {
                    "event": "task_thinking",
                    "data": {"task_id": task_id, "text": thinking},
                }

            result = self._parse_output(content, output_type)
            if thinking:
                result["thinking"] = thinking

        except Exception as e:
            logger.error("TaskAgent %s: LLM generation failed: %s", task_id, e)
            yield _task_event(task_id, "failed", error=str(e))
            return

        # Step 3: Check if conversation (pause)
        if result.get("type") == "conversation":
            logger.info("TaskAgent %s: needs user input — pausing", task_id)
            yield _task_event(task_id, "paused", result=result)
            return

        # Step 4: Validate
        yield _task_event(task_id, "validating")
        self._run_validation(result)

        yield _task_event(task_id, "completed", result=result)

    def _build_prompt(self, output_type: str, retrieved_context: str) -> str:
        """Assemble the full system prompt from base + type section + context."""
        type_section = _TYPE_SECTIONS.get(output_type, _SIMPLE_COMMAND_SECTION)
        return _BASE_TEMPLATE.format(
            type_specific_section=type_section,
            retrieved_context=retrieved_context,
        )

    def _parse_output(self, raw: str, output_type: str) -> dict[str, Any]:
        """Parse raw LLM output into structured data."""
        data = BaseSkill.extract_json(raw)

        if isinstance(data, dict) and "type" in data:
            return self._normalize_output(data)

        # JSON extraction failed — detect if this is a conversational response
        if raw and self._looks_like_conversation(raw):
            logger.info("_parse_output: JSON failed but detected conversational text, wrapping as conversation type")
            return {
                "type": "conversation",
                "questions": [
                    {
                        "param": "user_clarification",
                        "question": raw.strip(),
                        "options": [],
                        "default": None,
                    }
                ],
                "current_progress": "",
            }

        if output_type == "project":
            return {
                "type": "project",
                "project_name": "解析失败",
                "overview": raw[:500] if raw else "",
                "phases": [],
            }
        else:
            return {
                "type": "single_command",
                "command": {
                    "command": "",
                    "explanation": raw[:500] if raw else "",
                    "variants": [],
                    "warnings": ["JSON 解析失败，请查看原始输出"],
                },
            }

    @staticmethod
    def _looks_like_conversation(text: str) -> bool:
        """Heuristic: detect if raw text is a parameter refinement question.

        Triggers when the LLM outputs free-form text asking the user for
        clarification instead of structured JSON.
        """
        has_question = "？" in text or "?" in text
        # Strong conversational keywords (asking user for input)
        strong_keywords = ("请提供", "请指定", "请选择", "请确认", "请告诉",
                           "需要您", "需要你", "以下信息")
        has_strong_keyword = any(kw in text for kw in strong_keywords)
        # Weaker question keywords (need more evidence)
        weak_keywords = ("哪种", "哪个", "什么类型", "什么物品", "什么方块", "什么实体")
        has_weak_keyword = any(kw in text for kw in weak_keywords)
        # Numbered list (common in parameter questions)
        has_numbered_list = any(f"{i}." in text or f"{i}、" in text or f"{i}. " in text
                                for i in range(1, 6))
        # No valid command — rules out text that starts with a slash command
        text_stripped = text.strip()
        starts_with_command = text_stripped.startswith("/")

        if starts_with_command:
            return False
        # Strong keyword alone is sufficient (e.g. "请提供以下信息：")
        if has_strong_keyword:
            return True
        # Weak keyword + question mark
        if has_weak_keyword and has_question:
            return True
        # Question mark + numbered list
        if has_question and has_numbered_list:
            return True
        return False

    @staticmethod
    def _normalize_output(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize execute_chain/selector/rawtext types to single_command."""
        result_type = data.get("type", "")

        if result_type in ("execute_chain", "selector", "rawtext"):
            cmd_obj = data.get("command")
            commands_arr = data.get("commands")

            if cmd_obj is None and isinstance(commands_arr, list):
                cmd_strs = []
                for item in commands_arr:
                    if isinstance(item, str):
                        cmd_strs.append(item)
                    elif isinstance(item, dict) and "command" in item:
                        cmd_strs.append(item["command"])
                merged_cmd = "\n".join(cmd_strs) if cmd_strs else ""
                cmd_obj = {
                    "command": merged_cmd,
                    "explanation": data.get("explanation", ""),
                    "variants": data.get("variants", []),
                    "warnings": data.get("warnings", []),
                }
            elif isinstance(cmd_obj, str):
                cmd_obj = {
                    "command": cmd_obj,
                    "explanation": data.get("explanation", ""),
                    "variants": data.get("variants", []),
                    "warnings": data.get("warnings", []),
                }

            if isinstance(cmd_obj, dict):
                for key in ("chain_breakdown", "selector_breakdown", "preview"):
                    if key in data and key not in cmd_obj:
                        cmd_obj[key] = data[key]

            data["type"] = "single_command"
            data["command"] = cmd_obj or {
                "command": "",
                "explanation": "",
                "variants": [],
                "warnings": [],
            }
            data.pop("commands", None)

        return data

    @staticmethod
    def _run_validation(content_data: dict[str, Any]) -> None:
        """Run CommandValidator and merge results into content_data in-place."""
        command_obj = content_data.get("command")
        if not command_obj or not isinstance(command_obj, dict):
            return
        cmd_str = command_obj.get("command", "")
        if not cmd_str:
            return

        cmd_lines = [line.strip() for line in cmd_str.split("\n") if line.strip()]

        try:
            results = command_validator.validate(cmd_lines)
            if not results:
                return

            all_errors = []
            all_warnings = []
            all_valid = True

            for validation in results:
                errors = validation.get("errors", [])
                warnings_list = [w["message"] for w in validation.get("warnings", [])]
                if errors:
                    all_valid = False
                    for err in errors:
                        all_errors.append(
                            f"[{err['type']}] {err['message']} — {err.get('suggestion', '')}"
                        )
                all_warnings.extend(warnings_list)

            existing = command_obj.get("warnings") or []
            existing.extend(all_errors)
            existing.extend(all_warnings)
            if existing:
                command_obj["warnings"] = existing

            command_obj["validation"] = {
                "valid": all_valid,
                "error_count": len(all_errors),
            }
        except Exception as e:
            logger.warning("CommandValidator failed: %s", e)


def _task_event(
    task_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a task_update SSE event."""
    data: dict[str, Any] = {"task_id": task_id, "status": status}
    if result is not None:
        data["result"] = result
    if error is not None:
        data["error"] = error
    return {"event": "task_update", "data": data}
