"""
Structure helpers for legal and article-numbered documents.

The Constitution and similar legal documents encode many answers in headings
such as ``17. Abolition of Untouchability.``.  These helpers keep that
structure available to chunking, retrieval, and deterministic answer assembly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


ARTICLE_HEADING_RE = re.compile(
    r"(?P<num>\d{1,3}\s*[A-Za-z]?)\.\s+"
    r"(?P<title>[A-Z][A-Za-z][^.\n]{2,180}\.)"
)
ARTICLE_REFERENCE_RE = re.compile(r"\barticle\s+(?P<num>\d{1,3}\s*[A-Za-z]?)\b", re.I)
ARTICLE_START_RE = re.compile(
    r"(?<![A-Za-z0-9-])\[?\*?\s*(?P<num>\d{1,3}\s*[A-Za-z]?)\.\s+"
)


@dataclass(frozen=True)
class ArticleSpan:
    number: str
    title: str
    start: int
    end: int


def normalize_article_number(value: str) -> str:
    """Normalize article numbers for exact matching, e.g. ``21 A`` -> ``21A``."""
    return re.sub(r"\s+", "", value).upper()


def extract_article_reference(text: str) -> Optional[str]:
    """Return the article number explicitly requested in a query, if present."""
    match = ARTICLE_REFERENCE_RE.search(text)
    if not match:
        return None
    return normalize_article_number(match.group("num"))


def find_article_spans(text: str) -> list[ArticleSpan]:
    """Find article-heading spans and extend each span until the next heading."""
    matches = list(ARTICLE_HEADING_RE.finditer(text))
    spans: list[ArticleSpan] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if index + 1 < len(matches):
            previous_period = text.rfind(".", start, end)
            trailing = text[previous_period + 1:end].strip() if previous_period >= start else ""
            if trailing and not trailing[0].isdigit():
                end = previous_period + 1
        title = " ".join(match.group("title").split())
        spans.append(
            ArticleSpan(
                number=normalize_article_number(match.group("num")),
                title=title,
                start=start,
                end=end,
            )
        )
    return spans


def find_article_span_by_number(text: str, article_number: str) -> Optional[ArticleSpan]:
    normalized = normalize_article_number(article_number)
    for span in find_article_spans(text):
        if span.number == normalized:
            return span
    return None


def extract_article_text(text: str, article_number: str) -> Optional[str]:
    """
    Extract one article's text even when PDF extraction lost the formal heading.

    This handles forms commonly seen in legal PDFs, including ``*[21A. ...]``
    insertions and line-wrapped article bodies.  It stops before the next
    article marker so answer text and highlights do not bleed into Article 22.
    """
    normalized = normalize_article_number(article_number)
    matches = list(ARTICLE_START_RE.finditer(text))
    for index, match in enumerate(matches):
        if normalize_article_number(match.group("num")) != normalized:
            continue
        start = match.start()
        end = len(text)
        for next_match in matches[index + 1:]:
            next_number = normalize_article_number(next_match.group("num"))
            if next_number != normalized:
                end = next_match.start()
                break
        article_text = text[start:end].strip()
        article_text = re.sub(r"^\*\s*", "", article_text).strip()
        article_text = article_text.strip("[] ")
        return " ".join(article_text.split())
    return None


def chunk_article_number(chunk_text: str, metadata: dict[str, str] | None = None) -> Optional[str]:
    """Get a chunk's article number from metadata or from its leading heading."""
    if metadata and metadata.get("article_number"):
        return normalize_article_number(metadata["article_number"])
    spans = find_article_spans(chunk_text)
    if not spans:
        return None
    first = spans[0]
    if first.start <= 12:
        return first.number
    return None
