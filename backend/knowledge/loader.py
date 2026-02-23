"""Knowledge base loader — reads command docs and ID files from disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import KNOWLEDGE_BASE_DIR


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class KnowledgeLoader:
    """Lazy-loads and caches knowledge base files."""

    def __init__(self, base_dir: Path = KNOWLEDGE_BASE_DIR):
        self.base_dir = base_dir
        self._command_index: list[dict] | None = None
        self._categories: dict[str, list[str]] | None = None
        self._command_cache: dict[str, dict] = {}
        self._command_block_rules: dict | None = None
        self._intent_map: dict | None = None

    # --- Command index ---

    def get_command_index(self) -> list[dict]:
        """Return the full command index (name + description + category)."""
        if self._command_index is None:
            path = self.base_dir / "commands" / "index.json"
            self._command_index = _read_json(path) if path.exists() else []
        return self._command_index

    def get_categories(self) -> dict[str, list[str]]:
        if self._categories is None:
            path = self.base_dir / "commands" / "_categories.json"
            self._categories = _read_json(path) if path.exists() else {}
        return self._categories

    # --- Individual command docs ---

    def get_command_doc(self, name: str) -> dict | None:
        """Load the full documentation for a single command."""
        if name in self._command_cache:
            return self._command_cache[name]
        path = self.base_dir / "commands" / f"{name}.json"
        if not path.exists():
            return None
        doc = _read_json(path)
        self._command_cache[name] = doc
        return doc

    def get_command_docs(self, names: list[str]) -> list[dict]:
        """Load full docs for a list of commands."""
        docs = []
        for name in names:
            doc = self.get_command_doc(name)
            if doc is not None:
                docs.append(doc)
        return docs

    # --- ID files ---

    def get_id_file(self, category: str) -> list[dict]:
        """Load an ID file (items, entities, effects, enchantments, etc.)."""
        path = self.base_dir / "ids" / f"{category}.json"
        if not path.exists():
            return []
        return _read_json(path)

    def get_id_categories(self) -> list[str]:
        """List available ID categories."""
        ids_dir = self.base_dir / "ids"
        if not ids_dir.exists():
            return []
        return [p.stem for p in ids_dir.glob("*.json")]

    # --- Command block rules ---

    def get_command_block_rules(self) -> dict:
        """Load command block behavior rules."""
        if self._command_block_rules is None:
            path = self.base_dir / "command_blocks" / "rules.json"
            self._command_block_rules = _read_json(path) if path.exists() else {}
        return self._command_block_rules

    # --- Intent map ---

    def load_intent_map(self) -> dict:
        """Load the intent mapping data (user intent → correct command)."""
        if self._intent_map is None:
            path = self.base_dir / "intent_map.json"
            self._intent_map = _read_json(path) if path.exists() else {}
        return self._intent_map

    def format_intent_map_for_prompt(self, intent_map: dict | None = None) -> str:
        """Format intent_map.json into a compact prompt section organized by intent."""
        if intent_map is None:
            intent_map = self.load_intent_map()
        if not intent_map:
            return "（意图映射为空）"

        lines = []

        # Intent categories with scenarios
        for cat in intent_map.get("intent_categories", []):
            cat_name = cat.get("category", "")
            lines.append(f"### {cat_name}")
            for sc in cat.get("scenarios", []):
                keywords = ", ".join(sc.get("keywords", [])[:3])
                cmd = sc.get("correct_command", "")
                example = sc.get("usage_example", "")
                explanation = sc.get("explanation", "")
                line = f"- 【{keywords}】→ `{cmd}` ({explanation})"
                if example:
                    line += f" 例: `{example}`"
                mistake = sc.get("common_mistake")
                if mistake:
                    line += f" ⚠️ 不要用 /{mistake['wrong']}（{mistake['reason']}）"
                lines.append(line)

        # Disambiguation rules
        rules = intent_map.get("disambiguation_rules", [])
        if rules:
            lines.append("\n### 歧义词消歧规则")
            for rule in rules:
                word = rule.get("ambiguous_word", "")
                decision = rule.get("decision_rule", "")
                lines.append(f"- **{word}**: {decision}")

        return "\n".join(lines)

    # --- Formatted summaries for prompts ---

    def format_command_index_for_prompt(self) -> str:
        """Format the command index as a compact string for Agent 1's system prompt.

        Includes common_use_cases when available to provide semantic hints.
        """
        index = self.get_command_index()
        if not index:
            return "（命令索引为空）"
        lines = []
        for cmd in index:
            line = f"- {cmd['name']}: {cmd['description']} [{cmd.get('category', '')}]"
            use_cases = cmd.get("common_use_cases")
            if use_cases:
                line += f" (常见场景: {', '.join(use_cases)})"
            lines.append(line)
        return "\n".join(lines)

    def format_id_categories_for_prompt(self) -> str:
        """Format ID category listing for Agent 1's system prompt."""
        categories = self.get_id_categories()
        if not categories:
            return "（ID 索引为空）"
        return "可用 ID 类别: " + ", ".join(categories)

    def format_command_docs_minimal(self, command_names: list[str]) -> str:
        """Minimal command doc format — name + syntax + params only.

        For strong cloud LLMs that already know common commands.
        Saves ~60% tokens compared to format_command_docs_compact().
        """
        docs = self.get_command_docs(command_names)
        if not docs:
            return ""
        sections = []
        for doc in docs:
            name = doc.get("name", "?")
            syntax = doc.get("syntax", "")
            params = doc.get("parameters", [])
            param_parts = []
            for p in params:
                req = "必填" if p.get("required") else "可选"
                info = f"{p['name']}({req},{p.get('type', '?')}"
                if p.get("range"):
                    info += f",{p['range']}"
                info += ")"
                param_parts.append(info)
            sections.append(f"### /{name}\n{syntax}\n参数: {' | '.join(param_parts)}")
        return "\n\n".join(sections)

    def format_command_docs_compact(self, command_names: list[str]) -> str:
        """Format command docs as compact text for LLM prompts (saves tokens vs raw JSON)."""
        docs = self.get_command_docs(command_names)
        if not docs:
            return "（无匹配的命令文档）"

        sections = []
        for doc in docs:
            name = doc.get("name", "?")
            syntax = doc.get("syntax", "")
            desc = doc.get("description", "")

            # Compact parameter summary
            params = doc.get("parameters", [])
            param_parts = []
            for p in params:
                req = "必填" if p.get("required") else "可选"
                info = f"{p['name']}({req},{p.get('type', '?')}"
                if p.get("range"):
                    info += f",范围{p['range']}"
                if p.get("default"):
                    info += f",默认{p['default']}"
                info += f")"
                param_parts.append(info)

            # Examples (1-2 max)
            examples = doc.get("examples", [])[:2]
            example_lines = [f"  {ex['input']} → {ex['description']}" for ex in examples]

            # Bedrock notes
            notes = doc.get("bedrock_specific_notes", "")

            section = f"### /{name}\n描述: {desc}\n语法: {syntax}\n参数: {' | '.join(param_parts)}"
            if example_lines:
                section += "\n示例:\n" + "\n".join(example_lines)
            if notes:
                section += f"\n基岩版注意: {notes}"

            sections.append(section)

        return "\n\n".join(sections)

    # --- Enumeration methods for RAG indexer ---

    def enumerate_all_commands(self) -> list[dict]:
        """Return all command docs (full JSON) for RAG indexing."""
        commands_dir = self.base_dir / "commands"
        if not commands_dir.exists():
            return []
        docs = []
        for path in sorted(commands_dir.glob("*.json")):
            if path.name.startswith("_") or path.name == "index.json":
                continue
            try:
                doc = _read_json(path)
                if isinstance(doc, dict) and "name" in doc:
                    docs.append(doc)
            except Exception:
                continue
        return docs

    def enumerate_all_ids(self) -> dict[str, list[dict]]:
        """Return all ID files grouped by category for RAG indexing.

        Returns dict: category_name -> list of ID entries.
        """
        ids_dir = self.base_dir / "ids"
        if not ids_dir.exists():
            return {}
        result: dict[str, list[dict]] = {}
        for path in sorted(ids_dir.glob("*.json")):
            category = path.stem
            try:
                entries = _read_json(path)
                if isinstance(entries, list):
                    result[category] = entries
            except Exception:
                continue
        return result

    def reload(self) -> None:
        """Clear caches to reload from disk."""
        self._command_index = None
        self._categories = None
        self._command_cache.clear()
        self._command_block_rules = None
        self._intent_map = None


# Singleton
knowledge_loader = KnowledgeLoader()
