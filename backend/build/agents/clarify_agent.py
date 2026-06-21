"""ClarifyAgent — Analyses user requirements and decides whether clarification is needed.

Uses the build chat model (deepseek-chat) for fast, lightweight analysis.
Implements a 5-dimension gamification mechanism to decide whether to ask
clarifying questions or proceed directly with reasonable defaults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import BUILD_AGENT_MAX_TOKENS
from backend.skills.base import BaseSkill
from backend.subscription.llm_context import get_build_chat_client

logger = logging.getLogger(__name__)

_CLARIFY_PROMPT = """\
你是一个 Minecraft 基岩版（Bedrock Edition）命令方块项目需求分析专家。

**重要：你必须始终使用中文回复，不允许使用任何其他语言。**

## 你的职责

分析用户的构建需求，判断是否需要向用户澄清关键信息，并给出初步的步骤建议。

## 博弈判定规则

你需要评估以下 5 个维度，每个维度有"确定/模糊"两种状态：
1. **触发机制**：用户是否明确了何时/如何触发？（玩家操作、定时、条件触发）
2. **作用对象**：目标实体/物品/玩家是否明确？（具体 ID 还是类别）
3. **具体参数**：数值、范围、坐标等是否给出或可合理推断？
4. **反馈方式**：用户是否提及输出反馈（消息/标题/粒子/音效等）？
5. **边界条件**：是否有潜在的异常情况需要确认？（玩家下线、数值溢出、多人冲突）

判定逻辑：
- 若 ≥3 个维度模糊 → needs_clarification = true，列出对应问题
- 若 1-2 个维度模糊但影响核心逻辑 → needs_clarification = true
- 若 1-2 个维度模糊但可用合理默认值 → needs_clarification = false，\
在 requirements_summary 中说明使用了哪些默认假设
- 若 0 个维度模糊 → needs_clarification = false

同时判断是否需要搜索补充知识：
- needs_search = true 当涉及不常见的命令用法、版本特定特性、\
或需要查证基岩版是否支持某功能时

## 输出格式

**只输出 JSON 对象，不要输出其他内容。**

```json
{{
  "needs_clarification": true,
  "requirements_summary": "对用户需求的理解摘要，包含确定的部分和假设的默认值",
  "questions": [
    {{
      "question": "面向用户的自然语言问题",
      "options": ["选项A", "选项B", "选项C"],
      "default": "推荐的默认选项"
    }}
  ],
  "suggested_steps": ["步骤1概述", "步骤2概述"],
  "needs_search": false,
  "search_queries": []
}}
```

## 注意事项

1. questions 数组在 needs_clarification=false 时应为空数组
2. 每个问题最多 4 个选项，必须包含 default 推荐值
3. 问题数量控制在 2-4 个，聚焦最关键的模糊维度
4. suggested_steps 应为 2-6 个初步步骤建议
5. search_queries 应为具体的搜索关键词（如 "基岩版 /ride 命令用法"）
"""


@dataclass
class ClarifyResult:
    """Result of the clarification analysis."""

    needs_clarification: bool = False
    requirements_summary: str = ""
    questions: list[dict[str, Any]] = field(default_factory=list)
    suggested_steps: list[str] = field(default_factory=list)
    needs_search: bool = False
    search_queries: list[str] = field(default_factory=list)


class ClarifyAgent:
    """Analyses user requirements and decides whether clarification is needed."""

    async def analyze(self, user_request: str) -> ClarifyResult:
        """Analyse the user's build request.

        Returns a ClarifyResult indicating whether clarification is needed,
        along with questions, suggested steps, and search recommendations.
        """
        messages = [
            {"role": "system", "content": _CLARIFY_PROMPT},
            {"role": "user", "content": user_request},
        ]

        try:
            client = get_build_chat_client()
            response = await client.chat(
                messages, max_tokens=BUILD_AGENT_MAX_TOKENS // 2,
            )

            content = response.get("message", {}).get("content", "")
            parsed = BaseSkill.extract_json(content)

            if isinstance(parsed, dict):
                return ClarifyResult(
                    needs_clarification=bool(parsed.get("needs_clarification", False)),
                    requirements_summary=parsed.get("requirements_summary", ""),
                    questions=parsed.get("questions", []),
                    suggested_steps=parsed.get("suggested_steps", []),
                    needs_search=bool(parsed.get("needs_search", False)),
                    search_queries=parsed.get("search_queries", []),
                )

            logger.warning("ClarifyAgent: JSON parse failed, content=%s", content[:300])
            return ClarifyResult(
                needs_clarification=False,
                requirements_summary=user_request,
            )

        except Exception as e:
            logger.error("ClarifyAgent.analyze failed: %s", e)
            return ClarifyResult(
                needs_clarification=False,
                requirements_summary=user_request,
            )


# Singleton
clarify_agent = ClarifyAgent()
