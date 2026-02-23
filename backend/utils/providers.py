"""Cloud LLM provider registry.

Each provider entry describes an OpenAI-compatible API endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderInfo:
    """Metadata for a single cloud LLM provider."""

    id: str
    name: str
    base_url: str
    default_model: str
    models: list[str] = field(default_factory=list)
    supports_thinking: bool = False
    thinking_field: str = ""
    free_tier: bool = False
    requires_endpoint_id: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "models": self.models,
            "supports_thinking": self.supports_thinking,
            "free_tier": self.free_tier,
            "requires_endpoint_id": self.requires_endpoint_id,
        }


PROVIDERS: dict[str, ProviderInfo] = {
    "deepseek": ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
        supports_thinking=True,
        thinking_field="reasoning_content",
    ),
    "qwen": ProviderInfo(
        id="qwen",
        name="通义千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        models=["qwen-turbo", "qwen-plus", "qwen-max"],
    ),
    "glm": ProviderInfo(
        id="glm",
        name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        models=["glm-4-flash", "glm-4", "glm-4-plus"],
        free_tier=True,
    ),
    "kimi": ProviderInfo(
        id="kimi",
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-32k",
        models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    ),
    "doubao": ProviderInfo(
        id="doubao",
        name="豆包",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="",
        models=[],
        requires_endpoint_id=True,
    ),
    "openai": ProviderInfo(
        id="openai",
        name="ChatGPT",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        models=["gpt-4o", "gpt-4o-mini"],
    ),
    "gemini": ProviderInfo(
        id="gemini",
        name="Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.0-flash",
        models=["gemini-2.0-flash", "gemini-2.5-flash-preview-05-20"],
    ),
    "custom": ProviderInfo(
        id="custom",
        name="自定义",
        base_url="",
        default_model="",
        models=[],
    ),
}


def get_provider(provider_id: str) -> ProviderInfo | None:
    """Look up a provider by ID."""
    return PROVIDERS.get(provider_id)


def list_providers() -> list[dict[str, Any]]:
    """Return all providers as a list of dicts (for API responses)."""
    return [p.to_dict() for p in PROVIDERS.values()]
