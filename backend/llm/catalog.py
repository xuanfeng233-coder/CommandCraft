"""动态模型发现：运行时拉取 provider 的 /models 列表，curated 兜底。

优先 GET {base_url}/models（OpenAI 兼容；Gemini 用其 /v1beta/openai/models 同样兼容），
成功则缓存 TTL；失败/缺凭证则回落 curated 列表并告警。能力标志仍由 providers.py
的 curated 元数据维护——这里只刷新「有哪些 model id」。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from backend.config import MODEL_CATALOG_TTL
from backend.llm.curated_models import curated_models_for

logger = logging.getLogger(__name__)

Fetcher = Callable[[str, str], Awaitable[list[str]]]


@dataclass
class ModelInfo:
    """一个可选模型。source 标记来源（dynamic=实时拉取 / curated=兜底）。"""

    id: str
    provider_id: str
    source: str  # "dynamic" | "curated"


class ModelCatalog:
    """带 TTL 缓存的模型目录。"""

    def __init__(
        self,
        *,
        ttl: int = MODEL_CATALOG_TTL,
        fetcher: Fetcher | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._fetcher: Fetcher = fetcher or self._httpx_fetch_models
        self._now = time_fn
        # key=(provider_id, base_url) -> (fetched_at, [model_id,...])
        self._cache: dict[tuple[str, str], tuple[float, list[str]]] = {}

    async def list_models(
        self,
        provider_id: str,
        api_key: str = "",
        base_url: str = "",
    ) -> list[ModelInfo]:
        """返回某 provider 的可选模型。优先动态，失败回落 curated。"""
        # 无凭证/无 url：直接 curated，不尝试拉取
        if not api_key or not base_url:
            logger.warning(
                "缺少凭证（provider=%s），回落 curated 模型列表", provider_id
            )
            return self._curated(provider_id)

        cache_key = (provider_id, base_url)
        cached = self._cache.get(cache_key)
        if cached and (self._now() - cached[0]) < self._ttl:
            return [ModelInfo(mid, provider_id, "dynamic") for mid in cached[1]]

        try:
            ids = await self._fetcher(base_url, api_key)
        except Exception as exc:  # noqa: BLE001 - 任意拉取失败都回落
            logger.warning(
                "动态模型发现失败（provider=%s base_url=%s），回落 curated：%s",
                provider_id, base_url, exc,
            )
            return self._curated(provider_id)

        if not ids:
            logger.warning(
                "动态模型发现返回空（provider=%s），回落 curated", provider_id
            )
            return self._curated(provider_id)

        self._cache[cache_key] = (self._now(), ids)
        return [ModelInfo(mid, provider_id, "dynamic") for mid in ids]

    def _curated(self, provider_id: str) -> list[ModelInfo]:
        return [
            ModelInfo(mid, provider_id, "curated")
            for mid in curated_models_for(provider_id)
        ]

    async def _httpx_fetch_models(self, base_url: str, api_key: str) -> list[str]:
        """GET {base_url}/models，解析 OpenAI 兼容的 data[].id。"""
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(trust_env=False, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [item["id"] for item in data if isinstance(item, dict) and "id" in item]


# 单例
model_catalog = ModelCatalog()
