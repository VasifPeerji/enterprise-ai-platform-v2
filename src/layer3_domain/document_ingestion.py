"""
Document ingestion and chunking primitives.

This module turns normalized page-level document extracts into retrieval-ready
chunks while preserving enough provenance for exact page highlights later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from src.layer3_domain.document_models import DocumentChunk, IngestedDocument, IngestedPage
from src.layer3_domain.document_structure import find_article_spans
from src.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChunkingConfig:
    """Chunking configuration tuned for document-grounded QA."""

    target_chars: int = 900
    overlap_chars: int = 180
    min_chunk_chars: int = 180
    page_chunk_max_chars: int = 4200


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_into_paragraphs(text: str) -> list[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    return paragraphs or [normalized]


def _split_long_text(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []
    if len(normalized) <= target_chars:
        return [normalized]

    sentence_parts = [
        part.strip()
        for part in re.split(r"(?<!\d\.)(?<!\d[A-Za-z]\.)(?<=[.!?;:])\s+|\n", normalized)
        if part.strip()
    ] or [normalized]

    windows: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for part in sentence_parts:
        part_length = len(part)
        if current_parts and current_length + 1 + part_length > target_chars:
            windows.append(" ".join(current_parts).strip())
            overlap_tail = ""
            if overlap_chars > 0 and windows[-1]:
                overlap_tail = windows[-1][-overlap_chars:].strip()
            current_parts = [overlap_tail] if overlap_tail else []
            current_length = len(overlap_tail)

        current_parts.append(part)
        current_length += part_length + (1 if len(current_parts) > 1 else 0)

    if current_parts:
        windows.append(" ".join(current_parts).strip())

    final_windows: list[str] = []
    for window in windows:
        if len(window) <= target_chars:
            final_windows.append(window)
            continue

        step = max(target_chars - overlap_chars, int(target_chars * 0.7), 1)
        for start in range(0, len(window), step):
            piece = window[start:start + target_chars].strip()
            if piece:
                final_windows.append(piece)

    deduped: list[str] = []
    for window in final_windows:
        if not deduped or deduped[-1] != window:
            deduped.append(window)
    return deduped


class DocumentChunker:
    """
    Chunk page-level extracts into retrieval-ready units.

    Strategy:
    - keep chunks page-bounded to preserve highlight rendering
    - pack semantically related paragraphs together
    - add configurable character overlap for retrieval robustness
    """

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk_document(self, document: IngestedDocument) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []

        for page in document.pages:
            page_chunks = self.chunk_page(page)
            chunks.extend(page_chunks)

        logger.info(
            "document_chunked",
            document_id=document.document_id,
            title=document.title,
            page_count=len(document.pages),
            chunk_count=len(chunks),
            layer="layer3_domain",
        )
        return chunks

    def chunk_many(self, documents: Iterable[IngestedDocument]) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for document in documents:
            chunks.extend(self.chunk_document(document))
        return chunks

    def chunk_page(self, page: IngestedPage) -> list[DocumentChunk]:
        article_chunks = self._chunk_article_page(page)
        if article_chunks:
            return article_chunks

        if self._should_preserve_page_as_chunk(page):
            return [self._build_chunk(page, [page.text], 0, section_title=page.section_title)]

        raw_paragraphs = _split_into_paragraphs(page.text)
        paragraphs: list[str] = []
        for paragraph in raw_paragraphs:
            if len(paragraph) > self.config.target_chars:
                paragraphs.extend(
                    _split_long_text(
                        paragraph,
                        self.config.target_chars,
                        self.config.overlap_chars,
                    )
                )
            else:
                paragraphs.append(paragraph)
        if not paragraphs:
            return []

        chunks: list[DocumentChunk] = []
        current_parts: list[str] = []
        current_length = 0
        chunk_index = 0

        for paragraph in paragraphs:
            paragraph_length = len(paragraph)

            if (
                current_parts
                and current_length + 2 + paragraph_length > self.config.target_chars
            ):
                chunks.append(self._build_chunk(page, current_parts, chunk_index))
                chunk_index += 1
                overlap_parts = self._overlap_tail(current_parts)
                current_parts = overlap_parts[:] if overlap_parts else []
                current_length = sum(len(part) for part in current_parts) + max(len(current_parts) - 1, 0) * 2

            current_parts.append(paragraph)
            current_length += paragraph_length + (2 if len(current_parts) > 1 else 0)

        if current_parts:
            chunks.append(self._build_chunk(page, current_parts, chunk_index))

        if len(chunks) >= 2 and len(chunks[-1].content) < self.config.min_chunk_chars:
            merged = f"{chunks[-2].content}\n\n{chunks[-1].content}".strip()
            chunks[-2] = chunks[-2].model_copy(
                update={
                    "content": merged,
                    "end_char": chunks[-1].end_char,
                    "metadata": {
                        **chunks[-2].metadata,
                        "merged_tail_chunk": "true",
                    },
                }
            )
            chunks.pop()

        return chunks

    def _should_preserve_page_as_chunk(self, page: IngestedPage) -> bool:
        if len(page.text) > self.config.page_chunk_max_chars:
            return False
        if page.source_type == "pdf" and page.metadata.get("rag_section_boundary") == "page":
            return True
        return page.metadata.get("rag_section_boundary") == "page"

    def _build_chunk(
        self,
        page: IngestedPage,
        parts: list[str],
        chunk_index: int,
        *,
        section_title: str | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> DocumentChunk:
        content = "\n\n".join(parts).strip()
        start_char, end_char = self._find_offsets(page.text, content)
        return DocumentChunk(
            chunk_id=f"{page.document_id}:p{page.page_number}:c{chunk_index}",
            document_id=page.document_id,
            tenant_id=page.tenant_id,
            domain=page.domain,
            title=page.title,
            source_uri=page.source_uri,
            page_number=page.page_number,
            page_text=page.text,
            content=content,
            page_width=page.width,
            page_height=page.height,
            section_title=section_title if section_title is not None else page.section_title,
            start_char=start_char,
            end_char=end_char,
            metadata={
                **page.metadata,
                **(extra_metadata or {}),
                "source_type": page.source_type,
                "language": page.language,
                "chunk_index": str(chunk_index),
            },
        )

    def _chunk_article_page(self, page: IngestedPage) -> list[DocumentChunk]:
        # Article-style chunking is a Constitution/legal-document feature.
        # The ARTICLE_HEADING_RE pattern matches any "<digits>. <Title>" form,
        # which mis-fires on pharma docs where subsection headings like
        # "2.5 Instructions for Intravenous Administration." get tagged as
        # "Article 2". Gate strictly on the legal domain so other corpora are
        # chunked by paragraphs/length only.
        domain = (page.domain or "").strip().lower()
        if domain not in {"law", "legal", "constitution", "constitutional-law"}:
            return []
        spans = find_article_spans(page.text)
        if not spans:
            return []

        chunks: list[DocumentChunk] = []
        chunk_index = 0
        for span in spans:
            article_text = page.text[span.start:span.end].strip()
            if not article_text:
                continue

            article_parts = _split_long_text(
                article_text,
                self.config.target_chars,
                self.config.overlap_chars,
            )
            for part_index, part in enumerate(article_parts):
                chunks.append(
                    self._build_chunk(
                        page,
                        [part],
                        chunk_index,
                        section_title=f"Article {span.number}: {span.title}",
                        extra_metadata={
                            "article_number": span.number,
                            "article_title": span.title,
                            "article_part_index": str(part_index),
                        },
                    )
                )
                chunk_index += 1

        return chunks

    def _overlap_tail(self, parts: list[str]) -> list[str]:
        if not parts or self.config.overlap_chars <= 0:
            return []

        selected: list[str] = []
        total = 0
        for paragraph in reversed(parts):
            selected.insert(0, paragraph)
            total += len(paragraph)
            if total >= self.config.overlap_chars:
                break
        return selected

    def _find_offsets(self, page_text: str, chunk_text: str) -> tuple[int, int]:
        if not page_text or not chunk_text:
            return 0, 0

        # Fast path: the chunk text appears verbatim in the page.
        start = page_text.find(chunk_text)
        if start >= 0:
            return start, start + len(chunk_text)

        # chunk_text has been whitespace-normalized (single spaces, "\n\n"
        # paragraph breaks) while page_text keeps the source's original
        # whitespace — wide gaps from columns/justified text, single newlines
        # from line wraps. Match token-by-token with a flexible whitespace
        # separator so the returned offsets stay in ORIGINAL page_text space and
        # page_text[start:end] is the exact source substring.
        #
        # The previous implementation searched the *normalized* page text and
        # returned those offsets against the *un-normalized* page_text, which
        # silently mis-sliced the page (e.g. truncating "...per day." to
        # "...per") on any line containing a multi-space run. start_char/end_char
        # feed the citation/highlight fallback paths and the extracted-text
        # view, so the offsets must index page_text exactly.
        tokens = chunk_text.split()
        if tokens:
            pattern = r"\s+".join(re.escape(token) for token in tokens)
            match = re.search(pattern, page_text)
            if match:
                return match.start(), match.end()

        return 0, len(chunk_text)
