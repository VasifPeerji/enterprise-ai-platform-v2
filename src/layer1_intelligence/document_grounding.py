"""
Document grounding primitives for page-aware RAG.

The first production slice focuses on reliable source provenance:
- exact/normalized text highlight spans
- citation-ready snippets with page numbers
- backend-agnostic retrieval ranking contract
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from math import sqrt
from time import perf_counter
from typing import Iterable, Optional

from src.layer3_domain.document_models import (
    DocumentChunk,
    HighlightSpan,
    RetrievalQuery,
    RetrievalResult,
    SourceCitation,
)
from src.shared.logger import get_logger, log_rag_retrieval

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class _NormalizedText:
    text: str
    index_map: list[int]


def _normalize_for_match(text: str) -> _NormalizedText:
    """
    Lowercase text and collapse runs of non-alphanumeric chars to single spaces.

    `index_map[i]` returns the original-text index corresponding to normalized
    character `i`, which lets us recover exact highlight offsets after matching.
    """
    normalized_chars: list[str] = []
    index_map: list[int] = []
    last_was_space = True

    for idx, char in enumerate(text):
        lowered = char.lower()
        if lowered.isalnum():
            normalized_chars.append(lowered)
            index_map.append(idx)
            last_was_space = False
            continue

        if not last_was_space:
            normalized_chars.append(" ")
            index_map.append(idx)
            last_was_space = True

    if normalized_chars and normalized_chars[-1] == " ":
        normalized_chars.pop()
        index_map.pop()

    return _NormalizedText("".join(normalized_chars), index_map)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def locate_highlight_span(source_text: str, snippet: str) -> Optional[HighlightSpan]:
    """
    Locate a snippet inside source text, tolerating whitespace/punctuation drift.
    """
    if not source_text or not snippet:
        return None

    direct_start = source_text.lower().find(snippet.lower())
    if direct_start >= 0:
        direct_end = direct_start + len(snippet)
        return HighlightSpan(
            start_char=direct_start,
            end_char=direct_end,
            text=source_text[direct_start:direct_end],
        )

    normalized_source = _normalize_for_match(source_text)
    normalized_snippet = _normalize_for_match(snippet)

    if not normalized_snippet.text:
        return None

    start = normalized_source.text.find(normalized_snippet.text)
    if start < 0:
        return None

    end = start + len(normalized_snippet.text) - 1
    original_start = normalized_source.index_map[start]
    original_end = normalized_source.index_map[end] + 1

    return HighlightSpan(
        start_char=original_start,
        end_char=original_end,
        text=source_text[original_start:original_end],
    )


def build_citation(
    chunk: DocumentChunk,
    score: float,
    snippet: Optional[str] = None,
    *,
    snippet_truncated: bool = False,
) -> SourceCitation:
    """
    Convert a retrieved chunk into a citation with exact highlight metadata.
    """
    chosen_snippet = snippet or chunk.content
    proof_text = chunk.page_text or chunk.content
    highlight = locate_highlight_span(proof_text, chosen_snippet)
    if highlight is None and chunk.content != proof_text:
        local_highlight = locate_highlight_span(chunk.content, chosen_snippet)
        if local_highlight is not None:
            highlight = HighlightSpan(
                start_char=chunk.start_char + local_highlight.start_char,
                end_char=chunk.start_char + local_highlight.end_char,
                text=local_highlight.text,
            )
    highlights = [highlight] if highlight is not None else []

    return SourceCitation(
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        title=chunk.title,
        source_uri=chunk.source_uri,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        snippet=chosen_snippet,
        snippet_truncated=snippet_truncated,
        score=score,
        highlights=highlights,
    )


class InMemoryDocumentRetriever:
    """
    Lightweight retriever used for tests and early integration.

    Strategy:
    - lexical overlap for precision on clause-style queries
    - cosine-style normalization to avoid long chunks dominating
    - exact phrase bonus for extractive prompts

    This is not the long-term retrieval backend, but it gives us a stable,
    deterministic contract while we wire the rest of the stack.
    """

    def __init__(self, chunks: Optional[Iterable[DocumentChunk]] = None) -> None:
        self._chunks: list[DocumentChunk] = list(chunks or [])

    def add_chunks(self, chunks: Iterable[DocumentChunk]) -> None:
        self._chunks.extend(chunks)

    def search(self, request: RetrievalQuery) -> list[RetrievalResult]:
        start = perf_counter()
        query_tokens = _tokenize(request.query)
        query_counter = Counter(query_tokens)
        scored_results: list[RetrievalResult] = []

        for chunk in self._chunks:
            if chunk.tenant_id != request.tenant_id:
                continue
            if request.domain and chunk.domain != request.domain:
                continue

            score, matched_terms = self._score_chunk(request.query, query_counter, chunk)
            if score <= 0.0:
                continue
            scored_results.append(
                RetrievalResult(chunk=chunk, score=score, matched_terms=matched_terms)
            )

        scored_results.sort(key=lambda item: item.score, reverse=True)
        top_results = scored_results[: request.top_k]

        log_rag_retrieval(
            logger=logger,
            query=request.query,
            num_results=len(top_results),
            top_score=top_results[0].score if top_results else 0.0,
            latency_ms=(perf_counter() - start) * 1000,
        )

        return top_results

    def _score_chunk(
        self,
        raw_query: str,
        query_counter: Counter[str],
        chunk: DocumentChunk,
    ) -> tuple[float, list[str]]:
        chunk_tokens = _tokenize(chunk.content)
        section_tokens = _tokenize(chunk.section_title or "")
        combined_counter = Counter(chunk_tokens)
        combined_counter.update(section_tokens)

        if not combined_counter:
            return 0.0, []

        shared_terms = sorted(set(query_counter).intersection(combined_counter))
        if not shared_terms:
            return 0.0, []

        dot = sum(query_counter[token] * combined_counter[token] for token in shared_terms)
        query_norm = sqrt(sum(value * value for value in query_counter.values()))
        chunk_norm = sqrt(sum(value * value for value in combined_counter.values()))
        lexical_score = dot / (query_norm * chunk_norm)

        phrase_bonus = 0.0
        lowered_query = raw_query.lower().strip()
        lowered_chunk = chunk.content.lower()
        if lowered_query and lowered_query in lowered_chunk:
            phrase_bonus += 0.35
        elif len(shared_terms) >= 3:
            phrase_bonus += 0.1

        section_bonus = 0.0
        if section_tokens:
            if set(section_tokens).intersection(query_counter):
                section_bonus += 0.08

        final_score = lexical_score + phrase_bonus + section_bonus
        return round(final_score, 4), shared_terms
