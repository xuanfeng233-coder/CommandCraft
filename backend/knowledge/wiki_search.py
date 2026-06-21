"""Wiki knowledge base search — SQLite FTS5 backed full-text search.

Scans knowledge_base/wiki/articles/*.json, builds an FTS5 index in wiki.db,
and provides keyword search for game mechanics, advanced commands, and examples.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from backend.config import WIKI_ARTICLES_DIR, WIKI_DB_PATH, WIKI_SEARCH_MAX_RESULTS

logger = logging.getLogger(__name__)


def _tokenize_chinese(text: str) -> str:
    """Generate bigram tokens for Chinese text to improve FTS5 matching.

    FTS5 unicode61 tokenizer splits on word boundaries which doesn't work
    well for Chinese. We augment with character bigrams so that queries
    like "红石" match content containing "红石中继器".
    """
    # Extract CJK characters
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    bigrams: list[str] = []
    for segment in cjk:
        for i in range(len(segment) - 1):
            bigrams.append(segment[i : i + 2])
    return " ".join(bigrams)


class WikiSearcher:
    """FTS5-based local wiki knowledge search.

    Singleton — use ``wiki_searcher`` instance at module level.
    """

    def __init__(self) -> None:
        self._db: sqlite3.Connection | None = None
        self._initialized = False
        self._article_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Build or open the FTS index. Safe to call multiple times."""
        if self._initialized:
            return

        if not WIKI_ARTICLES_DIR.exists():
            logger.info("Wiki articles dir not found: %s — search disabled", WIKI_ARTICLES_DIR)
            return

        articles = list(WIKI_ARTICLES_DIR.glob("*.json"))
        if not articles:
            logger.info("No wiki articles found — search disabled")
            return

        self._open_db()
        self._ensure_schema()

        # Check if rebuild needed (compare article count & mtime)
        db_count = self._row_count()
        latest_mtime = max(a.stat().st_mtime for a in articles)
        db_mtime = WIKI_DB_PATH.stat().st_mtime if WIKI_DB_PATH.exists() else 0

        if db_count != len(articles) or latest_mtime > db_mtime:
            logger.info("Rebuilding wiki FTS index (%d articles)...", len(articles))
            self._rebuild_index(articles)
        else:
            logger.info("Wiki FTS index up to date (%d articles)", db_count)

        self._initialized = True

    def _open_db(self) -> None:
        WIKI_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(WIKI_DB_PATH))
        self._db.row_factory = sqlite3.Row

    def _ensure_schema(self) -> None:
        assert self._db is not None
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS wiki_articles (
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

            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
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
        self._db.commit()

    def _row_count(self) -> int:
        assert self._db is not None
        try:
            row = self._db.execute("SELECT count(*) FROM wiki_articles").fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _rebuild_index(self, articles: list[Path]) -> None:
        assert self._db is not None
        cur = self._db.cursor()
        cur.execute("DELETE FROM wiki_articles")
        cur.execute("DELETE FROM wiki_fts")

        for path in articles:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Skipping %s: %s", path.name, e)
                continue

            aid = data.get("id", path.stem)
            title = data.get("title", "")
            tags = ", ".join(data.get("tags", []))
            summary = data.get("summary", "")
            content = data.get("content", "")
            # If content is in sections format, flatten
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

            bigrams = _tokenize_chinese(f"{title} {tags} {summary} {content}")

            cur.execute(
                """INSERT OR REPLACE INTO wiki_articles
                   (id, title, source, url, category, tags, summary, content, platform, last_crawled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    aid,
                    title,
                    data.get("source", ""),
                    data.get("url", ""),
                    data.get("category", ""),
                    tags,
                    summary,
                    content,
                    data.get("platform", "BE"),
                    data.get("last_crawled", ""),
                ),
            )
            cur.execute(
                """INSERT INTO wiki_fts (rowid, id, title, tags, summary, content, bigrams)
                   SELECT rowid, id, title, tags, summary, content, ?
                   FROM wiki_articles WHERE id = ?""",
                (bigrams, aid),
            )

        self._db.commit()
        logger.info("Wiki FTS index rebuilt: %d articles indexed", cur.execute("SELECT count(*) FROM wiki_articles").fetchone()[0])

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = WIKI_SEARCH_MAX_RESULTS,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search the wiki knowledge base.

        Returns list of dicts with: id, title, category, source, summary, snippet.
        """
        if not self._initialized or self._db is None:
            return []

        terms = query.strip()
        if not terms:
            return []

        # For our data scale (dozens to hundreds of articles), LIKE search
        # with keyword scoring is reliable and handles CJK text naturally.
        # FTS5 unicode61 tokenizer doesn't handle Chinese well.
        return self._keyword_search(terms, max_results, category)

    def _keyword_search(
        self,
        query: str,
        max_results: int,
        category: str | None,
    ) -> list[dict[str, Any]]:
        """Keyword-based search with weighted scoring.

        Weights: title match (3x), tags match (2x), summary/content match (1x).
        """
        assert self._db is not None

        # Split query into individual keywords for multi-keyword matching
        keywords = query.split()

        sql = "SELECT id, title, category, source, tags, summary FROM wiki_articles WHERE 1=1"
        params: list[Any] = []

        if category:
            sql += " AND category = ?"
            params.append(category)

        # At least one keyword must match somewhere
        if keywords:
            keyword_clauses = []
            for kw in keywords:
                pattern = f"%{kw}%"
                keyword_clauses.append(
                    "(title LIKE ? OR tags LIKE ? OR summary LIKE ? OR content LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])
            sql += " AND (" + " OR ".join(keyword_clauses) + ")"

        rows = self._db.execute(sql, params).fetchall()

        # Score results
        scored: list[tuple[float, dict]] = []
        for r in rows:
            score = 0.0
            title = r["title"].lower()
            tags = r["tags"].lower()
            summary = r["summary"].lower()

            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in title:
                    score += 3.0
                if kw_lower in tags:
                    score += 2.0
                if kw_lower in summary:
                    score += 1.0

            scored.append((score, {
                "id": r["id"],
                "title": r["title"],
                "category": r["category"],
                "source": r["source"],
                "summary": r["summary"],
                "snippet": "",
            }))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:max_results]]

    def get_article(self, article_id: str, max_chars: int = 2000) -> dict[str, Any] | None:
        """Load a full article by ID. Content is truncated to max_chars."""
        if not self._initialized or self._db is None:
            return None

        # Check cache
        if article_id in self._article_cache:
            cached = self._article_cache[article_id]
            return {**cached, "content": cached["content"][:max_chars]}

        row = self._db.execute(
            "SELECT * FROM wiki_articles WHERE id = ?", (article_id,)
        ).fetchone()
        if not row:
            return None

        article = dict(row)
        self._article_cache[article_id] = article
        return {**article, "content": article["content"][:max_chars]}

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics."""
        if not self._initialized or self._db is None:
            return {"initialized": False, "total": 0}

        rows = self._db.execute(
            "SELECT category, count(*) as cnt FROM wiki_articles GROUP BY category"
        ).fetchall()

        return {
            "initialized": True,
            "total": sum(r["cnt"] for r in rows),
            "by_category": {r["category"]: r["cnt"] for r in rows},
        }


# Singleton
wiki_searcher = WikiSearcher()
