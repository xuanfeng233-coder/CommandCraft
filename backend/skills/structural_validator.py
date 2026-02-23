"""Structural command validator — validates commands against knowledge base syntax definitions.

Checks parameter counts, ID validity at specific positions, execute chain structure,
target selector format, and Java-only syntax patterns. Complements the lightweight
CommandValidator with deeper structural analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.knowledge.id_registry import id_registry
from backend.knowledge.loader import knowledge_loader

# Java Edition-only commands (not available in Bedrock)
_JAVA_ONLY_COMMANDS = {
    "advancement", "attribute", "ban-ip", "bossbar", "data", "datapack",
    "debug", "defaultgamemode", "forceload", "item",
    "jfr", "pardon", "pardon-ip", "perf", "place", "publish",
    "reload", "save-all", "save-off", "save-on", "seed", "setidletimeout",
    "spectate", "team", "teammsg", "trigger", "worldborder",
}

# Java Edition-only execute subcommands
_JAVA_ONLY_EXECUTE_SUBCMDS = {"store", "on"}

# Commands whose syntax is subcommand-based (skip param count check)
_SUBCOMMAND_BASED = {
    "execute", "scoreboard", "tag", "gamerule", "difficulty",
    "weather", "time", "gamemode", "music", "structure",
    "tickingarea", "fog", "camera", "dialogue", "hud",
    "inputpermission", "permission", "playanimation",
    "schedule", "scriptevent", "loot", "ride", "damage",
    "ability", "camerashake", "titleraw", "tellraw",
}

# Map: command_name -> list of (arg_index, id_category, skip_values)
# arg_index is 0-based in the tokenized args list (after command name)
_ID_POSITIONS: dict[str, list[tuple[int, str, frozenset[str]]]] = {
    "give": [(1, "items", frozenset())],
    "clear": [(1, "items", frozenset())],
    "summon": [(0, "entities", frozenset())],
    "setblock": [(3, "blocks", frozenset())],
    "fill": [(6, "blocks", frozenset())],
    "effect": [(1, "effects", frozenset({"clear"}))],
    "enchant": [(1, "enchantments", frozenset())],
    "playsound": [(0, "sounds", frozenset())],
    "particle": [(0, "particles", frozenset())],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single validation error."""
    type: str       # "syntax", "param_count", "id", "format", "version"
    message: str
    suggestion: str = ""


@dataclass
class ValidationResult:
    """Result of validating a single command."""
    command: str
    valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_feedback_text(self) -> str:
        """Format as text feedback for LLM retry prompt."""
        lines = [f"命令: {self.command}"]
        for e in self.errors:
            lines.append(f"  错误[{e.type}]: {e.message}")
            if e.suggestion:
                lines.append(f"    建议: {e.suggestion}")
        for w in self.warnings:
            lines.append(f"  警告: {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class StructuralValidator:
    """Validates commands structurally against knowledge base definitions."""

    def __init__(self) -> None:
        self._syntax_cache: dict[str, int] = {}  # cmd_name -> min required tokens

    def validate(self, commands: list[str]) -> list[ValidationResult]:
        """Validate a list of command strings."""
        return [self._validate_one(cmd) for cmd in commands]

    def has_errors(self, results: list[ValidationResult]) -> bool:
        """Check if any result has errors."""
        return any(not r.valid for r in results)

    def format_feedback(self, results: list[ValidationResult]) -> str:
        """Format validation results as feedback text for LLM retry."""
        lines = ["## 命令校验发现以下问题，请修正后重新生成：\n"]
        for r in results:
            if not r.valid:
                lines.append(r.to_feedback_text())
        return "\n".join(lines)

    # ----- Core validation -----

    def _validate_one(self, command: str) -> ValidationResult:
        """Validate a single command string."""
        result = ValidationResult(command=command)
        cmd = command.strip()

        if not cmd:
            result.valid = False
            result.errors.append(ValidationError("syntax", "命令为空"))
            return result

        # Strip leading /
        bare = cmd[1:] if cmd.startswith("/") else cmd

        # Extract command name and raw args
        parts = bare.split(None, 1)
        cmd_name = parts[0].lower() if parts else ""
        raw_args = parts[1] if len(parts) > 1 else ""

        if not cmd_name:
            result.valid = False
            result.errors.append(ValidationError("syntax", "无法解析命令名称"))
            return result

        # Java-only command
        if cmd_name in _JAVA_ONLY_COMMANDS:
            result.valid = False
            result.errors.append(ValidationError(
                "version",
                f"/{cmd_name} 是 Java 版独有命令，基岩版不支持",
                "请使用基岩版对应的命令",
            ))
            return result

        # Java-only syntax patterns
        self._check_java_only_syntax(cmd, cmd_name, result)

        # Tokenize args
        args = self._tokenize_args(raw_args)

        # Execute chain: special handling
        if cmd_name == "execute":
            self._check_execute(args, result)
            result.valid = len(result.errors) == 0
            return result

        # Parameter count check (skip subcommand-based commands)
        if cmd_name not in _SUBCOMMAND_BASED:
            self._check_param_count(cmd_name, args, result)

        # ID checks
        self._check_ids(cmd_name, args, result)

        # Target selector format
        self._check_selectors(cmd, result)

        result.valid = len(result.errors) == 0
        return result

    # ----- Syntax parsing -----

    def _count_min_required_tokens(self, syntax: str) -> int:
        """Parse a syntax string and return the minimum required token count.

        Handles multi-variant syntax separated by ``|``.
        Returns the minimum across all variants (most lenient).
        """
        variants = syntax.split("|")
        min_count = float("inf")

        for variant in variants:
            variant = variant.strip()
            # Remove the /commandname prefix
            variant = re.sub(r"^/\w+\s*", "", variant)
            count = self._count_variant_tokens(variant)
            min_count = min(min_count, count)

        return int(min_count) if min_count != float("inf") else 0

    @staticmethod
    def _count_variant_tokens(variant: str) -> int:
        """Count required tokens in a single syntax variant."""
        count = 0
        pos = 0

        while pos < len(variant):
            # Skip whitespace
            while pos < len(variant) and variant[pos] == " ":
                pos += 1
            if pos >= len(variant):
                break

            ch = variant[pos]

            if ch == "<":
                # Required parameter
                end = variant.find(">", pos)
                if end == -1:
                    break
                param_text = variant[pos + 1 : end]
                count += StructuralValidator._param_token_count(param_text)
                pos = end + 1

            elif ch == "[":
                # Optional parameter — skip entirely
                end = variant.find("]", pos)
                if end == -1:
                    break
                pos = end + 1

            elif ch == ".":
                # Ellipsis ... — skip
                while pos < len(variant) and variant[pos] == ".":
                    pos += 1

            else:
                # Literal word (e.g. "clear" in effect syntax)
                end = pos
                while end < len(variant) and variant[end] not in " <[":
                    end += 1
                count += 1
                pos = end

        return count

    @staticmethod
    def _param_token_count(param_text: str) -> int:
        """Determine how many tokens a parameter consumes.

        ``position: x y z`` → 3 tokens, ``player: target`` → 1 token.
        """
        if ":" in param_text:
            type_part = param_text.split(":", 1)[1].strip()
            if type_part == "x y z":
                return 3
        return 1

    # ----- Argument tokenizer -----

    @staticmethod
    def _tokenize_args(raw: str) -> list[str]:
        """Tokenize command arguments, respecting brackets, braces, and quotes.

        - ``@a[type=zombie,r=10]`` is one token
        - ``{"rawtext":[...]}`` is one token
        - ``"quoted string"`` is one token
        """
        tokens: list[str] = []
        raw = raw.strip()
        if not raw:
            return tokens

        i = 0
        length = len(raw)

        while i < length:
            # Skip whitespace
            while i < length and raw[i] == " ":
                i += 1
            if i >= length:
                break

            ch = raw[i]

            if ch == '"':
                # Quoted string — scan to matching unescaped quote
                end = i + 1
                while end < length:
                    if raw[end] == "\\" and end + 1 < length:
                        end += 2
                        continue
                    if raw[end] == '"':
                        end += 1
                        break
                    end += 1
                tokens.append(raw[i:end])
                i = end

            elif ch == "{":
                # JSON object — match balanced braces
                end = _scan_balanced(raw, i, "{", "}")
                tokens.append(raw[i:end])
                i = end

            else:
                # Regular token; handle embedded [...] and {...}
                end = i
                while end < length and raw[end] != " ":
                    if raw[end] == "[":
                        end = _scan_balanced(raw, end, "[", "]")
                    elif raw[end] == "{":
                        end = _scan_balanced(raw, end, "{", "}")
                    else:
                        end += 1
                tokens.append(raw[i:end])
                i = end

        return tokens

    # ----- Individual checks -----

    def _check_param_count(
        self, cmd_name: str, args: list[str], result: ValidationResult,
    ) -> None:
        """Check if the command has enough arguments based on its syntax definition."""
        if cmd_name not in self._syntax_cache:
            doc = knowledge_loader.get_command_doc(cmd_name)
            if doc and "syntax" in doc:
                self._syntax_cache[cmd_name] = self._count_min_required_tokens(
                    doc["syntax"],
                )
            else:
                return  # No doc available, skip

        min_required = self._syntax_cache[cmd_name]
        if len(args) < min_required:
            result.errors.append(ValidationError(
                "param_count",
                f"/{cmd_name} 需要至少 {min_required} 个参数，但只提供了 {len(args)} 个",
                "请补充缺少的参数",
            ))

    def _check_ids(
        self, cmd_name: str, args: list[str], result: ValidationResult,
    ) -> None:
        """Check ID validity at known argument positions."""
        positions = _ID_POSITIONS.get(cmd_name)
        if not positions:
            return

        for arg_idx, category, skip_values in positions:
            if arg_idx >= len(args):
                continue
            value = args[arg_idx]

            # Skip special values (e.g. "clear" for /effect)
            if value.lower() in skip_values:
                continue

            # Strip and warn about minecraft: prefix
            clean_value = value
            if value.startswith("minecraft:"):
                result.warnings.append(
                    f"基岩版 ID 不使用 minecraft: 前缀，"
                    f"应使用 '{value[10:]}' 而非 '{value}'"
                )
                clean_value = value[10:]

            if not id_registry.is_valid_id(clean_value, category):
                available = id_registry.get_all_ids(category)
                if available:
                    suggestion = _find_similar(clean_value, available)
                    result.errors.append(ValidationError(
                        "id",
                        f"ID '{clean_value}' 在 {category} 中未找到",
                        f"你是否指的是: {suggestion}" if suggestion else "请检查 ID 是否正确",
                    ))

    def _check_selectors(self, command: str, result: ValidationResult) -> None:
        """Check target selector format."""
        for match in re.finditer(r"@(\w+)", command):
            selector_type = match.group(1)
            if selector_type not in ("a", "e", "p", "r", "s", "initiator"):
                result.warnings.append(
                    f"未知的目标选择器 @{selector_type}，"
                    "有效的选择器为 @a, @e, @p, @r, @s, @initiator"
                )

    def _check_execute(self, args: list[str], result: ValidationResult) -> None:
        """Validate an execute command chain."""
        if not args:
            result.errors.append(ValidationError(
                "syntax",
                "execute 命令缺少子命令",
                "用法: /execute <子命令> ... run <命令>",
            ))
            return

        # Scan for 'run' and check for Java-only subcommands
        run_index = -1
        for i, token in enumerate(args):
            t = token.lower()
            if t == "run":
                run_index = i
                break
            if t in _JAVA_ONLY_EXECUTE_SUBCMDS:
                result.errors.append(ValidationError(
                    "version",
                    f"execute {t} 是 Java 版独有的子命令，基岩版不支持",
                    "基岩版请使用计分板等替代方案",
                ))

        if run_index == -1:
            result.errors.append(ValidationError(
                "syntax",
                "execute 命令链中缺少 run 子命令",
                "execute 命令必须以 run <命令> 结尾",
            ))
            return

        # Validate sub-command after run
        sub_args = args[run_index + 1 :]
        if not sub_args:
            result.errors.append(ValidationError(
                "syntax",
                "execute run 后面缺少要执行的命令",
            ))
            return

        # Warn about / prefix after run
        first = sub_args[0]
        if first.startswith("/"):
            result.warnings.append("execute run 后的命令不需要 / 前缀")
            first = first[1:]
            sub_args = [first] + sub_args[1:]

        # Reconstruct sub-command and validate recursively
        sub_cmd = "/" + " ".join(sub_args)
        sub_result = self._validate_one(sub_cmd)
        result.errors.extend(sub_result.errors)
        result.warnings.extend(sub_result.warnings)

    def _check_java_only_syntax(
        self, cmd: str, cmd_name: str, result: ValidationResult,
    ) -> None:
        """Check for Java Edition-only syntax patterns."""
        # minecraft: prefix — only warn for non-summon commands
        # (summon allows minecraft: in spawnEvent like minecraft:become_charged)
        if "minecraft:" in cmd and cmd_name != "summon":
            # Skip if inside a JSON string (e.g. rawtext components)
            if not re.search(r'"[^"]*minecraft:[^"]*"', cmd):
                result.warnings.append(
                    "检测到 minecraft: 前缀，基岩版通常不使用命名空间前缀"
                )

        # nbt= in selectors (Java-only)
        if "nbt=" in cmd:
            result.errors.append(ValidationError(
                "version",
                "检测到 Java 版 NBT 选择器语法 (nbt=)，基岩版不支持",
                "基岩版可使用 hasitem, has_property 等替代",
            ))

        # Java-style NBT JSON in /give or /summon commands
        # Bedrock /give only supports: can_place_on, can_destroy, item_lock, keep_on_death
        # Bedrock /summon does NOT support any NBT data
        if cmd_name in ("give", "summon") and "{" in cmd:
            # Known Java-only NBT patterns
            java_nbt_patterns = [
                (r'"?Enchantments"?\s*:', "Enchantments NBT（附魔）"),
                (r'"?display"?\s*:', "display NBT（自定义名称/描述）"),
                (r'"?CustomName"?\s*:', "CustomName NBT（自定义名称）"),
                (r'"?Damage"?\s*:', "Damage NBT（耐久度）"),
                (r'"?Unbreakable"?\s*:', "Unbreakable NBT"),
                (r'"?AttributeModifiers"?\s*:', "AttributeModifiers NBT（属性修改）"),
                (r'"?Potion"?\s*:', "Potion NBT（药水效果）"),
                (r'"?CustomPotionEffects"?\s*:', "CustomPotionEffects NBT"),
                (r'"?HandItems"?\s*:', "HandItems NBT（手持物品）"),
                (r'"?ArmorItems"?\s*:', "ArmorItems NBT（装备）"),
                (r'"?Health"?\s*:', "Health NBT（生命值）"),
                (r'"?id"?\s*:\s*"?\w+enchant', "附魔相关NBT"),
                (r'"?lvl"?\s*:', "附魔等级NBT"),
            ]
            for pattern, nbt_name in java_nbt_patterns:
                if re.search(pattern, cmd, re.IGNORECASE):
                    result.errors.append(ValidationError(
                        "version",
                        f"检测到 Java 版 {nbt_name} 语法，基岩版的 /{cmd_name} 命令不支持 NBT 标签",
                        f"基岩版 /give 仅支持 can_place_on/can_destroy/item_lock/keep_on_death 组件。"
                        f"要附魔请使用 /enchant 命令，要给实体穿装备请使用 /replaceitem 命令。",
                    ))
                    break  # One error per command is enough


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Scan from *start* to find the matching close bracket/brace.

    Respects string quoting. Returns the index **after** the closing character.
    """
    depth = 0
    in_str = False
    esc = False
    i = start

    while i < len(text):
        c = text[i]
        if esc:
            esc = False
            i += 1
            continue
        if c == "\\" and in_str:
            esc = True
            i += 1
            continue
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1

    return len(text)  # unbalanced — consume rest


def _find_similar(
    target: str, candidates: set[str], max_results: int = 3,
) -> str:
    """Find IDs that are similar to *target* (substring match)."""
    matches: list[str] = []
    target_lower = target.lower()
    for c in sorted(candidates):
        if target_lower in c.lower() or c.lower() in target_lower:
            matches.append(c)
            if len(matches) >= max_results:
                break
    return ", ".join(matches)


# Singleton
structural_validator = StructuralValidator()
