"""
AutoPilot onboarding orchestrator.

Paste a website URL and AutoPilot produces a **review-ready bot draft**: it
headless-renders the site (so JS/SPA pages work), screenshots it, extracts a
brand palette into a coherent theme, and uses the platform's own Smart Router →
LLM to write the bot's name, greeting, subtitle and suggested prompts from the
page's real content. The draft is returned to the admin console, which fills the
form and floats the live-preview bot over a screenshot of the actual site — so a
prospect immediately sees how it would look on *their* website.

Nothing is created here: AutoPilot only *drafts*. The admin reviews/tweaks and
hits Create (the existing flow), which keeps a human in the loop for demos.

Design notes:
* The router/gateway imports are lazy so this module stays torch-free to import
  (the unit tests mock the LLM and never load a model).
* ``guard_public_url`` is an SSRF backstop: by default it refuses URLs that
  resolve to private/loopback ranges (admin surface is network-restricted, but
  defence-in-depth is cheap).
"""

from __future__ import annotations

import ipaddress
import json
import re
import secrets
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from src.layer3_domain.site_renderer import (
    RenderedSite,
    RenderError,
    RendererUnavailableError,
    render_site,
)
from src.layer4_platform import theme_extractor
from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Repo root: src/layer4_platform/autopilot.py -> parents[2]. Mirrors bot_registry.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHOT_DIR = _REPO_ROOT / ".runtime" / "widget_screenshots"


class AutopilotError(RuntimeError):
    """A user-facing AutoPilot failure (bad URL, blocked host, render failure)."""


# ---------------------------------------------------------------------------
# URL hygiene / SSRF guard
# ---------------------------------------------------------------------------


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise AutopilotError("Please provide a website URL.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise AutopilotError(f"'{raw}' is not a valid http(s) URL.")
    return raw


def guard_public_url(url: str) -> None:
    """Refuse URLs that resolve to private/loopback/link-local ranges."""
    if settings.WIDGET_AUTOPILOT_ALLOW_PRIVATE_HOSTS:
        return
    host = urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as exc:
        raise AutopilotError(f"Could not resolve host '{host}'.") from exc
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise AutopilotError(
                f"Refusing to fetch a private/loopback address ({ip_str}). "
                "Set WIDGET_AUTOPILOT_ALLOW_PRIVATE_HOSTS=true to allow local URLs."
            )


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


def _registrable_slug(origin: str) -> str:
    host = (urlsplit(origin).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    label = host.split(".")[0] if host else "site"
    slug = re.sub(r"[^a-z0-9-]", "-", label).strip("-") or "site"
    return slug


def _brand_name(rendered: RenderedSite, slug: str) -> str:
    name = (rendered.site_name or "").strip()
    if not name and rendered.title:
        # Titles are often "Home | Acme" or "Acme - tagline"; take the first segment.
        name = re.split(r"\s*[|\-–—:·]\s*", rendered.title.strip())[0].strip()
    if not name:
        name = slug.replace("-", " ").title()
    return name[:40]


# ---------------------------------------------------------------------------
# Screenshot storage
# ---------------------------------------------------------------------------


def _store_screenshot(png: bytes) -> str:
    """Downscale + persist the screenshot as JPEG; return its id."""
    import io

    from PIL import Image

    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    shot_id = secrets.token_urlsafe(10).replace("-", "").replace("_", "")
    img = Image.open(io.BytesIO(png)).convert("RGB")
    target_w = max(320, int(settings.WIDGET_AUTOPILOT_SCREENSHOT_WIDTH))
    if img.width > target_w:
        ratio = target_w / float(img.width)
        img = img.resize((target_w, int(img.height * ratio)), Image.LANCZOS)
    path = _SHOT_DIR / f"{shot_id}.jpg"
    img.save(path, format="JPEG", quality=82, optimize=True)
    return shot_id


def screenshot_path(shot_id: str) -> Optional[Path]:
    safe = re.sub(r"[^A-Za-z0-9]", "", shot_id or "")
    if not safe:
        return None
    path = _SHOT_DIR / f"{safe}.jpg"
    return path if path.exists() else None


# ---------------------------------------------------------------------------
# Logo validation
# ---------------------------------------------------------------------------


async def _valid_image_url(url: str) -> bool:
    if not url:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Range": "bytes=0-2048"})
        if resp.status_code >= 400:
            return False
        ctype = resp.headers.get("content-type", "").lower()
        return ctype.startswith("image/")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# AI autofill (Smart Router -> LLM), with a deterministic fallback
# ---------------------------------------------------------------------------

_AUTOFILL_SYSTEM = (
    "You write concise, friendly configuration for a website's customer-support "
    "chatbot. You are given text scraped from a company's homepage. Respond with "
    "ONLY a single JSON object, no prose, no markdown fences."
)


def _autofill_prompt(name: str, url: str, page_text: str) -> str:
    return (
        f"Company: {name}\nWebsite: {url}\n\n"
        "Homepage text (may be noisy):\n\"\"\"\n"
        f"{page_text}\n\"\"\"\n\n"
        "Produce JSON with exactly these keys:\n"
        '{\n'
        '  "display_name": "the assistant\'s name, <= 30 chars, e.g. \\"Acme Assistant\\"",\n'
        '  "greeting": "one warm opening sentence shown when the chat opens",\n'
        '  "subtitle": "a 2-4 word header status line, e.g. \\"Ask us anything\\"",\n'
        '  "suggested_prompts": [\n'
        '    {"label": "<= 22 char chip text", "prompt": "the full question a visitor would actually ask"}\n'
        "  ]\n"
        "}\n"
        "Give 4 suggested_prompts grounded in what this company actually does. "
        "Do not invent facts; keep questions general if unsure."
    )


def _coerce_prompts(value: object) -> list[dict]:
    out: list[dict] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("prompt") or "").strip()
                prompt = str(item.get("prompt") or item.get("label") or "").strip()
            else:
                label = prompt = str(item).strip()
            if label and prompt:
                out.append({"label": label[:24], "prompt": prompt[:200]})
    return out[:5]


def _parse_autofill_json(content: str) -> Optional[dict]:
    if not content:
        return None
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(content[start : end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    prompts = _coerce_prompts(data.get("suggested_prompts"))
    result = {
        "display_name": str(data.get("display_name") or "").strip()[:40],
        "greeting": str(data.get("greeting") or "").strip()[:240],
        "subtitle": str(data.get("subtitle") or "").strip()[:60],
        "suggested_prompts": prompts,
    }
    return result if result["display_name"] and result["greeting"] else None


def _heuristic_copy(name: str) -> dict:
    return {
        "display_name": (f"{name} Assistant")[:40],
        "greeting": f"Hi! 👋 I'm the {name} assistant. How can I help you today?",
        "subtitle": "Ask me anything",
        "suggested_prompts": [
            {"label": "What you do", "prompt": f"What does {name} do?"},
            {"label": "Products", "prompt": "What products or services do you offer?"},
            {"label": "Pricing", "prompt": "What are your pricing plans?"},
            {"label": "Contact", "prompt": "How can I get in touch with your team?"},
        ],
        "_model": None,
    }


async def _ai_autofill(name: str, url: str, page_text: str) -> dict:
    """Route to a model and have it write the bot copy. Falls back to the
    deterministic template on any failure (no model/key, parse error, etc.)."""
    fallback = _heuristic_copy(name)
    text = (page_text or "").strip()
    if len(text) < 40:
        return fallback  # nothing useful to summarize
    try:
        from src.layer0_model_infra.gateway import LLMRequest, get_gateway
        from src.layer0_model_infra.router import get_router

        router = get_router()
        decision = router.route(
            query=f"Write chatbot onboarding copy for {name} ({url}).",
            user_tier="standard",
            budget_remaining=1.0,
        )
        model_id = decision.selected_model.model_id
        model_display = decision.selected_model.display_name

        resp = await get_gateway().complete(
            LLMRequest(
                model_id=model_id,
                messages=[
                    {"role": "system", "content": _AUTOFILL_SYSTEM},
                    {"role": "user", "content": _autofill_prompt(name, url, text)},
                ],
                temperature=0.4,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
        )
        parsed = _parse_autofill_json(resp.content)
        if parsed is None:
            logger.info("autopilot_autofill_unparseable", model=model_id, layer="layer4_platform")
            return fallback
        if not parsed["subtitle"]:
            parsed["subtitle"] = fallback["subtitle"]
        if not parsed["suggested_prompts"]:
            parsed["suggested_prompts"] = fallback["suggested_prompts"]
        parsed["_model"] = model_display
        return parsed
    except Exception as exc:
        logger.warning("autopilot_autofill_failed", error=str(exc), layer="layer4_platform")
        return fallback


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def analyze_site(url: str, *, tenant_id: Optional[str] = None) -> dict:
    """Render + analyze ``url`` and return a review-ready bot draft (a dict)."""
    target = normalize_url(url)
    guard_public_url(target)

    try:
        rendered = await render_site(
            target,
            viewport_width=settings.WIDGET_AUTOPILOT_VIEWPORT_WIDTH,
            timeout_s=settings.WIDGET_AUTOPILOT_TIMEOUT_S,
            full_page=True,
            max_text_chars=settings.WIDGET_AUTOPILOT_MAX_TEXT_CHARS,
        )
    except RendererUnavailableError as exc:
        raise AutopilotError(str(exc)) from exc
    except RenderError as exc:
        raise AutopilotError(str(exc)) from exc

    origin = rendered.origin or f"{urlsplit(target).scheme}://{urlsplit(target).netloc}"
    slug = _registrable_slug(origin)
    name = _brand_name(rendered, slug)

    # Theme from the actual rendered pixels (+ declared theme-color).
    theme = theme_extractor.derive_bot_theme(
        rendered.screenshot_png, theme_color_meta=rendered.theme_color
    )
    palette = theme.pop("_palette", [])

    # A square icon makes a better header avatar than an og:image banner.
    logo_url = ""
    for candidate in (rendered.icon_url, rendered.logo_url):
        if candidate and await _valid_image_url(candidate):
            logo_url = candidate
            break
    if logo_url:
        theme["logo_url"] = logo_url

    copy = await _ai_autofill(name, origin, rendered.text)
    shot_id = _store_screenshot(rendered.screenshot_png)

    warnings: list[str] = []
    if len((rendered.text or "").strip()) < 40:
        warnings.append(
            "The page returned very little text, so the copy is generic. The site "
            "may block bots or render unusually."
        )

    return {
        "source_url": target,
        "final_url": rendered.final_url,
        "origin": origin,
        "display_name": copy["display_name"],
        "greeting": copy["greeting"],
        "subtitle": copy["subtitle"],
        "suggested_prompts": copy["suggested_prompts"],
        "theme": theme,
        "palette": palette,
        "allowed_origins": [origin],
        "suggested_tenant_id": slug,
        "suggested_collection_id": f"{slug}-kb",
        "screenshot_id": shot_id,
        "screenshot_url": f"/admin/autopilot/screenshot/{shot_id}",
        "authored_by_model": copy.get("_model"),
        "page_title": rendered.title,
        "warnings": warnings,
    }
