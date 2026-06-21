"""Settings API router — provider listing, config apply/verify."""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.llm.catalog import model_catalog
from backend.utils.providers import list_providers
from backend.utils.settings_manager import settings_manager

router = APIRouter(prefix="/api/settings", tags=["settings"])


# -- Request / Response models -----------------------------------------------

class LLMSettingsRequest(BaseModel):
    provider_id: str = Field(..., description="Provider ID (deepseek, qwen, glm, ...)")
    api_key: str = Field(..., description="API key")
    base_url: str = Field("", description="Override base URL (optional)")
    model: str = Field("", description="Override model name (optional)")
    temperature: float = Field(0.6, ge=0, le=2)


class ConfigResponse(BaseModel):
    provider_id: str
    api_key: str  # masked
    base_url: str
    model: str
    temperature: float
    is_configured: bool


class VerifyResponse(BaseModel):
    ok: bool
    latency_ms: int = 0
    error: str = ""
    model: str = ""


class ModelsRequest(BaseModel):
    provider_id: str = Field(..., description="Provider ID")
    api_key: str = Field("", description="API key（动态发现用；空则直接 curated）")
    base_url: str = Field("", description="Override base URL（空则用 provider 默认）")


# -- Endpoints ---------------------------------------------------------------

@router.get("/providers")
async def get_providers():
    """List available LLM providers."""
    return list_providers()


@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Return current LLM config (API key masked)."""
    return settings_manager.get_config().to_safe_dict()


@router.post("/config", response_model=ConfigResponse)
async def post_config(req: LLMSettingsRequest):
    """Apply a new LLM configuration."""
    cfg = settings_manager.set_config(req.model_dump())
    return cfg.to_safe_dict()


@router.post("/verify", response_model=VerifyResponse)
async def verify_config(req: LLMSettingsRequest):
    """Test a configuration by making a minimal API call."""
    # Temporarily apply the config
    settings_manager.set_config(req.model_dump())

    from backend.utils.llm_client import llm_client

    start = time.monotonic()
    try:
        api_ok, model_ok = await llm_client.check_health()
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if api_ok and model_ok:
            return VerifyResponse(ok=True, latency_ms=elapsed_ms, model=llm_client.model)
        elif api_ok:
            return VerifyResponse(ok=False, error=f"模型 '{llm_client.model}' 不可用", model=llm_client.model)
        else:
            return VerifyResponse(ok=False, error="无法连接到 API 服务")
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return VerifyResponse(ok=False, latency_ms=elapsed_ms, error=str(e))


@router.post("/models")
async def get_models(req: ModelsRequest):
    """返回某 provider 的可选模型列表（优先动态发现，失败回落 curated）。"""
    from backend.utils.providers import get_provider

    base_url = req.base_url
    if not base_url:
        provider = get_provider(req.provider_id)
        base_url = provider.base_url if provider else ""

    models = await model_catalog.list_models(
        req.provider_id, api_key=req.api_key, base_url=base_url
    )
    overall = "dynamic" if models and all(m.source == "dynamic" for m in models) else "curated"
    return {
        "models": [
            {"id": m.id, "provider_id": m.provider_id, "source": m.source}
            for m in models
        ],
        "source": overall,
    }
