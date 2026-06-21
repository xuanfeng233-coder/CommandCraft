#!/usr/bin/env python3
"""Add Chinese descriptions to sounds.json and animations.json."""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "knowledge_base" / "ids"

# ─── Entity/block/biome name mappings (from existing knowledge base) ───

def load_name_map(filename: str) -> dict[str, str]:
    data = json.loads((BASE / filename).read_text("utf-8"))
    m = {}
    for entry in data:
        desc = entry.get("description", "") or ""
        if desc and not desc.isascii():  # has Chinese
            m[entry["id"]] = desc
    return m

ENTITY_CN = load_name_map("entities.json")
BLOCK_CN = load_name_map("blocks.json")
BIOME_CN = load_name_map("biomes.json")

# ─── Manual word→Chinese mappings ───

MOB_MAP = {
    **ENTITY_CN,
    "zombie": "僵尸", "skeleton": "骷髅", "creeper": "苦力怕", "spider": "蜘蛛",
    "enderman": "末影人", "slime": "史莱姆", "ghast": "恶魂", "blaze": "烈焰人",
    "witch": "女巫", "guardian": "守卫者", "elder_guardian": "远古守卫者",
    "wither": "凋灵", "ender_dragon": "末影龙", "pig": "猪", "cow": "牛",
    "sheep": "羊", "chicken": "鸡", "wolf": "狼", "cat": "猫", "ocelot": "豹猫",
    "horse": "马", "donkey": "驴", "mule": "骡", "rabbit": "兔子", "bat": "蝙蝠",
    "villager": "村民", "iron_golem": "铁傀儡", "snowgolem": "雪傀儡",
    "snow_golem": "雪傀儡", "magma_cube": "岩浆怪", "silverfish": "蠹虫",
    "shulker": "潜影贝", "phantom": "幻翼", "drowned": "溺尸", "turtle": "海龟",
    "dolphin": "海豚", "cod": "鳕鱼", "salmon": "鲑鱼", "pufferfish": "河豚",
    "tropical_fish": "热带鱼", "squid": "鱿鱼", "glow_squid": "发光鱿鱼",
    "parrot": "鹦鹉", "fox": "狐狸", "bee": "蜜蜂", "panda": "熊猫",
    "hoglin": "疣猪兽", "piglin": "猪灵", "piglin_brute": "猪灵蛮兵",
    "zoglin": "僵尸疣猪兽", "strider": "炽足兽", "axolotl": "美西螈",
    "goat": "山羊", "frog": "青蛙", "tadpole": "蝌蚪", "warden": "监守者",
    "allay": "悦灵", "camel": "骆驼", "sniffer": "嗅探兽", "armadillo": "犰狳",
    "breeze": "旋风人", "bogged": "沼骸", "llama": "羊驼", "ravager": "劫掠兽",
    "vex": "恼鬼", "evoker": "唤魔者", "vindicator": "卫道士", "pillager": "掠夺者",
    "stray": "流浪者", "husk": "尸壳", "wither_skeleton": "凋灵骷髅",
    "zombie_villager": "僵尸村民", "zombie_pigman": "僵尸猪灵",
    "cave_spider": "洞穴蜘蛛", "mooshroom": "哞菇", "polar_bear": "北极熊",
    "endermite": "末影螨", "wandering_trader": "流浪商人",
    "trader_llama": "行商羊驼", "armor_stand": "盔甲架", "evocation_illager": "唤魔者",
    "zombie_horse": "僵尸马", "skeleton_horse": "骷髅马",
    "agent": "代理机器人", "npc": "NPC",
    # Compound names without underscores (as used in sound IDs)
    "wanderingtrader": "流浪商人", "polarbear": "北极熊", "irongolem": "铁傀儡",
    "enderdragon": "末影龙", "zombiepig": "僵尸猪灵", "zombiepigman": "僵尸猪灵",
    "magmacube": "岩浆怪", "cavespider": "洞穴蜘蛛", "snowgolem": "雪傀儡",
    "elderguardian": "远古守卫者", "ghastling": "小恶魂",
    "witherbone": "凋灵骨", "witherskeleton": "凋灵骷髅",
    "zombievillager": "僵尸村民", "traderllama": "行商羊驼",
    "skeletonhorse": "骷髅马", "zombiehorse": "僵尸马",
    "piglinbrute": "猪灵蛮兵", "screamer": "尖叫者",
    "evocationillager": "唤魔者", "driedghast": "脱水恶魂",
    "creaking": "嘎枝怪",
}

BLOCK_MAP = {
    **BLOCK_CN,
    "stone": "石头", "dirt": "泥土", "grass": "草", "sand": "沙子", "gravel": "沙砾",
    "wood": "木头", "planks": "木板", "log": "原木", "leaves": "树叶",
    "glass": "玻璃", "wool": "羊毛", "anvil": "铁砧", "beacon": "信标",
    "bell": "钟", "brewing_stand": "酿造台", "barrel": "桶", "bamboo": "竹子",
    "bone": "骨头", "cake": "蛋糕", "campfire": "营火", "candle": "蜡烛",
    "chain": "锁链", "chest": "箱子", "composter": "堆肥桶",
    "copper": "铜", "coral": "珊瑚", "crop": "作物", "deepslate": "深板岩",
    "door": "门", "dripstone": "钟乳石", "enchant": "附魔台",
    "end_portal": "末地传送门", "fence": "栅栏", "fire": "火",
    "furnace": "熔炉", "grindstone": "砂轮", "honey": "蜂蜜", "ice": "冰",
    "iron_door": "铁门", "iron_trapdoor": "铁活板门", "ladder": "梯子",
    "lantern": "灯笼", "lava": "熔岩", "lever": "拉杆", "metal": "金属",
    "moss": "苔藓", "nether_brick": "下界砖", "nether_wart": "地狱疣",
    "pointed_dripstone": "尖滴石", "piston": "活塞", "portal": "传送门",
    "pressure_plate": "压力板", "pumpkin": "南瓜", "rail": "铁轨",
    "redstone": "红石", "respawn_anchor": "重生锚", "scaffolding": "脚手架",
    "sculk": "幽匿", "sculk_sensor": "幽匿感测体", "sculk_shrieker": "幽匿尖啸体",
    "sculk_catalyst": "幽匿催发体", "shroomlight": "菌光体",
    "shulker_box": "潜影盒", "sign": "告示牌", "smithing_table": "锻造台",
    "snow": "雪", "soul_sand": "灵魂沙", "sponge": "海绵",
    "stonecutter": "切石机", "suspicious_sand": "可疑的沙子",
    "suspicious_gravel": "可疑的沙砾", "sweet_berry_bush": "甜浆果丛",
    "tnt": "TNT", "torch": "火把", "trapdoor": "活板门",
    "tripwire": "绊线", "turtle_egg": "海龟蛋", "vine": "藤蔓",
    "water": "水", "wheat": "小麦", "amethyst": "紫水晶",
    "azalea": "杜鹃花", "basalt": "玄武岩", "big_dripleaf": "大型垂滴叶",
    "small_dripleaf": "小型垂滴叶", "calcite": "方解石", "candle_cake": "蜡烛蛋糕",
    "cave_vines": "洞穴藤蔓", "chain_command_block": "连锁命令方块",
    "command_block": "命令方块", "conduit": "导管", "crying_obsidian": "哭泣黑曜石",
    "dried_kelp": "干海带", "flowering_azalea": "盛开的杜鹃花",
    "froglight": "蛙明灯", "frogspawn": "青蛙卵", "gilded_blackstone": "镶金黑石",
    "glow_lichen": "发光地衣", "hanging_roots": "垂根",
    "lightning_rod": "避雷针", "lodestone": "磁石", "mangrove": "红树",
    "mud": "泥巴", "nylium": "菌岩", "packed_mud": "泥坯",
    "polished_deepslate": "磨制深板岩", "powder_snow": "细雪",
    "raw_copper": "粗铜", "raw_gold": "粗金", "raw_iron": "粗铁",
    "rooted_dirt": "缠根泥土", "spore_blossom": "孢子花",
    "tuff": "凝灰岩", "wart_block": "疣块", "decorated_pot": "饰纹陶罐",
    "brush": "刷子", "cherry": "樱花",
    "beehive": "蜂箱", "bee_nest": "蜂巢", "blastfurnace": "高炉",
    "cartography_table": "制图台", "end_bricks": "末地砖", "end_stone": "末地石",
    "end_rod": "末地烛", "end_gateway": "末地折跃门", "ender_chest": "末影箱",
    "enchanting_table": "附魔台", "dispenser": "发射器", "dropper": "投掷器",
    "observer": "侦测器", "hopper": "漏斗", "jukebox": "唱片机",
    "note_block": "音符盒", "noteblock": "音符盒", "slime": "黏液块",
    "honey_block": "蜂蜜块", "honeycomb": "蜜脾", "nether_gold_ore": "下界金矿",
    "netherrack": "下界岩", "nether_sprouts": "下界苗", "weeping_vines": "垂泪藤",
    "twisting_vines": "缠怨藤", "warped_stem": "诡异菌柄",
    "crimson_stem": "绯红菌柄", "warped_roots": "诡异菌索",
    "crimson_roots": "绯红菌索", "warped_fungus": "诡异菌",
    "crimson_fungus": "绯红菌", "shroomlight": "菌光体", "target": "标靶",
    "lodestone": "磁石", "loom": "织布机", "smoker": "烟熏炉",
    "lecturn": "讲台", "lectern": "讲台", "barrel": "桶",
    "chiseled_bookshelf": "雕纹书架", "bookshelf": "书架",
    "wet_sponge": "湿海绵", "heavy_core": "重力核心",
    "trial_spawner": "试炼刷怪笼", "vault": "宝库",
    "creaking_heart": "嘎枝之心", "resin": "树脂",
    "pale_hanging_moss": "苍白垂苔", "eyeblossom": "眼花",
    "cobweb": "蜘蛛网", "cloth": "布料", "stem": "菌柄",
    "roots": "菌索", "fungus": "菌", "nylium": "菌岩",
    # Compound block names without underscores
    "chorusflower": "紫颂花", "chorusplant": "紫颂植株",
    "copper_bulb": "铜灯", "copper_chest": "铜箱子",
    "copper_golem_statue": "铜傀儡雕像", "copper_door": "铜门",
    "copper_trapdoor": "铜活板门",
    "itemframe": "物品展示框", "item_frame": "物品展示框",
    "hangingsign": "悬挂告示牌", "hanging_sign": "悬挂告示牌",
    "hanging": "悬挂", "wooden": "木", "pale": "苍白",
    "nether_brick": "下界砖", "end_bricks": "末地砖",
    "brick": "砖", "bricks": "砖块",
    "shelf": "书架", "dry_grass": "干草",
    "bamboo_wood": "竹木", "bamboo_wood_button": "竹木按钮",
    "cherry_wood": "樱木", "cherry_wood_button": "樱木按钮",
    "stone_button": "石头按钮", "wooden_button": "木按钮",
    "wooden_door": "木门", "wooden_trapdoor": "木活板门",
    "wooden_pressure_plate": "木压力板",
    "nether_wood": "下界木", "nether_wood_button": "下界木按钮",
    "nether_wood_door": "下界木门", "nether_wood_trapdoor": "下界木活板门",
    "bamboo_wood_door": "竹木门", "bamboo_wood_trapdoor": "竹木活板门",
    "cherry_wood_door": "樱木门", "cherry_wood_trapdoor": "樱木活板门",
    "pale_oak_wood": "苍白橡木", "pale_oak_wood_button": "苍白橡木按钮",
    "mangrove_wood": "红树木",
    "stone_pressure_plate": "石质压力板",
    "iron_button": "铁按钮", "polished_blackstone_button": "磨制黑石按钮",
    "copper_button": "铜按钮",
    "copper_grate": "铜格栅", "copper_ore": "铜矿",
    "resin_brick": "树脂砖", "resin_bricks": "树脂砖块",
    "heavy_core": "重力核心",
    # Pressure plates and fence gates (compound keys used in click_on/off/open/close)
    "bamboo_wood_pressure_plate": "竹木压力板",
    "cherry_wood_pressure_plate": "樱木压力板",
    "metal_pressure_plate": "金属压力板",
    "nether_wood_pressure_plate": "下界木压力板",
    "bamboo_wood_fence_gate": "竹木栅栏门",
    "cherry_wood_fence_gate": "樱木栅栏门",
    "nether_wood_fence_gate": "下界木栅栏门",
    "pale_oak_wood_fence_gate": "苍白橡木栅栏门",
    "bamboo_wood_hanging_sign": "竹木悬挂告示牌",
    "cherry_wood_hanging_sign": "樱木悬挂告示牌",
    "nether_wood_hanging_sign": "下界木悬挂告示牌",
}

BIOME_MAP = {
    **BIOME_CN,
    "basalt_deltas": "玄武岩三角洲", "crimson_forest": "绯红森林",
    "nether_wastes": "下界荒地", "soul_sand_valley": "灵魂沙峡谷",
    "warped_forest": "诡异森林", "soulsand_valley": "灵魂沙峡谷",
    "end": "末地", "nether": "下界", "overworld": "主世界",
    "cave": "洞穴", "underwater": "水下", "the_end": "末地",
    "deep_dark": "深暗之域", "cherry_grove": "樱花树林",
    "dripstone_caves": "溶洞", "frozen_peaks": "冰封山峰",
    "grove": "雪林", "jagged_peaks": "尖峭山峰", "lush_caves": "繁茂洞穴",
    "meadow": "草甸", "snowy_slopes": "积雪山坡", "stony_peaks": "裸岩山峰",
    "pale_garden": "苍白花园",
}

ACTION_MAP = {
    "hit": "击打", "break": "破坏", "place": "放置", "step": "踩踏", "fall": "摔落",
    "land": "着地", "jump": "跳跃", "swim": "游泳", "splash": "泼溅", "fizz": "嘶嘶声",
    "attack": "攻击", "death": "死亡", "hurt": "受伤", "idle": "待机",
    "say": "叫声", "ambient": "环境音", "breathe": "呼吸", "roar": "吼叫",
    "scream": "尖叫", "charge": "蓄力", "shoot": "射击", "throw": "投掷",
    "eat": "进食", "drink": "饮用", "burp": "打嗝", "spit": "吐", "growl": "咆哮",
    "purr": "咕噜声", "hiss": "嘶嘶声", "stare": "凝视", "teleport": "传送",
    "explode": "爆炸", "ignite": "点燃", "thunder": "雷声", "rain": "雨声",
    "click": "点击", "open": "打开", "close": "关闭", "closed": "关闭",
    "detach": "分离", "attach": "附着", "equip": "装备", "unfold": "展开",
    "power": "充能", "on": "开启", "off": "关闭", "activate": "激活",
    "deactivate": "关闭", "big": "大型", "small": "小型",
    "loop": "循环", "mood": "氛围", "moody": "氛围", "additions": "附加音",
    "spawn": "生成", "convert": "转化", "shear": "剪", "milk": "挤奶",
    "celebrate": "庆祝", "retreat": "撤退", "prepare": "准备",
    "summon": "召唤", "cast": "施法", "fang": "尖牙",
    "haggle": "讨价还价", "trade": "交易", "yes": "同意", "no": "拒绝",
    "gulp": "吞咽", "sniff": "嗅探", "dig": "挖掘", "stomp": "踩踏",
    "walk": "行走", "fly": "飞行", "flap": "拍翅", "flop": "扑腾",
    "agitated": "躁动", "angry": "愤怒", "happy": "开心", "sad": "悲伤",
    "pre_ram": "准备冲撞", "ram_impact": "冲撞", "screaming_ram_impact": "尖啸冲撞",
    "born": "出生", "baby": "幼年", "tongue": "舌头",
    "listening": "聆听", "heartbeat": "心跳", "click_off": "关闭点击",
    "click_on": "开启点击", "item_given": "给予物品", "item_taken": "拿取物品",
    "item_thrown": "丢出物品", "shriek": "尖啸", "nearby_close": "靠近",
    "nearby_closer": "更靠近", "nearby_closest": "极近", "wax": "涂蜡",
    "copper_wax_on": "涂蜡", "copper_wax_off": "刮蜡",
    "detect": "检测", "emerge": "出现", "dig_roar": "挖掘吼叫",
    "sonic_charge": "音波蓄力", "sonic_boom": "音波冲击",
    "crossbow": "弩", "loading_end": "装填完成", "loading_middle": "装填中",
    "loading_start": "开始装填", "quick_charge": "快速装填",
    "armor": "盔甲", "armor_crack": "盔甲碎裂", "armor_damage": "盔甲损坏",
    "armor_repair": "盔甲修复", "brush": "刷子",
    "wind_charge": "风弹", "burst": "爆裂", "whirl": "旋转",
    "pop": "弹出", "insert": "插入", "decorated_pot_insert": "饰纹陶罐插入",
    "decorated_pot_shatter": "饰纹陶罐破碎",
    "tempt": "吸引", "panic": "恐慌", "admire": "欣赏", "jealous": "嫉妒",
    "suspicious": "可疑", "raid": "袭击", "warn": "警告",
    "pick_berries": "摘浆果", "roll": "滚动", "unroll": "展开", "peek": "窥视",
    "land_hard": "重着地", "land_soft": "轻着地",
    "enter": "进入", "exit": "退出", "drip": "滴落", "work": "工作",
    "crackle": "噼啪声", "use": "使用", "impact": "冲击", "fire": "发射",
    "fire_crackle": "火焰噼啪", "light_flash": "闪光",
    "critical": "暴击", "nodamage": "无伤", "strong": "强力",
    "pull": "拉弓", "release": "释放", "stun": "击晕",
    "levelup": "升级", "pickup": "拾取",
    "bowhit": "弓命中", "swing": "挥击", "extinguish": "熄灭",
    "plop": "落入", "destroy": "摧毁", "repair": "修复",
    "thorns": "荆棘反伤", "insert_enchanted": "插入附魔物品",
    "shimmer": "微光", "scrape": "刮除", "tilt_down": "下倾", "tilt_up": "上倾",
    "hand": "手持", "apply": "涂抹", "complete": "完成",
    "shatter": "碎裂", "fail": "失败", "success": "成功",
    "take": "取出", "deposit": "存入", "eject": "弹出",
    "deflect": "偏转", "lock": "锁定", "unlock": "解锁",
    "inhale": "吸气", "shoot_tongue": "射出舌头", "tongue_retract": "舌头收回",
    "gallop": "疾驰", "step_sand": "踩沙", "sit_down": "坐下", "stand_up": "站起",
    "dash": "冲刺", "dash_ready": "冲刺就绪",
    "lay_egg": "产卵", "hatch": "孵化", "bite": "咬",
    "pre_attack": "准备攻击", "aggressive": "攻击性",
    "plead": "恳求", "assert": "宣示", "copulate": "繁殖",
    "drop_seed": "掉落种子", "imitate": "模仿",
    "power_on": "开启", "power_off": "关闭",
    "ambient_with_rider": "骑乘环境音", "ambient_tame": "驯服环境音",
    "mad": "狂暴", "scared": "害怕", "presneeze": "打喷嚏前",
    "sneeze": "打喷嚏", "cant_breed": "无法繁殖",
    "empty": "倒空", "fill": "充填", "fill_water": "充水",
    "fill_lava": "充熔岩", "takewater": "取水", "takelava": "取熔岩",
    "saddle": "装鞍", "eat_grass": "吃草", "armor_tame": "盔甲驯服",
    "step_lava": "踩熔岩", "step_wood": "踩木头",
    "unfold_wings": "展开翅膀", "curse": "诅咒",
    "larger": "较大", "smaller": "较小",
    "flap_wings": "拍翅", "boost": "加速",
    "call": "鸣叫", "call0": "鸣叫", "call1": "鸣叫2",
    "call2": "鸣叫3", "call3": "鸣叫4", "call4": "鸣叫5",
    "call5": "鸣叫6", "call6": "鸣叫7", "call7": "鸣叫8",
    "steer": "转向", "smoke": "烟雾", "horn": "号角",
    "page_turn": "翻页", "latch": "闩锁", "polished": "磨制",
    "grow": "生长", "ready": "就绪", "trail": "踪迹",
    "spawn_mob": "生成生物", "place_in_water": "放入水中",
    "bark": "吠叫", "panting": "喘息", "whine": "呜咽",
    "shake": "甩水", "sit": "坐下", "stand": "站立",
    "purreow": "咪呜", "lunge": "突刺", "riptide": "激流",
    "crack": "碎裂", "damage": "损坏", "unequip": "卸下",
    "turn_on": "开启", "turn_off": "关闭",
    "oxidized": "氧化", "weathered": "风化", "exposed": "斑驳",
    "generic": "通用", "smash": "重击", "ground": "落地",
    "take_result": "取出结果", "long": "长",
    "converted_to_zombified": "僵尸化",
    "picky": "挑食", "cute": "可爱", "grumpy": "暴躁",
    "idle_water": "水中待机", "inwater": "水中",
    "in_water": "水中", "spawn_inwater": "水中生成",
    "mini": "小型", "royal": "皇家",
    "attack_hit": "攻击命中", "attack_miss": "攻击未中",
    # More actions for various patterns
    "lightning": "闪电", "state_change": "状态变化", "lit": "点亮",
    "add_item": "添加物品", "remove_item": "移除物品", "rotate_item": "旋转物品",
    "climb": "攀爬", "pick": "采摘", "drop": "掉落",
    "down": "下行", "up": "上行", "downinside": "下行(内部)", "upinside": "上行(内部)",
    "add_candle": "添加蜡烛", "take_picture": "拍照",
    "adddye": "加染料", "cleanarmor": "清洗盔甲", "cleanbanner": "清洗旗帜",
    "dyearmor": "染盔甲", "fillpotion": "充药水", "fillwater": "充水",
    "takepotion": "取药水", "remove_one": "取出一个", "drop_contents": "倒出内容",
    "multi_swap": "多项交换", "single_swap": "单项交换",
    "place_item": "放置物品", "waxed_interact_fail": "涂蜡交互失败",
    "add": "添加", "remove": "移除", "rotate": "旋转",
    "dry": "干燥", "attached": "附着", "picture": "照片",
    "empty_fish": "倒出鱼", "fill_fish": "装入鱼",
    "empty_powder_snow": "倒出细雪", "fill_powder_snow": "装入细雪",
    "craft": "合成", "failed": "失败", "button": "按钮",
    "false_permissions": "无权限",
    # Parrot imitation
    "bogged": "沼骸", "breeze": "旋风人",
    # riptide variations
    "riptide_1": "激流1", "riptide_2": "激流2", "riptide_3": "激流3",
    # note types
    "bass": "低音", "bassattack": "低音攻击", "bd": "底鼓", "harp": "竖琴",
    "hat": "踩镲", "snare": "军鼓", "pling": "叮铃", "guitar": "吉他",
    "bit": "比特", "banjo": "班卓琴", "didgeridoo": "迪吉里杜管",
    "chime": "风铃", "flute": "长笛", "icechime": "冰风铃",
    "iron_xylophone": "铁木琴", "xylophone": "木琴", "cow_bell": "牛铃",
    # misc
    "start": "开始", "end": "结束", "middle": "中段",
    "launch": "发射", "blast": "爆炸", "twinkle": "闪烁",
    "large_blast": "大爆炸", "shoot_grow": "射击生长",
    "heavy_step": "重踩踏", "item_interact": "物品交互",
    "swap": "交换", "clean": "清洗", "dye": "染色",
    "potion": "药水",
    # More compound/missing words
    "pressureplate": "压力板", "pressure_plate": "压力板",
    "gate": "门", "fence_gate": "栅栏门",
    "vines": "藤蔓", "vine": "藤蔓",
    "in": "在", "to": "到", "the": "",
    "loading": "装填", "spin": "旋转",
    "shutter": "快门", "interaction": "交互",
    "freeze": "冻结", "kill": "击杀",
    "ink_squirt": "喷墨", "ink": "墨",
    "ram": "冲撞", "ride": "骑乘",
    "goggles": "护目镜", "harness": "挽具",
    "short": "短", "disable_slot": "禁用槽位",
    "fallbig": "大摔落", "fallsmall": "小摔落",
    "die": "死亡", "put": "放入",
    "firecharge": "火焰弹", "fire_charge": "火焰弹",
    "stop_using": "停止使用", "return": "返回",
    "lava": "熔岩", "lavapop": "熔岩气泡",
    "base": "基础", "inside": "内部",
    "holding": "持有", "reduced": "减免",
    "scute": "鳞甲片", "scute_drop": "掉落鳞甲片",
    "finish": "完成", "takeoff": "起飞",
    "pollinate": "授粉", "sting": "蜇刺",
    "slide": "滑行", "beg": "乞食", "beg_for_food": "乞食",
    "meow": "喵叫", "straymeow": "流浪猫叫",
    "purreow": "咪呜", "jungle": "丛林",
    "endermen": "末影人", "puglin": "猪灵",
    "item": "物品", "block": "方块",
    "converted_to": "转化为", "converted_to_drowned": "转化为溺尸",
    "fish": "鱼", "forest": "森林", "loom": "织布机",
    "nautilus": "鹦鹉螺", "baby_nautilus": "幼年鹦鹉螺",
    "jump_to_block": "跳到方块",
    "heavy_smash_ground": "重击落地",
    "idle_holding": "待机持有",
    "hurt_reduced": "受伤减免",
    "unroll_finish": "展开完成",
    "light_flash": "闪光", "lightflash": "闪光",
    "the_end_light_flash": "末地闪光",
    # More mob actions
    "fuse": "引线", "sway": "摇晃", "twitch": "抽搐", "unfreeze": "解冻",
    "blowhole": "喷气孔", "play": "嬉戏", "spell": "咒语",
    "wololo": "沃洛洛", "prepare_wololo": "准备变色术",
    "aggro": "仇恨", "screech": "尖啸", "sleep": "睡觉",
    "affectionate_scream": "友好尖叫", "moan": "呻吟", "howl": "嚎叫",
    "soft": "轻声", "carpet": "地毯", "swag": "装饰",
    "carpet_unequip": "卸下地毯", "worried": "担忧",
    "swoop": "俯冲", "admiring_item": "欣赏物品",
    "drown": "溺水", "hurt_drown": "溺水受伤",
    "warning": "警告", "hop": "蹦跳",
    "bullet": "弹丸", "squish": "挤压",
    "digging": "挖掘中", "searching": "搜索中", "sniffsniff": "嗅嗅",
    "disappeared": "消失", "reappeared": "重现",
    "clicking": "嗒嗒声", "remedy": "治疗",
    "unfect": "解除感染", "woodbreak": "破门",
    "zpig": "待机", "zpigangry": "愤怒", "zpigdeath": "死亡", "zpighurt": "受伤",
    "becoming_statue": "石化中",
    "unsaddle": "卸鞍", "pause_growth": "暂停生长", "reset_growth": "重置生长",
    "lay_spawn": "产卵",
    # Music game modes
    "creative": "创造模式", "survival": "生存模式",
    "credits": "制作人员名单", "menu": "菜单", "nether": "下界", "end": "末地",
    # Evocation fangs
    "evocation_fangs": "唤魔者尖牙",
    # Misc
    "lunge1": "突刺1", "lunge2": "突刺2", "lunge3": "突刺3",
    "stop": "停止", "using": "使用中",
    "become": "变为", "becoming": "变为中",
    "squirt": "喷射",
    "lay": "产", "spawn_inwater": "水中生成",
    "hover": "悬浮", "bob": "摆动",
    # More specific translations
    "absorb": "吸收", "travel": "传送", "trigger": "触发",
    "carve": "雕刻", "soul_escape": "灵魂逸散",
    "about_to_spawn_item": "即将生成物品", "spawn_item_begin": "开始生成物品",
    "brewed": "酿造完成", "endboss": "末影龙Boss战",
    "ambient_ominous": "不祥环境音",
    "reject_rewarded_player": "拒绝已奖励玩家",
    "stutterturn": "间歇转向",
    "out": "伸出", "select_pattern": "选择图案",
}

ITEM_MAP = {
    "bow": "弓", "shield": "盾牌", "trident": "三叉戟", "crossbow": "弩",
    "flintandsteel": "打火石", "bucket": "桶", "bone_meal": "骨粉",
    "bottle": "玻璃瓶", "eye_of_ender": "末影之眼", "book": "书",
    "page_turn": "翻页", "totem": "图腾", "spyglass": "望远镜",
    "goat_horn": "山羊角", "ink_sac": "墨囊", "dye": "染料",
    "use_on": "使用", "elytra": "鞘翅", "armor_equip": "装备盔甲",
    "smithing_table": "锻造台", "mace": "钉锤", "bundle": "收纳袋",
    "lodestone_compass": "磁石指针", "spear": "长矛",
}

MATERIAL_MAP = {
    "diamond": "钻石", "gold": "黄金", "iron": "铁", "leather": "皮革",
    "netherite": "下界合金", "chain": "锁链", "chainmail": "锁链",
    "turtle": "海龟壳", "wolf": "狼铠",
}

CATEGORY_CN = {
    "block": "方块", "hostile": "敌对生物", "neutral": "中立生物",
    "player": "玩家", "ambient": "环境", "record": "唱片",
    "music": "音乐", "ui": "界面", "weather": "天气",
    "bottle": "瓶子", "sign": "告示牌", "game": "游戏",
}


def _lookup_word(w: str) -> str:
    """Try all dictionaries to translate a single word/key."""
    ALL_DICTS = [ACTION_MAP, MOB_MAP, BLOCK_MAP, BIOME_MAP, ITEM_MAP, MATERIAL_MAP]
    for d in ALL_DICTS:
        if w in d:
            return d[w]
    # Try joining underscored parts
    if "_" in w:
        sub_parts = w.split("_")
        translated_parts = []
        for p in sub_parts:
            found = p
            for d in ALL_DICTS:
                if p in d:
                    found = d[p]
                    break
            translated_parts.append(found)
        if any(not p.isascii() for p in translated_parts):
            return "".join(translated_parts)
    return w


def translate_sound(entry: dict) -> str:
    sid = entry["id"]
    cat = entry.get("category", "")
    parts = sid.split(".")

    # Special: music tracks
    if parts[0] == "music":
        MUSIC_SPECIAL = {
            "creative": "创造模式", "credits": "制作人员名单", "menu": "菜单",
            "endboss": "末影龙Boss战", "water": "水下",
            "swamp_music": "沼泽", "nether": "下界",
        }
        BIOME_EXTRA = {
            "bamboo_jungle": "竹林", "desert": "沙漠", "flower_forest": "繁花森林",
            "forest": "森林", "jungle": "丛林", "jungle_edge": "丛林边缘",
            "mesa": "恶地", "swamp": "沼泽",
        }
        if len(parts) >= 3:
            sub_key = "_".join(parts[2:])
            # Try game-specific, then biome maps
            cn = MUSIC_SPECIAL.get(sub_key) or BIOME_EXTRA.get(sub_key) or BIOME_MAP.get(sub_key) or BIOME_MAP.get(parts[-1]) or _lookup_word(sub_key)
            area = parts[1]
            area_cn = {"game": "游戏", "overworld": "主世界", "nether": "下界", "end": "末地"}.get(area, area)
            return f"音乐 — {area_cn}/{cn}"
        if len(parts) == 2:
            cn = {"game": "游戏", "overworld": "主世界", "nether": "下界", "end": "末地",
                  "menu": "菜单",
                  "game_and_wild_equal_chance": "游戏与野外(等概率)",
                  "game_and_wild_favor_game": "游戏与野外(偏游戏)"}.get(parts[1], parts[1])
            return f"音乐 — {cn}"
        return "游戏音乐"

    # Note block instrument sounds (must be before record check since note has cat=="record")
    if parts[0] == "note":
        NOTE_INSTRUMENTS = {
            "bass": "低音", "bassattack": "低音鼓", "bd": "底鼓", "harp": "竖琴",
            "hat": "踩镲", "snare": "军鼓", "pling": "叮铃", "guitar": "吉他",
            "bit": "比特", "banjo": "班卓琴", "didgeridoo": "迪吉里杜管",
            "chime": "风铃", "flute": "长笛", "icechime": "冰风铃",
            "iron_xylophone": "铁木琴", "xylophone": "木琴", "cow_bell": "牛铃",
            "bell": "钟", "creeper": "苦力怕", "enderdragon": "末影龙",
            "piglin": "猪灵", "skeleton": "骷髅", "witherskeleton": "凋灵骷髅",
            "zombie": "僵尸", "trumpet": "铜号角",
            "trumpet_exposed": "铜号角(斑驳)", "trumpet_oxidized": "铜号角(氧化)",
            "trumpet_weathered": "铜号角(风化)",
        }
        if len(parts) >= 2:
            inst = "_".join(parts[1:])
            inst_cn = NOTE_INSTRUMENTS.get(inst, _lookup_word(inst))
            return f"音符盒 — {inst_cn}"
        return "音符盒"

    # Special: records
    if parts[0] == "record" or (cat == "record" and parts[0] != "mob" and parts[0] != "note"):
        disc = parts[-1] if len(parts) > 1 else sid
        return f"唱片 — {disc}"

    # Special: horn/goat horn
    if parts[0] == "horn":
        suffix = parts[-1] if len(parts) > 2 else ""
        return f"山羊角 — 鸣叫{suffix}"

    # Mob sounds: mob.entity.action
    if parts[0] == "mob" and len(parts) >= 2:
        mob_key = parts[1]
        mob_cn = MOB_MAP.get(mob_key, _lookup_word(mob_key))
        if len(parts) >= 3:
            actions = parts[2:]
            action_cn = "".join(_lookup_word(a) for a in actions)
            return f"{mob_cn} — {action_cn}"
        return mob_cn

    # Block sounds: block.type.action or dig/step/fall pattern
    if parts[0] in ("block", "dig", "step", "fall", "hit", "place", "use"):
        action_cn = ACTION_MAP.get(parts[0], parts[0])
        if len(parts) >= 2:
            # Try compound block key (e.g., "copper_bulb")
            block_key = parts[1]
            # Also try joining parts[1:2] for compound blocks without underscore
            block_cn = BLOCK_MAP.get(block_key, _lookup_word(block_key))
            if len(parts) >= 3:
                sub_actions = [_lookup_word(p) for p in parts[2:]]
                return f"{block_cn} — {''.join(sub_actions)}"
            if parts[0] in ("dig", "step", "fall", "hit", "place", "use"):
                return f"{block_cn} — {action_cn}"
            return block_cn
        return action_cn

    # Game events: game.player.attack.critical etc
    if parts[0] == "game":
        rest = [_lookup_word(p) for p in parts[1:]]
        return " — ".join(rest) if rest else "游戏"

    # Apply effect: apply_effect.bad_omen
    if parts[0] == "apply_effect":
        effect_name = "_".join(parts[1:])
        EFFECT_CN = {
            "bad_omen": "不祥之兆", "raid_omen": "袭击之兆",
            "trial_omen": "试炼之兆", "infested": "寄生",
            "oozing": "渗出", "weaving": "编织", "wind_charged": "充风",
        }
        return f"效果 — {EFFECT_CN.get(effect_name, effect_name)}"

    # Armor sounds at top level: armor.equip_diamond, armor.crack_wolf
    if parts[0] == "armor":
        if len(parts) >= 2:
            sub = "_".join(parts[1:])
            # Try compound first
            cn = _lookup_word(sub)
            if cn != sub and not cn.isascii():
                return f"盔甲 — {cn}"
            # Split by underscore and translate each
            rest = [_lookup_word(p) for p in sub.split("_")]
            # Check for material: equip_diamond -> 装备钻石
            for i, p in enumerate(parts[1:]):
                if p in MATERIAL_MAP:
                    rest[i] = MATERIAL_MAP[p]
            return f"盔甲 — {''.join(rest)}"
        return "盔甲"

    # Breeze / wind_charge at top level
    if parts[0] in ("breeze_wind_charge", "wind_charge"):
        if len(parts) >= 2:
            return f"风弹 — {_lookup_word(parts[1])}"
        return "风弹"

    # Ambient sounds
    if parts[0] == "ambient":
        if len(parts) >= 2:
            place_key = parts[1]
            if place_key == "weather":
                if len(parts) >= 3:
                    weather_action = "_".join(parts[2:])
                    weather_cn = _lookup_word(weather_action)
                    return f"天气 — {weather_cn}"
                return "天气音效"
            place_cn = BIOME_MAP.get(place_key, BLOCK_MAP.get(place_key, _lookup_word(place_key)))
            if len(parts) >= 3:
                rest_parts = parts[2:]
                rest_cn = "".join(_lookup_word(p) for p in rest_parts)
                return f"{place_cn} — 环境{rest_cn}"
            return f"{place_cn} — 环境音"
        return "环境音"

    # Item sounds: item.*
    if parts[0] == "item":
        if len(parts) >= 2:
            item_key = parts[1]
            item_cn = ITEM_MAP.get(item_key, BLOCK_MAP.get(item_key, _lookup_word(item_key)))
            if len(parts) >= 3:
                sub = "_".join(parts[2:])
                action_cn = _lookup_word(sub)
                if action_cn == sub:
                    action_cn = "".join(_lookup_word(p) for p in parts[2:])
                return f"{item_cn} — {action_cn}"
            return item_cn
        return "物品音效"

    # Random sounds
    if parts[0] == "random":
        RANDOM_MAP = {
            "anvil_break": "铁砧破碎", "anvil_land": "铁砧落地", "anvil_use": "铁砧使用",
            "bow": "射箭", "chestclosed": "关箱子", "chestopen": "开箱子",
            "door_close": "关门", "door_open": "开门", "drink_honey": "喝蜂蜜",
            "enderchestclosed": "关末影箱", "enderchestopen": "开末影箱",
            "glass": "玻璃碎", "lever_click": "拉杆", "orb": "经验球",
            "pop2": "弹出", "screenshot": "截图",
            "shulkerboxclosed": "关潜影盒", "shulkerboxopen": "开潜影盒",
            "stone_click": "石头点击", "toast": "提示通知",
            "toast_recipe_unlocking_in": "配方解锁通知(进入)",
            "toast_recipe_unlocking_out": "配方解锁通知(退出)",
            "totem": "不死图腾", "wood_click": "木头点击",
        }
        if len(parts) >= 2:
            sub = "_".join(parts[1:])
            cn = RANDOM_MAP.get(sub, _lookup_word(sub))
            return f"随机 — {cn}"
        return "随机音效"

    # Liquid
    if parts[0] == "liquid":
        LIQUID_MAP = {"lava": "熔岩", "lavapop": "熔岩气泡", "water": "水"}
        if len(parts) >= 2:
            return f"液体 — {LIQUID_MAP.get(parts[1], _lookup_word(parts[1]))}"
        return "液体音效"

    # Cauldron, conduit, etc
    if parts[0] == "cauldron":
        if len(parts) >= 2:
            sub = "_".join(parts[1:])
            return f"炼药锅 — {_lookup_word(sub)}"
        return "炼药锅"

    # Respawn anchor
    if "respawn_anchor" in sid:
        return "重生锚"

    # Fire, rain, thunder at top level
    if parts[0] == "fire":
        return f"火焰 — {_lookup_word(parts[1]) if len(parts) > 1 else '音效'}"

    # Bubble sounds
    if parts[0] == "bubble":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"气泡 — {rest}" if rest else "气泡"

    # Bundle
    if parts[0] == "bundle":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"收纳袋 — {rest}" if rest else "收纳袋"

    # Firework
    if parts[0] == "firework":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"烟花 — {rest}" if rest else "烟花"

    # Mace
    if parts[0] == "mace":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"钉锤 — {rest}" if rest else "钉锤"

    # Crossbow at top level
    if parts[0] == "crossbow":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"弩 — {rest}" if rest else "弩"

    # Entity
    if parts[0] == "entity":
        if len(parts) >= 2:
            entity_cn = MOB_MAP.get(parts[1], _lookup_word(parts[1]))
            if len(parts) >= 3:
                act_cn = "".join(_lookup_word(p) for p in parts[2:])
                return f"{entity_cn} — {act_cn}"
            return entity_cn
        return "实体"

    # Trial spawner
    if parts[0] == "trial_spawner":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"试炼刷怪笼 — {rest}" if rest else "试炼刷怪笼"

    # Vault
    if parts[0] == "vault":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"宝库 — {rest}" if rest else "宝库"

    # Crafter
    if parts[0] == "crafter":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"合成器 — {rest}" if rest else "合成器"

    # Bucket
    if parts[0] == "bucket":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"桶 — {rest}" if rest else "桶"

    # Conduit
    if parts[0] == "conduit":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"导管 — {rest}" if rest else "导管"

    # Elytra
    if parts[0] == "elytra":
        return "鞘翅"

    # Lodestone compass
    if parts[0] == "lodestone_compass":
        return "磁石指针"

    # Beacon
    if parts[0] == "beacon":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"信标 — {rest}" if rest else "信标"

    # Portal
    if parts[0] == "portal":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"传送门 — {rest}" if rest else "传送门"

    # Minecart
    if parts[0] == "minecart":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"矿车 — {rest}" if rest else "矿车"

    # Leashknot / lead
    if parts[0] in ("leashknot", "lead"):
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"拴绳 — {rest}" if rest else "拴绳"

    # Damage
    if parts[0] == "damage":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"伤害 — {rest}" if rest else "伤害"

    # Sign
    if parts[0] == "sign":
        rest = "".join(_lookup_word(p) for p in parts[1:]) if len(parts) > 1 else ""
        return f"告示牌 — {rest}" if rest else "告示牌"

    # Simple top-level actions that map directly
    SIMPLE_TOPS = {
        "bloom": "绽放", "brush_completed": "刷洗完成", "cake": "蛋糕",
        "camera": "相机", "charge": "蓄力", "chime": "风铃",
        "component": "组件", "drip": "滴落", "hatch": "孵化",
        "imitate": "模仿", "insert": "插入", "insert_enchanted": "插入附魔物品",
        "ominous_bottle": "不祥之瓶", "ominous_item_spawner": "不祥物品生成器",
        "particle": "粒子", "pick_berries": "摘浆果", "pickup": "拾取",
        "pickup_enchanted": "拾取附魔物品", "power": "充能", "pumpkin": "南瓜",
        "raid": "袭击", "resonate": "共鸣", "scrape": "刮除",
        "shatter": "碎裂", "shriek": "尖啸", "smithing_table": "锻造台",
        "sponge": "海绵", "spread": "传播", "tile": "方块",
        "tilt_down": "下倾", "tilt_up": "上倾", "vr": "VR",
        "close_door": "关门", "open_door": "开门", "open_trapdoor": "开活板门",
        "copper": "铜",
    }
    if parts[0] in SIMPLE_TOPS:
        base_cn = SIMPLE_TOPS[parts[0]]
        if len(parts) > 1:
            rest = "".join(_lookup_word(p) for p in parts[1:])
            return f"{base_cn} — {rest}" if rest else base_cn
        return base_cn

    # Generic open/close patterns (open.chest, close.chest, etc.)
    if parts[0] in ("open", "close", "click_on", "click_off"):
        action_cn = ACTION_MAP.get(parts[0], parts[0])
        if len(parts) >= 2:
            target_cn = BLOCK_MAP.get(parts[1], _lookup_word(parts[1]))
            return f"{target_cn} — {action_cn}"
        return action_cn

    # Jump/land/random at top level with material
    if parts[0] in ("jump", "land", "random"):
        action_cn = ACTION_MAP.get(parts[0], parts[0])
        if len(parts) >= 2:
            target = "_".join(parts[1:])
            target_cn = BLOCK_MAP.get(target, _lookup_word(target))
            return f"{target_cn} — {action_cn}"
        return action_cn

    # UI / HUD
    if parts[0] in ("hud", "ui"):
        UI_MAP = {
            "cartography_table.take_result": "制图台取出",
            "loom.select_pattern": "织布机选图案",
            "loom.take_result": "织布机取出",
            "stonecutter.take_result": "切石机取出",
            "drawer_close": "抽屉关闭", "drawer_open": "抽屉打开",
            "hardcore_disable": "关闭极限模式", "hardcore_enable": "启用极限模式",
            "hardcore_toggle_press": "极限模式切换", "reject": "拒绝",
            "bubble.pop": "气泡弹出",
        }
        rest_key = ".".join(parts[1:])
        cn = UI_MAP.get(rest_key)
        if cn:
            return f"界面 — {cn}"
        rest = "".join(_lookup_word(p) for p in parts[1:])
        return f"界面 — {rest}" if rest else "界面"

    # Fallback: use the category + name for a basic translation
    cat_cn = CATEGORY_CN.get(cat, cat)
    # Build from parts
    part_translations = []
    for p in parts:
        if p in MOB_MAP:
            part_translations.append(MOB_MAP[p])
        elif p in BLOCK_MAP:
            part_translations.append(BLOCK_MAP[p])
        elif p in ACTION_MAP:
            part_translations.append(ACTION_MAP[p])
        elif p in BIOME_MAP:
            part_translations.append(BIOME_MAP[p])
        elif p in ITEM_MAP:
            part_translations.append(ITEM_MAP[p])
    if part_translations:
        return " — ".join(part_translations)

    # Last resort: category + name
    if cat_cn:
        name = entry.get("name", "")
        return f"{cat_cn} — {name}" if name else cat_cn
    return ""


ANIM_ENTITY_MAP = {
    **MOB_MAP,
    "player": "玩家", "humanoid": "人形", "boat": "船", "minecart": "矿车",
    "fishing_hook": "鱼钩", "fireworks_rocket": "烟花火箭",
    "trident": "三叉戟", "arrow": "箭", "crossbow": "弩",
    "lead_knot": "拴绳结", "item": "物品", "xp_orb": "经验球",
    "egg": "鸡蛋", "ender_pearl": "末影珍珠", "snowball": "雪球",
    "shulker_bullet": "潜影弹", "fireball": "火球", "dragon_fireball": "龙息火球",
    "wither_skull": "凋灵之首", "thrown_trident": "投掷三叉戟",
    "camera": "相机", "map": "地图", "shield": "盾牌", "banner": "旗帜",
    "bell": "钟", "conduit": "导管", "ender_chest": "末影箱",
    "chest_minecart": "运输矿车", "command_block_minecart": "命令方块矿车",
    "hopper_minecart": "漏斗矿车", "tnt_minecart": "TNT矿车",
    "piston": "活塞", "default": "默认",
    "actor": "角色", "armor": "盔甲", "bow": "弓",
    "elytra": "鞘翅", "spear": "长矛", "spyglass": "望远镜",
    "wind_charge": "风弹", "wither_boss": "凋灵Boss",
    "look_at_target": "注视目标", "quadruped": "四足动物",
    "horse_v1": "马v1", "horse_v2": "马v2", "horse_v3": "马v3",
    "player_firstperson": "玩家第一人称", "npc": "NPC",
}


def translate_animation(entry: dict) -> str:
    aid = entry["id"]
    # Strip "animation." prefix
    rest = aid.removeprefix("animation.")

    # Strip version/anim suffixes like .animation.v1.0, .animations.v1.0, .anim, .v1, .v2
    import re as _re
    rest = _re.sub(r'\.animations?\.v\d+\.\d+$', '', rest)
    rest = _re.sub(r'\.animations?$', '', rest)
    rest = _re.sub(r'\.anim$', '', rest)
    rest = _re.sub(r'\.v\d+$', '', rest)

    parts = rest.split(".")

    if not parts:
        return ""

    # Check if entire rest is a dressing_room pattern
    if parts[0].startswith("dressing_room"):
        # Parse: dressing_room_idle_arm_1, dressing_room_react_bored_head_1
        dr_rest = parts[0].removeprefix("dressing_room_")
        BODY_PARTS = {"arm": "手臂", "back": "背部", "bottom": "下身", "torso": "躯干", "head": "头部"}
        DR_ACTIONS = {"idle": "待机", "react": "反应", "react_bored": "无聊反应",
                      "react_confirm": "确认反应", "react_offer": "提供反应", "react_idle": "反应待机"}
        # Try to match action + body part + number
        dr_parts = dr_rest.split("_")
        action_cn = ""
        body_cn = ""
        num = ""
        for i, p in enumerate(dr_parts):
            if p.isdigit():
                num = p
            elif p in BODY_PARTS:
                body_cn = BODY_PARTS[p]
            elif not action_cn:
                # Try compound action
                test_key = "_".join(dr_parts[:i+1])
                if test_key in DR_ACTIONS:
                    action_cn = DR_ACTIONS[test_key]
        if not action_cn:
            action_cn = DR_ACTIONS.get(dr_parts[0], dr_parts[0]) if dr_parts else "待机"
        desc = f"试衣间 — {action_cn}"
        if body_cn:
            desc += f"({body_cn})"
        if num:
            desc += num
        return desc

    # First part is usually entity
    entity_key = parts[0]
    entity_cn = ANIM_ENTITY_MAP.get(entity_key, MOB_MAP.get(entity_key, _lookup_word(entity_key)))

    if len(parts) == 1:
        return f"{entity_cn} 动画"

    # Remaining parts describe the animation
    action_parts = parts[1:]
    action_str = "_".join(action_parts)

    ANIM_ACTION_MAP = {
        "move": "移动", "walk": "行走", "idle": "待机", "attack": "攻击",
        "death": "死亡", "hurt": "受伤", "swim": "游泳", "jump": "跳跃",
        "fly": "飞行", "look_at_target": "注视目标", "eat": "进食",
        "sleep": "睡觉", "sit": "坐下", "stand": "站立", "run": "奔跑",
        "sprint": "冲刺", "sneak": "潜行", "ride": "骑乘", "baby": "幼年",
        "spawn": "生成", "despawn": "消失", "breathe": "呼吸",
        "charge": "蓄力", "shoot": "射击", "cast": "施法", "roar": "吼叫",
        "dig": "挖掘", "emerge": "出现", "sniff": "嗅探", "search": "搜索",
        "celebrate": "庆祝", "dance": "跳舞", "explode": "爆炸",
        "open": "打开", "close": "关闭", "flap": "拍翅", "glide": "滑翔",
        "bob": "上下晃动", "hover": "悬浮", "swing": "挥动", "pull": "拉弓",
        "holding": "持有", "tooting": "吹号角", "admiring": "欣赏",
        "base_pose": "基础姿态", "brandish": "挥舞", "celebrate_hunting": "庆祝捕猎",
        "cross_arm": "交叉手臂", "riding": "骑行中", "rowing": "划船",
        "bob_v2": "上下晃动", "first_person": "第一人称",
        "breathing": "呼吸中", "rolling": "翻滚", "peeking": "窥视中",
        "curling_up": "蜷缩", "un_curling": "展开",
    }

    action_cn = ANIM_ACTION_MAP.get(action_str, "")
    if not action_cn:
        # Try individual words
        cn_parts = []
        for p in action_parts:
            cn_parts.append(ANIM_ACTION_MAP.get(p, ACTION_MAP.get(p, _lookup_word(p))))
        action_cn = "".join(cn_parts)

    return f"{entity_cn} — {action_cn}"


def main():
    # Process sounds
    sounds_path = BASE / "sounds.json"
    sounds = json.loads(sounds_path.read_text("utf-8"))
    for entry in sounds:
        desc = translate_sound(entry)
        entry["description"] = desc
    sounds_path.write_text(json.dumps(sounds, ensure_ascii=False, indent=2) + "\n", "utf-8")
    filled = sum(1 for s in sounds if s["description"])
    print(f"Sounds: {filled}/{len(sounds)} descriptions filled")

    # Process animations
    anims_path = BASE / "animations.json"
    anims = json.loads(anims_path.read_text("utf-8"))
    for entry in anims:
        desc = translate_animation(entry)
        entry["description"] = desc
    anims_path.write_text(json.dumps(anims, ensure_ascii=False, indent=2) + "\n", "utf-8")
    filled = sum(1 for a in anims if a["description"])
    print(f"Animations: {filled}/{len(anims)} descriptions filled")


if __name__ == "__main__":
    main()
