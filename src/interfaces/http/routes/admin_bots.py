"""
Admin API for provisioning external chatbot widgets.

These endpoints are the *internal* control plane: they create and manage the
per-company ``BotConfig`` records that the public ``/widget/*`` surface reads
from. They live on the main app (strict CORS, no public origin), so the full
config — including ``tenant_id``, ``collection_id`` and ``allowed_origins`` —
never reaches a browser on a company website.

There is intentionally no auth layer here (consistent with the existing
``/tenants`` and ``/grounded-documents`` admin endpoints on this platform);
deployments are expected to network-restrict the admin surface.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.layer3_domain.document_collections import get_document_collection_service
from src.layer4_platform.bot_registry import (
    BotConfig,
    BotConfigInvalidError,
    BotNotFoundError,
    BotTheme,
    SuggestedPrompt,
    get_bot_config_service,
)
from src.shared.logger import get_logger

router = APIRouter(prefix="/admin/bots", tags=["Admin · Bots"])
logger = get_logger(__name__)

bot_service = get_bot_config_service()
collection_service = get_document_collection_service()


class BotCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    collection_id: str = Field(..., min_length=1)
    display_name: str = Field(default="Assistant")
    greeting: str = Field(default="Hi! How can I help you today?")
    suggested_prompts: list[SuggestedPrompt] = Field(default_factory=list)
    theme: BotTheme = Field(default_factory=BotTheme)
    allowed_origins: list[str] = Field(default_factory=list)
    grounded_domain: Optional[str] = Field(default=None)
    grounded_top_k: int = Field(default=6, ge=1, le=20)
    enabled: bool = Field(default=True)


class BotUpdateRequest(BaseModel):
    collection_id: Optional[str] = None
    display_name: Optional[str] = None
    greeting: Optional[str] = None
    suggested_prompts: Optional[list[SuggestedPrompt]] = None
    theme: Optional[BotTheme] = None
    allowed_origins: Optional[list[str]] = None
    grounded_domain: Optional[str] = None
    grounded_top_k: Optional[int] = Field(default=None, ge=1, le=20)
    enabled: Optional[bool] = None


class BotAdminView(BaseModel):
    """Full bot record plus the paste-ready embed snippet and any warnings."""

    config: BotConfig
    embed_snippet: str
    warnings: list[str] = Field(default_factory=list)


async def _collection_warnings(tenant_id: str, collection_id: str) -> list[str]:
    """Advisory checks (never fatal): does the collection exist, and is it
    gateway-mode? The widget forces gateway generation at answer time, so a
    non-gateway collection still works — but onboarding should surface it."""
    warnings: list[str] = []
    try:
        summaries = await collection_service.list_collections(tenant_id)
    except Exception as exc:  # advisory only
        logger.warning("bot_collection_check_failed", error=str(exc))
        return warnings
    match = next((s for s in summaries if s.collection_id == collection_id), None)
    if match is None:
        warnings.append(
            f"Collection '{collection_id}' has no documents for tenant '{tenant_id}' yet. "
            "Upload files or run a crawl before the bot can answer."
        )
    elif match.generation_mode != "gateway":
        warnings.append(
            f"Collection '{collection_id}' is in '{match.generation_mode}' mode. The widget "
            "forces gateway mode at answer time (so routing still applies), but consider "
            "re-ingesting it as gateway."
        )
    return warnings


def _view(config: BotConfig, request: Request, warnings: Optional[list[str]] = None) -> BotAdminView:
    api_base = str(request.base_url).rstrip("/")
    return BotAdminView(
        config=config,
        embed_snippet=bot_service.embed_snippet(config.bot_id, api_base),
        warnings=warnings or [],
    )


@router.post("", response_model=BotAdminView, status_code=status.HTTP_201_CREATED, summary="Create a bot")
async def create_bot(request: Request, body: BotCreateRequest) -> BotAdminView:
    try:
        config = bot_service.create_bot(
            tenant_id=body.tenant_id,
            collection_id=body.collection_id,
            display_name=body.display_name,
            greeting=body.greeting,
            suggested_prompts=body.suggested_prompts,
            theme=body.theme,
            allowed_origins=body.allowed_origins,
            grounded_domain=body.grounded_domain,
            grounded_top_k=body.grounded_top_k,
            enabled=body.enabled,
        )
    except BotConfigInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    warnings = await _collection_warnings(body.tenant_id, body.collection_id)
    return _view(config, request, warnings)


@router.get("", response_model=list[BotAdminView], summary="List bots (optionally by tenant)")
async def list_bots(request: Request, tenant_id: Optional[str] = None) -> list[BotAdminView]:
    return [_view(c, request) for c in bot_service.list_bots(tenant_id)]


@router.get("/{bot_id}", response_model=BotAdminView, summary="Get a bot")
async def get_bot(request: Request, bot_id: str) -> BotAdminView:
    try:
        config = bot_service.get_bot(bot_id)
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    return _view(config, request)


@router.put("/{bot_id}", response_model=BotAdminView, summary="Update a bot")
async def update_bot(request: Request, bot_id: str, body: BotUpdateRequest) -> BotAdminView:
    patch = body.model_dump(exclude_unset=True)
    try:
        config = bot_service.update_bot(bot_id, patch)
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except BotConfigInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    warnings = await _collection_warnings(config.tenant_id, config.collection_id)
    return _view(config, request, warnings)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a bot")
async def delete_bot(bot_id: str) -> None:
    bot_service.delete_bot(bot_id)
