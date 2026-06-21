#!/usr/bin/env python3
"""Crawl Minecraft Wiki via MediaWiki API for Bedrock Edition content.

Uses zh.minecraft.wiki API (bypasses Cloudflare) to fetch parsed HTML,
then extracts structured text content.

Usage:
    python scripts/crawl_wiki.py              # Full crawl
    python scripts/crawl_wiki.py --update     # Incremental (skip existing)
    python scripts/crawl_wiki.py --list       # Show configured pages
"""

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "wiki" / "articles"
DELAY = 1.0  # seconds between API requests

API_URL = "https://zh.minecraft.wiki/api.php"
WIKI_BASE = "https://zh.minecraft.wiki"

HEADERS = {
    "User-Agent": "MCBECommandCraft/1.0 (https://commandcraft.cn; bot) python-httpx",
    "Accept": "application/json",
}

# =====================================================================
# Pages to crawl — organized by category
# =====================================================================

PAGES: list[dict] = [
    # ── 命令进阶（补充 knowledge_base/commands/ 中没有的深度内容）────
    # execute 和选择器是最核心的进阶内容，Wiki 上有大量子命令细节
    {"id": "commands_execute",         "page": "命令/execute",        "category": "commands", "tags": ["execute", "子命令", "条件执行", "as", "at", "positioned", "if", "unless", "run"]},
    {"id": "commands_target_selector", "page": "目标选择器",          "category": "commands", "tags": ["选择器", "@a", "@e", "@s", "@p", "@r", "hasitem", "type", "tag", "scores"]},
    # 命令方块机制 — 连锁/条件/红石信号控制，现有命令文档不涉及
    {"id": "commands_command_block",   "page": "命令方块",            "category": "commands", "tags": ["命令方块", "脉冲", "连锁", "循环", "条件", "红石"]},
    # 函数系统 — 行为包函数调用，现有文档缺失
    {"id": "commands_function",        "page": "基岩版函数",          "category": "commands", "tags": ["函数", "mcfunction", "行为包", "function"]},
    # rawtext JSON 格式 — 复杂格式详解，现有文档仅有基本语法
    {"id": "commands_rawtext",         "page": "原始JSON文本格式",    "category": "commands", "tags": ["rawtext", "tellraw", "titleraw", "JSON文本", "translate", "score", "selector"]},
    # 记分板系统概念 — 准则、显示位置、队伍等系统性知识
    {"id": "commands_scoreboard",      "page": "记分板",              "category": "commands", "tags": ["记分板", "计分板", "scoreboard", "objective", "dummy", "准则"]},
    # 教程页面 — 这些是Wiki上独立的实战教程，高价值内容
    {"id": "tutorial_command_blocks",  "page": "教程:命令方块",       "category": "commands", "tags": ["教程", "命令方块", "入门", "连锁", "实战"]},
    {"id": "tutorial_scoreboard",      "page": "教程:记分板",         "category": "commands", "tags": ["教程", "记分板", "计时器", "货币", "实战"]},
    {"id": "tutorial_selector",        "page": "教程:目标选择器",     "category": "commands", "tags": ["教程", "选择器", "进阶", "hasitem"]},
    # camera/dialogue/hud 等基岩版独有命令 — 现有命令文档较薄
    {"id": "commands_camera",          "page": "命令/camera",         "category": "commands", "tags": ["camera", "相机", "视角", "镜头"]},
    {"id": "commands_dialogue",        "page": "命令/dialogue",       "category": "commands", "tags": ["dialogue", "对话", "NPC"]},
    {"id": "commands_hud",             "page": "命令/hud",            "category": "commands", "tags": ["hud", "界面", "隐藏"]},
    {"id": "commands_inputpermission", "page": "命令/inputpermission", "category": "commands", "tags": ["inputpermission", "输入权限", "控制"]},
    {"id": "commands_tickingarea",     "page": "命令/tickingarea",    "category": "commands", "tags": ["tickingarea", "常加载区域", "tick"]},
    {"id": "commands_loot",            "page": "命令/loot",           "category": "commands", "tags": ["loot", "战利品", "掉落"]},

    # ── 游戏机制（AI 需要理解机制才能设计命令系统）──────────────
    {"id": "mechanics_redstone",            "page": "红石电路",         "category": "mechanics", "tags": ["红石", "电路", "信号", "红石粉", "充能"]},
    {"id": "mechanics_redstone_repeater",   "page": "红石中继器",       "category": "mechanics", "tags": ["中继器", "红石", "延迟", "锁存"]},
    {"id": "mechanics_redstone_comparator", "page": "红石比较器",       "category": "mechanics", "tags": ["比较器", "红石", "检测", "减法"]},
    {"id": "mechanics_piston",              "page": "活塞",             "category": "mechanics", "tags": ["活塞", "推拉", "红石", "粘性活塞"]},
    {"id": "mechanics_hopper",              "page": "漏斗",             "category": "mechanics", "tags": ["漏斗", "物品传输", "红石"]},
    {"id": "mechanics_observer",            "page": "侦测器",           "category": "mechanics", "tags": ["侦测器", "红石", "方块更新"]},
    {"id": "mechanics_spawning",            "page": "生成",             "category": "mechanics", "tags": ["生成", "刷怪", "自然生成", "生成规则"]},
    {"id": "mechanics_damage",              "page": "伤害",             "category": "mechanics", "tags": ["伤害", "攻击", "防御", "盔甲"]},
    {"id": "mechanics_enchanting",          "page": "魔咒",             "category": "mechanics", "tags": ["附魔", "魔咒", "经验", "附魔台"]},
    {"id": "mechanics_trading",             "page": "交易",             "category": "mechanics", "tags": ["交易", "村民", "绿宝石", "职业"]},
    {"id": "mechanics_block_states",        "page": "方块状态",         "category": "mechanics", "tags": ["方块状态", "方块属性", "数据值"]},
    {"id": "mechanics_loot_table",          "page": "战利品表",         "category": "mechanics", "tags": ["战利品表", "掉落", "loot_table"]},
    {"id": "mechanics_tick",                "page": "刻",               "category": "mechanics", "tags": ["游戏刻", "红石刻", "tick"]},
    {"id": "mechanics_nbt",                 "page": "NBT格式",          "category": "mechanics", "tags": ["NBT", "数据标签"]},
    {"id": "mechanics_difficulty",          "page": "难度",             "category": "mechanics", "tags": ["难度", "区域难度", "简单", "困难"]},
    {"id": "mechanics_mob_spawner",         "page": "刷怪笼",           "category": "mechanics", "tags": ["刷怪笼", "刷怪", "生成"]},

    # ── 生物行为（理解生物行为才能设计涉及实体的命令系统）──────
    {"id": "entity_zombie",       "page": "僵尸",    "category": "mechanics", "tags": ["僵尸", "怪物", "亡灵", "增援", "溺尸"]},
    {"id": "entity_skeleton",     "page": "骷髅",    "category": "mechanics", "tags": ["骷髅", "弓箭", "亡灵"]},
    {"id": "entity_creeper",      "page": "苦力怕",  "category": "mechanics", "tags": ["苦力怕", "爆炸"]},
    {"id": "entity_villager",     "page": "村民",    "category": "mechanics", "tags": ["村民", "交易", "职业", "铁傀儡"]},
    {"id": "entity_iron_golem",   "page": "铁傀儡",  "category": "mechanics", "tags": ["铁傀儡", "守卫", "村庄"]},
    {"id": "entity_armor_stand",  "page": "盔甲架",  "category": "mechanics", "tags": ["盔甲架", "展示", "装饰", "命令"]},
    {"id": "entity_enderman",     "page": "末影人",  "category": "mechanics", "tags": ["末影人", "传送"]},
    {"id": "entity_warden",       "page": "监守者",  "category": "mechanics", "tags": ["监守者", "深暗之域", "振动"]},
    {"id": "entity_wither",       "page": "凋灵",    "category": "mechanics", "tags": ["凋灵", "Boss"]},
    {"id": "entity_ender_dragon", "page": "末影龙",  "category": "mechanics", "tags": ["末影龙", "Boss", "末地"]},
]


# =====================================================================
# MediaWiki API fetch + HTML extraction
# =====================================================================

def fetch_page_via_api(
    client: httpx.Client,
    page_name: str,
) -> tuple[str, str, list[dict]]:
    """Fetch a page via MediaWiki API.

    Returns (title, html_content, sections_meta).
    """
    resp = client.get(API_URL, params={
        "action": "parse",
        "page": page_name,
        "prop": "text|sections|displaytitle",
        "redirects": "1",
        "format": "json",
        "disableeditsection": "1",
    })
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise ValueError(data["error"].get("info", "Unknown API error"))

    parse = data["parse"]
    title = parse.get("title", page_name)
    html = parse.get("text", {}).get("*", "")
    sections = parse.get("sections", [])
    return title, html, sections


def extract_text_from_html(html: str) -> list[dict]:
    """Extract structured sections from MediaWiki parsed HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove unwanted elements
    for selector in [
        "script", "style", "nav",
        ".navbox", ".mw-editsection", ".hatnote", ".noprint",
        ".toc", ".mw-empty-elt", ".gallery", ".mw-references-wrap",
        ".notablock",
    ]:
        for el in soup.select(selector):
            el.decompose()

    # Remove ALL tables — they're mostly infoboxes / data tables with noise
    for table in soup.find_all("table"):
        table.decompose()

    sections: list[dict] = []
    current_heading = "概述"
    current_parts: list[str] = []

    def _flush():
        nonlocal current_heading
        text = "\n".join(current_parts).strip()
        if text:
            sections.append({"heading": current_heading, "content": text})
        current_parts.clear()

    def _walk(el):
        nonlocal current_heading
        if not isinstance(el, Tag):
            return

        if el.name in ("h2", "h3"):
            _flush()
            current_heading = el.get_text(strip=True)
            return

        if el.name in ("p", "dl", "blockquote"):
            text = el.get_text(separator=" ", strip=True)
            if text and len(text) > 10:
                current_parts.append(text)
        elif el.name in ("ul", "ol"):
            items = []
            for li in el.find_all("li", recursive=False):
                li_text = li.get_text(separator=" ", strip=True)
                if li_text and len(li_text) > 5:
                    items.append(f"• {li_text}")
            if items:
                current_parts.append("\n".join(items))
        elif el.name == "pre":
            text = el.get_text(strip=True)
            if text:
                current_parts.append(f"```\n{text}\n```")
        elif el.name == "div":
            for child in el.children:
                _walk(child)

    for child in soup.children:
        _walk(child)

    _flush()
    return sections


# =====================================================================
# Post-processing: BE filtering + noise removal
# =====================================================================

# Regex patterns for inline JE-only content removal
_JE_ONLY_SENTENCE = re.compile(
    r"[^。\n]*\[仅\s*Java版?\s*\][^。\n]*[。\n]?",
)
# Noise patterns: bare stat numbers like "20 （ × 10）", version tags
_NOISE_STAT = re.compile(r"\d+\s*（\s*×\s*\d+\.?\d*\s*）")
_NOISE_VERSION_TAG = re.compile(r"\[\s*(?:失效|新增)\s*：[^\]]*\]")
_NOISE_MULTI_SPACE = re.compile(r"  +")


_NOISE_STAT_LINE = re.compile(
    r"^[^。\n]*(?:简单|普通|困难|近战|远程|生命值|护甲|伤害|掉落|速度|高度|宽度)\s*[:：].*$",
    re.MULTILINE,
)
_NOISE_BARE_LABEL = re.compile(r"^(?:幼年|成年|Java版|基岩版)\s*$", re.MULTILINE)
_NOISE_BRACKET_REF = re.compile(r"\[\s*\d+\s*\]")


def _clean_text(text: str) -> str:
    """Remove JE-only sentences and noise from extracted text."""
    # Remove sentences that are JE-only
    text = _JE_ONLY_SENTENCE.sub("", text)
    # Remove broken stat numbers like "20 （ × 10）"
    text = _NOISE_STAT.sub("", text)
    # Remove version lifecycle tags like "[失效：JE 26.1]"
    text = _NOISE_VERSION_TAG.sub("", text)
    # Remove stat lines (damage/health/speed values)
    text = _NOISE_STAT_LINE.sub("", text)
    # Remove bare labels (lone "幼年", "成年" etc.)
    text = _NOISE_BARE_LABEL.sub("", text)
    # Remove wiki reference markers [1] [2] etc.
    text = _NOISE_BRACKET_REF.sub("", text)
    # Clean up whitespace
    text = _NOISE_MULTI_SPACE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def filter_bedrock_content(sections: list[dict]) -> list[dict]:
    """Filter and clean sections for BE-relevant content."""
    # Headings to skip entirely
    skip_headings = {
        "历史", "画廊", "参考", "导航", "音效", "视频", "成就", "进度",
        "你知道吗", "ID", "实体数据", "方块数据", "物品数据", "数据值",
    }
    je_only_headings = {"仅Java版", "Java版", "Java版独有"}

    filtered = []
    for s in sections:
        heading = s["heading"]

        # Skip JE-only and non-useful sections
        if any(kw in heading for kw in je_only_headings):
            continue
        if heading in skip_headings:
            continue

        # Clean content: remove JE-only inline text + noise
        cleaned = _clean_text(s["content"])

        # Skip sections that became empty or too short after cleaning
        if len(cleaned) < 20:
            continue

        filtered.append({"heading": heading, "content": cleaned})

    return filtered


def _extract_summary(sections: list[dict], title: str) -> str:
    """Build a meaningful summary from the first substantive section.

    Skips sections that are just stats/numbers and finds actual description text.
    """
    for s in sections:
        content = s["content"]
        for para in content.split("\n"):
            para = para.strip()
            if len(para) < 30:
                continue
            if para.startswith("•"):
                continue
            # Skip lines that are just numbers/stats
            if re.match(r"^[\d（(×\s\.\-]+", para):
                continue
            # Skip "见 教程:xxx" lines
            if re.match(r"^见\s", para):
                continue
            # Skip "请帮助我们检查" wiki notices
            if "请帮助我们检查" in para:
                continue
            # Skip lines that mention only Java without Bedrock
            if "Java版" in para and "基岩" not in para and "Bedrock" not in para:
                continue
            return para[:300] + "..." if len(para) > 300 else para
    # Fallback
    return f"{title} — Minecraft基岩版百科内容。"


def build_article(page_info: dict, title: str, sections: list[dict]) -> dict:
    """Build a standard article dict from extracted sections."""
    full_content = "\n\n".join(
        f"## {s['heading']}\n{s['content']}" for s in sections
    )
    summary = _extract_summary(sections, title)

    return {
        "id": page_info["id"],
        "title": title,
        "source": "zh.minecraft.wiki",
        "url": f"{WIKI_BASE}/w/{page_info['page']}",
        "category": page_info["category"],
        "tags": page_info["tags"],
        "summary": summary,
        "content": full_content,
        "platform": "BE",
        "last_crawled": str(date.today()),
    }


# =====================================================================
# Main crawl logic
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Crawl Minecraft Wiki for MCBE content")
    parser.add_argument("--update", action="store_true", help="Incremental update (skip existing)")
    parser.add_argument("--list", action="store_true", help="List configured pages and exit")
    args = parser.parse_args()

    if args.list:
        print(f"Configured pages: {len(PAGES)}")
        for p in PAGES:
            print(f"  [{p['category']}] {p['id']}: {p['page']}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    saved = 0
    errors = 0

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        print(f"Crawling {len(PAGES)} pages via zh.minecraft.wiki API")
        print(f"Output: {OUTPUT_DIR}\n")

        for i, page in enumerate(PAGES):
            out_path = OUTPUT_DIR / f"{page['id']}.json"
            if args.update and out_path.exists():
                print(f"  [{i+1}/{len(PAGES)}] Skipping {page['id']} (exists)")
                continue

            print(f"  [{i+1}/{len(PAGES)}] {page['id']} ({page['page']})...", end=" ", flush=True)

            try:
                title, html, _ = fetch_page_via_api(client, page["page"])
                raw_sections = extract_text_from_html(html)
                sections = filter_bedrock_content(raw_sections)

                if not sections:
                    print(f"WARNING: no content extracted")
                    errors += 1
                    continue

                article = build_article(page, title, sections)
                content_len = len(article["content"])

                if content_len < 50:
                    print(f"WARNING: content too short ({content_len} chars)")
                    errors += 1
                    continue

                out_path.write_text(
                    json.dumps(article, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                saved += 1
                print(f"OK ({content_len:,} chars, {len(sections)} sections)")

            except Exception as e:
                print(f"ERROR: {e}")
                errors += 1

            time.sleep(DELAY)

    print(f"\n{'='*50}")
    print(f"Done! Saved: {saved}, Errors: {errors}, Total: {len(PAGES)}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Next step: python scripts/build_wiki_index.py")


if __name__ == "__main__":
    main()
