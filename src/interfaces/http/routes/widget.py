"""
Public, cross-origin API for the embeddable chatbot widget.

This is the only surface a website visitor's browser talks to. It exposes two
endpoints under ``/widget``:

* ``GET  /widget/{bot_id}/config`` — the safe ``PublicBotConfig`` (branding only).
* ``POST /widget/{bot_id}/chat``   — a routed, grounded, cited answer.

The chat handler is the fusion point of the platform's two pillars: it runs the
kNN smart router to pick the best model for the query, then generates the answer
grounded in the company's collection *with that routed model* (Phase 1 threaded
``answer_model_id`` end to end for exactly this). The visitor only ever receives
the answer plus its sources — never cost, routing trace, or which model ran. The
selected-vs-executed model is logged server-side (and exposed on the admin
debug surface), honoring the platform rule that the *selected* model is the
headline and the executed fallback stays internal.

Safety posture (the endpoint is effectively public): per-bot origin enforcement,
per-IP/per-bot rate limiting, and a strict request shape (the client cannot pick
the model, tier, or budget).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.layer0_model_infra.router import get_router
from src.layer3_domain.document_collections import (
    CollectionNotFoundError,
    get_document_collection_service,
)
from src.layer4_platform.bot_registry import (
    BotNotFoundError,
    PublicBotConfig,
    get_bot_config_service,
)
from src.layer4_platform.widget_rate_limit import WidgetRateLimiter
from src.shared.config import get_settings
from src.shared.errors import NoRelevantContextError
from src.shared.logger import get_logger

router = APIRouter(prefix="/widget", tags=["Public Widget"])
logger = get_logger(__name__)
settings = get_settings()

bot_service = get_bot_config_service()
model_router = get_router()
grounded_collection_service = get_document_collection_service()
rate_limiter = WidgetRateLimiter(
    per_ip_per_min=settings.WIDGET_RATE_PER_IP_PER_MIN,
    per_bot_per_min=settings.WIDGET_RATE_PER_BOT_PER_MIN,
    bot_daily_cap=settings.WIDGET_BOT_DAILY_CAP,
)

# Fast-path categories we answer conversationally instead of grounding. A
# greeting/thanks/goodbye/gibberish should never come back as "I couldn't find
# that in our knowledge base".
_SMALL_TALK = {"trivial_greeting", "trivial_acknowledgment", "trivial_farewell", "malformed"}

_NO_CONTEXT_MESSAGE = (
    "I couldn't find anything about that in our knowledge base. "
    "Try rephrasing, or ask me something else about us."
)
_SNIPPET_MAX = 240


# ---------------------------------------------------------------------------
# Wire contracts (end-user-safe ONLY)
# ---------------------------------------------------------------------------


class WidgetChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class WidgetSource(BaseModel):
    """A citation, stripped to what a visitor may safely see."""

    title: str
    source_uri: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    snippet: str = ""


class WidgetChatResponse(BaseModel):
    answer: str
    grounded: bool = False
    sources: list[WidgetSource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_enabled() -> None:
    if not settings.WIDGET_PUBLIC_ENABLED:
        # Hide the surface entirely when the kill switch is off.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is spoofable; for rate-limiting in this single-node demo it
    # is good enough. In production, trust it only from a known proxy.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _field(citation: object, key: str) -> object:
    if isinstance(citation, dict):
        return citation.get(key)
    return getattr(citation, key, None)


def _snippet(text: object) -> str:
    body = str(text or "").strip().replace("\n", " ")
    if len(body) <= _SNIPPET_MAX:
        return body
    clipped = body[:_SNIPPET_MAX].rsplit(" ", 1)[0]
    return f"{clipped}…"


def _project_sources(citations: list) -> list[WidgetSource]:
    """Project citations to the safe shape and dedupe by (uri, page)."""
    seen: set[tuple[str, Optional[int]]] = set()
    out: list[WidgetSource] = []
    for citation in citations or []:
        uri = str(_field(citation, "source_uri") or "")
        page = _field(citation, "page_number")
        page_int = int(page) if isinstance(page, (int, float)) else None
        key = (uri, page_int)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            WidgetSource(
                title=str(_field(citation, "title") or "Source"),
                source_uri=uri,
                page_number=page_int,
                section_title=(_field(citation, "section_title") or None),
                snippet=_snippet(_field(citation, "content") or _field(citation, "snippet")),
            )
        )
    return out


def _small_talk_reply(category: str, greeting: str, display_name: str) -> str:
    if category == "trivial_greeting":
        return greeting or f"Hello! I'm {display_name}. How can I help you today?"
    if category == "trivial_acknowledgment":
        return "You're welcome! Is there anything else I can help you with?"
    if category == "trivial_farewell":
        return "Thanks for stopping by — have a great day!"
    return "Sorry, I didn't quite catch that. Could you rephrase your question?"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{bot_id}/config", response_model=PublicBotConfig, summary="Public widget config")
async def widget_config(bot_id: str) -> PublicBotConfig:
    _require_enabled()
    try:
        return bot_service.get_public_config(bot_id)
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found") from exc


@router.post("/{bot_id}/chat", response_model=WidgetChatResponse, summary="Chat with a widget bot")
async def widget_chat(bot_id: str, body: WidgetChatRequest, request: Request) -> WidgetChatResponse:
    _require_enabled()

    # 1. Resolve the bot (and treat disabled as absent).
    try:
        bot = bot_service.get_bot(bot_id)
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found") from exc
    if not bot.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

    # 2. Origin enforcement — the authoritative gate (CORS is browser-side only).
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not bot_service.is_origin_allowed(bot_id, origin):
        logger.warning("widget_origin_rejected", bot_id=bot_id, origin=origin[:120])
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    # 3. Abuse guard.
    ip = _client_ip(request)
    limited = rate_limiter.check_and_record(ip=ip, bot_id=bot_id)
    if limited:
        logger.warning("widget_rate_limited", bot_id=bot_id, reason=limited)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": "60"},
        )

    message = body.message.strip()

    # 4. Route once: this both triages small-talk (fast path) and selects the
    #    best model for a real query.
    decision = model_router.route(query=message, user_tier="standard", budget_remaining=1.0)
    category = decision.fast_path_category or "none"
    if category in _SMALL_TALK:
        return WidgetChatResponse(
            answer=_small_talk_reply(category, bot.greeting, bot.display_name),
            grounded=False,
            sources=[],
        )

    selected_id = decision.selected_model.model_id
    selected_display = decision.selected_model.display_name

    # 5. Grounded answer generated BY the routed model (the fusion). Force
    #    gateway mode so the routed model is actually used (heuristic mode would
    #    ignore answer_model_id).
    try:
        grounded = await grounded_collection_service.answer_query(
            collection_id=bot.collection_id,
            query=message,
            tenant_id=bot.tenant_id,
            domain=bot.grounded_domain,
            top_k=bot.grounded_top_k,
            generation_mode="gateway",
            answer_model_id=selected_id,
        )
    except NoRelevantContextError:
        logger.info("widget_no_context", bot_id=bot_id, selected_model=selected_id)
        return WidgetChatResponse(answer=_NO_CONTEXT_MESSAGE, grounded=False, sources=[])
    except CollectionNotFoundError as exc:
        # Misconfigured bot (points at a non-existent collection). Loud for ops,
        # generic for the visitor.
        logger.error("widget_collection_missing", bot_id=bot_id, collection_id=bot.collection_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="This assistant is temporarily unavailable.",
        ) from exc

    # 6. The internals live here in the log, never in the response.
    logger.info(
        "widget_chat_answered",
        bot_id=bot_id,
        selected_model=selected_id,
        selected_display=selected_display,
        executed_model=grounded.model_id,
        retrieval_count=grounded.retrieval_count,
        grounded=grounded.grounded,
    )

    return WidgetChatResponse(
        answer=grounded.answer,
        grounded=bool(grounded.grounded),
        sources=_project_sources(grounded.citations),
    )
