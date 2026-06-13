"""
Original-page rendering and highlight-rect mapping for grounded citations.

Backed by PyMuPDF (fitz). Given the original PDF bytes this module can:
- render a page to a PNG image, and
- locate citation snippets on that page as *normalized* rectangles

so the UI can overlay highlights on the exact original page image instead of
re-flowed extracted text. Normalized rectangles (fractions of page width/height)
keep the overlay correct at any display size or render DPI.

The module degrades gracefully: if PyMuPDF is unavailable or a lookup fails it
returns ``None`` / an empty list and the caller falls back to the text proof.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from src.layer3_domain.document_models import NormalizedRect
from src.shared.logger import get_logger

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency/runtime behavior
    fitz = None

logger = get_logger(__name__)

# Sentence splitter consistent with grounded_answer.py so long multi-sentence
# snippets are broken into pieces fitz.search_for can actually match.
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d\.)(?<!\d[A-Za-z]\.)(?<=[.!?])\s+|\n+")
# fitz.search_for matches a literal needle; very long needles rarely match
# cleanly across layout, so we split anything longer than this.
_MAX_SEARCH_LEN = 380


def is_available() -> bool:
    """Whether original-page rendering is supported in this runtime."""
    return fitz is not None


def render_page_to_png(pdf_bytes: bytes, page_number: int, *, dpi: int = 150) -> Optional[bytes]:
    """Render a 1-based page of the PDF to PNG bytes, or None on failure."""
    if fitz is None or not pdf_bytes:
        return None
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            index = page_number - 1
            if index < 0 or index >= doc.page_count:
                return None
            page = doc.load_page(index)
            pix = page.get_pixmap(dpi=dpi)
            return pix.tobytes("png")
    except Exception as exc:  # pragma: no cover - depends on file content
        logger.warning(
            "page_render_failed",
            page_number=page_number,
            error=str(exc),
            layer="layer1_intelligence",
        )
        return None


def _needles_from_text(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= _MAX_SEARCH_LEN:
        return [text]
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p and p.strip()]
    needles = [p for p in parts if len(p) >= 8]
    return needles or [text[:_MAX_SEARCH_LEN]]


def _to_normalized(rect, page_w: float, page_h: float) -> Optional[NormalizedRect]:
    try:
        x0 = max(0.0, min(1.0, rect.x0 / page_w))
        y0 = max(0.0, min(1.0, rect.y0 / page_h))
        x1 = max(0.0, min(1.0, rect.x1 / page_w))
        y1 = max(0.0, min(1.0, rect.y1 / page_h))
    except Exception:
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return NormalizedRect(x0=x0, y0=y0, x1=x1, y1=y1)


def locate_highlight_rects(
    pdf_bytes: bytes,
    page_number: int,
    snippets: Sequence[str],
    *,
    max_rects: int = 12,
) -> list[NormalizedRect]:
    """Locate each snippet on the page; return de-duplicated normalized rects.

    Each snippet may match on multiple lines (fitz returns one rect per line),
    which is exactly what we want for multi-line highlights.
    """
    if fitz is None or not pdf_bytes or not snippets:
        return []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            index = page_number - 1
            if index < 0 or index >= doc.page_count:
                return []
            page = doc.load_page(index)
            page_w, page_h = float(page.rect.width), float(page.rect.height)
            if page_w <= 0 or page_h <= 0:
                return []

            # search_for returns coordinates in the page's *unrotated* space,
            # but page.rect and the rendered pixmap are in *displayed* (rotated)
            # space. Apply the page's rotation matrix so the rects line up with
            # the rendered original-page image. For unrotated pages this matrix
            # is the identity, so the common case is unchanged.
            rotation = page.rotation_matrix

            seen: set[tuple] = set()
            rects: list[NormalizedRect] = []
            for snippet in snippets:
                for needle in _needles_from_text(snippet):
                    try:
                        hits = page.search_for(needle, quads=False)
                    except Exception:
                        hits = []
                    for hit in hits:
                        normalized = _to_normalized(hit * rotation, page_w, page_h)
                        if normalized is None:
                            continue
                        key = (
                            round(normalized.x0, 4),
                            round(normalized.y0, 4),
                            round(normalized.x1, 4),
                            round(normalized.y1, 4),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        rects.append(normalized)
                        if len(rects) >= max_rects:
                            return rects
            return rects
    except Exception as exc:  # pragma: no cover - depends on file content
        logger.warning(
            "highlight_rect_mapping_failed",
            page_number=page_number,
            error=str(exc),
            layer="layer1_intelligence",
        )
        return []
