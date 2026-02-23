"""Skill 9: CommandValidator — Validates generated commands against knowledge base."""

from __future__ import annotations

import re
from typing import Any

from backend.knowledge.id_registry import id_registry
from backend.knowledge.loader import knowledge_loader
from backend.skills.base import BaseSkill

# Commands that are Java Edition only (not available in Bedrock)
_JAVA_ONLY_COMMANDS = {
    "advancement", "attribute", "ban-ip", "bossbar", "data", "datapack",
    "debug", "defaultgamemode", "forceload", "item",
    "jfr", "pardon", "pardon-ip", "perf", "place", "publish",
    "reload", "save-all", "save-off", "save-on", "seed", "setidletimeout",
    "spectate", "team", "teammsg", "trigger", "worldborder",
}

# Valid Bedrock command names (from our knowledge base + common ones)
_KNOWN_BEDROCK_COMMANDS: set[str] | None = None


def _get_known_commands() -> set[str]:
    global _KNOWN_BEDROCK_COMMANDS
    if _KNOWN_BEDROCK_COMMANDS is None:
        index = knowledge_loader.get_command_index()
        _KNOWN_BEDROCK_COMMANDS = {cmd["name"] for cmd in index}
    return _KNOWN_BEDROCK_COMMANDS


def _extract_command_name(command: str) -> str | None:
    """Extract the command name from a command string like '/give ...'."""
    cmd = command.strip()
    if cmd.startswith("/"):
        cmd = cmd[1:]
    parts = cmd.split(None, 1)
    return parts[0].lower() if parts else None


def _extract_ids_from_command(command: str) -> list[tuple[str, str]]:
    """Try to extract potential IDs from a command. Returns (id, likely_category) pairs."""
    ids: list[tuple[str, str]] = []
    parts = command.split()
    cmd_name = _extract_command_name(command)

    if cmd_name == "give" and len(parts) >= 3:
        ids.append((parts[2], "items"))
    elif cmd_name == "summon":
        # Fix: properly extract entity ID regardless of / prefix
        entity_id = parts[1] if len(parts) > 1 else None
        if entity_id:
            ids.append((entity_id, "entities"))
    elif cmd_name == "effect" and len(parts) >= 3:
        # /effect <target> <effect> ...
        for i, p in enumerate(parts):
            if i >= 2 and not p.startswith("@") and not p.lstrip("-").isdigit():
                ids.append((p, "effects"))
                break
    elif cmd_name in ("setblock", "fill") and len(parts) >= 5:
        # Blocks are after coordinate args
        for p in parts[4:]:
            if not p.lstrip("-").isdigit() and not p.startswith("~") and not p.startswith("^"):
                if p not in ("destroy", "hollow", "keep", "outline", "replace"):
                    ids.append((p, "blocks"))
                    break
    elif cmd_name == "enchant" and len(parts) >= 3:
        ids.append((parts[2], "enchantments"))
    elif cmd_name == "playsound" and len(parts) >= 2:
        ids.append((parts[1], "sounds"))
    elif cmd_name == "particle" and len(parts) >= 2:
        ids.append((parts[1], "particles"))

    return ids


class CommandValidator(BaseSkill):
    """Validates generated commands without calling the LLM.

    This is a rule-based validator, not an LLM skill.
    """

    name = "CommandValidator"
    description = "校验生成命令的语法和 ID 正确性"

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        # Not used — this skill is rule-based
        return ""

    def parse_output(self, raw: str) -> dict[str, Any]:
        # Not used — this skill doesn't call the LLM
        return {}

    def validate(self, commands: list[str]) -> list[dict[str, Any]]:
        """Validate a list of command strings.

        Returns a list of result dicts, one per command:
        {
            "command": original string,
            "valid": bool,
            "errors": [{"type": str, "message": str, "suggestion": str}],
            "warnings": [{"message": str}]
        }
        """
        results = []
        for cmd in commands:
            result = self._validate_single(cmd)
            results.append(result)
        return results

    def _validate_single(self, command: str) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        cmd = command.strip()
        if not cmd:
            return {
                "command": command,
                "valid": False,
                "errors": [{"type": "syntax", "message": "命令为空", "suggestion": "输入有效的命令"}],
                "warnings": [],
            }

        # Check starts with /
        if not cmd.startswith("/"):
            warnings.append({"message": "命令通常以 / 开头（在命令方块中可省略）"})

        # Extract command name
        cmd_name = _extract_command_name(cmd)
        if not cmd_name:
            errors.append({
                "type": "syntax",
                "message": "无法解析命令名称",
                "suggestion": "命令格式应为 /命令名 参数...",
            })
            return {"command": command, "valid": False, "errors": errors, "warnings": warnings}

        # Check if Java-only
        if cmd_name in _JAVA_ONLY_COMMANDS:
            errors.append({
                "type": "version",
                "message": f"/{cmd_name} 是 Java 版独有命令，基岩版不支持",
                "suggestion": "请使用基岩版对应的命令",
            })

        # Check for execute store (Java-only subcommand) in the full command
        if cmd_name == "execute" and "store " in cmd:
            errors.append({
                "type": "version",
                "message": "execute store 是 Java 版独有的子命令，基岩版不支持",
                "suggestion": "基岩版可使用计分板配合条件执行来实现类似功能",
            })

        # Check if command is known
        known = _get_known_commands()
        if known and cmd_name not in known and cmd_name not in _JAVA_ONLY_COMMANDS:
            warnings.append({"message": f"/{cmd_name} 不在已收录的命令列表中（可能是合法命令但未收录）"})

        # Check for execute run /command (should be run command without /)
        if cmd_name == "execute" and re.search(r'\brun\s+/', cmd):
            warnings.append({"message": "execute run 后的命令不需要 / 前缀（如 run say Hello 而非 run /say Hello）"})

        # Validate IDs
        extracted_ids = _extract_ids_from_command(cmd)
        for id_value, category in extracted_ids:
            if not id_registry.is_valid_id(id_value, category):
                available = id_registry.get_all_ids(category)
                if available:
                    # Find similar IDs for suggestion
                    suggestion = self._find_similar(id_value, available)
                    errors.append({
                        "type": "id",
                        "message": f"ID '{id_value}' 在 {category} 中未找到",
                        "suggestion": f"你是否指的是: {suggestion}" if suggestion else "请检查 ID 是否正确",
                    })

        # Check for Java-only NBT syntax — but skip if inside rawtext JSON
        # Only warn about {} if it appears in selector brackets or as NBT
        if "nbt=" in cmd:
            warnings.append({"message": "检测到 Java 版 NBT 选择器语法 (nbt=)，基岩版不支持"})

        # Check for Java-style NBT in /give and /summon (Bedrock doesn't support NBT tags)
        if cmd_name in ("give", "summon") and "{" in cmd:
            java_nbt_keys = [
                "Enchantments", "display", "CustomName", "Damage",
                "Unbreakable", "AttributeModifiers", "Potion",
                "CustomPotionEffects", "HandItems", "ArmorItems", "Health",
            ]
            for nbt_key in java_nbt_keys:
                if nbt_key in cmd or f'"{nbt_key}"' in cmd:
                    errors.append({
                        "type": "version",
                        "message": f"检测到 Java 版 NBT 标签 ({nbt_key})，基岩版 /{cmd_name} 不支持 NBT",
                        "suggestion": "基岩版 /give 仅支持 can_place_on/can_destroy/item_lock/keep_on_death 组件。附魔请用 /enchant，装备请用 /replaceitem",
                    })
                    break

        # Check selector syntax
        selector_pattern = r'@[aeprs]\[([^\]]*)\]'
        for match in re.finditer(selector_pattern, cmd):
            selector_args = match.group(1)
            # Check for Java-only selector args
            java_args = ["nbt", "predicate", "advancements"]
            for ja in java_args:
                if f"{ja}=" in selector_args:
                    errors.append({
                        "type": "parameter",
                        "message": f"选择器参数 '{ja}' 是 Java 版独有的",
                        "suggestion": "基岩版选择器不支持此参数",
                    })

        valid = len(errors) == 0
        return {"command": command, "valid": valid, "errors": errors, "warnings": warnings}

    def _find_similar(self, target: str, candidates: set[str], max_results: int = 3) -> str:
        """Find IDs that contain the target as substring or vice versa."""
        matches = []
        target_lower = target.lower()
        for c in sorted(candidates):
            if target_lower in c.lower() or c.lower() in target_lower:
                matches.append(c)
                if len(matches) >= max_results:
                    break
        return ", ".join(matches)


command_validator = CommandValidator()
