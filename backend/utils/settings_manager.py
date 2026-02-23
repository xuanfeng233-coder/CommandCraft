"""In-memory LLM configuration manager.

The frontend localStorage is the source of truth.  On app start the frontend
pushes config to the backend via POST /api/settings/config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.utils.providers import get_provider

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Current LLM configuration."""

    provider_id: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.6

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def to_safe_dict(self) -> dict[str, Any]:
        """Return config with masked API key (for GET responses)."""
        masked_key = ""
        if self.api_key:
            masked_key = self.api_key[:4] + "****" + self.api_key[-4:]
        return {
            "provider_id": self.provider_id,
            "api_key": masked_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "is_configured": self.is_configured,
        }


class SettingsManager:
    """Singleton holding the current LLM configuration."""

    def __init__(self) -> None:
        self._config = LLMConfig()

    def get_config(self) -> LLMConfig:
        return self._config

    def set_config(self, config: dict[str, Any]) -> LLMConfig:
        """Validate and apply a new configuration.

        Also reconfigures the LLM client singleton.
        """
        provider_id = config.get("provider_id", "custom")
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "")
        model = config.get("model", "")
        temperature = float(config.get("temperature", 0.6))

        # Resolve base_url and model from provider if not explicitly set
        provider = get_provider(provider_id)
        if provider:
            if not base_url:
                base_url = provider.base_url
            if not model:
                model = provider.default_model

        self._config = LLMConfig(
            provider_id=provider_id,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
        )

        # Apply to the LLM client
        from backend.utils.llm_client import llm_client

        thinking_field = ""
        if provider and provider.supports_thinking:
            thinking_field = provider.thinking_field

        llm_client.configure(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_id=provider_id,
            thinking_field=thinking_field,
        )

        logger.info(
            "Settings applied: provider=%s model=%s base_url=%s",
            provider_id, model, base_url,
        )
        return self._config


# Singleton
settings_manager = SettingsManager()
