"""
Admin AutoPilot route.

``POST /admin/autopilot/analyze`` turns a pasted website URL into a review-ready
bot draft — theme (from the rendered screenshot), AI-written copy (via the Smart
Router), a suggested collection/tenant/origin, and a stored screenshot the
console floats the live preview over. ``GET /admin/autopilot/screenshot/{id}``
serves that screenshot.

This is admin-only (same posture as the rest of ``/admin/*``: no auth, expected
to be network-restricted) and never auto-creates a bot — the console fills the
form from the draft and the human clicks Create.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.layer4_platform.autopilot import AutopilotError, analyze_site, screenshot_path
from src.layer4_platform.bot_registry import BotTheme, SuggestedPrompt
from src.shared.config import get_settings
from src.shared.logger import get_logger

router = APIRouter(prefix="/admin/autopilot", tags=["Admin · AutoPilot"])
logger = get_logger(__name__)
settings = get_settings()


class AutopilotAnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=1, description="Website URL to analyze")
    tenant_id: Optional[str] = Field(default=None, description="Optional tenant override")


class AutopilotDraft(BaseModel):
    """A review-ready draft the console maps onto the create-bot form."""

    source_url: str
    final_url: str
    origin: str
    display_name: str
    greeting: str
    subtitle: str
    suggested_prompts: list[SuggestedPrompt] = Field(default_factory=list)
    theme: BotTheme
    palette: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)
    suggested_tenant_id: str
    suggested_collection_id: str
    screenshot_id: str
    screenshot_url: str
    authored_by_model: Optional[str] = None
    page_title: str = ""
    warnings: list[str] = Field(default_factory=list)


@router.post("/analyze", response_model=AutopilotDraft, summary="Analyze a URL into a bot draft")
async def autopilot_analyze(body: AutopilotAnalyzeRequest) -> AutopilotDraft:
    if not settings.WIDGET_AUTOPILOT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AutoPilot is disabled."
        )
    try:
        draft = await analyze_site(body.url, tenant_id=body.tenant_id)
    except AutopilotError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AutopilotDraft(**draft)


@router.get("/screenshot/{shot_id}", summary="Serve a stored AutoPilot screenshot")
async def autopilot_screenshot(shot_id: str) -> FileResponse:
    path = screenshot_path(shot_id)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    return FileResponse(str(path), media_type="image/jpeg")
