#!/usr/bin/env python3
"""Crawl Chinese MCBE community forums for advanced command examples.

Sources:
  - klpbbs.com (苦力怕论坛) — 命令教程板块
  - Bilibili 专栏 — 基岩版命令方块相关文章

Extracts tutorials with command blocks, PvP systems, mini-games, etc.
Saves as JSON articles to knowledge_base/wiki/articles/ with category="examples".

Usage:
    python scripts/crawl_forums.py                    # Full crawl
    python scripts/crawl_forums.py --update           # Incremental
    python scripts/crawl_forums.py --source klpbbs    # Only 苦力怕论坛
    python scripts/crawl_forums.py --source bilibili  # Only Bilibili
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
DELAY = 2.0  # Be respectful to community sites

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# Minimum quality thresholds
MIN_CONTENT_LENGTH = 300  # chars
MIN_COMMAND_COUNT = 2     # must contain at least 2 commands


# =====================================================================
# Content quality filters
# =====================================================================

def count_commands(text: str) -> int:
    """Count Minecraft command occurrences in text."""
    # Match /command patterns
    return len(re.findall(r"/(?:execute|give|summon|tp|scoreboard|tag|setblock|fill|clone|effect|enchant|tellraw|titleraw|playsound|particle|replaceitem|structure|dialogue|camera|inputpermission|hud)\b", text))


def has_bedrock_indicators(text: str) -> bool:
    """Check if text is about Bedrock Edition."""
    be_keywords = ["基岩版", "基岩", "Bedrock", "MCBE", "BE版", "手机版", "手游",
                   "命令方块", "行为包", "附加包", "addon"]
    je_only = ["仅Java", "Java版独有", "模组", "Forge", "Fabric"]

    be_score = sum(1 for kw in be_keywords if kw in text)
    je_score = sum(1 for kw in je_only if kw in text)

    # Accept if has BE indicators or no JE-only indicators
    return be_score > 0 or je_score == 0


# =====================================================================
# 苦力怕论坛 (klpbbs.com)
# =====================================================================

# Pre-defined tutorial URLs from the command section
# These are manually curated starting points — the crawler can be extended
# with a list discovery step later.
KLPBBS_TUTORIALS: list[dict] = [
    # Format: {"id": "forum_xxx", "url": "...", "tags": [...]}
    # Users should populate this list by browsing klpbbs.com/forum-command
    # and adding URLs of high-quality MCBE command tutorials.
    #
    # Example entry:
    # {"id": "forum_pvp_system", "url": "https://klpbbs.com/thread-xxxxx-1-1.html",
    #  "tags": ["PVP", "攻防", "计分板"]},
]


def crawl_klpbbs(client: httpx.Client, incremental: bool = False) -> int:
    """Crawl tutorials from klpbbs.com."""
    if not KLPBBS_TUTORIALS:
        print("  No klpbbs URLs configured. Add URLs to KLPBBS_TUTORIALS in this script.")
        print("  Browse https://klpbbs.com/ for MCBE command tutorials and add their URLs.")
        return 0

    saved = 0
    for i, entry in enumerate(KLPBBS_TUTORIALS):
        out_path = OUTPUT_DIR / f"{entry['id']}.json"
        if incremental and out_path.exists():
            print(f"  [{i+1}/{len(KLPBBS_TUTORIALS)}] Skipping {entry['id']} (exists)")
            continue

        print(f"  [{i+1}/{len(KLPBBS_TUTORIALS)}] Fetching {entry['id']}...")
        try:
            resp = client.get(entry["url"], follow_redirects=True)
            if resp.status_code != 200:
                print(f"    ERROR: HTTP {resp.status_code}")
                continue

            article = _extract_klpbbs_article(resp.text, entry)
            if not article or not article.get("content"):
                print(f"    WARNING: No content extracted")
                continue

            # Quality check
            cmd_count = count_commands(article["content"])
            if cmd_count < MIN_COMMAND_COUNT:
                print(f"    SKIP: Only {cmd_count} commands found (min: {MIN_COMMAND_COUNT})")
                continue
            if len(article["content"]) < MIN_CONTENT_LENGTH:
                print(f"    SKIP: Content too short ({len(article['content'])} chars)")
                continue
            if not has_bedrock_indicators(article["content"]):
                print(f"    SKIP: No Bedrock Edition indicators")
                continue

            out_path.write_text(
                json.dumps(article, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            saved += 1
            print(f"    OK: {len(article['content'])} chars, {cmd_count} commands")

        except Exception as e:
            print(f"    ERROR: {e}")
        time.sleep(DELAY)

    return saved


def _extract_klpbbs_article(html: str, entry: dict) -> dict | None:
    """Extract article content from a klpbbs.com thread page."""
    soup = BeautifulSoup(html, "html.parser")

    # Thread title
    title_el = soup.find("span", {"id": "thread_subject"})
    title = title_el.get_text(strip=True) if title_el else ""

    # First post content (thread body)
    post_div = soup.find("div", class_="t_f") or soup.find("td", class_="t_f")
    if not post_div:
        return None

    # Remove images, scripts
    for tag in post_div.find_all(["script", "style", "img"]):
        tag.decompose()

    content = post_div.get_text(separator="\n", strip=True)
    # Clean up excessive whitespace
    content = re.sub(r"\n{3,}", "\n\n", content)

    summary = content[:200] + "..." if len(content) > 200 else content

    return {
        "id": entry["id"],
        "title": title,
        "source": "klpbbs.com",
        "url": entry["url"],
        "category": "examples",
        "tags": entry.get("tags", []),
        "summary": summary,
        "content": content,
        "platform": "BE",
        "last_crawled": str(date.today()),
    }


# =====================================================================
# Bilibili 专栏
# =====================================================================

BILI_SEARCH_KEYWORDS = [
    "基岩版 命令方块 教程",
    "MCBE 命令 攻防",
    "基岩版 小游戏 命令",
    "基岩版 RPG 命令方块",
    "基岩版 跑酷 命令",
    "基岩版 计分板 系统",
]


def crawl_bilibili(client: httpx.Client, incremental: bool = False) -> int:
    """Crawl Bilibili articles about MCBE commands.

    Uses Bilibili search API to find relevant articles, then fetches content.
    """
    saved = 0
    seen_ids: set[str] = set()

    # Check existing articles to avoid duplicates
    if incremental:
        for p in OUTPUT_DIR.glob("bili_article_*.json"):
            seen_ids.add(p.stem)

    for keyword in BILI_SEARCH_KEYWORDS:
        print(f"  Searching Bilibili for: {keyword}")
        try:
            articles = _bili_search_articles(client, keyword)
            print(f"    Found {len(articles)} articles")

            for art in articles:
                article_id = f"bili_article_{art['id']}"
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)

                out_path = OUTPUT_DIR / f"{article_id}.json"
                if incremental and out_path.exists():
                    continue

                print(f"    Fetching article: {art['title'][:30]}...")
                try:
                    article = _fetch_bili_article(client, art)
                    if not article or not article.get("content"):
                        continue

                    cmd_count = count_commands(article["content"])
                    if cmd_count < MIN_COMMAND_COUNT:
                        print(f"      SKIP: Only {cmd_count} commands")
                        continue
                    if not has_bedrock_indicators(article["content"]):
                        print(f"      SKIP: Not Bedrock content")
                        continue

                    out_path.write_text(
                        json.dumps(article, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    saved += 1
                    print(f"      OK: {len(article['content'])} chars")

                except Exception as e:
                    print(f"      ERROR: {e}")
                time.sleep(DELAY)

        except Exception as e:
            print(f"    Search ERROR: {e}")
        time.sleep(DELAY)

    return saved


def _bili_search_articles(client: httpx.Client, keyword: str) -> list[dict]:
    """Search Bilibili for articles matching keyword."""
    # Bilibili search API for articles (type=4 = 专栏)
    url = "https://api.bilibili.com/x/web-interface/search/type"
    params = {
        "search_type": "article",
        "keyword": keyword,
        "page": 1,
        "page_size": 10,
        "order": "totalrank",  # by relevance
    }

    try:
        resp = client.get(url, params=params)
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        return [
            {
                "id": str(r.get("id", "")),
                "title": re.sub(r"<[^>]+>", "", r.get("title", "")),  # strip HTML
                "url": f"https://www.bilibili.com/read/cv{r.get('id', '')}",
            }
            for r in results
            if r.get("id")
        ]
    except Exception:
        return []


def _fetch_bili_article(client: httpx.Client, art: dict) -> dict | None:
    """Fetch full Bilibili article content."""
    # Bilibili article API
    url = f"https://api.bilibili.com/x/article/view"
    params = {"id": art["id"]}

    try:
        resp = client.get(url, params=params)
        if resp.status_code != 200:
            return None

        data = resp.json().get("data", {})
        content_html = data.get("content", "")
        if not content_html:
            return None

        # HTML to text
        soup = BeautifulSoup(content_html, "html.parser")
        content = soup.get_text(separator="\n", strip=True)
        content = re.sub(r"\n{3,}", "\n\n", content)

        title = data.get("title", art.get("title", ""))
        summary = content[:200] + "..." if len(content) > 200 else content

        # Extract tags from content
        tags = ["基岩版", "命令方块"]
        if "计分板" in content or "scoreboard" in content.lower():
            tags.append("计分板")
        if "PVP" in content.upper() or "攻防" in content:
            tags.append("PVP")
        if "RPG" in content.upper():
            tags.append("RPG")
        if "跑酷" in content:
            tags.append("跑酷")
        if "小游戏" in content:
            tags.append("小游戏")

        return {
            "id": f"bili_article_{art['id']}",
            "title": title,
            "source": "bilibili.com",
            "url": art["url"],
            "category": "examples",
            "tags": tags,
            "summary": summary,
            "content": content,
            "platform": "BE",
            "last_crawled": str(date.today()),
        }
    except Exception:
        return None


# =====================================================================
# Main
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Crawl MCBE community forums for command examples")
    parser.add_argument("--update", action="store_true", help="Incremental update")
    parser.add_argument("--source", choices=["klpbbs", "bilibili", "all"], default="all")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        total = 0

        if args.source in ("klpbbs", "all"):
            print(f"\n{'='*60}")
            print("Crawling klpbbs.com (苦力怕论坛)")
            print(f"{'='*60}")
            count = crawl_klpbbs(client, incremental=args.update)
            total += count
            print(f"  → Saved {count} articles")

        if args.source in ("bilibili", "all"):
            print(f"\n{'='*60}")
            print("Crawling Bilibili 专栏")
            print(f"{'='*60}")
            count = crawl_bilibili(client, incremental=args.update)
            total += count
            print(f"  → Saved {count} articles")

        print(f"\nDone! Total: {total} example articles saved to {OUTPUT_DIR}/")
        print("Next step: python scripts/build_wiki_index.py")


if __name__ == "__main__":
    main()
