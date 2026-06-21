"""SearXNG 联网搜索客户端（local-first，best-effort 软依赖）。

任何失败都返回 []（不抛进循环）；base_url 经 url_guard 校验（允许运营方配置的本地环回）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from backend.config import SEARXNG_TIMEOUT, SEARXNG_URL, WEB_SEARCH_MAX_RESULTS
from backend.llm.url_guard import UnsafeURLError, assert_safe_outbound_url

logger = logging.getLogger(__name__)


@dataclass
class WebHit:
    title: str
    url: str
    snippet: str
    engine: str | None = None


class SearXNGClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = SEARXNG_TIMEOUT,
        max_results: int = WEB_SEARCH_MAX_RESULTS,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        # 信任边界：base_url 必须来自运营方配置（SEARXNG_URL 环境变量），绝不能来自 LLM/用户输入，
        # 因为 search() 以 allow_loopback=True 调用 url_guard，会放行本地环回地址。
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_results = max_results
        self._http = http

    async def search(self, query: str, *, categories: str | None = None) -> list[WebHit]:
        url = self._base_url + "/search"
        try:
            # 允许运营方配置的本地环回 SearXNG；其余内网/元数据仍拒绝
            assert_safe_outbound_url(url, allow_loopback=True)
        except UnsafeURLError as exc:
            logger.warning("SearXNG base_url 不安全，跳过联网搜索：%s", exc)
            return []

        params = {"q": query, "format": "json"}
        if categories:
            params["categories"] = categories
        try:
            if self._http is not None:
                resp = await self._http.get(url, params=params, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(trust_env=False, timeout=self._timeout) as client:
                    resp = await client.get(url, params=params, follow_redirects=False)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - best-effort：任何失败都降级为空
            logger.warning("SearXNG 搜索失败（query=%s）：%s", query, exc)
            return []

        results = payload.get("results", []) if isinstance(payload, dict) else []
        hits: list[WebHit] = []
        for r in results[: self._max_results]:
            if not isinstance(r, dict):
                continue
            hits.append(WebHit(
                title=str(r.get("title", "")),
                url=str(r.get("url", "")),
                snippet=str(r.get("content", "")),
                engine=r.get("engine"),
            ))
        return hits


_client_singleton: SearXNGClient | None = None
_client_resolved: bool = False


def get_searxng_client() -> SearXNGClient | None:
    """返回单例客户端；SEARXNG_URL 为空时返回 None（联网搜索禁用）。"""
    global _client_singleton, _client_resolved
    if not _client_resolved:
        _client_singleton = SearXNGClient(SEARXNG_URL) if SEARXNG_URL else None
        _client_resolved = True
    return _client_singleton
