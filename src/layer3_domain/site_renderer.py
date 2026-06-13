"""
Headless-browser site renderer for AutoPilot onboarding.

Lazy-loads Playwright (an *optional* dependency). Renders a URL in a real
Chromium so JavaScript / SPA sites work, then returns a full-page screenshot
plus the metadata AutoPilot needs to theme and describe a bot: ``<title>``, the
meta description, ``theme-color``, ``og:site_name``, a best-effort logo/icon
URL, and the visible body text.

This is deliberately distinct from ``web_crawler.py`` (``httpx`` +
stdlib ``html.parser``, runs no JS). The crawler is light and feeds the public
grounded-knowledge path; this renderer executes the page and is therefore much
heavier — it is used **only** for the one-shot, admin-only AutoPilot analysis,
never on the public hot path.

Playwright's **sync** API is driven inside a worker thread (``asyncio.to_thread``)
on purpose: it sidesteps the Windows asyncio-subprocess (Proactor) pitfall that
bites the async API under uvicorn, and keeps the event loop unblocked. Every
Playwright import is lazy, so the rest of the app runs fine when the engine is
not installed — callers get a clear :class:`RendererUnavailableError` instead.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from src.shared.logger import get_logger

logger = get_logger(__name__)

# Browsers default to a project-local directory on the real filesystem rather than
# %LOCALAPPDATA%\ms-playwright. Two reasons: (1) it keeps the engine self-contained
# / portable with the repo, and (2) it sidesteps Windows AppContainer *virtualization*
# of AppData — a sandboxed `playwright install` would otherwise land the browser in a
# per-sandbox redirected path that the real server process cannot see ("Executable
# doesn't exist" even though it appears present to the installer). An operator who has
# already provisioned browsers elsewhere can override via PLAYWRIGHT_BROWSERS_PATH.
_PROJECT_BROWSERS = Path(__file__).resolve().parents[2] / ".runtime" / "pw-browsers"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_PROJECT_BROWSERS))

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36 EnterpriseAI-AutoPilot/1.0"
)

_INSTALL_HINT = (
    "The headless browser engine is not available. Install it once with: "
    "`pip install playwright` then `playwright install chromium`."
)


class RendererUnavailableError(RuntimeError):
    """Playwright / Chromium is not installed or could not be launched."""


class RenderError(RuntimeError):
    """The page itself could not be rendered (bad URL / navigation timeout)."""


@dataclass
class RenderedSite:
    """Everything AutoPilot needs from one rendered page."""

    final_url: str
    origin: str
    title: str = ""
    description: str = ""
    theme_color: str = ""
    site_name: str = ""
    logo_url: str = ""        # og:image (banner-ish, but often a usable brand mark)
    icon_url: str = ""        # apple-touch-icon / favicon (square, logo-like)
    text: str = ""
    screenshot_png: bytes = b""


# Pulled in a single page.evaluate so we touch the DOM once after it settles.
_META_JS = r"""
() => {
  const pick = (sel, attr) => { const el = document.querySelector(sel); return el ? (el.getAttribute(attr) || '').trim() : ''; };
  const abs = (u) => { try { return u ? new URL(u, document.baseURI).href : ''; } catch (e) { return ''; } };
  let icon = pick('link[rel="apple-touch-icon"]','href')
    || pick('link[rel="apple-touch-icon-precomposed"]','href')
    || pick('link[rel="icon"]','href')
    || pick('link[rel="shortcut icon"]','href');
  return {
    title: (document.title || '').trim(),
    description: pick('meta[name="description"]','content') || pick('meta[property="og:description"]','content'),
    theme_color: pick('meta[name="theme-color"]','content'),
    site_name: pick('meta[property="og:site_name"]','content'),
    og_image: abs(pick('meta[property="og:image"]','content')),
    icon: abs(icon),
    text: (document.body ? (document.body.innerText || '') : '').replace(/\s+/g,' ').trim(),
  };
}
"""


def _render_sync(
    url: str,
    *,
    viewport_width: int,
    timeout_ms: int,
    full_page: bool,
    max_text_chars: int,
) -> RenderedSite:
    try:
        from playwright.sync_api import sync_playwright  # lazy: optional dependency
    except Exception as exc:  # pragma: no cover - depends on local install
        raise RendererUnavailableError(_INSTALL_HINT) from exc

    try:
        pw = sync_playwright().start()
    except Exception as exc:  # pragma: no cover
        raise RendererUnavailableError(_INSTALL_HINT) from exc

    browser = None
    try:
        try:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        except Exception as exc:
            raise RendererUnavailableError(
                f"Chromium failed to launch: {exc}. {_INSTALL_HINT}"
            ) from exc

        context = browser.new_context(
            viewport={"width": viewport_width, "height": 900},
            user_agent=_USER_AGENT,
            locale="en-US",
            device_scale_factor=1,
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        # `load` is the sweet spot; fall back to a softer wait if a heavy page
        # never fully "loads" within the budget.
        try:
            page.goto(url, wait_until="load", timeout=timeout_ms)
        except Exception:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # Give late/lazy content a moment to paint before we capture.
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(700)

        meta = {}
        try:
            meta = page.evaluate(_META_JS) or {}
        except Exception:
            meta = {}

        final_url = page.url
        screenshot = page.screenshot(full_page=full_page, type="png")
    except RendererUnavailableError:
        raise
    except Exception as exc:
        raise RenderError(f"Could not render {url}: {exc}") from exc
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass

    parts = urlsplit(final_url)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    return RenderedSite(
        final_url=final_url,
        origin=origin,
        title=meta.get("title", "") or "",
        description=meta.get("description", "") or "",
        theme_color=meta.get("theme_color", "") or "",
        site_name=meta.get("site_name", "") or "",
        logo_url=meta.get("og_image", "") or "",
        icon_url=meta.get("icon", "") or "",
        text=(meta.get("text", "") or "")[:max_text_chars],
        screenshot_png=screenshot,
    )


async def render_site(
    url: str,
    *,
    viewport_width: int = 1366,
    timeout_s: float = 25.0,
    full_page: bool = True,
    max_text_chars: int = 6000,
) -> RenderedSite:
    """Render ``url`` in headless Chromium and return a :class:`RenderedSite`.

    Runs the blocking Playwright sync API in a worker thread so it never blocks
    the event loop. Raises :class:`RendererUnavailableError` if the engine is
    missing, or :class:`RenderError` if the page can't be rendered.
    """
    return await asyncio.to_thread(
        _render_sync,
        url,
        viewport_width=viewport_width,
        timeout_ms=int(timeout_s * 1000),
        full_page=full_page,
        max_text_chars=max_text_chars,
    )
