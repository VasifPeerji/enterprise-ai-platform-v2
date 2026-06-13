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

import html
import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.layer0_model_infra.router import get_router
from src.layer3_domain.document_collections import (
    CollectionNotFoundError,
    get_document_collection_service,
)
from src.layer4_platform.bot_registry import (
    BotConfig,
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

# A follow-up ("what about pro?", "and the price?", "tell me more") needs the
# previous turn to retrieve the right content. These signals decide when to
# prepend the last user message to the *retrieval* query (generation/routing
# still see the original message).
_FOLLOWUP_PREFIX_RE = re.compile(
    r"^\s*(and|but|also|what about|how about|what else|tell me more|more|why|"
    r"then|ok(?:ay)?|and what|what if|which one|compare)\b",
    re.I,
)
_PRONOUN_RE = re.compile(r"\b(it|its|that|those|them|they|this|these|their|one)\b", re.I)
# Public bot ids are "bot_" + token_urlsafe (base64url charset). The preview
# page reflects bot_id from the query string into HTML, so it is validated to
# this exact shape to close a reflected-XSS vector.
_BOT_ID_RE = re.compile(r"^bot_[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Wire contracts (end-user-safe ONLY)
# ---------------------------------------------------------------------------


class WidgetTurn(BaseModel):
    role: str = Field(..., pattern="^(user|bot|assistant)$")
    content: str = Field(..., max_length=2000)


class WidgetChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: Optional[list[WidgetTurn]] = Field(
        default=None,
        max_length=20,
        description="Recent prior turns (oldest first), used to resolve follow-up questions.",
    )


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


def _resolve_and_guard(bot_id: str, request: Request) -> BotConfig:
    """Shared gate for both chat surfaces: kill switch, bot existence, per-bot
    origin enforcement, and rate limiting. Raises the appropriate HTTPException;
    returns the bot on success."""
    _require_enabled()
    try:
        bot = bot_service.get_bot(bot_id)
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found") from exc
    if not bot.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not bot_service.is_origin_allowed(bot_id, origin):
        logger.warning("widget_origin_rejected", bot_id=bot_id, origin=origin[:120])
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    limited = rate_limiter.check_and_record(ip=_client_ip(request), bot_id=bot_id)
    if limited:
        logger.warning("widget_rate_limited", bot_id=bot_id, reason=limited)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": "60"},
        )
    return bot


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


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


def _expand_retrieval_query(message: str, history: Optional[list[WidgetTurn]]) -> str:
    """For a follow-up, prepend the previous user turn so retrieval has context.

    Self-contained questions are left untouched (prepending an unrelated prior
    turn would only pollute retrieval). Only the *retrieval* query is expanded;
    routing and small-talk triage still run on the original message.
    """
    if not history:
        return message
    looks_followup = (
        len(message.split()) <= 6
        or bool(_FOLLOWUP_PREFIX_RE.search(message))
        or bool(_PRONOUN_RE.search(message))
    )
    if not looks_followup:
        return message
    last_user = next((t.content for t in reversed(history) if t.role == "user"), None)
    if not last_user or last_user.strip() == message.strip():
        return message
    return f"{last_user}\n{message}"


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
    bot = _resolve_and_guard(bot_id, request)
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
    retrieval_query = _expand_retrieval_query(message, body.history)
    try:
        grounded = await grounded_collection_service.answer_query(
            collection_id=bot.collection_id,
            query=retrieval_query,
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


@router.post("/{bot_id}/chat/stream", summary="Streaming (SSE) chat with a widget bot")
async def widget_chat_stream(bot_id: str, body: WidgetChatRequest, request: Request) -> StreamingResponse:
    """Same fusion as the blocking chat, but the answer is streamed token-by-token
    over Server-Sent Events. Events: `{type:'token',value}` … then
    `{type:'done',grounded,sources}` (or `{type:'error',value}`). Guards (origin,
    rate-limit) run before streaming starts, so they surface as normal HTTP errors."""
    bot = _resolve_and_guard(bot_id, request)
    message = body.message.strip()
    decision = model_router.route(query=message, user_tier="standard", budget_remaining=1.0)
    category = decision.fast_path_category or "none"
    selected_id = decision.selected_model.model_id
    selected_display = decision.selected_model.display_name
    retrieval_query = _expand_retrieval_query(message, body.history)

    async def event_stream():
        try:
            if category in _SMALL_TALK:
                yield _sse({"type": "token", "value": _small_talk_reply(category, bot.greeting, bot.display_name)})
                yield _sse({"type": "done", "grounded": False, "sources": []})
                return

            grounded_context, token_iter = await grounded_collection_service.stream_answer(
                collection_id=bot.collection_id,
                query=retrieval_query,
                tenant_id=bot.tenant_id,
                domain=bot.grounded_domain,
                top_k=bot.grounded_top_k,
                generation_mode="gateway",
                answer_model_id=selected_id,
            )
            if grounded_context is None:
                yield _sse({"type": "token", "value": _NO_CONTEXT_MESSAGE})
                yield _sse({"type": "done", "grounded": False, "sources": []})
                return

            sources = [s.model_dump() for s in _project_sources(grounded_context.citations)]
            produced = False
            try:
                async for chunk in token_iter:
                    if chunk:
                        produced = True
                        yield _sse({"type": "token", "value": chunk})
            except Exception as exc:
                logger.warning("widget_stream_generation_failed", bot_id=bot_id, error=str(exc))

            if not produced:
                # The routed model streamed nothing (rate-limit/empty). Fall back
                # to the blocking path, which has gateway failover to a free model.
                try:
                    resp = await grounded_collection_service.answer_query(
                        collection_id=bot.collection_id,
                        query=retrieval_query,
                        tenant_id=bot.tenant_id,
                        domain=bot.grounded_domain,
                        top_k=bot.grounded_top_k,
                        generation_mode="gateway",
                        answer_model_id=selected_id,
                    )
                    yield _sse({"type": "token", "value": resp.answer})
                except Exception:
                    yield _sse({"type": "token", "value": "Sorry, I had trouble answering that."})

            logger.info(
                "widget_chat_stream_answered",
                bot_id=bot_id,
                selected_model=selected_id,
                selected_display=selected_display,
                citation_count=len(grounded_context.citations),
            )
            yield _sse({"type": "done", "grounded": True, "sources": sources})
        except CollectionNotFoundError:
            logger.error("widget_stream_collection_missing", bot_id=bot_id, collection_id=bot.collection_id)
            yield _sse({"type": "error", "value": "This assistant is temporarily unavailable."})
        except Exception as exc:
            logger.error("widget_stream_failed", bot_id=bot_id, error=str(exc))
            yield _sse({"type": "error", "value": "Sorry, something went wrong."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Embeddable front-end: a single vanilla-JS loader served from the backend.
#
# The whole point is config-driven theming with zero per-company code: the
# loader fetches PublicBotConfig, mounts a Shadow DOM (so the host site's CSS can
# neither leak in nor out), and writes the company's theme into CSS custom
# properties (--bot-*). Every rule references those variables, so re-skinning a
# company is purely a config edit.
# ---------------------------------------------------------------------------

WIDGET_LOADER_JS = r"""
(function () {
  "use strict";
  try {
    var script = document.currentScript || document.querySelector('script[data-bot-id]');
    if (!script) return;
    var botId = script.getAttribute('data-bot-id');
    var apiBase = (script.getAttribute('data-api-base') || '').replace(/\/+$/, '');
    if (!botId) return;
    var guard = '__ENTERPRISE_WIDGET__' + botId;
    if (window[guard]) return;
    window[guard] = true;

    fetch(apiBase + '/widget/' + encodeURIComponent(botId) + '/config')
      .then(function (r) { if (!r.ok) throw new Error('config ' + r.status); return r.json(); })
      .then(function (cfg) { boot(cfg || {}); })
      .catch(function () { /* fail silent: never break the host page */ });

    // Only absolute http(s) URLs are navigable from the visitor's browser.
    // Uploaded-document sources carry a filename/relative path (e.g. /docs/faq.txt)
    // that points at our API, not a real page, so they render as plain labels
    // rather than links that 404. Crawled pages keep their live URL and link.
    function safeHref(u) { return typeof u === 'string' && /^https?:\/\//i.test(u); }

    function escMd(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    }
    // Minimal, XSS-safe markdown: escape everything first, then re-introduce only
    // a known-safe set of tags. Links are restricted to http(s) / relative.
    function mdToHtml(src) {
      var s = escMd(src);
      s = s.replace(/```([\s\S]*?)```/g, function (m, c) { return '<pre><code>' + c.replace(/^\n+|\n+$/g, '') + '</code></pre>'; });
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
      s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      var lines = s.split('\n'), html = '', inList = false;
      for (var i = 0; i < lines.length; i++) {
        var m = lines[i].match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);
        if (m) { if (!inList) { html += '<ul>'; inList = true; } html += '<li>' + m[1] + '</li>'; }
        else { if (inList) { html += '</ul>'; inList = false; } if (lines[i].trim()) html += '<p>' + lines[i] + '</p>'; }
      }
      if (inList) html += '</ul>';
      return html || '<p></p>';
    }

    function css(t) {
      var fg = t.dark_mode ? '255,255,255' : '17,24,39';   // neutral overlay base
      var botBubble = t.dark_mode ? 'rgba(255,255,255,0.08)' : 'rgba(17,24,39,0.045)';
      var side = (t.launcher_position === 'bottom-left') ? 'left' : 'right';
      return ''
        + ':host{all:initial;'
        + '--bot-primary:' + (t.primary_color || '#4f46e5') + ';'
        + '--bot-accent:' + (t.accent_color || t.primary_color || '#4f46e5') + ';'
        + '--bot-surface:' + (t.surface_color || '#ffffff') + ';'
        + '--bot-text:' + (t.text_color || '#1f2937') + ';'
        + '--bot-user:' + (t.user_bubble_color || t.primary_color || '#4f46e5') + ';'
        + '--bot-bubble:' + botBubble + ';'
        + '--bot-line:rgba(' + fg + ',0.10);'
        + '--bot-radius:' + (t.corner_radius_px != null ? t.corner_radius_px : 16) + 'px;'
        + '--bot-font:' + (t.font_family || '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif') + ';'
        + 'font-family:var(--bot-font);line-height:1.5;}'
        + '*{box-sizing:border-box;font-family:var(--bot-font);}'
        // launcher
        + '.launcher{position:fixed;bottom:24px;' + side + ':24px;width:60px;height:60px;border-radius:50%;'
        + 'background:var(--bot-primary);color:#fff;border:none;cursor:pointer;box-shadow:0 6px 24px rgba(0,0,0,.22);'
        + 'display:flex;align-items:center;justify-content:center;z-index:2147483000;'
        + 'transition:transform .2s cubic-bezier(.2,.8,.2,1),box-shadow .2s;}'
        + '.launcher:hover{transform:scale(1.08);box-shadow:0 10px 30px rgba(0,0,0,.28);}'
        + '.launcher:active{transform:scale(1);}'
        + '.launcher svg{width:28px;height:28px;}'
        + '.launcher img{width:38px;height:38px;border-radius:50%;object-fit:cover;}'
        // panel
        + '.panel{position:fixed;bottom:98px;' + side + ':24px;width:384px;max-width:calc(100vw - 32px);height:600px;'
        + 'max-height:calc(100vh - 140px);background:var(--bot-surface);color:var(--bot-text);'
        + 'border-radius:18px;box-shadow:0 18px 60px rgba(0,0,0,.20),0 4px 14px rgba(0,0,0,.08);'
        + 'display:flex;flex-direction:column;overflow:hidden;z-index:2147483000;'
        + 'opacity:0;transform:translateY(16px) scale(.98);transform-origin:bottom ' + side + ';pointer-events:none;'
        + 'transition:opacity .22s ease,transform .22s cubic-bezier(.2,.8,.2,1);}'
        + '.panel.open{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}'
        // header
        + '.header{background:var(--bot-primary);color:#fff;padding:15px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0;}'
        + '.header .av{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;'
        + 'background:rgba(255,255,255,.22);color:#fff;font-weight:700;font-size:16px;overflow:hidden;flex-shrink:0;}'
        + '.header .av img{width:100%;height:100%;object-fit:cover;}'
        + '.header .meta{flex:1;min-width:0;}'
        + '.header .name{font-weight:600;font-size:15px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}'
        + '.header .status{font-size:12px;opacity:.9;display:flex;align-items:center;gap:6px;margin-top:3px;}'
        + '.header .status::before{content:"";width:7px;height:7px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 2px rgba(74,222,128,.35);}'
        + '.header .x{background:transparent;border:none;color:#fff;cursor:pointer;font-size:22px;line-height:1;opacity:.8;'
        + 'padding:2px 6px;border-radius:7px;transition:opacity .15s,background .15s;}'
        + '.header .x:hover{opacity:1;background:rgba(255,255,255,.16);}'
        // messages
        + '.messages{flex:1;overflow-y:auto;padding:18px 16px;display:flex;flex-direction:column;gap:12px;}'
        + '.messages::-webkit-scrollbar{width:6px;}'
        + '.messages::-webkit-scrollbar-thumb{background:rgba(' + fg + ',0.16);border-radius:3px;}'
        + '.msg{max-width:84%;padding:11px 14px;border-radius:16px;font-size:14px;line-height:1.5;word-wrap:break-word;'
        + 'animation:msgIn .25s ease;}'
        + '@keyframes msgIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}'
        + '.msg.user{align-self:flex-end;background:var(--bot-user);color:#fff;border-bottom-right-radius:5px;white-space:pre-wrap;}'
        + '.msg.bot{align-self:flex-start;background:var(--bot-bubble);color:var(--bot-text);'
        + 'border:1px solid var(--bot-line);border-bottom-left-radius:5px;}'
        + '.msg.bot p{margin:0 0 8px;}.msg.bot p:last-child{margin-bottom:0;}'
        + '.msg.bot ul{margin:6px 0;padding-left:20px;}.msg.bot li{margin:3px 0;}'
        + '.msg.bot a{color:var(--bot-accent);font-weight:500;}'
        + '.msg.bot code{background:rgba(' + fg + ',0.07);padding:2px 5px;border-radius:5px;font-size:.9em;font-family:ui-monospace,Consolas,monospace;}'
        + '.msg.bot pre{background:rgba(' + fg + ',0.06);padding:10px;border-radius:8px;overflow:auto;margin:6px 0;}'
        + '.msg.bot pre code{background:none;padding:0;}'
        // sources
        + '.sources{margin-top:10px;padding-top:9px;border-top:1px solid var(--bot-line);display:flex;flex-direction:column;gap:5px;}'
        + '.sources .h{font-size:10px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;opacity:.5;}'
        + '.sources a{font-size:12.5px;color:var(--bot-accent);text-decoration:none;line-height:1.3;}'
        + '.sources a:hover{text-decoration:underline;}'
        + '.sources span{font-size:12.5px;color:var(--bot-text);opacity:.65;line-height:1.3;}'
        // chips
        + '.chips{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 14px;}'
        + '.chip{border:1px solid var(--bot-accent);color:var(--bot-accent);background:transparent;border-radius:18px;'
        + 'padding:8px 14px;font-size:13px;cursor:pointer;transition:background .15s,color .15s;}'
        + '.chip:hover{background:var(--bot-accent);color:#fff;}'
        // composer
        + '.composer{display:flex;align-items:center;gap:8px;padding:12px 14px;border-top:1px solid var(--bot-line);flex-shrink:0;}'
        + '.composer input{flex:1;border:1px solid var(--bot-line);border-radius:22px;padding:11px 16px;font-size:14px;'
        + 'background:rgba(' + fg + ',0.03);color:var(--bot-text);outline:none;transition:border-color .15s,background .15s;}'
        + '.composer input:focus{border-color:var(--bot-primary);}'
        + '.composer input::placeholder{color:rgba(' + fg + ',0.4);}'
        + '.composer .send{width:40px;height:40px;flex-shrink:0;border-radius:50%;background:var(--bot-primary);color:#fff;'
        + 'border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform .15s;}'
        + '.composer .send:hover{transform:scale(1.07);}'
        + '.composer .send svg{width:18px;height:18px;}'
        // typing
        + '.typing{display:flex;gap:5px;align-self:flex-start;padding:14px 16px;background:var(--bot-bubble);'
        + 'border:1px solid var(--bot-line);border-radius:16px;border-bottom-left-radius:5px;}'
        + '.typing span{width:7px;height:7px;border-radius:50%;background:var(--bot-text);opacity:.4;animation:bob 1.2s infinite;}'
        + '.typing span:nth-child(2){animation-delay:.18s;}.typing span:nth-child(3){animation-delay:.36s;}'
        + '@keyframes bob{0%,60%,100%{transform:translateY(0);opacity:.3;}30%{transform:translateY(-5px);opacity:.75;}}'
        + '@media (max-width:480px){.panel{width:100vw;height:100vh;max-height:100vh;bottom:0;right:0;left:0;border-radius:0;}'
        + '.launcher{bottom:18px;' + side + ':18px;}}';
    }

    function boot(cfg) {
      var t = cfg.theme || {};
      var host = document.createElement('div');
      host.setAttribute('data-enterprise-widget', botId);
      document.body.appendChild(host);
      var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;

      if (t.font_url) {
        var fl = document.createElement('link'); fl.rel = 'stylesheet'; fl.href = t.font_url; root.appendChild(fl);
      }
      var st = document.createElement('style'); st.textContent = css(t); root.appendChild(st);

      var launcher = document.createElement('button');
      launcher.className = 'launcher'; launcher.setAttribute('aria-label', 'Open chat');
      if (t.launcher_icon_url || t.logo_url) {
        var li = document.createElement('img'); li.src = t.launcher_icon_url || t.logo_url; li.alt = ''; launcher.appendChild(li);
      } else {
        launcher.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C7 3 3 6.6 3 11c0 2 .9 3.8 2.4 5.2L4.5 20l4-1.3c1.1.4 2.3.6 3.5.6 5 0 9-3.6 9-8s-4-8.3-9-8.3z"/></svg>';
      }
      root.appendChild(launcher);

      var initial = escMd((cfg.display_name || 'A').trim().charAt(0).toUpperCase() || 'A');
      var avatar = t.logo_url ? '<img src="' + encodeURI(t.logo_url) + '" alt="">' : initial;
      var panel = document.createElement('div'); panel.className = 'panel';
      panel.innerHTML =
        '<div class="header">' +
          '<div class="av">' + avatar + '</div>' +
          '<div class="meta"><div class="name"></div><div class="status">Online</div></div>' +
          '<button class="x" aria-label="Close">&times;</button>' +
        '</div>' +
        '<div class="messages"></div>' +
        '<div class="chips"></div>' +
        '<div class="composer">' +
          '<input type="text" placeholder="Type your message…">' +
          '<button class="send" aria-label="Send"><svg viewBox="0 0 24 24" fill="currentColor">' +
          '<path d="M3.4 20.4l17.45-7.48a1 1 0 000-1.84L3.4 3.6a1 1 0 00-1.4.92V9.5c0 .5.36.93.86 1l11.14 1.5-11.14 1.5c-.5.07-.86.5-.86 1v4.98a1 1 0 001.4.92z"/>' +
          '</svg></button>' +
        '</div>';
      root.appendChild(panel);

      panel.querySelector('.name').textContent = cfg.display_name || 'Assistant';
      var messagesEl = panel.querySelector('.messages');
      var chipsEl = panel.querySelector('.chips');
      var inputEl = panel.querySelector('.composer input');
      var sendBtn = panel.querySelector('.composer button');
      var greeted = false;
      var history = [];

      function open() {
        panel.classList.add('open');
        if (!greeted) {
          greeted = true;
          addMessage(cfg.greeting || 'Hi! How can I help you today?', 'bot');
          (cfg.suggested_prompts || []).forEach(function (p) {
            var c = document.createElement('button'); c.className = 'chip'; c.textContent = p.label || p.prompt;
            c.addEventListener('click', function () { chipsEl.innerHTML = ''; send(p.prompt); });
            chipsEl.appendChild(c);
          });
        }
        inputEl.focus();
      }
      function close() { panel.classList.remove('open'); }
      launcher.addEventListener('click', function () { panel.classList.contains('open') ? close() : open(); });
      panel.querySelector('.x').addEventListener('click', close);

      function addMessage(text, who, sources) {
        var wrap = document.createElement('div'); wrap.className = 'msg ' + who;
        var body = document.createElement('div');
        if (who === 'bot') { body.innerHTML = mdToHtml(text); } else { body.textContent = text || ''; }
        wrap.appendChild(body);
        if (sources && sources.length) {
          var sd = document.createElement('div'); sd.className = 'sources';
          var h = document.createElement('div'); h.className = 'h'; h.textContent = 'Sources'; sd.appendChild(h);
          sources.forEach(function (s, i) {
            var ok = safeHref(s.source_uri);
            var el = document.createElement(ok ? 'a' : 'span');
            if (ok) { el.href = s.source_uri; el.target = '_blank'; el.rel = 'noopener noreferrer'; }
            el.textContent = '[' + (i + 1) + '] ' + (s.title || s.source_uri || 'Source') + (s.page_number ? ' (p.' + s.page_number + ')' : '');
            sd.appendChild(el);
          });
          wrap.appendChild(sd);
        }
        messagesEl.appendChild(wrap); messagesEl.scrollTop = messagesEl.scrollHeight;
      }
      function addTyping() {
        var t2 = document.createElement('div'); t2.className = 'typing';
        t2.innerHTML = '<span></span><span></span><span></span>';
        messagesEl.appendChild(t2); messagesEl.scrollTop = messagesEl.scrollHeight; return t2;
      }
      function renderSources(wrap, sources) {
        if (!sources || !sources.length) return;
        var sd = document.createElement('div'); sd.className = 'sources';
        var h = document.createElement('div'); h.className = 'h'; h.textContent = 'Sources'; sd.appendChild(h);
        sources.forEach(function (s, i) {
          var ok = safeHref(s.source_uri);
          var el = document.createElement(ok ? 'a' : 'span');
          if (ok) { el.href = s.source_uri; el.target = '_blank'; el.rel = 'noopener noreferrer'; }
          el.textContent = '[' + (i + 1) + '] ' + (s.title || s.source_uri || 'Source') + (s.page_number ? ' (p.' + s.page_number + ')' : '');
          sd.appendChild(el);
        });
        wrap.appendChild(sd); messagesEl.scrollTop = messagesEl.scrollHeight;
      }
      function startBotMessage() {
        var wrap = document.createElement('div'); wrap.className = 'msg bot';
        var body = document.createElement('div'); wrap.appendChild(body);
        messagesEl.appendChild(wrap); messagesEl.scrollTop = messagesEl.scrollHeight;
        return {
          setText: function (md) { body.innerHTML = mdToHtml(md); messagesEl.scrollTop = messagesEl.scrollHeight; },
          setSources: function (sources) { renderSources(wrap, sources); }
        };
      }

      function send(text) {
        text = (text || '').trim(); if (!text) return;
        chipsEl.innerHTML = '';
        var prior = history.slice(-8);
        addMessage(text, 'user'); history.push({ role: 'user', content: text }); inputEl.value = '';
        streamAnswer(text, prior);
      }

      async function streamAnswer(text, prior) {
        var typing = addTyping();
        try {
          var resp = await fetch(apiBase + '/widget/' + encodeURIComponent(botId) + '/chat/stream', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, history: prior })
          });
          if (!resp.ok) {
            typing.remove();
            var ej = await resp.json().catch(function () { return {}; });
            addMessage((ej && ej.detail) || 'Sorry, something went wrong.', 'bot'); return;
          }
          if (!resp.body || !resp.body.getReader) { typing.remove(); return blockingAnswer(text, prior); }
          typing.remove();
          var msg = startBotMessage();
          var reader = resp.body.getReader(), dec = new TextDecoder(), buf = '', answer = '';
          while (true) {
            var r = await reader.read();
            if (r.done) break;
            buf += dec.decode(r.value, { stream: true });
            var idx;
            while ((idx = buf.indexOf('\n\n')) >= 0) {
              var line = buf.slice(0, idx).replace(/^data:\s?/, '').trim(); buf = buf.slice(idx + 2);
              if (!line) continue;
              var evt; try { evt = JSON.parse(line); } catch (e) { continue; }
              if (evt.type === 'token') { answer += evt.value; msg.setText(answer); }
              else if (evt.type === 'error') { answer = evt.value; msg.setText(answer); }
              else if (evt.type === 'done') { msg.setSources(evt.sources); }
            }
          }
          history.push({ role: 'bot', content: answer });
        } catch (e) { typing.remove(); addMessage('Network error. Please try again.', 'bot'); }
      }

      async function blockingAnswer(text, prior) {
        var typing = addTyping();
        try {
          var r = await fetch(apiBase + '/widget/' + encodeURIComponent(botId) + '/chat', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, history: prior })
          });
          var j = await r.json(); typing.remove();
          if (!r.ok) { addMessage((j && j.detail) || 'Sorry, something went wrong.', 'bot'); return; }
          var ans = j.answer || ''; addMessage(ans, 'bot', j.sources); history.push({ role: 'bot', content: ans });
        } catch (e) { typing.remove(); addMessage('Network error. Please try again.', 'bot'); }
      }
      sendBtn.addEventListener('click', function () { send(inputEl.value); });
      inputEl.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); send(inputEl.value); } });
    }
  } catch (e) { /* never throw into the host page */ }
})();
"""


_PREVIEW_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Widget Preview</title>
<style>
  /* Deliberately HOSTILE global CSS. If the widget below is unaffected by any
     of this, Shadow DOM isolation is working. */
  * { color: #d00 !important; font-family: 'Comic Sans MS', cursive !important; }
  a, button, div, input, span { border: 2px dashed magenta !important; }
  body { background: #f3f4f6; margin: 0; padding: 48px; }
  h1 { font-size: 38px; }
</style>
</head>
<body>
  <h1>Acme Corp — host page</h1>
  <p>This page applies hostile global CSS (everything red, Comic Sans, magenta
     dashed borders). The chat widget in the corner should ignore all of it.</p>
  <p>__STATUS__</p>
  __SCRIPT__
</body>
</html>
"""


@router.get("/loader.js", summary="Embeddable widget loader script")
async def widget_loader() -> Response:
    _require_enabled()
    return Response(
        content=WIDGET_LOADER_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/preview", response_class=HTMLResponse, summary="Local preview host page")
async def widget_preview(request: Request, bot_id: str = "") -> HTMLResponse:
    _require_enabled()
    api_base = str(request.base_url).rstrip("/")
    api_base_attr = html.escape(api_base, quote=True)
    bot_id = (bot_id or "").strip()
    if _BOT_ID_RE.match(bot_id):
        # bot_id is validated to a safe charset, so it is attribute-safe; api_base
        # (derived from the Host header) is escaped defensively.
        snippet = (
            f'<script src="{api_base_attr}/widget/loader.js" '
            f'data-bot-id="{bot_id}" data-api-base="{api_base_attr}" async></script>'
        )
        status_line = (
            f"Embedding bot <code>{html.escape(bot_id)}</code>. "
            f"Its allowed_origins must include <code>{html.escape(api_base)}</code>."
        )
    else:
        snippet = ""
        status_line = "Append <code>?bot_id=YOUR_BOT_ID</code> (a real, enabled bot) to the URL to load it."
    page = _PREVIEW_HTML.replace("__SCRIPT__", snippet).replace("__STATUS__", status_line)
    return HTMLResponse(content=page)

