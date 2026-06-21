"""LLM tool definitions for command documentation lookup.

Replaces the RAG system with explicit tool calling. Three tools:
- get_command_usage: full syntax/params/examples for a command
- get_parameter_options: valid values for a parameter category (items, entities, etc.)
- get_formatting_codes: color codes and formatting reference for display commands
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.knowledge.loader import knowledge_loader, get_loader
from backend.knowledge.wiki_search import wiki_searcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_command_usage",
            "description": "获取指定基岩版命令的完整用法文档，包括语法、参数说明和示例。当你不确定命令的具体语法或参数时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command_name": {
                        "type": "string",
                        "description": "命令名称（不含/前缀），如 give, execute, tellraw",
                    },
                },
                "required": ["command_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_parameter_options",
            "description": "获取指定类别的有效参数值列表。可用类别: blocks, items, entities, effects, enchantments, particles, sounds, biomes, structures, fog, gamerules, animations。当你需要确认某个ID是否有效或查找正确的ID名称时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "ID 类别名称，如 items, entities, effects, enchantments, blocks",
                    },
                    "search_term": {
                        "type": "string",
                        "description": "可选的搜索关键词，用于过滤结果（支持中英文）",
                    },
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_formatting_codes",
            "description": "获取基岩版 § 颜色代码和格式修饰符的完整参考表。当任务涉及 tellraw、titleraw、say、title 等文本显示命令且需要颜色/格式美化时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wiki",
            "description": "搜索基岩版百科知识库，获取游戏机制、命令进阶用法、高级项目示例等百科内容。当问题涉及游戏机制（红石、生物行为、方块状态等）、命令高级用法（execute组合、选择器技巧、命令方块链设计等）、或需要参考高级项目示例（攻防战争、跑酷系统、RPG机制等）时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如'红石中继器延迟'、'僵尸生成规则'、'攻防战争命令方块'",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选分类过滤: mechanics(游戏机制) | commands(命令进阶) | examples(高级项目示例)",
                        "enum": ["mechanics", "commands", "examples"],
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def execute_tool(name: str, args: dict[str, Any]) -> str:
    """Dispatch a tool call and return the result as a string."""
    if name == "get_command_usage":
        return _get_command_usage(args.get("command_name", ""))
    elif name == "get_parameter_options":
        return _get_parameter_options(
            args.get("category", ""),
            args.get("search_term"),
        )
    elif name == "get_formatting_codes":
        return _get_formatting_codes()
    elif name == "search_wiki":
        return _search_wiki(
            args.get("query", ""),
            args.get("category"),
        )
    else:
        return f"未知工具: {name}"


def _get_command_usage(command_name: str) -> str:
    """Return formatted command documentation."""
    name = command_name.strip().lstrip("/").lower()
    doc = knowledge_loader.get_command_doc(name)
    if not doc:
        return f"未找到命令 '{name}' 的文档。请检查命令名称是否正确。"

    return knowledge_loader.format_command_docs_compact([name])


def _get_parameter_options(category: str, search_term: str | None = None) -> str:
    """Return filtered ID entries for a category."""
    category = category.strip().lower()
    entries = knowledge_loader.get_id_file(category)
    if not entries:
        available = knowledge_loader.get_id_categories()
        return f"未找到类别 '{category}'。可用类别: {', '.join(available)}"

    # Filter by search term if provided
    if search_term:
        term = search_term.lower()
        filtered = []
        for entry in entries:
            # Search in id, name, and description fields
            searchable = json.dumps(entry, ensure_ascii=False).lower()
            if term in searchable:
                filtered.append(entry)
        if not filtered:
            return f"在 '{category}' 中未找到与 '{search_term}' 匹配的条目。共 {len(entries)} 个条目。"
        entries = filtered

    # Format entries compactly
    MAX_ENTRIES = 50
    lines = []
    for entry in entries[:MAX_ENTRIES]:
        if isinstance(entry, dict):
            entry_id = entry.get("id", entry.get("name", ""))
            # Prefer description, then name_cn, then name (English), then category
            desc = (entry.get("description")
                    or entry.get("name_cn")
                    or entry.get("name", ""))
            # Avoid repeating the id as description
            if desc and desc.lower().replace(" ", "_") != entry_id.lower():
                lines.append(f"- {entry_id}: {desc}")
            else:
                lines.append(f"- {entry_id}")
        elif isinstance(entry, str):
            lines.append(f"- {entry}")

    result = f"## {category} ({len(entries)} 条"
    if len(entries) > MAX_ENTRIES:
        result += f"，显示前 {MAX_ENTRIES} 条"
    result += ")\n" + "\n".join(lines)
    return result


def _get_formatting_codes() -> str:
    """Return formatting codes reference."""
    text = knowledge_loader.format_formatting_codes_for_prompt()
    if not text:
        return "格式代码数据不可用。基本颜色: §0-§f (16色), §g-§u (基岩版材质色), §k混淆 §l加粗 §o斜体 §r重置"
    return text


def _search_wiki(query: str, category: str | None = None) -> str:
    """Search local wiki knowledge base and return formatted results."""
    query = query.strip()
    if not query:
        return "请提供搜索关键词。"

    stats = wiki_searcher.get_stats()
    if not stats.get("initialized"):
        return "Wiki知识库未初始化。本地知识库中暂无百科数据，请参考你已有的知识回答。"

    results = wiki_searcher.search(query, category=category)
    if not results:
        return f"未找到与 '{query}' 相关的百科内容。请尝试更换关键词或直接参考你已有的知识。"

    lines = [f"## 搜索结果: {query} ({len(results)} 条)\n"]
    for r in results:
        lines.append(f"### {r['title']}")
        if r.get("source"):
            lines.append(f"来源: {r['source']} | 分类: {r.get('category', '')}")
        if r.get("summary"):
            lines.append(f"摘要: {r['summary']}")
        if r.get("snippet"):
            lines.append(f"片段: {r['snippet']}")

        # Load full article content for richer context
        article = wiki_searcher.get_article(r["id"])
        if article and article.get("content"):
            content = article["content"]
            if len(content) > 800:
                content = content[:800] + "..."
            lines.append(f"内容: {content}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command directory (injected into system prompt)
# ---------------------------------------------------------------------------

def build_command_directory_text(edition: str = "bedrock") -> str:
    """Build a compact command directory for the system prompt.

    This is always included so the LLM knows which commands exist
    and can decide whether it needs to call get_command_usage.
    """
    loader = get_loader(edition)
    index = loader.get_command_index()
    if not index:
        return ""

    edition_label = "Java 版" if edition == "java" else "基岩版"
    lines = [f"## {edition_label}命令目录\n以下是所有可用的{edition_label}命令。如需确认具体语法，请调用 get_command_usage 工具。\n"]
    # Group by category
    categories: dict[str, list[str]] = {}
    for cmd in index:
        cat = cmd.get("category", "other")
        name = cmd.get("name", "")
        desc = cmd.get("description", "")
        entry = f"{name}: {desc}" if desc else name
        categories.setdefault(cat, []).append(entry)

    # Category display names
    CAT_NAMES = {
        "item_management": "物品管理",
        "teleportation": "传送",
        "execution": "条件执行",
        "scoreboard": "计分板",
        "effects": "效果/附魔",
        "entity": "实体",
        "world_editing": "世界编辑",
        "display": "文本显示",
        "entity_management": "实体管理",
        "game_settings": "游戏设置",
        "multimedia": "多媒体",
        "spawn": "出生点",
        "communication": "通信",
        "server_admin": "服务器管理",
        "world_management": "世界管理",
        "player_management": "玩家管理",
        "testing": "检测/测试",
        "advanced": "高级",
    }

    for cat, entries in categories.items():
        display_name = CAT_NAMES.get(cat, cat)
        lines.append(f"### {display_name}")
        for e in entries:
            lines.append(f"- {e}")
        lines.append("")

    return "\n".join(lines)
