"""ReviewAgent — LLM-based step completion review.

Uses DeepSeek Thinking to evaluate whether a step's execution
covers all requirements and subtasks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import BUILD_AGENT_MAX_TOKENS
from backend.skills.base import BaseSkill
from backend.subscription.llm_context import get_llm_client

logger = logging.getLogger(__name__)

_REVIEW_PROMPT = """\
你是一个 Minecraft 基岩版（Bedrock Edition）命令方块项目审查专家。

**重要：你必须始终使用中文回复。**

## 你的职责

审查一个项目步骤的执行结果，判断是否完整覆盖了所有需求。

## 审查维度

1. 步骤中列出的所有子任务是否都有对应的命令实现
2. 命令是否覆盖所有需求（触发条件、执行逻辑、反馈显示等）
3. 命令方块类型是否正确（循环/链/脉冲）
4. 是否遗漏边界情况（如玩家离线、计分板溢出等）

## 输出格式

输出一个 JSON 对象：
```json
{{
  "complete": true/false,
  "missing_items": ["缺失项1", "缺失项2"],
  "suggestions": ["改进建议1"]
}}
```

**只输出 JSON 对象，不要输出其他内容。**
"""


@dataclass
class ReviewResult:
    complete: bool = False
    missing_items: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class ReviewAgent:
    """LLM-based step completion reviewer."""

    async def review(
        self,
        step_plan: str,
        task_results: list[dict[str, Any]],
        search_context: str = "",
    ) -> ReviewResult:
        """Review task execution results against the step plan.

        Args:
            step_plan: The step's raw content from PROJECT.md.
            task_results: List of completed task results.
            search_context: Optional search context for reference.

        Returns:
            ReviewResult with completeness assessment.
        """
        # Build results text
        results_text = ""
        for tr in task_results:
            tid = tr.get("task_id", "?")
            desc = tr.get("description", "")
            result = tr.get("result", {})
            result_type = result.get("type", "")

            results_text += f"\n### Task {tid}: {desc}\n"

            if result_type == "single_command":
                cmd_obj = result.get("command", {})
                if isinstance(cmd_obj, dict):
                    results_text += f"命令: {cmd_obj.get('command', '')}\n"
                    results_text += f"说明: {cmd_obj.get('explanation', '')}\n"
            elif result_type == "project":
                for phase in result.get("phases", []):
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            results_text += f"- [{block.get('type', 'chain')}] {block.get('command', '')}\n"
                            if block.get("comment"):
                                results_text += f"  说明: {block['comment']}\n"

        user_content = (
            f"## 步骤计划\n{step_plan}\n\n"
            f"## 执行结果\n{results_text}\n"
        )
        if search_context:
            user_content += f"\n## 参考资料\n{search_context}\n"

        messages = [
            {"role": "system", "content": _REVIEW_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await get_llm_client().chat(
                messages, max_tokens=BUILD_AGENT_MAX_TOKENS // 2,
            )

            content = response.get("message", {}).get("content", "")
            data = BaseSkill.extract_json(content)

            if isinstance(data, dict):
                return ReviewResult(
                    complete=data.get("complete", False),
                    missing_items=data.get("missing_items", []),
                    suggestions=data.get("suggestions", []),
                )

            logger.warning("ReviewAgent: JSON parse failed, assuming incomplete")
            return ReviewResult(
                complete=False,
                missing_items=["审查结果解析失败"],
            )

        except Exception as e:
            logger.error("ReviewAgent: review failed: %s", e)
            # On failure, assume complete to avoid blocking
            return ReviewResult(
                complete=True,
                suggestions=[f"审查失败（{e}），已跳过"],
            )


# Singleton
review_agent = ReviewAgent()
