"""Curated 兜底模型列表。

仅在「动态发现失败/不支持」时作为兜底。运行时优先用 ModelCatalog 拉到的
真实 /models 列表。这里只保证「不至于过时到全是死模型」，并剔除已知下线项。
"""

from __future__ import annotations

CURATED_MODELS: dict[str, list[str]] = {
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "qwen": ["qwen-max-latest", "qwen-plus-latest", "qwen-turbo-latest", "qwen-max", "qwen-plus", "qwen-turbo"],
    "glm": ["glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4-long"],
    "kimi": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    # doubao 需 endpoint_id、custom 用户自填：留空
    "doubao": [],
    "custom": [],
}


def curated_models_for(provider_id: str) -> list[str]:
    """返回某 provider 的 curated 兜底模型列表（未知返回空列表）。"""
    return list(CURATED_MODELS.get(provider_id, []))
