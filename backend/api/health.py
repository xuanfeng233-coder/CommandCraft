"""Health check endpoint."""

from fastapi import APIRouter

from backend.models.schemas import HealthResponse
from backend.utils.llm_client import llm_client

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    if not llm_client.is_configured:
        status = "not_configured"
        api_ok = False
        model_ok = False
    else:
        api_ok, model_ok = await llm_client.check_health()
        if api_ok and model_ok:
            status = "ok"
        elif api_ok:
            status = "model_unavailable"
        else:
            status = "api_unreachable"

    return HealthResponse(
        status=status,
        provider_name=llm_client.provider_id if llm_client.is_configured else "",
        model_name=llm_client.model if llm_client.is_configured else "",
    )
