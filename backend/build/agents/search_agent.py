"""SearchAgent — Local wiki knowledge search for Bedrock Edition info.

Replaces the old DDG web search with local FTS5-backed wiki search.
Other agents call ``await search_agent.search(query, context)`` to get
authoritative search results from the local knowledge base.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.knowledge.wiki_search import wiki_searcher

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    url: str = ""
    title: str = ""
    content: str = ""
    is_authoritative: bool = False
    verified: bool = False
    platform: str = ""  # "BE" | "JE" | "both"
    summary: str = ""


class SearchAgent:
    """Local wiki search service for build mode agents."""

    async def search(
        self,
        query: str,
        context: str = "",
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Search local wiki knowledge base.

        Returns SearchResult list. Empty if wiki not initialized.
        """
        stats = wiki_searcher.get_stats()
        if not stats.get("initialized"):
            logger.warning("SearchAgent: wiki not initialized, no results for: %s", query)
            return []

        hits = wiki_searcher.search(query, max_results=max_results)
        if not hits:
            logger.info("SearchAgent: no local results for: %s", query)
            return []

        results: list[SearchResult] = []
        for hit in hits:
            # Load full article for content
            article = wiki_searcher.get_article(hit["id"], max_chars=2000)
            content = ""
            if article:
                content = article.get("content", "")

            results.append(SearchResult(
                url=article.get("url", "") if article else "",
                title=hit.get("title", ""),
                content=content or hit.get("summary", ""),
                is_authoritative=True,  # local data is curated
                verified=True,
                platform=article.get("platform", "BE") if article else "BE",
                summary=hit.get("summary", ""),
            ))

        logger.info("SearchAgent: found %d local results for: %s", len(results), query)
        return results


# Singleton
search_agent = SearchAgent()
