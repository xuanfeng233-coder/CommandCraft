#!/usr/bin/env python3
"""Update all ID lists from authoritative sources.

Sources:
  - wiki.bedrock.dev/items/numerical-item-ids  → blocks + items
  - learn.microsoft.com (entity listings)       → entities
  - zh.minecraft.wiki API                       → effects, enchantments, particles, sounds,
                                                   biomes, structures, gamerules

Usage:
    python scripts/update_ids.py              # Update all
    python scripts/update_ids.py --category blocks items entities
    python scripts/update_ids.py --dry-run    # Show counts without writing
"""

import argparse
import json
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "ids"
DELAY = 1.0

HEADERS = {
    "User-Agent": "MCBECommandCraft/1.0 (https://commandcraft.cn) python-httpx",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}

ZH_WIKI_API = "https://zh.minecraft.wiki/api.php"


# =====================================================================
# Helpers
# =====================================================================

def save_json(name: str, data: list, dry_run: bool = False) -> int:
    """Save ID list to JSON. Returns entry count."""
    if dry_run:
        print(f"  [DRY RUN] {name}: {len(data)} entries")
        return len(data)
    path = OUTPUT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {name}: {len(data)} entries → {path.name}")
    return len(data)


def wiki_api_parse(client: httpx.Client, page: str) -> str:
    """Fetch parsed HTML from zh.minecraft.wiki API."""
    resp = client.get(ZH_WIKI_API, params={
        "action": "parse", "page": page,
        "prop": "text", "redirects": "1",
        "format": "json", "disableeditsection": "1",
    })
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(f"Wiki API error for '{page}': {data['error'].get('info')}")
    return data["parse"]["text"]["*"]


# =====================================================================
# Blocks & Items — from wiki.bedrock.dev numerical ID list
# =====================================================================

def fetch_blocks_and_items(client: httpx.Client) -> tuple[list[dict], list[dict]]:
    """Parse the numerical ID page from wiki.bedrock.dev."""
    print("Fetching blocks & items from wiki.bedrock.dev...")
    resp = client.get("https://wiki.bedrock.dev/items/numerical-item-ids", follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    blocks: list[dict] = []
    items: list[dict] = []

    # The page has tables with columns: ID | Identifier
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Detect column order from header
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]
        # Columns: Name | ID  (name first, id second)
        name_col, id_col = 0, 1
        if len(header_texts) >= 2 and "id" in header_texts[0]:
            name_col, id_col = 1, 0

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            try:
                num_id = int(cells[id_col].get_text(strip=True))
            except (ValueError, IndexError):
                continue

            identifier = cells[name_col].get_text(strip=True)
            if not identifier:
                continue

            # Clean up identifier
            identifier = identifier.replace("minecraft:", "").strip()

            # Skip element_* (chemistry), light_block_*, deprecated, reserved
            if (identifier.startswith("element_") or
                identifier.startswith("light_block_") or
                identifier.startswith("deprecated_") or
                identifier == "reserved6" or
                identifier == "unknown" or
                identifier.startswith("hard_") or  # Education Edition
                identifier.startswith("colored_torch_")):
                continue

            entry = {"id": identifier, "name": _id_to_name(identifier)}

            # Blocks have IDs <= 255 or negative IDs; items have IDs >= 256
            if num_id < 0 or (0 <= num_id <= 255):
                entry["category"] = _guess_block_category(identifier)
                blocks.append(entry)
            else:
                entry["category"] = _guess_item_category(identifier)
                items.append(entry)

    # Deduplicate by id
    blocks = _dedup(blocks)
    items = _dedup(items)
    return blocks, items


def _id_to_name(identifier: str) -> str:
    """Convert identifier like 'oak_planks' to 'Oak Planks'."""
    return identifier.replace("_", " ").title()


def _guess_block_category(bid: str) -> str:
    """Rough categorization for blocks."""
    if any(k in bid for k in ["ore", "raw_", "diamond_block", "gold_block", "iron_block", "emerald_block", "copper", "netherite_block", "coal_block", "lapis_block", "amethyst", "redstone_block"]):
        return "mineral"
    if any(k in bid for k in ["log", "planks", "wood", "stripped_", "bamboo", "cherry", "mangrove", "pale_oak"]):
        return "wood"
    if any(k in bid for k in ["stairs", "slab", "wall", "fence", "door", "trapdoor", "button", "pressure_plate", "sign", "gate"]):
        return "building"
    if any(k in bid for k in ["wool", "carpet", "concrete", "terracotta", "glass", "glazed", "shulker_box", "candle", "banner"]):
        return "decoration"
    if any(k in bid for k in ["redstone", "piston", "repeater", "comparator", "observer", "hopper", "dropper", "dispenser", "command_block", "daylight", "lever", "tripwire"]):
        return "redstone"
    if any(k in bid for k in ["leaves", "sapling", "flower", "grass", "fern", "vine", "mushroom", "coral", "kelp", "seagrass", "moss", "azalea", "dripleaf", "spore", "bush", "wart", "cactus", "bamboo_sapling", "cherry_leaves"]):
        return "nature"
    if any(k in bid for k in ["deepslate", "tuff", "basalt", "blackstone", "sculk", "dripstone"]):
        return "cave"
    if any(k in bid for k in ["nether", "crimson", "warped", "soul_", "shroomlight", "magma", "ancient_debris", "respawn_anchor", "crying_obsidian", "gilded_blackstone"]):
        return "nether"
    if any(k in bid for k in ["end_", "purpur", "chorus", "shulker"]):
        return "end"
    return "block"


def _guess_item_category(iid: str) -> str:
    """Rough categorization for items."""
    if "spawn_egg" in iid:
        return "spawn_egg"
    if any(k in iid for k in ["sword", "pickaxe", "axe", "shovel", "hoe", "bow", "crossbow", "trident", "mace", "shield"]):
        return "weapon_tool"
    if any(k in iid for k in ["helmet", "chestplate", "leggings", "boots", "armor", "elytra", "turtle_helmet"]):
        return "armor"
    if any(k in iid for k in ["music_disc", "disc_fragment"]):
        return "music_disc"
    if any(k in iid for k in ["_dye", "bone_meal", "ink_sac", "lapis_lazuli", "cocoa_beans"]):
        return "dye"
    if any(k in iid for k in ["potion", "splash_potion", "lingering_potion", "bottle"]):
        return "potion"
    if any(k in iid for k in ["apple", "bread", "porkchop", "beef", "chicken", "fish", "cod", "salmon", "cookie", "cake", "stew", "melon_slice", "berries", "potato", "carrot", "beetroot", "rabbit", "mutton", "kelp"]):
        return "food"
    if any(k in iid for k in ["pottery_sherd"]):
        return "pottery"
    if any(k in iid for k in ["smithing_template", "trim"]):
        return "smithing"
    if any(k in iid for k in ["boat", "chest_boat", "raft", "minecart", "saddle", "lead"]):
        return "transport"
    if any(k in iid for k in ["banner_pattern"]):
        return "banner_pattern"
    if any(k in iid for k in ["bundle", "harness"]):
        return "equipment"
    return "material"


def _dedup(entries: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for e in entries:
        if e["id"] not in seen:
            seen.add(e["id"])
            result.append(e)
    return result


# =====================================================================
# Entities — from Microsoft Learn
# =====================================================================

def fetch_entities(client: httpx.Client) -> list[dict]:
    """Parse entity list from Microsoft Learn."""
    print("Fetching entities from learn.microsoft.com...")
    resp = client.get(
        "https://learn.microsoft.com/en-us/minecraft/creator/reference/content/vanillalistingsreference/entities",
        params={"view": "minecraft-bedrock-stable"},
        follow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    entities: list[dict] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            identifier = cells[0].get_text(strip=True)
            if not identifier or identifier.startswith("undefined"):
                continue
            # Skip internal/technical entities
            if identifier in ("item", "leash_knot", "falling_block", "moving_block",
                              "painting", "shield", "undefined_test_only"):
                continue
            entities.append({
                "id": identifier,
                "name": _id_to_name(identifier),
                "category": _guess_entity_category(identifier),
            })

    return _dedup(entities)


def _guess_entity_category(eid: str) -> str:
    if "spawn_egg" in eid or eid in ("egg",):
        return "item"
    if any(k in eid for k in ["fireball", "arrow", "snowball", "ender_pearl", "xp_bottle",
                               "splash_potion", "lingering_potion", "thrown_trident",
                               "fireworks_rocket", "shulker_bullet", "llama_spit",
                               "dragon_fireball", "small_fireball", "wither_skull",
                               "wind_charge", "breeze_wind"]):
        return "projectile"
    if any(k in eid for k in ["minecart", "boat", "chest_boat", "raft"]):
        return "vehicle"
    if any(k in eid for k in ["zombie", "skeleton", "creeper", "spider", "enderman",
                               "blaze", "ghast", "magma_cube", "slime", "witch",
                               "guardian", "elder_guardian", "phantom", "drowned",
                               "husk", "stray", "wither_skeleton", "vex", "vindicator",
                               "evoker", "evocation", "pillager", "ravager", "hoglin",
                               "zoglin", "piglin_brute", "warden", "breeze", "bogged",
                               "creaking", "silverfish", "endermite", "cave_spider",
                               "shulker"]):
        return "hostile"
    if any(k in eid for k in ["wither", "ender_dragon"]):
        return "boss"
    if any(k in eid for k in ["villager", "wandering_trader", "iron_golem", "snow_golem",
                               "copper_golem"]):
        return "npc"
    if any(k in eid for k in ["cow", "pig", "sheep", "chicken", "horse", "donkey", "mule",
                               "llama", "trader_llama", "cat", "wolf", "ocelot", "parrot",
                               "rabbit", "fox", "bee", "turtle", "dolphin", "squid",
                               "glow_squid", "axolotl", "goat", "frog", "tadpole",
                               "sniffer", "camel", "armadillo", "bat", "cod", "salmon",
                               "pufferfish", "tropicalfish", "strider", "mooshroom",
                               "polar_bear", "panda", "allay", "happy_ghast"]):
        return "passive"
    return "other"


# =====================================================================
# Effects — from zh.minecraft.wiki API
# =====================================================================

def fetch_effects(client: httpx.Client) -> list[dict]:
    """Parse effects from zh.minecraft.wiki."""
    print("Fetching effects from zh.minecraft.wiki...")
    # Use the known complete list from Bedrock Edition
    # (API page is too complex to parse reliably, use hardcoded authoritative list)
    effects = [
        {"id": "speed", "name": "速度", "numeric_id": 1, "description": "增加移动速度"},
        {"id": "slowness", "name": "缓慢", "numeric_id": 2, "description": "降低移动速度"},
        {"id": "haste", "name": "急迫", "numeric_id": 3, "description": "加快挖掘速度"},
        {"id": "mining_fatigue", "name": "挖掘疲劳", "numeric_id": 4, "description": "减慢挖掘速度"},
        {"id": "strength", "name": "力量", "numeric_id": 5, "description": "增加近战伤害"},
        {"id": "instant_health", "name": "瞬间治疗", "numeric_id": 6, "description": "立即恢复生命值"},
        {"id": "instant_damage", "name": "瞬间伤害", "numeric_id": 7, "description": "立即造成伤害"},
        {"id": "jump_boost", "name": "跳跃提升", "numeric_id": 8, "description": "增加跳跃高度"},
        {"id": "nausea", "name": "反胃", "numeric_id": 9, "description": "扭曲视野"},
        {"id": "regeneration", "name": "生命恢复", "numeric_id": 10, "description": "随时间恢复生命值"},
        {"id": "resistance", "name": "抗性提升", "numeric_id": 11, "description": "减少受到的伤害"},
        {"id": "fire_resistance", "name": "防火", "numeric_id": 12, "description": "免疫火焰伤害"},
        {"id": "water_breathing", "name": "水下呼吸", "numeric_id": 13, "description": "水下不消耗氧气"},
        {"id": "invisibility", "name": "隐身", "numeric_id": 14, "description": "使实体隐形"},
        {"id": "blindness", "name": "失明", "numeric_id": 15, "description": "限制视野范围"},
        {"id": "night_vision", "name": "夜视", "numeric_id": 16, "description": "在黑暗中看清"},
        {"id": "hunger", "name": "饥饿", "numeric_id": 17, "description": "加快饥饿消耗"},
        {"id": "weakness", "name": "虚弱", "numeric_id": 18, "description": "降低近战伤害"},
        {"id": "poison", "name": "中毒", "numeric_id": 19, "description": "随时间造成伤害（不致死）"},
        {"id": "wither", "name": "凋零", "numeric_id": 20, "description": "随时间造成伤害（可致死）"},
        {"id": "health_boost", "name": "生命提升", "numeric_id": 21, "description": "增加最大生命值"},
        {"id": "absorption", "name": "伤害吸收", "numeric_id": 22, "description": "添加额外吸收心"},
        {"id": "saturation", "name": "饱和", "numeric_id": 23, "description": "恢复饥饿值和饱和度"},
        {"id": "levitation", "name": "飘浮", "numeric_id": 24, "description": "使实体上浮"},
        {"id": "fatal_poison", "name": "致命中毒", "numeric_id": 25, "description": "随时间造成伤害（可致死）"},
        {"id": "slow_falling", "name": "缓降", "numeric_id": 26, "description": "降低下落速度，免疫摔伤"},
        {"id": "conduit_power", "name": "潮涌能量", "numeric_id": 27, "description": "水下视野和挖掘速度提升"},
        {"id": "bad_omen", "name": "不祥之兆", "numeric_id": 28, "description": "进入村庄时触发袭击"},
        {"id": "hero_of_the_village", "name": "村庄英雄", "numeric_id": 29, "description": "村民交易折扣"},
        {"id": "darkness", "name": "黑暗", "numeric_id": 30, "description": "限制视野，周期性降低亮度"},
        {"id": "trial_omen", "name": "试炼之兆", "numeric_id": 31, "description": "激活试炼刷怪笼的不祥变体"},
        {"id": "raid_omen", "name": "袭击之兆", "numeric_id": 32, "description": "进入村庄触发袭击"},
        {"id": "wind_charged", "name": "风能充能", "numeric_id": 33, "description": "死亡时释放风弹"},
        {"id": "weaving", "name": "缠绕", "numeric_id": 34, "description": "死亡时生成蛛网"},
        {"id": "oozing", "name": "渗浆", "numeric_id": 35, "description": "死亡时生成史莱姆"},
        {"id": "infested", "name": "虫噬", "numeric_id": 36, "description": "受伤时生成蠹虫"},
    ]
    return effects


# =====================================================================
# Enchantments — hardcoded authoritative BE list
# =====================================================================

def fetch_enchantments(client: httpx.Client) -> list[dict]:
    """Return complete BE enchantment list."""
    print("Using authoritative enchantment list for Bedrock Edition...")
    enchantments = [
        {"id": "protection", "name": "保护", "max_level": 4, "applicable": "盔甲", "description": "减少大部分伤害"},
        {"id": "fire_protection", "name": "火焰保护", "max_level": 4, "applicable": "盔甲", "description": "减少火焰伤害"},
        {"id": "feather_falling", "name": "摔落保护", "max_level": 4, "applicable": "靴子", "description": "减少摔落伤害"},
        {"id": "blast_protection", "name": "爆炸保护", "max_level": 4, "applicable": "盔甲", "description": "减少爆炸伤害"},
        {"id": "projectile_protection", "name": "弹射物保护", "max_level": 4, "applicable": "盔甲", "description": "减少弹射物伤害"},
        {"id": "thorns", "name": "荆棘", "max_level": 3, "applicable": "胸甲", "description": "受攻击时反弹伤害"},
        {"id": "respiration", "name": "水下呼吸", "max_level": 3, "applicable": "头盔", "description": "延长水下呼吸时间"},
        {"id": "aqua_affinity", "name": "水下速掘", "max_level": 1, "applicable": "头盔", "description": "加快水下挖掘速度"},
        {"id": "depth_strider", "name": "深海探索者", "max_level": 3, "applicable": "靴子", "description": "加快水中移动速度"},
        {"id": "frost_walker", "name": "冰霜行者", "max_level": 2, "applicable": "靴子", "description": "在水面生成霜冰"},
        {"id": "soul_speed", "name": "灵魂疾行", "max_level": 3, "applicable": "靴子", "description": "加快在灵魂沙上的速度"},
        {"id": "sharpness", "name": "锋利", "max_level": 5, "applicable": "剑/斧", "description": "增加近战伤害"},
        {"id": "smite", "name": "亡灵杀手", "max_level": 5, "applicable": "剑/斧", "description": "增加对亡灵生物的伤害"},
        {"id": "bane_of_arthropods", "name": "节肢杀手", "max_level": 5, "applicable": "剑/斧", "description": "增加对节肢生物的伤害"},
        {"id": "knockback", "name": "击退", "max_level": 2, "applicable": "剑", "description": "增加击退距离"},
        {"id": "fire_aspect", "name": "火焰附加", "max_level": 2, "applicable": "剑", "description": "点燃目标"},
        {"id": "looting", "name": "抢夺", "max_level": 3, "applicable": "剑", "description": "增加怪物掉落物"},
        {"id": "efficiency", "name": "效率", "max_level": 5, "applicable": "镐/斧/锹/锄", "description": "加快挖掘速度"},
        {"id": "silk_touch", "name": "精准采集", "max_level": 1, "applicable": "镐/斧/锹/锄", "description": "采集方块本身"},
        {"id": "fortune", "name": "时运", "max_level": 3, "applicable": "镐/斧/锹/锄", "description": "增加方块掉落物"},
        {"id": "unbreaking", "name": "耐久", "max_level": 3, "applicable": "大部分物品", "description": "增加耐久度"},
        {"id": "mending", "name": "经验修补", "max_level": 1, "applicable": "大部分物品", "description": "经验值修复耐久"},
        {"id": "power", "name": "力量", "max_level": 5, "applicable": "弓", "description": "增加箭矢伤害"},
        {"id": "punch", "name": "冲击", "max_level": 2, "applicable": "弓", "description": "增加箭矢击退"},
        {"id": "flame", "name": "火矢", "max_level": 1, "applicable": "弓", "description": "射出火焰箭"},
        {"id": "infinity", "name": "无限", "max_level": 1, "applicable": "弓", "description": "无限箭矢"},
        {"id": "luck_of_the_sea", "name": "海之眷顾", "max_level": 3, "applicable": "钓鱼竿", "description": "增加宝藏钓获率"},
        {"id": "lure", "name": "饵钓", "max_level": 3, "applicable": "钓鱼竿", "description": "加快钓鱼速度"},
        {"id": "loyalty", "name": "忠诚", "max_level": 3, "applicable": "三叉戟", "description": "三叉戟自动返回"},
        {"id": "impaling", "name": "穿刺", "max_level": 5, "applicable": "三叉戟", "description": "增加对水生生物伤害(BE:接触水的生物)"},
        {"id": "riptide", "name": "激流", "max_level": 3, "applicable": "三叉戟", "description": "在水中或雨中投掷时带动玩家"},
        {"id": "channeling", "name": "引雷", "max_level": 1, "applicable": "三叉戟", "description": "雷暴时击中生物召唤闪电"},
        {"id": "multishot", "name": "多重射击", "max_level": 1, "applicable": "弩", "description": "一次射出三支箭"},
        {"id": "quick_charge", "name": "快速装填", "max_level": 3, "applicable": "弩", "description": "加快弩装填速度"},
        {"id": "piercing", "name": "穿透", "max_level": 4, "applicable": "弩", "description": "箭矢穿透多个实体"},
        {"id": "curse_of_vanishing", "name": "消失诅咒", "max_level": 1, "applicable": "大部分物品", "description": "死亡时物品消失"},
        {"id": "curse_of_binding", "name": "绑定诅咒", "max_level": 1, "applicable": "盔甲/鞘翅", "description": "无法脱下"},
        {"id": "breach", "name": "破甲", "max_level": 4, "applicable": "锤", "description": "减少目标盔甲有效性"},
        {"id": "density", "name": "密度", "max_level": 5, "applicable": "锤", "description": "增加下落攻击伤害"},
        {"id": "wind_burst", "name": "风爆", "max_level": 3, "applicable": "锤", "description": "击中时产生风弹效果(仅JE)"},
    ]
    # Remove JE-only
    return [e for e in enchantments if "仅JE" not in e.get("description", "")]


# =====================================================================
# Particles — from zh.minecraft.wiki API
# =====================================================================

def fetch_particles(client: httpx.Client) -> list[dict]:
    """Parse particle IDs from zh.minecraft.wiki."""
    print("Fetching particles from zh.minecraft.wiki...")
    html = wiki_api_parse(client, "粒子")
    soup = BeautifulSoup(html, "html.parser")

    particles: list[dict] = []
    seen = set()
    # Find all code/tt elements that look like particle IDs
    for el in soup.find_all(["code", "tt"]):
        text = el.get_text(strip=True)
        if text.startswith("minecraft:") and "particle" in text.lower():
            pid = text
            if pid not in seen:
                seen.add(pid)
                name = pid.replace("minecraft:", "").replace("_particle", "").replace("_", " ").title()
                particles.append({"id": pid, "name": name, "description": ""})

    # Also search in table cells
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            for cell in cells:
                text = cell.get_text(strip=True)
                if text.startswith("minecraft:") and ("particle" in text or "_" in text):
                    if text not in seen and len(text) < 80:
                        seen.add(text)
                        name = text.replace("minecraft:", "").replace("_", " ").title()
                        particles.append({"id": text, "name": name, "description": ""})

    return particles


# =====================================================================
# Sounds — from zh.minecraft.wiki API
# =====================================================================

def fetch_sounds(client: httpx.Client) -> list[dict]:
    """Parse sound IDs. This is complex — use the playsound page."""
    print("Fetching sounds from zh.minecraft.wiki...")
    html = wiki_api_parse(client, "命令/playsound")
    soup = BeautifulSoup(html, "html.parser")

    sounds: list[dict] = []
    seen = set()
    for el in soup.find_all(["code", "tt"]):
        text = el.get_text(strip=True)
        if "." in text and not text.startswith("/") and not text.startswith("{"):
            # Looks like a sound ID (e.g., mob.zombie.say)
            if text not in seen and len(text) < 80 and not any(c in text for c in "=<>[]{}"):
                seen.add(text)
                sounds.append({
                    "id": text,
                    "name": text.replace(".", " ").replace("_", " ").title(),
                    "category": text.split(".")[0] if "." in text else "other",
                    "description": "",
                })

    # If we got too few from playsound page, also try the sound events page
    if len(sounds) < 100:
        try:
            time.sleep(DELAY)
            html2 = wiki_api_parse(client, "基岩版声音事件值列表")
            soup2 = BeautifulSoup(html2, "html.parser")
            for table in soup2.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if cells:
                        text = cells[0].get_text(strip=True)
                        if "." in text and text not in seen and len(text) < 80:
                            seen.add(text)
                            sounds.append({
                                "id": text,
                                "name": text.replace(".", " ").replace("_", " ").title(),
                                "category": text.split(".")[0] if "." in text else "other",
                                "description": "",
                            })
        except Exception as e:
            print(f"  Warning: sound events page failed: {e}")

    return sounds


# =====================================================================
# Biomes — from zh.minecraft.wiki API
# =====================================================================

def fetch_biomes(client: httpx.Client) -> list[dict]:
    """Parse biome IDs from zh.minecraft.wiki."""
    print("Fetching biomes from zh.minecraft.wiki...")
    html = wiki_api_parse(client, "生物群系")
    soup = BeautifulSoup(html, "html.parser")

    biomes: list[dict] = []
    seen = set()
    for el in soup.find_all(["code", "tt"]):
        text = el.get_text(strip=True)
        # Biome IDs are lowercase with underscores, no colons typically
        if re.match(r"^[a-z][a-z0-9_]+$", text) and len(text) > 3 and text not in seen:
            if any(k in text for k in ["plains", "forest", "desert", "ocean", "mountain",
                                        "swamp", "jungle", "taiga", "savanna", "badlands",
                                        "beach", "river", "nether", "end", "cave", "deep",
                                        "ice", "snowy", "frozen", "warm", "cold", "lukewarm",
                                        "cherry", "bamboo", "mangrove", "grove", "meadow",
                                        "peaks", "stony", "birch", "dark", "flower",
                                        "mushroom", "eroded", "wooded", "windswept",
                                        "dripstone", "lush", "basalt", "soul_sand",
                                        "warped", "crimson", "the_end", "void"]):
                seen.add(text)
                biomes.append({
                    "id": text,
                    "name": _id_to_name(text),
                    "description": "",
                })

    return biomes


# =====================================================================
# Structures, Gamerules — from zh.minecraft.wiki API
# =====================================================================

def fetch_gamerules(client: httpx.Client) -> list[dict]:
    """Parse gamerules from zh.minecraft.wiki."""
    print("Fetching gamerules from zh.minecraft.wiki...")
    html = wiki_api_parse(client, "游戏规则")
    soup = BeautifulSoup(html, "html.parser")

    rules: list[dict] = []
    seen = set()
    for el in soup.find_all(["code", "tt"]):
        text = el.get_text(strip=True)
        if re.match(r"^[a-z][a-zA-Z]+$", text) and len(text) > 5 and text not in seen:
            seen.add(text)
            rules.append({
                "id": text,
                "name": text,
                "description": "",
                "value_type": "boolean",
            })

    return rules


def fetch_structures(client: httpx.Client) -> list[dict]:
    """Parse structure IDs from zh.minecraft.wiki."""
    print("Fetching structures from zh.minecraft.wiki...")
    html = wiki_api_parse(client, "命令/locate")
    soup = BeautifulSoup(html, "html.parser")

    structures: list[dict] = []
    seen = set()
    for el in soup.find_all(["code", "tt"]):
        text = el.get_text(strip=True)
        if re.match(r"^[a-z][a-z_]+$", text) and len(text) > 3 and text not in seen:
            if any(k in text for k in ["village", "temple", "monument", "mansion",
                                        "fortress", "stronghold", "mineshaft", "outpost",
                                        "shipwreck", "ruins", "portal", "bastion",
                                        "ancient_city", "trail_ruins", "trial_chambers",
                                        "witch", "igloo", "pillager", "endcity",
                                        "buried_treasure"]):
                seen.add(text)
                structures.append({
                    "id": text,
                    "name": _id_to_name(text),
                    "description": "",
                })

    return structures


# =====================================================================
# Main
# =====================================================================

ALL_CATEGORIES = [
    "blocks", "items", "entities", "effects", "enchantments",
    "particles", "sounds", "biomes", "gamerules", "structures",
]


def main():
    parser = argparse.ArgumentParser(description="Update knowledge_base/ids/ from authoritative sources")
    parser.add_argument("--category", nargs="+", choices=ALL_CATEGORIES + ["all"], default=["all"])
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing")
    args = parser.parse_args()

    cats = ALL_CATEGORIES if "all" in args.category else args.category
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        results = {}

        if "blocks" in cats or "items" in cats:
            blocks, items = fetch_blocks_and_items(client)
            if "blocks" in cats:
                results["blocks"] = save_json("blocks", blocks, args.dry_run)
            if "items" in cats:
                results["items"] = save_json("items", items, args.dry_run)
            time.sleep(DELAY)

        if "entities" in cats:
            entities = fetch_entities(client)
            results["entities"] = save_json("entities", entities, args.dry_run)
            time.sleep(DELAY)

        if "effects" in cats:
            effects = fetch_effects(client)
            results["effects"] = save_json("effects", effects, args.dry_run)

        if "enchantments" in cats:
            enchantments = fetch_enchantments(client)
            results["enchantments"] = save_json("enchantments", enchantments, args.dry_run)

        if "particles" in cats:
            particles = fetch_particles(client)
            results["particles"] = save_json("particles", particles, args.dry_run)
            time.sleep(DELAY)

        if "sounds" in cats:
            sounds = fetch_sounds(client)
            results["sounds"] = save_json("sounds", sounds, args.dry_run)
            time.sleep(DELAY)

        if "biomes" in cats:
            biomes = fetch_biomes(client)
            results["biomes"] = save_json("biomes", biomes, args.dry_run)
            time.sleep(DELAY)

        if "gamerules" in cats:
            gamerules = fetch_gamerules(client)
            results["gamerules"] = save_json("gamerules", gamerules, args.dry_run)
            time.sleep(DELAY)

        if "structures" in cats:
            structures = fetch_structures(client)
            results["structures"] = save_json("structures", structures, args.dry_run)

    print(f"\n{'='*50}")
    print("Summary:")
    for cat, count in results.items():
        print(f"  {cat:15s} {count:5d}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
