#!/usr/bin/env python3
"""Build SQLite FTS5 index from wiki article JSON files.

Scans knowledge_base/wiki/articles/*.json and creates/rebuilds
the FTS5 search database at knowledge_base/wiki/wiki.db.

Usage:
    python scripts/build_wiki_index.py
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

WIKI_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "wiki"
ARTICLES_DIR = WIKI_DIR / "articles"
DB_PATH = WIKI_DIR / "wiki.db"


def tokenize_chinese(text: str) -> str:
    """Generate bigram tokens for Chinese text."""
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    bigrams: list[str] = []
    for segment in cjk:
        for i in range(len(segment) - 1):
            bigrams.append(segment[i : i + 2])
    return " ".join(bigrams)


def main():
    if not ARTICLES_DIR.exists():
        print(f"ERROR: Articles directory not found: {ARTICLES_DIR}")
        print("Run crawl_wiki.py or crawl_forums.py first.")
        sys.exit(1)

    articles = list(ARTICLES_DIR.glob("*.json"))
    if not articles:
        print(f"ERROR: No JSON articles found in {ARTICLES_DIR}")
        sys.exit(1)

    print(f"Found {len(articles)} article files")

    # Remove old DB
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed old index: {DB_PATH}")

    db = sqlite3.connect(str(DB_PATH))
    db.executescript("""
        CREATE TABLE wiki_articles (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            source      TEXT NOT NULL DEFAULT '',
            url         TEXT NOT NULL DEFAULT '',
            category    TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '',
            summary     TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            platform    TEXT NOT NULL DEFAULT 'BE',
            last_crawled TEXT NOT NULL DEFAULT ''
        );

        CREATE VIRTUAL TABLE wiki_fts USING fts5(
            id,
            title,
            tags,
            summary,
            content,
            bigrams,
            content=wiki_articles,
            content_rowid=rowid,
            tokenize='unicode61'
        );
    """)

    stats: dict[str, int] = {}
    total_chars = 0
    errors = 0

    for path in sorted(articles):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  SKIP {path.name}: {e}")
            errors += 1
            continue

        aid = data.get("id", path.stem)
        title = data.get("title", "")
        tags = ", ".join(data.get("tags", []))
        summary = data.get("summary", "")
        content = data.get("content", "")
        category = data.get("category", "")

        # Flatten sections if needed
        if not content and "sections" in data:
            parts = []
            for sec in data["sections"]:
                heading = sec.get("heading", "")
                body = sec.get("content", "")
                if heading:
                    parts.append(f"{heading}: {body}")
                else:
                    parts.append(body)
            content = "\n".join(parts)

        if not content:
            print(f"  SKIP {path.name}: empty content")
            errors += 1
            continue

        bigrams = tokenize_chinese(f"{title} {tags} {summary} {content}")

        db.execute(
            """INSERT OR REPLACE INTO wiki_articles
               (id, title, source, url, category, tags, summary, content, platform, last_crawled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid, title, data.get("source", ""), data.get("url", ""),
                category, tags, summary, content,
                data.get("platform", "BE"), data.get("last_crawled", ""),
            ),
        )
        db.execute(
            """INSERT INTO wiki_fts (rowid, id, title, tags, summary, content, bigrams)
               SELECT rowid, id, title, tags, summary, content, ?
               FROM wiki_articles WHERE id = ?""",
            (bigrams, aid),
        )

        stats[category] = stats.get(category, 0) + 1
        total_chars += len(content)

    db.commit()

    # Verify
    count = db.execute("SELECT count(*) FROM wiki_articles").fetchone()[0]
    db.close()

    print(f"\n{'='*50}")
    print(f"Index built: {DB_PATH}")
    print(f"Total articles: {count}")
    print(f"Total content: {total_chars:,} chars")
    print(f"Errors/skipped: {errors}")
    print(f"\nBy category:")
    for cat, cnt in sorted(stats.items()):
        print(f"  {cat}: {cnt}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
