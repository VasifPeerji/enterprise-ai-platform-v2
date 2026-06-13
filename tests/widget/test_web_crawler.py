"""Tests for the same-domain website crawler (no network — httpx MockTransport)."""

import pathlib
import sys

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.layer3_domain.web_crawler as wc  # noqa: E402
from src.layer3_domain.web_crawler import WebCrawler, _registrable_host, _TextExtractor  # noqa: E402


def test_text_extractor_skips_boilerplate_and_grabs_title_links():
    ex = _TextExtractor()
    ex.feed(
        "<title>Acme</title><nav>MENU HOME</nav><script>var x=1</script>"
        "<h1>Welcome</h1><p>We sell loans.</p><footer>copyright junk</footer>"
        "<a href='/about'>About</a>"
    )
    text = ex.get_text()
    assert "Welcome" in text and "loans" in text
    assert all(noise not in text for noise in ("MENU", "var x", "copyright"))
    assert ex.title == "Acme"
    assert "/about" in ex.links


def test_registrable_host_strips_www_and_port():
    assert _registrable_host("www.acme.com:443") == "acme.com"
    assert _registrable_host("acme.com") == "acme.com"
    assert _registrable_host("WWW.ACME.COM") == "acme.com"


def _mock_site(pages):
    def handler(request: httpx.Request) -> httpx.Response:
        entry = pages.get(request.url.path)
        if entry is None:
            return httpx.Response(404)
        code, ctype, body = entry
        return httpx.Response(code, headers={"content-type": ctype}, text=body)

    return httpx.MockTransport(handler)


def _patch_transport(monkeypatch, transport):
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original(*args, **kwargs)

    monkeypatch.setattr(wc.httpx, "AsyncClient", factory)


async def test_crawl_honors_robots_and_stays_in_domain(monkeypatch):
    pages = {
        "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private\n"),
        "/": (200, "text/html", "<title>Home</title><p>Welcome to Acme lending and savings.</p>"
                                 "<a href='/about'>about</a><a href='/private'>secret</a>"
                                 "<a href='https://other.test/x'>offsite</a>"),
        "/about": (200, "text/html", "<title>About</title><p>About Acme and its long lending history here.</p>"),
        "/private": (200, "text/html", "<title>Secret</title><p>secret internal data not for crawling</p>"),
    }
    _patch_transport(monkeypatch, _mock_site(pages))

    crawler = WebCrawler(max_pages=10, max_depth=2, politeness_delay=0.0)
    result = await crawler.crawl("https://acme.test/", collection_id="c", tenant_id="t", domain="general")

    urls = [a.source_uri for a in result.assets]
    assert any(u.endswith("acme.test/") for u in urls)
    assert any("/about" in u for u in urls)
    assert not any("/private" in u for u in urls)        # robots disallow respected
    assert not any("other.test" in u for u in urls)      # stayed on-domain
    assert result.robots_blocked >= 1


async def test_crawl_respects_page_cap(monkeypatch):
    pages = {
        "/robots.txt": (404, "text/plain", ""),
        "/": (200, "text/html", "<title>P0</title><p>Page zero of Acme with enough words to ingest.</p><a href='/p1'>p1</a>"),
        "/p1": (200, "text/html", "<title>P1</title><p>Page one of Acme with enough words to ingest.</p><a href='/p2'>p2</a>"),
        "/p2": (200, "text/html", "<title>P2</title><p>Page two of Acme with enough words to ingest.</p>"),
    }
    _patch_transport(monkeypatch, _mock_site(pages))

    crawler = WebCrawler(max_pages=2, max_depth=5, politeness_delay=0.0)
    result = await crawler.crawl("https://acme.test/", collection_id="c", tenant_id="t", domain="general")
    assert result.pages_crawled == 2  # hard cap honored


async def test_js_rendered_site_warns(monkeypatch):
    # Pages with almost no text (a JS shell) chained together.
    pages = {
        "/robots.txt": (404, "text/plain", ""),
        "/": (200, "text/html", "<a href='/p2'>x</a>"),
        "/p2": (200, "text/html", "<a href='/p3'>y</a>"),
        "/p3": (200, "text/html", "z"),
    }
    _patch_transport(monkeypatch, _mock_site(pages))

    crawler = WebCrawler(max_pages=10, max_depth=3, politeness_delay=0.0)
    result = await crawler.crawl("https://spa.test/", collection_id="c", tenant_id="t", domain="general")
    assert result.pages_crawled == 0
    assert result.thin_pages >= 3
    assert any("JavaScript-rendered" in w for w in result.warnings)
