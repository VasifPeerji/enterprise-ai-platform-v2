"""
Basic same-domain website crawler for grounded-knowledge ingestion.

Turns a company's public website into ``RawDocumentAsset`` objects that flow
through the SAME ingestion path as uploaded files
(``DocumentCollectionService.ingest_assets``). Each crawled page keeps its live
URL as ``source_uri``, so the grounded answer can cite straight back to the page
it came from.

Deliberately dependency-light: ``httpx`` (already a project dependency) for
fetching and the standard-library ``html.parser`` for text extraction — no
BeautifulSoup, no headless browser. The crawler is polite by construction:
honors ``robots.txt`` (stdlib ``urllib.robotparser``), stays on the start
domain, bounds concurrency, delays between requests, and hard-caps pages, depth,
and bytes.

KNOWN LIMITATION — JavaScript-rendered sites. Because nothing here runs JS, a
React/Vue/Angular/SPA site returns near-empty pages (only its server-rendered
shell is visible). Such pages are detected as "thin" and reported in
``CrawlResult.warnings`` so onboarding fails loudly rather than silently
ingesting nothing. Rendering SPAs would require a headless browser (e.g.
Playwright) — a future upgrade.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from src.layer3_domain.document_parsing import RawDocumentAsset
from src.shared.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = "EnterpriseAI-WidgetCrawler/1.0 (+grounded-knowledge-ingest)"
_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "svg", "form", "aside", "template"}
_BLOCK_TAGS = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol"}
_NON_HTML_EXT = re.compile(
    r"\.(pdf|png|jpe?g|gif|webp|svg|ico|css|js|mjs|zip|gz|tar|rar|"
    r"mp4|mp3|wav|avi|mov|woff2?|ttf|eot|xml|json|csv|rss|atom|"
    r"docx?|xlsx?|pptx?|exe|dmg|bin)(?:[?#]|$)",
    re.I,
)
_MIN_INGEST_CHARS = 25       # below this a page has no usable content -> skip
_THIN_TEXT_CHARS = 200       # below this a page is "thin" (often JS-rendered)


class _TextExtractor(HTMLParser):
    """Pull readable text, the <title>, and outbound links from raw HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._chunks: list[str] = []
        self.title: Optional[str] = None
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.links.append(value)
        if tag in _BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = ((self.title or "") + data).strip() or None
            return
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip() + " ")

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.split("\n")]
        out: list[str] = []
        blank = False
        for line in lines:
            if line:
                out.append(line)
                blank = False
            elif not blank:
                out.append("")
                blank = True
        return "\n".join(out).strip()


@dataclass
class CrawlResult:
    assets: list[RawDocumentAsset] = field(default_factory=list)
    pages_crawled: int = 0
    pages_skipped: int = 0
    thin_pages: int = 0
    robots_blocked: int = 0
    bytes_fetched: int = 0
    warnings: list[str] = field(default_factory=list)


def _registrable_host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _normalize_url(url: str) -> str:
    url, _ = urldefrag(url.strip())
    return url


class WebCrawler:
    """Same-domain BFS crawler producing ingestable ``RawDocumentAsset`` pages."""

    def __init__(
        self,
        *,
        max_pages: int,
        max_depth: int,
        same_domain: bool = True,
        max_bytes_per_page: int = 2_000_000,
        total_byte_budget: int = 60_000_000,
        request_timeout: float = 15.0,
        politeness_delay: float = 0.3,
        concurrency: int = 3,
    ) -> None:
        self.max_pages = max(1, max_pages)
        self.max_depth = max(0, max_depth)
        self.same_domain = same_domain
        self.max_bytes_per_page = max_bytes_per_page
        self.total_byte_budget = total_byte_budget
        self.request_timeout = request_timeout
        self.politeness_delay = politeness_delay
        self.concurrency = max(1, concurrency)

    async def crawl(
        self,
        start_url: str,
        *,
        collection_id: str,
        tenant_id: str = "default",
        domain: str = "general",
    ) -> CrawlResult:
        start = _normalize_url(start_url)
        parts = urlsplit(start)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            result = CrawlResult()
            result.warnings.append(f"Invalid start URL '{start_url}' (need an http/https URL).")
            return result

        base_host = _registrable_host(parts.netloc)
        result = CrawlResult()
        visited: set[str] = set()
        sem = asyncio.Semaphore(self.concurrency)

        headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.request_timeout,
            follow_redirects=True,
        ) as client:
            robots = await self._load_robots(client, parts.scheme, parts.netloc, result)

            frontier = [start]
            depth = 0
            while frontier and depth <= self.max_depth and result.pages_crawled < self.max_pages:
                to_fetch: list[str] = []
                for url in frontier:
                    norm = _normalize_url(url)
                    if norm in visited:
                        continue
                    visited.add(norm)
                    to_fetch.append(norm)
                remaining = self.max_pages - result.pages_crawled
                to_fetch = to_fetch[:remaining]

                async def _worker(u: str) -> Optional[dict]:
                    if robots is not None and not robots.can_fetch(_USER_AGENT, u):
                        return {"url": u, "skip": "robots"}
                    async with sem:
                        await asyncio.sleep(self.politeness_delay)
                        return await self._fetch(client, u, base_host)

                outcomes = await asyncio.gather(*[_worker(u) for u in to_fetch])

                next_frontier: list[str] = []
                for outcome in outcomes:
                    if outcome is None:
                        result.pages_skipped += 1
                        continue
                    if outcome.get("skip"):
                        if outcome["skip"] == "robots":
                            result.robots_blocked += 1
                        else:
                            result.pages_skipped += 1
                        continue

                    result.bytes_fetched += outcome["bytes"]
                    text = outcome["text"]
                    if len(text) < _MIN_INGEST_CHARS:
                        result.thin_pages += 1
                        result.pages_skipped += 1
                    else:
                        if len(text) < _THIN_TEXT_CHARS:
                            result.thin_pages += 1
                        result.assets.append(
                            self._asset(outcome["url"], outcome["title"], text, collection_id, tenant_id, domain)
                        )
                        result.pages_crawled += 1

                    for link in outcome["links"]:
                        if result.pages_crawled + len(next_frontier) >= self.max_pages:
                            break
                        if self._in_scope(link, base_host) and _normalize_url(link) not in visited:
                            next_frontier.append(link)

                    if result.bytes_fetched >= self.total_byte_budget:
                        result.warnings.append("Stopped early: total byte budget reached.")
                        frontier = []
                        break

                frontier = next_frontier
                depth += 1

        self._finalize_warnings(result)
        logger.info(
            "web_crawl_completed",
            start_url=start,
            pages_crawled=result.pages_crawled,
            pages_skipped=result.pages_skipped,
            thin_pages=result.thin_pages,
            robots_blocked=result.robots_blocked,
            layer="layer3_domain",
        )
        return result

    # -- internals ---------------------------------------------------------

    async def _load_robots(
        self, client: httpx.AsyncClient, scheme: str, netloc: str, result: CrawlResult
    ) -> Optional[RobotFileParser]:
        robots_url = f"{scheme}://{netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            response = await client.get(robots_url, timeout=10.0)
        except Exception as exc:
            # Unreachable robots.txt: stay permissive but record it.
            logger.warning("robots_unreachable", url=robots_url, error=str(exc), layer="layer3_domain")
            result.warnings.append("robots.txt could not be fetched; proceeding without robots restrictions.")
            return None
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
            return parser
        # 404 / other: no robots policy -> allow all.
        parser.parse([])
        return parser

    async def _fetch(self, client: httpx.AsyncClient, url: str, base_host: str) -> Optional[dict]:
        try:
            response = await client.get(url)
        except Exception as exc:
            logger.info("crawl_fetch_failed", url=url, error=str(exc), layer="layer3_domain")
            return None
        if response.status_code != 200:
            return {"url": url, "skip": "status"}
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return {"url": url, "skip": "non_html"}
        # Redirects may have left the start domain.
        final = str(response.url)
        if self.same_domain and _registrable_host(urlsplit(final).netloc) != base_host:
            return {"url": final, "skip": "offsite"}
        body = response.content[: self.max_bytes_per_page]
        try:
            html = body.decode(response.encoding or "utf-8", errors="replace")
        except (LookupError, TypeError):
            html = body.decode("utf-8", errors="replace")
        extractor = _TextExtractor()
        try:
            extractor.feed(html)
        except Exception as exc:  # malformed HTML
            logger.info("crawl_parse_failed", url=url, error=str(exc), layer="layer3_domain")
            return {"url": url, "skip": "parse_error"}
        resolved_links = [urljoin(final, href) for href in extractor.links]
        return {
            "url": final,
            "title": extractor.title or final,
            "text": extractor.get_text(),
            "links": resolved_links,
            "bytes": len(body),
        }

    def _in_scope(self, link: str, base_host: str) -> bool:
        parts = urlsplit(link)
        if parts.scheme not in {"http", "https"}:
            return False
        if _NON_HTML_EXT.search(parts.path or ""):
            return False
        if self.same_domain and _registrable_host(parts.netloc) != base_host:
            return False
        return True

    @staticmethod
    def _asset(
        url: str, title: Optional[str], text: str, collection_id: str, tenant_id: str, domain: str
    ) -> RawDocumentAsset:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return RawDocumentAsset(
            document_id=f"{collection_id}:crawl:{digest}",
            tenant_id=tenant_id,
            domain=domain,
            title=(title or url)[:200],
            source_uri=url,
            source_type="text",
            mime_type="text/plain",
            content_bytes=text.encode("utf-8"),
            metadata={"crawl_source": "web", "url": url},
        )

    @staticmethod
    def _finalize_warnings(result: CrawlResult) -> None:
        attempted = result.pages_crawled + result.thin_pages
        if attempted >= 3 and result.thin_pages >= max(2, attempted * 0.6):
            result.warnings.append(
                "Most pages returned little or no text. The site is likely JavaScript-rendered "
                "(SPA), which this crawler cannot read. Consider uploading documents instead, or "
                "crawling a server-rendered/static version of the site."
            )
        if result.robots_blocked:
            result.warnings.append(
                f"{result.robots_blocked} URL(s) were skipped because robots.txt disallows them."
            )
