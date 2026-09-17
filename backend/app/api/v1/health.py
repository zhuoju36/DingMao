"""健康检查端点 - 用于 Docker / k8s 探针。"""

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/llm")
async def health_llm() -> dict[str, Any]:
    """检查 LLM 配置是否可用（不实际调用，仅检查 key 存在）。"""
    from app.core.config import settings

    providers: dict[str, bool] = {
        "minimax": bool(settings.minimax_api_key),
        "deepseek": bool(settings.deepseek_api_key),
        "openai": bool(settings.openai_api_key),
    }
    return {
        "default": settings.llm_default,
        "providers": providers,
        "available": any(providers.values()),
    }
