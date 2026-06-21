#!/usr/bin/env python3
"""Scrape Minecraft Wiki command pages for Bedrock Edition.

Fetches the main command listing page and each individual command page,
saving raw HTML to scripts/wiki_raw/ for later parsing.

Usage:
    python scripts/scrape_wiki.py
"""

import os
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

WIKI_BASE = "https://zh.minecraft.wiki"
COMMANDS_PAGE = f"{WIKI_BASE}/w/%E5%91%BD%E4%BB%A4"  # /w/命令
OUTPUT_DIR = Path(__file__).parent / "wiki_raw"
DELAY = 1.0  # seconds between requests


def fetch_page(url: str, client: httpx.Client) -> str:
    """Fetch a page and return its HTML content."""
    print(f"  Fetching: {url}")
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def get_command_links(html: str) -> list[tuple[str, str]]:
    """Extract command names and URLs from the main commands page."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    seen = set()

    # Look for command links in the main content area
    content = soup.find("div", {"id": "mw-content-text"}) or soup
    for a in content.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        # Match links like /w/命令/give or /w/命令/execute
        if "/w/%E5%91%BD%E4%BB%A4/" in href or "/w/命令/" in href:
            # Extract command name from the URL
            cmd_name = href.rsplit("/", 1)[-1]
            # Decode percent-encoded names
            from urllib.parse import unquote
            cmd_name_decoded = unquote(cmd_name)

            if cmd_name_decoded not in seen and cmd_name_decoded:
                seen.add(cmd_name_decoded)
                full_url = href if href.startswith("http") else f"{WIKI_BASE}{href}"
                links.append((cmd_name_decoded, full_url))

    return links


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MCBECommandCraft/1.0; +https://commandcraft.cn)",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    with httpx.Client(headers=headers, timeout=30.0) as client:
        # Step 1: Fetch main commands page
        print("Fetching main commands page...")
        main_html = fetch_page(COMMANDS_PAGE, client)
        main_path = OUTPUT_DIR / "_commands_index.html"
        main_path.write_text(main_html, encoding="utf-8")
        print(f"  Saved to {main_path}")

        # Step 2: Extract command links
        command_links = get_command_links(main_html)
        print(f"\nFound {len(command_links)} command pages")

        # Step 3: Fetch each command page
        for i, (name, url) in enumerate(command_links):
            safe_name = name.replace("/", "_").replace("\\", "_")
            out_path = OUTPUT_DIR / f"{safe_name}.html"

            if out_path.exists():
                print(f"  [{i+1}/{len(command_links)}] Skipping {name} (already exists)")
                continue

            print(f"  [{i+1}/{len(command_links)}] Fetching {name}...")
            try:
                html = fetch_page(url, client)
                out_path.write_text(html, encoding="utf-8")
                time.sleep(DELAY)
            except Exception as e:
                print(f"    ERROR: {e}")

    print(f"\nDone! Raw HTML saved to {OUTPUT_DIR}/")
    print("Next step: parse these files to generate structured JSON for knowledge_base/")


if __name__ == "__main__":
    main()
