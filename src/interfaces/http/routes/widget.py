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

    // --- Inline markdown -> safe HTML (escape first, re-introduce safe tags). ---
    function mdInline(s) {
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      s = s.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, function (m, a, u) { return '<img src="' + u + '" alt="' + a + '" loading="lazy">'; });
      s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
      s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
      return s;
    }

    // Block markdown -> safe HTML string: headings, hr, blockquote, lists, GFM
    // tables, bare image/video URLs, paragraphs. (Fenced ``` blocks are handled
    // by renderRich before this runs; the fallback here is for streaming.)
    function mdToHtml(src) {
      var lines = escMd(src).split('\n'), html = '', i = 0;
      function block(re, tag) { var out = '<' + tag + '>'; while (i < lines.length && re.test(lines[i])) { out += '<li>' + mdInline(lines[i].replace(re, '$1')) + '</li>'; i++; } return out + '</' + tag + '>'; }
      function table() {
        function cells(r) { return r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(function (c) { return mdInline(c.trim()); }); }
        var head = cells(lines[i]); i += 2;
        var out = '<table><thead><tr><th>' + head.join('</th><th>') + '</th></tr></thead><tbody>';
        while (i < lines.length && lines[i].indexOf('|') >= 0 && lines[i].trim()) { out += '<tr><td>' + cells(lines[i]).join('</td><td>') + '</td></tr>'; i++; }
        return out + '</tbody></table>';
      }
      while (i < lines.length) {
        var ln = lines[i];
        if (/^\s*$/.test(ln)) { i++; continue; }
        if (/^\s*```/.test(ln)) { var code = ''; i++; while (i < lines.length && !/^\s*```/.test(lines[i])) { code += lines[i] + '\n'; i++; } i++; html += '<pre><code>' + code.replace(/\n+$/, '') + '</code></pre>'; continue; }
        var hm = ln.match(/^\s*(#{1,3})\s+(.*)/);
        if (hm) { var n = hm[1].length; html += '<h' + n + '>' + mdInline(hm[2]) + '</h' + n + '>'; i++; continue; }
        if (/^\s*([-*_])\1\1+\s*$/.test(ln)) { html += '<hr>'; i++; continue; }
        if (/^\s*&gt;\s?/.test(ln)) { var q = ''; while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) { q += lines[i].replace(/^\s*&gt;\s?/, '') + ' '; i++; } html += '<blockquote>' + mdInline(q.trim()) + '</blockquote>'; continue; }
        if (/\|/.test(ln) && i + 1 < lines.length && /\|/.test(lines[i + 1]) && /^\s*\|?[-:\s|]+-[-:\s|]*\|?\s*$/.test(lines[i + 1])) { html += table(); continue; }
        if (/^\s*[-*]\s+/.test(ln)) { html += block(/^\s*[-*]\s+(.*)/, 'ul'); continue; }
        if (/^\s*\d+\.\s+/.test(ln)) { html += block(/^\s*\d+\.\s+(.*)/, 'ol'); continue; }
        var u = ln.trim();
        if (/^https?:\/\/\S+\.(png|jpe?g|gif|webp|svg|avif)(\?\S*)?$/i.test(u)) { html += '<img src="' + u + '" alt="" loading="lazy">'; i++; continue; }
        if (/^https?:\/\/\S+\.(mp4|webm|ogg)(\?\S*)?$/i.test(u)) { html += '<video src="' + u + '" controls preload="metadata"></video>'; i++; continue; }
        var para = ln; i++;
        while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^\s*(#{1,3}\s|&gt;|[-*]\s|\d+\.\s|```|([-*_])\2\2)/.test(lines[i])) { para += '\n' + lines[i]; i++; }
        html += '<p>' + mdInline(para).replace(/\n/g, '<br>') + '</p>';
      }
      return html || '<p></p>';
    }

    function ytEmbed(url) {
      var y = (url || '').match(/(?:youtube\.com\/(?:watch\?v=|embed\/)|youtu\.be\/)([\w-]{11})/);
      if (y) return 'https://www.youtube-nocookie.com/embed/' + y[1];
      var v = (url || '').match(/vimeo\.com\/(\d+)/);
      if (v) return 'https://player.vimeo.com/video/' + v[1];
      return '';
    }
    function upgradeMedia(div) {
      Array.prototype.slice.call(div.querySelectorAll('a')).forEach(function (a) {
        var emb = ytEmbed(a.getAttribute('href') || ''); if (!emb) return;
        var wrap = document.createElement('div'); wrap.className = 'embed';
        var f = document.createElement('iframe');
        f.src = emb; f.setAttribute('allowfullscreen', ''); f.setAttribute('loading', 'lazy');
        f.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
        wrap.appendChild(f); a.replaceWith(wrap);
      });
    }
    // Arbitrary HTML/CSS/JS renders inside a SANDBOXED iframe with NO
    // allow-same-origin, so its scripts run in an isolated opaque origin and
    // cannot touch the host page, its cookies, or this widget. Height is synced
    // back over postMessage (scoped to this iframe's contentWindow).
    function makeSandbox(rawHtml) {
      var wrap = document.createElement('div'); wrap.className = 'rich';
      var f = document.createElement('iframe');
      f.setAttribute('sandbox', 'allow-scripts allow-popups allow-popups-to-escape-sandbox');
      f.setAttribute('referrerpolicy', 'no-referrer'); f.setAttribute('loading', 'lazy');
      f.style.cssText = 'width:100%;border:0;height:80px;display:block;background:#fff;';
      var resize = '<scr' + 'ipt>(function(){function p(){try{parent.postMessage({__rh:Math.ceil(document.body.scrollHeight)},"*");}catch(e){}}if(window.ResizeObserver){new ResizeObserver(p).observe(document.body);}window.addEventListener("load",p);[60,250,700,1600].forEach(function(t){setTimeout(p,t);});})();</scr' + 'ipt>';
      f.srcdoc = '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><base target="_blank">'
        + '<style>html,body{margin:0;padding:0;}body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1f2937;padding:2px;}*{box-sizing:border-box;}img,video,canvas,svg,table{max-width:100%;}</style></head><body>'
        + rawHtml + resize + '</body></html>';
      function onMsg(e) { if (e.source === f.contentWindow && e.data && typeof e.data.__rh === 'number') { f.style.height = Math.max(40, Math.min(e.data.__rh + 4, 680)) + 'px'; } }
      window.addEventListener('message', onMsg);
      wrap.appendChild(f); return wrap;
    }
    // Full rich render: split fenced blocks (```html -> sandbox, others -> code),
    // markdown + media for the rest. Used for finished answers.
    function renderRich(container, text) {
      container.innerHTML = '';
      var src = String(text == null ? '' : text), re = /```([\w-]*)\r?\n?([\s\S]*?)```/g, last = 0, m;
      function addText(seg) { if (!seg || !seg.trim()) return; var d = document.createElement('div'); d.innerHTML = mdToHtml(seg); upgradeMedia(d); container.appendChild(d); }
      while ((m = re.exec(src))) {
        addText(src.slice(last, m.index));
        var lang = (m[1] || '').toLowerCase(), code = m[2].replace(/\n+$/, '');
        if (lang === 'html' || lang === 'preview' || lang === 'widget') { container.appendChild(makeSandbox(code)); }
        else { var pre = document.createElement('pre'); var c = document.createElement('code'); c.textContent = code; pre.appendChild(c); container.appendChild(pre); }
        last = re.lastIndex;
      }
      addText(src.slice(last));
      if (!container.childNodes.length) container.innerHTML = '<p></p>';
    }

    function css(t) {
      var fg = t.dark_mode ? '255,255,255' : '17,24,39';   // neutral overlay base
      var bubble = t.dark_mode ? 'rgba(255,255,255,0.07)' : 'rgba(17,24,39,0.04)';
      var side = (t.launcher_position === 'bottom-left') ? 'left' : 'right';
      return ''
        + ':host{all:initial;'
        + '--bot-primary:' + (t.primary_color || '#4f46e5') + ';'
        + '--bot-accent:' + (t.accent_color || t.primary_color || '#4f46e5') + ';'
        + '--bot-surface:' + (t.surface_color || '#ffffff') + ';'
        + '--bot-text:' + (t.text_color || '#1f2937') + ';'
        + '--bot-user:' + (t.user_bubble_color || t.primary_color || '#4f46e5') + ';'
        + '--bot-bubble:' + bubble + ';'
        + '--bot-line:rgba(' + fg + ',0.10);'
        + '--bot-muted:rgba(' + fg + ',0.55);'
        + '--bot-radius:' + (t.corner_radius_px != null ? t.corner_radius_px : 20) + 'px;'
        + '--bot-font:' + (t.font_family || '-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif') + ';'
        + 'font-family:var(--bot-font);line-height:1.5;}'
        + '*{box-sizing:border-box;font-family:var(--bot-font);-webkit-font-smoothing:antialiased;}'
        // launcher
        + '.launcher{position:fixed;bottom:24px;' + side + ':24px;width:62px;height:62px;border-radius:50%;'
        + 'background:var(--bot-primary);color:#fff;border:none;cursor:pointer;'
        + 'box-shadow:0 8px 24px -4px rgba(0,0,0,.30),0 3px 8px -2px rgba(0,0,0,.18);'
        + 'display:flex;align-items:center;justify-content:center;z-index:2147483000;'
        + 'transition:transform .28s cubic-bezier(.34,1.4,.5,1),box-shadow .25s;animation:lin .45s cubic-bezier(.34,1.5,.5,1) both;}'
        + '.launcher:hover{transform:scale(1.07);box-shadow:0 12px 30px -4px rgba(0,0,0,.36);}'
        + '.launcher:active{transform:scale(.95);}'
        + '.launcher .ic{position:absolute;display:flex;transition:opacity .22s,transform .28s cubic-bezier(.34,1.4,.5,1);}'
        + '.launcher .ic svg{width:27px;height:27px;}'
        + '.launcher .ic-c{opacity:0;transform:rotate(-90deg) scale(.5);}'
        + '.launcher.open .ic-o{opacity:0;transform:rotate(90deg) scale(.5);}'
        + '.launcher.open .ic-c{opacity:1;transform:rotate(0) scale(1);}'
        + '.launcher>img{width:40px;height:40px;border-radius:50%;object-fit:cover;}'
        + '@keyframes lin{from{opacity:0;transform:scale(0) translateY(8px);}to{opacity:1;transform:scale(1);}}'
        // teaser nudge
        + '.teaser{position:fixed;bottom:100px;' + side + ':22px;max-width:230px;background:var(--bot-surface);color:var(--bot-text);'
        + 'border:1px solid var(--bot-line);border-radius:16px;border-bottom-' + side + '-radius:5px;padding:13px 30px 13px 15px;'
        + 'font-size:13.5px;line-height:1.45;box-shadow:0 14px 34px -8px rgba(0,0,0,.22);z-index:2147482999;cursor:pointer;'
        + 'opacity:0;transform:translateY(10px) scale(.96);transform-origin:bottom ' + side + ';pointer-events:none;'
        + 'transition:opacity .3s,transform .3s cubic-bezier(.34,1.4,.5,1);}'
        + '.teaser.show{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}'
        + '.teaser .tx{position:absolute;top:6px;right:7px;background:transparent;border:none;color:var(--bot-text);opacity:.35;cursor:pointer;font-size:16px;line-height:1;padding:2px;}'
        + '.teaser .tx:hover{opacity:.7;}'
        // panel
        + '.panel{position:fixed;bottom:98px;' + side + ':24px;width:400px;max-width:calc(100vw - 32px);height:640px;'
        + 'max-height:calc(100vh - 134px);background:var(--bot-surface);color:var(--bot-text);'
        + 'border-radius:var(--bot-radius);box-shadow:0 28px 72px -18px rgba(0,0,0,.34),0 8px 24px -12px rgba(0,0,0,.16);'
        + 'display:flex;flex-direction:column;overflow:hidden;z-index:2147483000;'
        + 'opacity:0;transform:translateY(22px) scale(.95);transform-origin:bottom ' + side + ';pointer-events:none;'
        + 'transition:opacity .26s cubic-bezier(.22,1,.36,1),transform .36s cubic-bezier(.34,1.28,.5,1);}'
        + '.panel.open{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}'
        // header
        + '.header{position:relative;background:var(--bot-primary);'
        + 'background-image:linear-gradient(135deg,rgba(255,255,255,.14),rgba(0,0,0,.10));'
        + 'color:#fff;padding:17px 16px 17px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0;}'
        + '.header .av{position:relative;width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;'
        + 'background:rgba(255,255,255,.22);color:#fff;font-weight:600;font-size:17px;overflow:hidden;flex-shrink:0;}'
        + '.header .av img{width:100%;height:100%;object-fit:cover;}'
        + '.header .av::after{content:"";position:absolute;bottom:-1px;right:-1px;width:11px;height:11px;border-radius:50%;background:#34d399;border:2.5px solid var(--bot-primary);}'
        + '.header .meta{flex:1;min-width:0;}'
        + '.header .name{font-weight:600;font-size:16px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}'
        + '.header .status{font-size:12.5px;opacity:.92;margin-top:2px;}'
        + '.header .ib{background:transparent;border:none;color:#fff;cursor:pointer;opacity:.85;padding:7px;border-radius:9px;display:flex;transition:opacity .15s,background .15s;}'
        + '.header .ib:hover{opacity:1;background:rgba(255,255,255,.16);}'
        + '.header .ib svg{width:19px;height:19px;}'
        // messages
        + '.messages{flex:1;overflow-y:auto;padding:18px 16px 6px;display:flex;flex-direction:column;gap:14px;scroll-behavior:smooth;}'
        + '.messages::-webkit-scrollbar{width:6px;}'
        + '.messages::-webkit-scrollbar-thumb{background:rgba(' + fg + ',0.18);border-radius:3px;}'
        + '.messages::-webkit-scrollbar-track{background:transparent;}'
        // welcome hero
        + '.welcome{padding:6px 4px 2px;animation:msgIn .35s cubic-bezier(.22,1,.36,1);}'
        + '.welcome .wav{width:54px;height:54px;border-radius:50%;background:var(--bot-primary);color:#fff;display:flex;align-items:center;'
        + 'justify-content:center;font-weight:600;font-size:23px;overflow:hidden;margin-bottom:14px;box-shadow:0 6px 16px -4px rgba(0,0,0,.25);}'
        + '.welcome .wav img{width:100%;height:100%;object-fit:cover;}'
        + '.welcome .wt{font-size:20px;font-weight:600;line-height:1.3;letter-spacing:-.01em;}'
        + '.welcome .ws{font-size:14px;color:var(--bot-muted);line-height:1.5;margin-top:5px;}'
        // message rows
        + '.row{display:flex;gap:8px;align-items:flex-end;max-width:90%;animation:msgIn .3s cubic-bezier(.22,1,.36,1);}'
        + '.row.user{align-self:flex-end;flex-direction:row-reverse;}'
        + '.row.bot{align-self:flex-start;}'
        + '.row .ava{width:28px;height:28px;border-radius:50%;flex-shrink:0;background:var(--bot-primary);color:#fff;'
        + 'display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;overflow:hidden;}'
        + '.row .ava img{width:100%;height:100%;object-fit:cover;}'
        + '@keyframes msgIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}'
        + '.bubble{padding:11px 15px;border-radius:18px;font-size:14.5px;line-height:1.55;word-wrap:break-word;}'
        + '.row.user .bubble{background:var(--bot-user);color:#fff;border-bottom-right-radius:6px;white-space:pre-wrap;}'
        + '.row.bot .bubble{background:var(--bot-bubble);color:var(--bot-text);border:1px solid var(--bot-line);border-bottom-left-radius:6px;}'
        + '.bubble p{margin:0 0 8px;}.bubble p:last-child{margin-bottom:0;}'
        + '.bubble ul,.bubble ol{margin:6px 0;padding-left:20px;}.bubble li{margin:3px 0;}'
        + '.bubble a{color:var(--bot-accent);font-weight:500;}'
        + '.bubble code{background:rgba(' + fg + ',0.07);padding:2px 5px;border-radius:5px;font-size:.9em;font-family:ui-monospace,Consolas,monospace;}'
        + '.bubble pre{background:rgba(' + fg + ',0.06);padding:10px;border-radius:8px;overflow:auto;margin:6px 0;}'
        + '.bubble pre code{background:none;padding:0;}'
        + '.bubble h1,.bubble h2,.bubble h3{margin:10px 0 6px;line-height:1.3;font-weight:600;}'
        + '.bubble h1:first-child,.bubble h2:first-child,.bubble h3:first-child{margin-top:0;}'
        + '.bubble h1{font-size:1.25em;}.bubble h2{font-size:1.14em;}.bubble h3{font-size:1.05em;}'
        + '.bubble hr{border:none;border-top:1px solid var(--bot-line);margin:10px 0;}'
        + '.bubble blockquote{margin:8px 0;padding:3px 0 3px 12px;border-left:3px solid var(--bot-line);color:var(--bot-muted);}'
        + '.bubble del{opacity:.65;}'
        + '.bubble img{max-width:100%;border-radius:10px;margin:6px 0;display:block;}'
        + '.bubble video{max-width:100%;border-radius:10px;margin:6px 0;display:block;background:#000;}'
        + '.bubble table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px;}'
        + '.bubble th,.bubble td{border:1px solid var(--bot-line);padding:6px 9px;text-align:left;}'
        + '.bubble th{background:rgba(' + fg + ',0.04);font-weight:600;}'
        + '.bubble .embed{position:relative;width:100%;padding-top:56.25%;margin:8px 0;border-radius:10px;overflow:hidden;background:#000;}'
        + '.bubble .embed iframe{position:absolute;inset:0;width:100%;height:100%;border:0;}'
        + '.bubble .rich{margin:8px 0;border:1px solid var(--bot-line);border-radius:10px;overflow:hidden;}'
        // sources
        + '.sources{margin-top:10px;padding-top:9px;border-top:1px solid var(--bot-line);display:flex;flex-direction:column;gap:5px;}'
        + '.sources .h{font-size:10px;text-transform:uppercase;letter-spacing:.06em;font-weight:600;opacity:.5;}'
        + '.sources a{font-size:12.5px;color:var(--bot-accent);text-decoration:none;line-height:1.35;}'
        + '.sources a:hover{text-decoration:underline;}'
        + '.sources span{font-size:12.5px;color:var(--bot-muted);line-height:1.35;}'
        // suggested-question cards
        + '.chips{display:flex;flex-direction:column;gap:8px;padding:2px 16px 14px;}'
        + '.chip{display:flex;align-items:center;justify-content:space-between;gap:8px;text-align:left;'
        + 'border:1px solid var(--bot-line);background:var(--bot-surface);color:var(--bot-text);border-radius:14px;'
        + 'padding:12px 14px;font-size:13.5px;font-family:inherit;cursor:pointer;'
        + 'transition:border-color .15s,background .15s,transform .1s;animation:msgIn .3s cubic-bezier(.22,1,.36,1);}'
        + '.chip:hover{border-color:var(--bot-primary);background:rgba(' + fg + ',0.02);}'
        + '.chip:active{transform:scale(.99);}'
        + '.chip .ar{color:var(--bot-primary);opacity:.55;flex-shrink:0;display:flex;}'
        + '.chip .ar svg{width:15px;height:15px;}'
        // composer
        + '.composer{padding:10px 14px 12px;border-top:1px solid var(--bot-line);flex-shrink:0;}'
        + '.inwrap{display:flex;align-items:flex-end;gap:6px;background:rgba(' + fg + ',0.04);border:1px solid var(--bot-line);'
        + 'border-radius:24px;padding:5px 5px 5px 16px;transition:border-color .15s,box-shadow .15s;}'
        + '.inwrap:focus-within{border-color:var(--bot-primary);box-shadow:0 0 0 3px rgba(' + fg + ',0.04);}'
        + '.composer textarea{flex:1;border:none;background:transparent;resize:none;outline:none;font-size:14.5px;line-height:1.45;'
        + 'color:var(--bot-text);max-height:104px;padding:7px 0;font-family:inherit;}'
        + '.composer textarea::placeholder{color:rgba(' + fg + ',0.42);}'
        + '.send{width:38px;height:38px;flex-shrink:0;border-radius:50%;background:var(--bot-primary);color:#fff;border:none;'
        + 'cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform .15s,opacity .15s;}'
        + '.send:disabled{opacity:.35;cursor:default;}'
        + '.send:not(:disabled):hover{transform:scale(1.08);}'
        + '.send:not(:disabled):active{transform:scale(.94);}'
        + '.send svg{width:17px;height:17px;}'
        + '.pwr{text-align:center;font-size:11px;color:rgba(' + fg + ',0.42);padding:9px 0 1px;}'
        + '.pwr b{font-weight:600;color:rgba(' + fg + ',0.55);}'
        // typing
        + '.typing{display:inline-flex;gap:5px;padding:14px 16px;background:var(--bot-bubble);border:1px solid var(--bot-line);'
        + 'border-radius:18px;border-bottom-left-radius:6px;}'
        + '.typing span{width:7px;height:7px;border-radius:50%;background:var(--bot-text);opacity:.35;animation:bob 1.3s infinite;}'
        + '.typing span:nth-child(2){animation-delay:.18s;}.typing span:nth-child(3){animation-delay:.36s;}'
        + '@keyframes bob{0%,60%,100%{transform:translateY(0);opacity:.3;}30%{transform:translateY(-5px);opacity:.7;}}'
        + '@media (max-width:480px){.panel{width:100vw;height:100vh;height:100dvh;max-height:100vh;max-height:100dvh;bottom:0;right:0;left:0;border-radius:0;}'
        + '.launcher{bottom:18px;' + side + ':18px;}.teaser{display:none;}}';
    }

    function prefersDark() { try { return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches); } catch (e) { return false; } }
    function detectBrand() {
      try {
        var m = document.querySelector('meta[name="theme-color"]');
        if (m && m.content) { var c = m.content.trim(); if (/^#?[0-9a-fA-F]{3,8}$/.test(c)) return c.charAt(0) === '#' ? c : '#' + c; }
      } catch (e) {}
      return '';
    }
    // Make the widget blend into the host: adapt to the visitor's dark-mode
    // preference (derive a dark palette while keeping the brand color), and
    // optionally match the site's theme-color as the primary.
    function resolveTheme(theme) {
      var t = {}; for (var k in theme) t[k] = theme[k];
      if (!t.dark_mode && t.auto_dark !== false && prefersDark()) {
        t.dark_mode = true; t.surface_color = '#0f172a'; t.text_color = '#e5e7eb';
      }
      if (t.auto_brand) {
        var b = detectBrand();
        if (b) { t.primary_color = b; if (!t.accent_color) t.accent_color = b; if (!t.user_bubble_color) t.user_bubble_color = b; }
      }
      return t;
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
      var st = document.createElement('style'); root.appendChild(st);
      function applyStyle() { st.textContent = css(resolveTheme(t)); }
      applyStyle();
      try { var mq = window.matchMedia('(prefers-color-scheme: dark)'); mq.addEventListener ? mq.addEventListener('change', applyStyle) : mq.addListener(applyStyle); } catch (e) {}

      var dn = cfg.display_name || 'Assistant';
      var avatarInner = t.logo_url
        ? '<img src="' + encodeURI(t.logo_url) + '" alt="">'
        : escMd((dn).trim().charAt(0).toUpperCase() || 'A');

      var launcher = document.createElement('button');
      launcher.className = 'launcher'; launcher.setAttribute('aria-label', 'Open chat');
      if (t.launcher_icon_url) {
        launcher.innerHTML = '<img src="' + encodeURI(t.launcher_icon_url) + '" alt="">';
      } else {
        launcher.innerHTML =
          '<span class="ic ic-o"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C7 3 3 6.6 3 11c0 2 .9 3.8 2.4 5.2L4.5 20l4-1.3c1.1.4 2.3.6 3.5.6 5 0 9-3.6 9-8s-4-8.3-9-8.3z"/></svg></span>' +
          '<span class="ic ic-c"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></span>';
      }
      root.appendChild(launcher);

      var teaser = document.createElement('div'); teaser.className = 'teaser';
      teaser.innerHTML = '<button class="tx" aria-label="Dismiss">&times;</button><div class="tt"></div>';
      teaser.querySelector('.tt').textContent = 'Hi there 👋 Have a question? I’m here to help.';
      root.appendChild(teaser);

      var panel = document.createElement('div'); panel.className = 'panel';
      panel.innerHTML =
        '<div class="header">' +
          '<div class="av">' + avatarInner + '</div>' +
          '<div class="meta"><div class="name"></div><div class="status">Typically replies instantly</div></div>' +
          '<button class="ib close" aria-label="Minimize"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>' +
        '</div>' +
        '<div class="messages"></div>' +
        '<div class="composer">' +
          '<div class="inwrap">' +
            '<textarea rows="1" placeholder="Type your message…"></textarea>' +
            '<button class="send" aria-label="Send" disabled><svg viewBox="0 0 24 24" fill="currentColor"><path d="M3.4 20.4l17.45-7.48a1 1 0 000-1.84L3.4 3.6a1 1 0 00-1.4.92V9.5c0 .5.36.93.86 1l11.14 1.5-11.14 1.5c-.5.07-.86.5-.86 1v4.98a1 1 0 001.4.92z"/></svg></button>' +
          '</div>' +
          '<div class="pwr">Powered by <b>Smart Routing</b></div>' +
        '</div>';
      root.appendChild(panel);

      panel.querySelector('.name').textContent = dn;
      var messagesEl = panel.querySelector('.messages');
      var inputEl = panel.querySelector('textarea');
      var sendBtn = panel.querySelector('.send');
      var greeted = false, busy = false, history = [], chipsEl = null;

      function scrollDown() { messagesEl.scrollTop = messagesEl.scrollHeight; }

      function showWelcome() {
        var w = document.createElement('div'); w.className = 'welcome';
        w.innerHTML = '<div class="wav">' + avatarInner + '</div><div class="wt"></div><div class="ws"></div>';
        w.querySelector('.wt').textContent = cfg.greeting || ('Hi! I’m ' + dn);
        w.querySelector('.ws').textContent = 'Ask me anything — pick a question below or type your own.';
        messagesEl.appendChild(w);
        var prompts = cfg.suggested_prompts || [];
        if (prompts.length) {
          chipsEl = document.createElement('div'); chipsEl.className = 'chips';
          prompts.forEach(function (p) {
            var c = document.createElement('button'); c.className = 'chip'; c.type = 'button';
            var lab = document.createElement('span'); lab.textContent = p.label || p.prompt; c.appendChild(lab);
            var ar = document.createElement('span'); ar.className = 'ar';
            ar.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
            c.appendChild(ar);
            c.addEventListener('click', function () { send(p.prompt); });
            chipsEl.appendChild(c);
          });
          messagesEl.appendChild(chipsEl);
        }
        scrollDown();
      }
      function removeChips() { if (chipsEl) { chipsEl.remove(); chipsEl = null; } }

      var teaserDismissed = false;
      function dismissTeaser() { teaserDismissed = true; teaser.classList.remove('show'); }
      teaser.addEventListener('click', function (e) {
        if (e.target.closest('.tx')) { dismissTeaser(); return; }
        open();
      });
      setTimeout(function () { if (!teaserDismissed && !panel.classList.contains('open')) teaser.classList.add('show'); }, 2400);

      function open() {
        dismissTeaser();
        panel.classList.add('open'); launcher.classList.add('open');
        launcher.setAttribute('aria-label', 'Close chat');
        if (!greeted) { greeted = true; showWelcome(); }
        setTimeout(function () { inputEl.focus(); }, 120);
      }
      function close() {
        panel.classList.remove('open'); launcher.classList.remove('open');
        launcher.setAttribute('aria-label', 'Open chat');
      }
      launcher.addEventListener('click', function () { panel.classList.contains('open') ? close() : open(); });
      panel.querySelector('.header .close').addEventListener('click', close);

      function botAva() { var a = document.createElement('div'); a.className = 'ava'; a.innerHTML = avatarInner; return a; }
      function addRow(who) {
        var row = document.createElement('div'); row.className = 'row ' + who;
        if (who === 'bot') row.appendChild(botAva());
        var bubble = document.createElement('div'); bubble.className = 'bubble'; row.appendChild(bubble);
        messagesEl.appendChild(row); scrollDown();
        return bubble;
      }
      function renderSources(bubble, sources) {
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
        bubble.appendChild(sd); scrollDown();
      }
      function addMessage(text, who, sources) {
        var bubble = addRow(who);
        if (who === 'bot') renderRich(bubble, text); else bubble.textContent = text || '';
        if (sources) renderSources(bubble, sources);
        scrollDown();
      }
      function addTyping() {
        var row = document.createElement('div'); row.className = 'row bot';
        row.appendChild(botAva());
        var tp = document.createElement('div'); tp.className = 'typing';
        tp.innerHTML = '<span></span><span></span><span></span>'; row.appendChild(tp);
        messagesEl.appendChild(row); scrollDown(); return row;
      }
      function startBotMessage() {
        var bubble = addRow('bot');
        return {
          setText: function (md) { bubble.innerHTML = mdToHtml(md); scrollDown(); },
          finalize: function (md) { renderRich(bubble, md); scrollDown(); },
          setSources: function (sources) { renderSources(bubble, sources); }
        };
      }

      function setBusy(b) { busy = b; inputEl.disabled = b; sendBtn.disabled = b || !inputEl.value.trim(); }

      function send(text) {
        text = (text || '').trim(); if (!text || busy) return;
        removeChips();
        var prior = history.slice(-8);
        addMessage(text, 'user'); history.push({ role: 'user', content: text });
        inputEl.value = ''; autogrow(); setBusy(true);
        streamAnswer(text, prior).then(function () { setBusy(false); inputEl.focus(); });
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
          var reader = resp.body.getReader(), dec = new TextDecoder(), buf = '', answer = '', sources = null;
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
              else if (evt.type === 'done') { sources = evt.sources; }
            }
          }
          msg.finalize(answer);
          if (sources) msg.setSources(sources);
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
      function autogrow() {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 104) + 'px';
        if (!busy) sendBtn.disabled = !inputEl.value.trim();
      }
      inputEl.addEventListener('input', autogrow);
      inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(inputEl.value); }
      });
      sendBtn.addEventListener('click', function () { send(inputEl.value); });
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

