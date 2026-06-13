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

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
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

    function safeHref(u) { return typeof u === 'string' && /^(https?:\/\/|\/)/i.test(u); }

    function css(t) {
      var botBubble = t.dark_mode ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.05)';
      var pos = (t.launcher_position === 'bottom-left') ? 'left: 20px;' : 'right: 20px;';
      var panelPos = (t.launcher_position === 'bottom-left') ? 'left: 20px;' : 'right: 20px;';
      return ''
        + ':host{all:initial;'
        + '--bot-primary:' + (t.primary_color || '#2d6a4f') + ';'
        + '--bot-accent:' + (t.accent_color || '#8a5a2b') + ';'
        + '--bot-surface:' + (t.surface_color || '#fffbf4') + ';'
        + '--bot-text:' + (t.text_color || '#1d2b2a') + ';'
        + '--bot-user:' + (t.user_bubble_color || t.primary_color || '#2d6a4f') + ';'
        + '--bot-bot-bubble:' + botBubble + ';'
        + '--bot-radius:' + (t.corner_radius_px != null ? t.corner_radius_px : 16) + 'px;'
        + '--bot-font:' + (t.font_family || 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif') + ';'
        + 'font-family:var(--bot-font);}'
        + '*{box-sizing:border-box;font-family:var(--bot-font);}'
        + '.launcher{position:fixed;bottom:20px;' + pos + 'width:60px;height:60px;border-radius:50%;'
        + 'background:var(--bot-primary);color:#fff;border:none;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);'
        + 'display:flex;align-items:center;justify-content:center;z-index:2147483000;transition:transform .15s ease;}'
        + '.launcher:hover{transform:scale(1.06);}'
        + '.launcher svg{width:28px;height:28px;}'
        + '.launcher img{width:34px;height:34px;border-radius:50%;object-fit:cover;}'
        + '.panel{position:fixed;bottom:92px;' + panelPos + 'width:380px;max-width:calc(100vw - 32px);height:560px;'
        + 'max-height:calc(100vh - 120px);background:var(--bot-surface);color:var(--bot-text);'
        + 'border-radius:var(--bot-radius);box-shadow:0 16px 48px rgba(0,0,0,.28);display:flex;flex-direction:column;'
        + 'overflow:hidden;z-index:2147483000;opacity:0;transform:translateY(12px);pointer-events:none;'
        + 'transition:opacity .18s ease,transform .18s ease;}'
        + '.panel.open{opacity:1;transform:translateY(0);pointer-events:auto;}'
        + '.header{background:var(--bot-primary);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px;}'
        + '.header img{width:28px;height:28px;border-radius:50%;object-fit:cover;background:#fff;}'
        + '.header .name{font-weight:600;font-size:15px;flex:1;}'
        + '.header .x{background:transparent;border:none;color:#fff;cursor:pointer;font-size:20px;line-height:1;opacity:.85;}'
        + '.header .x:hover{opacity:1;}'
        + '.messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;}'
        + '.msg{max-width:86%;padding:10px 13px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word;}'
        + '.msg.user{align-self:flex-end;background:var(--bot-user);color:#fff;border-bottom-right-radius:4px;}'
        + '.msg.bot{align-self:flex-start;background:var(--bot-bot-bubble);color:var(--bot-text);border-bottom-left-radius:4px;}'
        + '.sources{margin-top:8px;padding-top:8px;border-top:1px solid rgba(0,0,0,.12);display:flex;flex-direction:column;gap:4px;}'
        + '.sources .h{font-size:11px;text-transform:uppercase;letter-spacing:.04em;opacity:.6;}'
        + '.sources a,.sources span{font-size:12px;color:var(--bot-accent);text-decoration:none;}'
        + '.sources a:hover{text-decoration:underline;}'
        + '.chips{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 12px;}'
        + '.chip{border:1px solid var(--bot-accent);color:var(--bot-accent);background:transparent;border-radius:16px;'
        + 'padding:7px 12px;font-size:13px;cursor:pointer;}'
        + '.chip:hover{background:var(--bot-accent);color:#fff;}'
        + '.composer{display:flex;gap:8px;padding:12px;border-top:1px solid rgba(0,0,0,.12);}'
        + '.composer input{flex:1;border:1px solid rgba(0,0,0,.18);border-radius:10px;padding:10px 12px;font-size:14px;'
        + 'background:#fff;color:#1d2b2a;outline:none;}'
        + '.composer button{background:var(--bot-primary);color:#fff;border:none;border-radius:10px;padding:0 14px;cursor:pointer;font-size:14px;}'
        + '.typing{display:flex;gap:4px;align-self:flex-start;padding:12px 14px;}'
        + '.typing span{width:7px;height:7px;border-radius:50%;background:var(--bot-text);opacity:.4;animation:bob 1s infinite;}'
        + '.typing span:nth-child(2){animation-delay:.15s;}.typing span:nth-child(3){animation-delay:.3s;}'
        + '@keyframes bob{0%,60%,100%{transform:translateY(0);opacity:.35;}30%{transform:translateY(-5px);opacity:.8;}}'
        + '@media (max-width:480px){.panel{width:100vw;height:100vh;max-height:100vh;bottom:0;right:0;left:0;border-radius:0;}'
        + '.launcher{bottom:16px;}}';
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

      var panel = document.createElement('div'); panel.className = 'panel';
      panel.innerHTML =
        '<div class="header">' +
        (t.logo_url ? '<img src="' + encodeURI(t.logo_url) + '" alt="">' : '') +
        '<span class="name"></span><button class="x" aria-label="Close">&times;</button></div>' +
        '<div class="messages"></div>' +
        '<div class="chips"></div>' +
        '<div class="composer"><input type="text" placeholder="Type your message…"><button>Send</button></div>';
      root.appendChild(panel);

      panel.querySelector('.name').textContent = cfg.display_name || 'Assistant';
      var messagesEl = panel.querySelector('.messages');
      var chipsEl = panel.querySelector('.chips');
      var inputEl = panel.querySelector('.composer input');
      var sendBtn = panel.querySelector('.composer button');
      var greeted = false;

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
        var body = document.createElement('div'); body.textContent = text || ''; wrap.appendChild(body);
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
      function send(text) {
        text = (text || '').trim(); if (!text) return;
        chipsEl.innerHTML = '';
        addMessage(text, 'user'); inputEl.value = '';
        var typing = addTyping();
        fetch(apiBase + '/widget/' + encodeURIComponent(botId) + '/chat', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text })
        }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            typing.remove();
            if (!res.ok) { addMessage((res.j && res.j.detail) || 'Sorry, something went wrong.', 'bot'); return; }
            addMessage(res.j.answer || '', 'bot', res.j.sources);
          }).catch(function () { typing.remove(); addMessage('Network error. Please try again.', 'bot'); });
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
    if bot_id:
        snippet = (
            f'<script src="{api_base}/widget/loader.js" '
            f'data-bot-id="{bot_id}" data-api-base="{api_base}" async></script>'
        )
        status_line = f"Embedding bot <code>{bot_id}</code>. Its allowed_origins must include <code>{api_base}</code>."
    else:
        snippet = ""
        status_line = "Append <code>?bot_id=YOUR_BOT_ID</code> to the URL to load a specific bot."
    html = _PREVIEW_HTML.replace("__SCRIPT__", snippet).replace("__STATUS__", status_line)
    return HTMLResponse(content=html)

