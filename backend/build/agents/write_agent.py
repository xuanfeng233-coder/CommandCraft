"""WriteAgent — LLM-based plan document generator and updater.

Uses DeepSeek Thinking for structured Markdown plan generation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.config import BUILD_AGENT_MAX_TOKENS
from backend.skills.base import BaseSkill
from backend.subscription.llm_context import get_build_chat_client

logger = logging.getLogger(__name__)

_CREATE_PLAN_PROMPT = """\
你是一个 Minecraft 基岩版（Bedrock Edition）命令方块项目规划专家。

**重要：你必须始终使用中文回复，不允许使用任何其他语言。**

## 你的职责

根据用户需求和任务分析结果，生成结构化的项目方案文档（Markdown 格式）。

## 输出格式要求

必须严格按照以下格式输出，不要添加额外内容：

```
# {{项目名称}}

## 概述
{{项目描述，2-3句}}

## 步骤 1: {{标题}} [ ]
**需求**: {{这一步要实现什么}}
**实现思路**: {{用什么命令/机制来实现}}
**涉及命令**: {{command1, command2}}
**子任务**:
- [ ] 子任务描述1
- [ ] 子任务描述2

## 步骤 2: {{标题}} [ ]
**需求**: ...
**实现思路**: ...
**涉及命令**: ...
**子任务**:
- [ ] ...

...更多步骤...
```

## 规则

1. 每个步骤应当是一个独立的功能模块
2. 步骤之间按依赖顺序排列（初始化 → 核心逻辑 → 反馈/展示）
3. 子任务应当可以被拆解为具体的命令生成任务
4. 涉及命令必须是基岩版支持的命令
5. **直接输出 Markdown 内容**，不要包裹在代码块中
"""

_MARK_DONE_PROMPT = """\
你是一个 Minecraft 基岩版项目文档更新专家。

**重要：你必须始终使用中文回复。**

## 你的职责

更新 PROJECT.md 中已完成步骤的状态标记和结果摘要。

## 当前 PROJECT.md
{current_md}

## 要更新的步骤
步骤 {step_index}

## 执行结果摘要
{summary}

## 生成的命令方块布局
{command_layout}

## 要求

1. 将 `## 步骤 {step_index}: ... [ ]` 改为 `## 步骤 {step_index}: ... [x]`
2. 将该步骤下的所有 `- [ ]` 改为 `- [x]`
3. 在该步骤末尾添加 `**执行结果**: {{结果摘要}}`
4. 保持其他步骤内容不变
5. **直接输出完整的更新后 Markdown 内容**
"""


class WriteAgent:
    """LLM-based plan document writer."""

    async def create_plan(
        self,
        user_request: str,
        clarify_context: Any | None = None,
        clarify_answers: dict[str, str] | None = None,
        search_results: list[Any] | None = None,
    ) -> str:
        """Generate a PROJECT.md plan from clarification analysis and search results.

        Args:
            user_request: Original user request.
            clarify_context: ClarifyResult from ClarifyAgent (has requirements_summary,
                suggested_steps).
            clarify_answers: User answers to clarification questions (question → answer).
            search_results: Optional search results from SearchAgent.

        Returns the Markdown content string.
        """
        user_content = f"## 用户需求\n{user_request}\n\n"

        if clarify_context:
            summary = getattr(clarify_context, "requirements_summary", "")
            if summary:
                user_content += f"## 需求分析\n{summary}\n\n"

            steps = getattr(clarify_context, "suggested_steps", [])
            if steps:
                user_content += "## 建议步骤\n"
                for i, s in enumerate(steps, 1):
                    user_content += f"{i}. {s}\n"
                user_content += "\n"

        if clarify_answers:
            user_content += "## 用户补充信息\n"
            for q, a in clarify_answers.items():
                user_content += f"- {q}: {a}\n"
            user_content += "\n"

        if search_results:
            user_content += "## 参考资料\n"
            for sr in search_results:
                if hasattr(sr, "summary") and sr.summary:
                    user_content += f"- {sr.title}: {sr.summary}\n"
                elif hasattr(sr, "content"):
                    user_content += f"- {sr.title}: {sr.content[:200]}\n"

        messages = [
            {"role": "system", "content": _CREATE_PLAN_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = await get_build_chat_client().chat(
            messages, max_tokens=BUILD_AGENT_MAX_TOKENS // 2,
        )

        content = response.get("message", {}).get("content", "")

        # Strip any code block wrappers
        content = self._strip_code_block(content)

        return content.strip()

    async def mark_step_done(
        self,
        md_content: str,
        step_index: int,
        summary: str,
        command_layout: str = "",
    ) -> str:
        """Update PROJECT.md to mark a step as completed.

        Returns the updated Markdown content.
        """
        prompt = _MARK_DONE_PROMPT.format(
            current_md=md_content,
            step_index=step_index,
            summary=summary,
            command_layout=command_layout or "（无）",
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"请更新步骤 {step_index} 的状态为已完成。"},
        ]

        response = await get_build_chat_client().chat(
            messages, max_tokens=BUILD_AGENT_MAX_TOKENS // 2,
        )

        content = response.get("message", {}).get("content", "")
        content = self._strip_code_block(content)

        # Sanity check: if the LLM returned something too short, do regex fallback
        if len(content.strip()) < len(md_content) * 0.5:
            logger.warning("WriteAgent: LLM output too short, using regex fallback")
            return self._regex_mark_done(md_content, step_index, summary)

        return content.strip()

    @staticmethod
    def _strip_code_block(text: str) -> str:
        """Remove Markdown code block wrappers if present."""
        text = text.strip()
        if text.startswith("```markdown"):
            text = text[len("```markdown"):]
        elif text.startswith("```md"):
            text = text[len("```md"):]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    @staticmethod
    def _regex_mark_done(md_content: str, step_index: int, summary: str) -> str:
        """Regex-based fallback for marking a step done."""
        # Update step header
        pattern = re.compile(
            rf"(##\s+步骤\s*{step_index}\s*[:：]\s*.+?)\s*\[\s*\]",
            re.MULTILINE,
        )
        md_content = pattern.sub(rf"\1 [x]", md_content)

        # Find the step section and update subtasks
        step_header = re.compile(
            rf"^##\s+步骤\s*{step_index}\s*[:：]",
            re.MULTILINE,
        )
        next_header = re.compile(r"^##\s+步骤\s*\d+", re.MULTILINE)

        match = step_header.search(md_content)
        if match:
            start = match.start()
            next_match = next_header.search(md_content, match.end())
            end = next_match.start() if next_match else len(md_content)

            section = md_content[start:end]
            # Mark subtasks done
            section = re.sub(r"- \[ \]", "- [x]", section)
            # Add result summary if not present
            if "**执行结果**" not in section:
                section = section.rstrip() + f"\n**执行结果**: {summary}\n\n"

            md_content = md_content[:start] + section + md_content[end:]

        return md_content


# Singleton
write_agent = WriteAgent()
