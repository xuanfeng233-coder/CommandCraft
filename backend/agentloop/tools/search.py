"""联网搜索工具 search_web（SearXNG，本地优先，best-effort，带子预算）。"""

from __future__ import annotations

from typing import Any

from backend.agentloop.schemas import Observation
from backend.agentloop.searxng_client import get_searxng_client
from backend.agentloop.tools.registry import ToolContext, ToolRegistry

SEARCH_WEB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "当本地命令文档与百科都无法解答时，搜索外部网络获取参考信息。优先使用本地知识库，仅在必要时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
    },
}


async def handle_search_web(args: dict, ctx: ToolContext) -> Observation:
    used = ctx.counters.get("search_web", 0)
    if used >= ctx.budget.max_search_web_calls:
        return Observation(
            tool_name="search_web", ok=False,
            summary=f"联网搜索已达本轮上限（{ctx.budget.max_search_web_calls} 次），请基于已有信息给出答案。",
        )

    client = get_searxng_client()
    if client is None:
        return Observation(
            tool_name="search_web", ok=False,
            summary="联网搜索未启用（未配置 SEARXNG_URL）。请基于本地知识回答。",
            data={"hits": []},
        )

    query = str(args.get("query", "")).strip()
    if not query:
        return Observation(tool_name="search_web", ok=False, summary="请提供搜索关键词。")

    ctx.counters["search_web"] = used + 1
    hits = await client.search(query)
    if not hits:
        return Observation(
            tool_name="search_web", ok=True,
            summary=f"未找到与 '{query}' 相关的外部结果。",
            data={"hits": []},
        )
    lines = [f"## 联网搜索: {query} ({len(hits)} 条)\n"]
    for h in hits:
        lines.append(f"### {h.title}")
        lines.append(f"链接: {h.url}")
        if h.snippet:
            lines.append(f"摘要: {h.snippet}")
        lines.append("")
    return Observation(
        tool_name="search_web", ok=True, summary="\n".join(lines),
        data={"hits": [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits]},
    )


def register_search_tools(reg: ToolRegistry) -> None:
    reg.register(SEARCH_WEB_SCHEMA, handle_search_web)
