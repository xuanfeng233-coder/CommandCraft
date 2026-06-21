"""本地知识查询工具（edition 感知）。

复用 backend/tools/command_tools.py 的 4 个工具 schema（线级名称不变），
但所有数据访问改走 get_loader(ctx.edition)，修复既有 bedrock-only 单例的多版本错误。
"""

from __future__ import annotations

import json

from backend.agentloop.schemas import Observation
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.knowledge.loader import get_loader
from backend.knowledge.wiki_search import wiki_searcher
from backend.tools.command_tools import TOOL_DEFINITIONS

# 从既有 TOOL_DEFINITIONS 按名取出 4 个 schema（线级契约不变）
_SCHEMAS = {d["function"]["name"]: d for d in TOOL_DEFINITIONS}

MAX_ENTRIES = 50


async def handle_get_command_usage(args: dict, ctx: ToolContext) -> Observation:
    name = str(args.get("command_name", "")).strip().lstrip("/").lower()
    loader = get_loader(ctx.edition)
    doc = loader.get_command_doc(name)
    if not doc:
        return Observation(
            tool_name="get_command_usage", ok=False,
            summary=f"未找到命令 '{name}' 的文档。请检查命令名称是否正确。",
        )
    text = loader.format_command_docs_compact([name])
    return Observation(tool_name="get_command_usage", ok=True, summary=text)


async def handle_get_parameter_options(args: dict, ctx: ToolContext) -> Observation:
    category = str(args.get("category", "")).strip().lower()
    search_term = args.get("search_term")
    loader = get_loader(ctx.edition)
    entries = loader.get_id_file(category)
    if not entries:
        available = loader.get_id_categories()
        return Observation(
            tool_name="get_parameter_options", ok=False,
            summary=f"未找到类别 '{category}'。可用类别: {', '.join(available)}",
        )
    if search_term:
        term = str(search_term).lower()
        filtered = [e for e in entries if term in json.dumps(e, ensure_ascii=False).lower()]
        if not filtered:
            return Observation(
                tool_name="get_parameter_options", ok=True,
                summary=f"在 '{category}' 中未找到与 '{search_term}' 匹配的条目。共 {len(entries)} 个条目。",
                data={"category": category, "count": 0},
            )
        entries = filtered
    lines = []
    for entry in entries[:MAX_ENTRIES]:
        if isinstance(entry, dict):
            entry_id = entry.get("id", entry.get("name", ""))
            desc = entry.get("description") or entry.get("name_cn") or entry.get("name", "")
            if desc and desc.lower().replace(" ", "_") != entry_id.lower():
                lines.append(f"- {entry_id}: {desc}")
            else:
                lines.append(f"- {entry_id}")
        elif isinstance(entry, str):
            lines.append(f"- {entry}")
    header = f"## {category} ({len(entries)} 条"
    if len(entries) > MAX_ENTRIES:
        header += f"，显示前 {MAX_ENTRIES} 条"
    header += ")"
    summary = header + "\n" + "\n".join(lines)
    return Observation(
        tool_name="get_parameter_options", ok=True, summary=summary,
        data={"category": category, "count": len(entries)},
    )


async def handle_get_formatting_codes(args: dict, ctx: ToolContext) -> Observation:
    loader = get_loader(ctx.edition)
    text = loader.format_formatting_codes_for_prompt()
    if not text:
        text = "格式代码数据不可用。基本颜色: §0-§f (16色), §g-§u (基岩版材质色), §k混淆 §l加粗 §o斜体 §r重置"
    return Observation(tool_name="get_formatting_codes", ok=True, summary=text)


async def handle_search_wiki(args: dict, ctx: ToolContext) -> Observation:
    query = str(args.get("query", "")).strip()
    category = args.get("category")
    if not query:
        return Observation(tool_name="search_wiki", ok=False, summary="请提供搜索关键词。")
    stats = wiki_searcher.get_stats()
    if not stats.get("initialized"):
        return Observation(
            tool_name="search_wiki", ok=True,
            summary="Wiki知识库未初始化。请参考你已有的知识回答。",
            data={"hits": []},
        )
    results = wiki_searcher.search(query, category=category)
    if not results:
        return Observation(
            tool_name="search_wiki", ok=True,
            summary=f"未找到与 '{query}' 相关的百科内容。",
            data={"hits": []},
        )
    lines = [f"## 搜索结果: {query} ({len(results)} 条)\n"]
    for r in results:
        lines.append(f"### {r['title']}")
        if r.get("source"):
            lines.append(f"来源: {r['source']} | 分类: {r.get('category', '')}")
        if r.get("summary"):
            lines.append(f"摘要: {r['summary']}")
        if r.get("snippet"):
            lines.append(f"片段: {r['snippet']}")
        article = wiki_searcher.get_article(r["id"])
        if article and article.get("content"):
            content = article["content"]
            if len(content) > 800:
                content = content[:800] + "..."
            lines.append(f"内容: {content}")
        lines.append("")
    return Observation(
        tool_name="search_wiki", ok=True, summary="\n".join(lines),
        data={"hits": [{"id": r["id"], "title": r["title"]} for r in results]},
    )


def register_lookup_tools(reg: ToolRegistry) -> None:
    reg.register(_SCHEMAS["get_command_usage"], handle_get_command_usage)
    reg.register(_SCHEMAS["get_parameter_options"], handle_get_parameter_options)
    reg.register(_SCHEMAS["get_formatting_codes"], handle_get_formatting_codes)
    reg.register(_SCHEMAS["search_wiki"], handle_search_wiki)
