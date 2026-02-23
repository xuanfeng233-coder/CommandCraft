"""TemplateCommandBuilder — builds commands from templates using knowledge base data.

Bypasses LLM for simple commands (give, tp, effect, etc.) by using command
syntax templates + extracted parameters. Falls back to LLM if template
construction fails or parameters are ambiguous.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.knowledge.loader import knowledge_loader

logger = logging.getLogger(__name__)

# Commands where enchantment is involved → should trigger ambiguity
_ENCHANT_TRIGGER_COMMANDS: set[str] = {"give", "enchant"}

# Keywords indicating user wants enchantment on an item
_ENCHANT_KEYWORDS: list[str] = [
    "附魔", "锋利", "锐利", "力量", "效率", "耐久", "精准", "时运",
    "保护", "火焰附加", "击退", "亡灵杀手", "节肢杀手", "抢夺",
    "无限", "火矢", "冲击", "经验修补", "消失诅咒", "绑定诅咒",
    "引雷", "忠诚", "激流", "穿刺", "水下呼吸", "水下速掘",
    "荆棘", "冰霜行者", "深海探索者", "灵魂疾行", "迅捷潜行",
    "sharpness", "smite", "bane_of_arthropods", "knockback",
    "fire_aspect", "looting", "efficiency", "silk_touch", "fortune",
    "unbreaking", "mending", "power", "punch", "flame", "infinity",
    "protection", "enchant",
]

# Keywords indicating NBT-dependent customization that Bedrock can't do via single command
# Maps: command_name → list of (keywords, limitation_description, suggestion)
# Fixed enum options — aligned with frontend type-mappings.ts FIXED_OPTIONS
_FIXED_OPTIONS: dict[str, list[dict[str, str]]] = {
    "target": [
        {"value": "@s", "label": "@s (自己)"},
        {"value": "@a", "label": "@a (所有玩家)"},
        {"value": "@p", "label": "@p (最近的玩家)"},
        {"value": "@r", "label": "@r (随机玩家)"},
        {"value": "@e", "label": "@e (所有实体)"},
    ],
    "Boolean": [
        {"value": "true", "label": "true (是)"},
        {"value": "false", "label": "false (否)"},
    ],
    "boolean": [
        {"value": "true", "label": "true (是)"},
        {"value": "false", "label": "false (否)"},
    ],
    "GameMode": [
        {"value": "survival", "label": "survival (生存)"},
        {"value": "creative", "label": "creative (创造)"},
        {"value": "adventure", "label": "adventure (冒险)"},
        {"value": "spectator", "label": "spectator (旁观)"},
    ],
    "Difficulty": [
        {"value": "peaceful", "label": "peaceful (和平)"},
        {"value": "easy", "label": "easy (简单)"},
        {"value": "normal", "label": "normal (普通)"},
        {"value": "hard", "label": "hard (困难)"},
    ],
    "FillMode": [
        {"value": "destroy", "label": "destroy (破坏原方块并替换)"},
        {"value": "hollow", "label": "hollow (仅填充外壳)"},
        {"value": "keep", "label": "keep (仅替换空气方块)"},
        {"value": "outline", "label": "outline (仅外壳)"},
        {"value": "replace", "label": "replace (替换所有方块)"},
    ],
    "SetBlockMode": [
        {"value": "destroy", "label": "destroy (破坏原方块并替换)"},
        {"value": "keep", "label": "keep (仅替换空气方块)"},
        {"value": "replace", "label": "replace (直接替换)"},
    ],
    "MaskMode": [
        {"value": "masked", "label": "masked (仅复制非空气方块)"},
        {"value": "filtered", "label": "filtered (仅复制指定方块)"},
        {"value": "replace", "label": "replace (复制所有方块)"},
    ],
    "CloneMode": [
        {"value": "force", "label": "force (强制复制)"},
        {"value": "move", "label": "move (移动)"},
        {"value": "normal", "label": "normal (正常复制)"},
    ],
    "DamageCause": [
        {"value": "anvil", "label": "anvil (铁砧砸落)"},
        {"value": "block_explosion", "label": "block_explosion (方块爆炸)"},
        {"value": "charging", "label": "charging (冲撞)"},
        {"value": "contact", "label": "contact (接触伤害)"},
        {"value": "drowning", "label": "drowning (溺水)"},
        {"value": "entity_attack", "label": "entity_attack (实体攻击)"},
        {"value": "entity_explosion", "label": "entity_explosion (实体爆炸)"},
        {"value": "fall", "label": "fall (摔落)"},
        {"value": "falling_block", "label": "falling_block (下落方块)"},
        {"value": "fire", "label": "fire (火焰)"},
        {"value": "fire_tick", "label": "fire_tick (着火)"},
        {"value": "fireworks", "label": "fireworks (烟花)"},
        {"value": "fly_into_wall", "label": "fly_into_wall (撞墙)"},
        {"value": "freezing", "label": "freezing (冰冻)"},
        {"value": "lava", "label": "lava (岩浆)"},
        {"value": "lightning", "label": "lightning (雷击)"},
        {"value": "magic", "label": "magic (魔法)"},
        {"value": "magma", "label": "magma (岩浆块)"},
        {"value": "none", "label": "none (无)"},
        {"value": "override", "label": "override (覆盖)"},
        {"value": "piston", "label": "piston (活塞)"},
        {"value": "projectile", "label": "projectile (弹射物)"},
        {"value": "ram_attack", "label": "ram_attack (山羊冲撞)"},
        {"value": "self_destruct", "label": "self_destruct (自毁)"},
        {"value": "sonic_boom", "label": "sonic_boom (音波攻击)"},
        {"value": "soul_campfire", "label": "soul_campfire (灵魂营火)"},
        {"value": "stalactite", "label": "stalactite (钟乳石)"},
        {"value": "stalagmite", "label": "stalagmite (石笋)"},
        {"value": "starve", "label": "starve (饥饿)"},
        {"value": "suffocation", "label": "suffocation (窒息)"},
        {"value": "temperature", "label": "temperature (温度)"},
        {"value": "thorns", "label": "thorns (荆棘)"},
        {"value": "void", "label": "void (虚空)"},
        {"value": "wither", "label": "wither (凋零)"},
    ],
    "HudElement": [
        {"value": "paperdoll", "label": "paperdoll (角色纸娃娃)"},
        {"value": "armor", "label": "armor (护甲栏)"},
        {"value": "tooltips", "label": "tooltips (工具提示)"},
        {"value": "touch_controls", "label": "touch_controls (触控按钮)"},
        {"value": "crosshair", "label": "crosshair (准心)"},
        {"value": "hotbar", "label": "hotbar (快捷栏)"},
        {"value": "health", "label": "health (生命值)"},
        {"value": "progress_bar", "label": "progress_bar (进度条)"},
        {"value": "food_bar", "label": "food_bar (饥饿值)"},
        {"value": "air_bubbles", "label": "air_bubbles (氧气泡)"},
        {"value": "horse_health", "label": "horse_health (马匹生命值)"},
        {"value": "status_effects", "label": "status_effects (状态效果图标)"},
        {"value": "item_text", "label": "item_text (物品文本)"},
        {"value": "all", "label": "all (所有元素)"},
    ],
    "InputPermission": [
        {"value": "camera", "label": "camera (摄像机控制)"},
        {"value": "movement", "label": "movement (移动控制)"},
        {"value": "lateral_movement", "label": "lateral_movement (横向移动控制)"},
    ],
    "Ability": [
        {"value": "worldbuilder", "label": "worldbuilder (世界建造者)"},
        {"value": "mayfly", "label": "mayfly (允许飞行)"},
        {"value": "mute", "label": "mute (禁言)"},
        {"value": "noclip", "label": "noclip (穿墙)"},
        {"value": "flyspeed", "label": "flyspeed (飞行速度)"},
        {"value": "walkspeed", "label": "walkspeed (行走速度)"},
        {"value": "instabuild", "label": "instabuild (瞬间破坏)"},
        {"value": "lightning", "label": "lightning (闪电)"},
        {"value": "invulnerable", "label": "invulnerable (无敌)"},
        {"value": "mine", "label": "mine (挖掘)"},
        {"value": "doorsandswitches", "label": "doorsandswitches (使用门和开关)"},
        {"value": "opencontainers", "label": "opencontainers (打开容器)"},
        {"value": "attackplayers", "label": "attackplayers (攻击玩家)"},
        {"value": "attackmobs", "label": "attackmobs (攻击生物)"},
        {"value": "operatorcommands", "label": "operatorcommands (管理员命令)"},
        {"value": "teleport", "label": "teleport (传送)"},
        {"value": "build", "label": "build (放置方块)"},
    ],
    "EaseType": [
        {"value": "linear", "label": "linear (线性)"},
        {"value": "in_back", "label": "in_back (回弹缓入)"},
        {"value": "in_bounce", "label": "in_bounce (弹跳缓入)"},
        {"value": "in_circ", "label": "in_circ (圆形缓入)"},
        {"value": "in_cubic", "label": "in_cubic (三次方缓入)"},
        {"value": "in_elastic", "label": "in_elastic (弹性缓入)"},
        {"value": "in_expo", "label": "in_expo (指数缓入)"},
        {"value": "in_quad", "label": "in_quad (二次方缓入)"},
        {"value": "in_quart", "label": "in_quart (四次方缓入)"},
        {"value": "in_quint", "label": "in_quint (五次方缓入)"},
        {"value": "in_sine", "label": "in_sine (正弦缓入)"},
        {"value": "out_back", "label": "out_back (回弹缓出)"},
        {"value": "out_bounce", "label": "out_bounce (弹跳缓出)"},
        {"value": "out_circ", "label": "out_circ (圆形缓出)"},
        {"value": "out_cubic", "label": "out_cubic (三次方缓出)"},
        {"value": "out_elastic", "label": "out_elastic (弹性缓出)"},
        {"value": "out_expo", "label": "out_expo (指数缓出)"},
        {"value": "out_quad", "label": "out_quad (二次方缓出)"},
        {"value": "out_quart", "label": "out_quart (四次方缓出)"},
        {"value": "out_quint", "label": "out_quint (五次方缓出)"},
        {"value": "out_sine", "label": "out_sine (正弦缓出)"},
        {"value": "in_out_back", "label": "in_out_back (回弹缓入缓出)"},
        {"value": "in_out_bounce", "label": "in_out_bounce (弹跳缓入缓出)"},
        {"value": "in_out_circ", "label": "in_out_circ (圆形缓入缓出)"},
        {"value": "in_out_cubic", "label": "in_out_cubic (三次方缓入缓出)"},
        {"value": "in_out_elastic", "label": "in_out_elastic (弹性缓入缓出)"},
        {"value": "in_out_expo", "label": "in_out_expo (指数缓入缓出)"},
        {"value": "in_out_quad", "label": "in_out_quad (二次方缓入缓出)"},
        {"value": "in_out_quart", "label": "in_out_quart (四次方缓入缓出)"},
        {"value": "in_out_quint", "label": "in_out_quint (五次方缓入缓出)"},
        {"value": "in_out_sine", "label": "in_out_sine (正弦缓入缓出)"},
        {"value": "spring", "label": "spring (弹簧)"},
    ],
    "CameraPreset": [
        {"value": "minecraft:first_person", "label": "minecraft:first_person (第一人称)"},
        {"value": "minecraft:third_person", "label": "minecraft:third_person (第三人称)"},
        {"value": "minecraft:third_person_front", "label": "minecraft:third_person_front (第三人称正面)"},
        {"value": "minecraft:free", "label": "minecraft:free (自由视角)"},
    ],
    "MobEvent": [
        {"value": "minecraft:pillager_patrols_event", "label": "pillager_patrols_event (掠夺者巡逻)"},
        {"value": "minecraft:wandering_trader_event", "label": "wandering_trader_event (流浪商人)"},
        {"value": "minecraft:ender_dragon_event", "label": "ender_dragon_event (末影龙)"},
        {"value": "minecraft:events_enabled", "label": "events_enabled (全部事件开关)"},
    ],
    "Dimension": [
        {"value": "overworld", "label": "overworld (主世界)"},
        {"value": "nether", "label": "nether (下界)"},
        {"value": "the_end", "label": "the_end (末地)"},
    ],
    "EntityEquipmentSlot": [
        {"value": "mainhand", "label": "mainhand (主手)"},
        {"value": "offhand", "label": "offhand (副手)"},
        {"value": "head", "label": "head (头部)"},
        {"value": "chest", "label": "chest (胸部)"},
        {"value": "legs", "label": "legs (腿部)"},
        {"value": "feet", "label": "feet (脚部)"},
        {"value": "slot.weapon.mainhand", "label": "slot.weapon.mainhand (主手武器槽)"},
        {"value": "slot.weapon.offhand", "label": "slot.weapon.offhand (副手武器槽)"},
        {"value": "slot.armor.head", "label": "slot.armor.head (头盔槽)"},
        {"value": "slot.armor.chest", "label": "slot.armor.chest (胸甲槽)"},
        {"value": "slot.armor.legs", "label": "slot.armor.legs (护腿槽)"},
        {"value": "slot.armor.feet", "label": "slot.armor.feet (靴子槽)"},
        {"value": "slot.hotbar", "label": "slot.hotbar (快捷栏)"},
        {"value": "slot.inventory", "label": "slot.inventory (物品栏)"},
        {"value": "slot.enderchest", "label": "slot.enderchest (末影箱)"},
    ],
    "operator": [
        {"value": "+=", "label": "+= (加法赋值)"},
        {"value": "-=", "label": "-= (减法赋值)"},
        {"value": "*=", "label": "*= (乘法赋值)"},
        {"value": "/=", "label": "/= (除法赋值)"},
        {"value": "%=", "label": "%= (取余赋值)"},
        {"value": "<", "label": "< (取较小值)"},
        {"value": ">", "label": "> (取较大值)"},
        {"value": "=", "label": "= (直接赋值)"},
        {"value": "><", "label": ">< (交换值)"},
    ],
}

# Commands excluded from template building (have subcommands or complex syntax)
_EXCLUDED_FROM_TEMPLATE: set[str] = {
    "execute", "scoreboard", "title", "titleraw",
    "structure", "camera", "dialogue", "hud", "inputpermission",
    "loot", "replaceitem", "schedule", "script",
    "recipe", "ride", "tickingarea", "volumearea",
    "whitelist", "music", "camerashake",
}

_NBT_LIMITATION_RULES: dict[str, list[tuple[list[str], str, str]]] = {
    "give": [
        (
            _ENCHANT_KEYWORDS,
            "基岩版的 /give 命令无法直接给予附魔物品（不支持附魔NBT/组件）",
            "需要分两步：先 /give 获得物品，再 /enchant 附魔",
        ),
        (
            ["命名", "叫做", "名为", "名字叫", "自定义名称", "自定义名字", "重命名"],
            "基岩版的 /give 命令无法给予带自定义名称的物品（不支持NBT标签）",
            "基岩版中只能通过铁砧或行为包来命名物品",
        ),
        (
            ["耐久度", "耐久值", "损坏", "快坏的", "半耐久"],
            "基岩版的 /give 命令无法指定物品耐久度（不支持NBT标签）",
            "可以用数据值(data参数)指定某些变种，但无法精确控制耐久度",
        ),
    ],
    "summon": [
        (
            ["穿着", "装备", "拿着", "手持", "戴着", "头戴", "身穿", "全套装备",
             "穿钻石", "穿铁", "穿金", "穿皮", "穿锁链", "穿下界合金",
             "戴头盔", "盔甲", "铠甲", "护甲", "套装"],
            "基岩版的 /summon 命令无法给生成的实体穿装备（不支持NBT标签）",
            "需要分步：先 /summon 生成实体，再用 /replaceitem 给实体穿装备",
        ),
        (
            ["血量", "生命值", "HP", "hp", "自定义血量"],
            "基岩版的 /summon 命令无法设置实体生命值（不支持NBT标签）",
            "基岩版只能通过行为包或 /damage 命令间接调整",
        ),
    ],
}


class TemplateCommandBuilder:
    """Rule-based command builder using knowledge base templates."""

    def supported_commands(self) -> list[str]:
        """Return list of command names that can be template-built."""
        all_docs = knowledge_loader.enumerate_all_commands()
        return [
            doc["name"] for doc in all_docs
            if isinstance(doc, dict) and "name" in doc and self.can_build(doc["name"])
        ]

    def can_build(self, command_name: str) -> bool:
        """Check if a command is supported for template building.

        Dynamically detects buildable commands: any command with a doc
        that is not in the exclusion list and has no subcommand parameters.
        """
        if command_name in _EXCLUDED_FROM_TEMPLATE:
            return False
        doc = knowledge_loader.get_command_doc(command_name)
        if not doc:
            return False
        # Commands with subcommand-type parameters need LLM routing
        for p in doc.get("parameters", []):
            if p.get("type") in ("子命令", "Command"):
                return False
        return True

    def build(
        self,
        command_name: str,
        params: dict[str, str],
        command_doc: dict[str, Any] | None = None,
        user_text: str = "",
    ) -> dict[str, Any] | None:
        """Build a command from template and extracted parameters.

        Returns:
            A single_command result dict on success, or None on failure.
        """
        if not self.can_build(command_name):
            return None

        if not command_doc:
            command_doc = knowledge_loader.get_command_doc(command_name)
        if not command_doc:
            return None

        # Check for NBT-dependent customization that Bedrock can't do
        limitation = self._check_nbt_limitation(command_name, user_text)
        if limitation is not None:
            return None  # Fall through to conversation path

        param_defs = command_doc.get("parameters", [])

        # Check if all required params are present
        missing_required = []
        for pdef in param_defs:
            pname = pdef.get("name", "")
            if pdef.get("required") and pname not in params:
                missing_required.append(pdef)

        if missing_required:
            return None  # Caller should use get_missing_params() instead

        # Build command string from syntax template
        cmd_str = self._assemble_command(command_name, params, param_defs)
        if not cmd_str:
            return None

        # Build explanation
        explanation = self._build_explanation(params, param_defs)

        # Build template metadata for frontend editing
        template = self._build_template_meta(command_name, params, param_defs)

        return {
            "type": "single_command",
            "command": {
                "command": cmd_str,
                "explanation": explanation,
                "variants": [],
                "warnings": [],
                "template": template,
            },
        }

    def get_missing_params(
        self,
        command_name: str,
        params: dict[str, str],
        command_doc: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate question dicts for missing parameters.

        Returns:
            List of question objects compatible with conversation type.
        """
        if not command_doc:
            command_doc = knowledge_loader.get_command_doc(command_name)
        if not command_doc:
            return []

        param_defs = command_doc.get("parameters", [])
        questions: list[dict[str, Any]] = []

        for pdef in param_defs:
            pname = pdef.get("name", "")
            if not pdef.get("required") or pname in params:
                continue

            question = {
                "param": pname,
                "question": self._make_question_text(pdef),
                "options": self._get_param_options(pname, pdef),
                "default": pdef.get("default"),
            }
            questions.append(question)

        return questions

    def get_param_options(
        self,
        command_name: str,
        param_name: str,
    ) -> list[dict[str, str]]:
        """Get available options for a command parameter from knowledge base."""
        doc = knowledge_loader.get_command_doc(command_name)
        if not doc:
            return []

        for pdef in doc.get("parameters", []):
            if pdef.get("name") == param_name:
                return self._get_param_options(param_name, pdef)

        return []

    def _assemble_command(
        self,
        command_name: str,
        params: dict[str, str],
        param_defs: list[dict],
    ) -> str:
        """Assemble the full command string."""
        parts = [f"/{command_name}"]

        for pdef in param_defs:
            pname = pdef.get("name", "")
            value = params.get(pname)

            if value is not None:
                parts.append(str(value))
            elif pdef.get("required"):
                return ""  # Can't build without required param
            elif pdef.get("default") is not None and pname in params:
                parts.append(str(pdef["default"]))
            # Skip optional params not provided

        return " ".join(parts)

    def _build_explanation(
        self,
        params: dict[str, str],
        param_defs: list[dict],
    ) -> str:
        """Build a human-readable explanation of the command parameters."""
        lines = []
        for pdef in param_defs:
            pname = pdef.get("name", "")
            value = params.get(pname)
            if value:
                desc = pdef.get("description", pname)
                lines.append(f"{value} = {desc}")
        return "\n".join(lines)

    def _build_template_meta(
        self,
        command_name: str,
        params: dict[str, str],
        param_defs: list[dict],
    ) -> dict[str, Any]:
        """Build template metadata for frontend CommandEditor."""
        enriched_defs = []
        for pdef in param_defs:
            pname = pdef.get("name", "")
            enriched = {
                "name": pname,
                "type": pdef.get("type", "string"),
                "required": pdef.get("required", False),
                "description": pdef.get("description", ""),
            }
            if pdef.get("default") is not None:
                enriched["default"] = str(pdef["default"])
            if pdef.get("range"):
                enriched["range"] = pdef["range"]

            # Add knowledge-base options
            options = self._get_param_options(pname, pdef)
            if options:
                enriched["options"] = options

            enriched_defs.append(enriched)

        return {
            "command_name": command_name,
            "params": params,
            "param_defs": enriched_defs,
        }

    def _get_param_options(
        self,
        param_name: str,
        param_def: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Get options for a parameter — unified lookup.

        Priority:
        1. target type → fixed 5 selectors
        2. _FIXED_OPTIONS by type
        3. ID category → load from knowledge base (limit 50)
        4. Pipe-delimited inline enum → parse from type string
        5. param_name fallback to _FIXED_OPTIONS (gameMode → GameMode)
        """
        ptype = param_def.get("type", "")

        # 1. Target selector
        if ptype == "target" or param_name in ("player", "target", "origin", "destination"):
            return _FIXED_OPTIONS["target"]

        # 2. Fixed enum options by type
        if ptype in _FIXED_OPTIONS:
            return _FIXED_OPTIONS[ptype]

        # 3. ID-based parameters → load from knowledge base
        category = self._type_to_id_category(ptype, param_name)
        if category:
            entries = knowledge_loader.get_id_file(category)
            options = []
            for entry in entries[:50]:
                eid = entry.get("id", "")
                name = entry.get("name", "")
                if eid:
                    options.append({"value": eid, "label": f"{eid} ({name})" if name else eid})
            return options

        # 4. Pipe-delimited inline enum
        inline = self._parse_inline_enum(ptype)
        if inline:
            return inline

        # 5. param_name fallback (e.g. gameMode → GameMode)
        _NAME_TO_FIXED: dict[str, str] = {
            "gameMode": "GameMode",
            "mode": "GameMode",
            "difficulty": "Difficulty",
            "cause": "DamageCause",
            "damageCause": "DamageCause",
            "ability": "Ability",
            "hud_element": "HudElement",
            "hudElement": "HudElement",
            "easeType": "EaseType",
            "preset": "CameraPreset",
            "dimension": "Dimension",
            "mobEvent": "MobEvent",
            "slot": "EntityEquipmentSlot",
            "slotId": "EntityEquipmentSlot",
            "inputPermission": "InputPermission",
        }
        fixed_key = _NAME_TO_FIXED.get(param_name)
        if fixed_key and fixed_key in _FIXED_OPTIONS:
            return _FIXED_OPTIONS[fixed_key]

        return []

    @staticmethod
    def _parse_inline_enum(type_str: str) -> list[dict[str, str]] | None:
        """Parse 'hide|reset' style pipe-delimited enum types."""
        if "|" not in type_str:
            return None
        parts = type_str.split("|")
        if len(parts) < 2 or len(parts) > 15:
            return None
        # Exclude compound types with spaces (e.g. "target 或 x y z")
        for part in parts:
            if " " in part.strip():
                return None
        return [{"value": p.strip(), "label": p.strip()} for p in parts]

    @staticmethod
    def _type_to_id_category(ptype: str, pname: str) -> str | None:
        """Map parameter type/name to knowledge base ID category."""
        type_mapping = {
            "Item": "items",
            "Block": "blocks",
            "block": "blocks",
            "EntityType": "entities",
            "entityType": "entities",
            "Effect": "effects",
            "Enchant": "enchantments",
            "Enchantment": "enchantments",
            "Particle": "particles",
            "Sound": "sounds",
            "Biome": "biomes",
            "Fog": "fog",
            "Animation": "animations",
            "GameRule": "gamerules",
            "Structure": "structures",
        }
        cat = type_mapping.get(ptype)
        if cat:
            return cat

        # Name-based fallback
        name_mapping = {
            "itemName": "items",
            "item": "items",
            "entityType": "entities",
            "effect": "effects",
            "enchantName": "enchantments",
            "enchantment": "enchantments",
            "tileName": "blocks",
            "block": "blocks",
            "sound": "sounds",
            "particle": "particles",
            "fogId": "fog",
            "animationId": "animations",
            "rule": "gamerules",
            "biome": "biomes",
        }
        return name_mapping.get(pname)

    @staticmethod
    def _check_nbt_limitation(
        command_name: str, text: str,
    ) -> tuple[str, str] | None:
        """Check if user text implies NBT-dependent customization that Bedrock can't do.

        Returns (limitation_desc, suggestion) if a limitation is detected, else None.
        """
        if not text:
            return None
        rules = _NBT_LIMITATION_RULES.get(command_name)
        if not rules:
            return None
        text_lower = text.lower()
        for keywords, limitation, suggestion in rules:
            if any(kw in text_lower for kw in keywords):
                return (limitation, suggestion)
        return None

    def get_nbt_limitation_conversation(
        self,
        command_name: str,
        user_text: str,
        params: dict[str, str],
    ) -> dict[str, Any] | None:
        """Build a conversation result explaining Bedrock NBT limitations.

        Returns a conversation dict if a limitation applies, else None.
        """
        limitation = self._check_nbt_limitation(command_name, user_text)
        if limitation is None:
            return None

        limitation_desc, suggestion = limitation
        progress_parts = [f"{k}={v}" for k, v in params.items()]

        # Build context-appropriate questions
        questions = [{
            "param": "workaround_method",
            "question": f"{limitation_desc}。{suggestion}。请选择处理方式：",
            "options": [
                {"value": "multi_step", "label": "生成分步命令（推荐）"},
                {"value": "simple_only", "label": "只生成基础命令（不含自定义属性）"},
            ],
            "default": "multi_step",
        }]

        return {
            "type": "conversation",
            "questions": questions,
            "current_progress": f"已确定：{', '.join(progress_parts)}" if progress_parts else "等待参数输入",
        }

    @staticmethod
    def _make_question_text(param_def: dict[str, Any]) -> str:
        """Generate a friendly question for a missing parameter."""
        desc = param_def.get("description", "")
        pname = param_def.get("name", "参数")
        return f"请指定 {desc or pname}："


# Singleton
template_builder = TemplateCommandBuilder()
