"""
Pluggable per-domain RAG heuristics.

The grounded RAG engine stays domain-agnostic; domain-specific knowledge
(legal article structure, medicine dosing vocabulary, ...) lives here behind a
small profile interface. This is the seam that replaces domain literals that
used to be hardcoded inline in the engine.

Profiles are intentionally *content-triggered* — they inspect the query /
citations rather than the declared domain — so this extraction is
behavior-identical to the previous inline heuristics. Scoping strictly by the
declared domain is a follow-up refinement that changes behavior and needs
corpus validation.
"""

from __future__ import annotations

import re
from typing import Optional, Protocol, Sequence

from src.layer3_domain.document_structure import (
    chunk_article_number,
    extract_article_reference,
    extract_article_text,
    find_article_spans,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DOSE_QUERY_RE = re.compile(r"\b(max(?:imum)?|dose|dosage|daily dose|mg|milligram)\b", re.I)
_PM_QUERY_RE = re.compile(r"\bpm\b|prime minister|contest for pm", re.I)
_QUOTED_TEXT_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_ARTICLE_TITLE_QUERY_RE = re.compile(r"\b(?:deals with|about|under)\s+(?:the\s+)?(.+?)\??$", re.I)

# Demo drugs whose name is prepended to a dose-expansion query. Kept as an
# explicit set (not the full alias table) to preserve the exact prior behavior.
_DOSE_EXPANSION_DRUGS = {
    "acetaminophen",
    "albuterol",
    "amlodipine",
    "norvasc",
    "atorvastatin",
    "levothyroxine",
    "metformin",
    "omeprazole",
    "sertraline",
}

# Mirrors rag_service._GROUNDING_STOPWORDS so legal title matching is identical.
_GROUNDING_STOPWORDS = {
    "a", "an", "and", "any", "are", "be", "by", "for", "from", "how", "in", "is",
    "of", "on", "or", "the", "to", "what", "when", "where", "which", "who", "why",
    "with", "work",
}


def _query_terms(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _GROUNDING_STOPWORDS]


class DomainProfile(Protocol):
    """A pluggable bundle of domain-specific RAG heuristics."""

    name: str

    def expand_queries(self, query: str) -> list[str]:
        """Extra retrieval queries this domain wants to also search for."""

    def structured_answer(self, query: str, citations: Sequence) -> Optional[str]:
        """A deterministic, domain-shaped answer assembled from citations, or None."""


class LegalDomainProfile:
    """Constitution / article-numbered legal documents."""

    name = "legal"

    def expand_queries(self, query: str) -> list[str]:
        lowered = query.lower()
        expansions: list[str] = []
        if "emergenc" in lowered and ("three" in lowered or "types" in lowered):
            expansions.extend(
                [
                    "Proclamation of Emergency Article 352",
                    "failure of constitutional machinery in States Article 356",
                    "Financial Emergency Article 360",
                ]
            )
        if _PM_QUERY_RE.search(query):
            expansions.extend(
                [
                    "Prime Minister Article 75 appointed by the President",
                    "Minister not member of Parliament six consecutive months Article 75",
                    "qualification for membership of Parliament Article 84",
                    "Council of Ministers Prime Minister Constitution of India",
                ]
            )
        return expansions

    def structured_answer(self, query: str, citations: Sequence) -> Optional[str]:
        requested_article = extract_article_reference(query)
        if requested_article:
            for citation in citations:
                article_number = chunk_article_number(
                    citation.snippet,
                    {"article_number": citation.section_title.split(":", 1)[0].removeprefix("Article ").strip()}
                    if citation.section_title and citation.section_title.startswith("Article ")
                    else {},
                )
                if article_number == requested_article:
                    title = self._article_title_from_citation(citation.snippet, citation.section_title)
                    exact_article = extract_article_text(citation.snippet, requested_article) or citation.snippet
                    body = self._article_body_from_snippet(exact_article, requested_article, title)
                    if body:
                        return f"Article {requested_article} provides: {body}"
                    if title:
                        return f"Article {requested_article} deals with {title}"
                    return citation.snippet.strip()

        if "financial emergency" in query.lower():
            for citation in citations:
                article_number = chunk_article_number(citation.snippet, None)
                if article_number and "financial emergency" in citation.snippet.lower():
                    return f"The President can declare a Financial Emergency under Article {article_number}."

        wanted_title = self._extract_requested_title(query)
        if wanted_title:
            wanted_terms = set(_query_terms(wanted_title))
            best: tuple[int, str] | None = None
            for citation in citations:
                for span in find_article_spans(citation.snippet):
                    title_terms = set(_query_terms(span.title))
                    overlap = len(wanted_terms.intersection(title_terms))
                    if overlap and (best is None or overlap > best[0]):
                        best = (overlap, f"Article {span.number} deals with {span.title.rstrip('.')}.")
                if citation.section_title and citation.section_title.startswith("Article "):
                    match = re.match(r"Article\s+([0-9A-Z]+):\s+(.+)", citation.section_title)
                    if match:
                        title = match.group(2).rstrip(".")
                        overlap = len(wanted_terms.intersection(_query_terms(title)))
                        if overlap and (best is None or overlap > best[0]):
                            best = (overlap, f"Article {match.group(1)} deals with {title}.")
            if best:
                return best[1]

        if "three" in query.lower() and "emergenc" in query.lower():
            emergency_answer = self._try_emergency_types_answer(citations)
            if emergency_answer:
                return emergency_answer

        return None

    def _try_emergency_types_answer(self, citations: Sequence) -> Optional[str]:
        joined = " ".join(citation.snippet.lower() for citation in citations)
        has_national = "proclamation of emergency" in joined or "article 352" in joined
        has_state = (
            "failure of constitutional machinery" in joined
            or "president's rule" in joined
            or "article 356" in joined
        )
        has_financial = "financial emergency" in joined or "article 360" in joined
        if has_national and has_state and has_financial:
            return (
                "The Constitution mentions three types of emergencies: "
                "National Emergency, State Emergency or President's Rule, and Financial Emergency."
            )
        return None

    def _extract_requested_title(self, query: str) -> Optional[str]:
        quoted = _QUOTED_TEXT_RE.search(query)
        if quoted:
            return quoted.group(1) or quoted.group(2)
        match = _ARTICLE_TITLE_QUERY_RE.search(query)
        if match:
            return match.group(1).strip(" .")
        return None

    def _article_title_from_citation(self, snippet: str, section_title: Optional[str]) -> Optional[str]:
        if section_title and section_title.startswith("Article "):
            return section_title.split(":", 1)[1].strip() if ":" in section_title else None
        spans = find_article_spans(snippet)
        return spans[0].title if spans else None

    def _article_body_from_snippet(
        self,
        snippet: str,
        article_number: str,
        title: Optional[str],
    ) -> str:
        text = snippet.strip()
        if title:
            text = re.sub(
                rf"^\s*{re.escape(article_number)}\.\s+{re.escape(title)}\s*",
                "",
                text,
                flags=re.I,
            ).strip()
            if text and title.rstrip(".").lower() not in text[:80].lower():
                return f"{title.rstrip('.')}. {text}"
        else:
            text = re.sub(rf"^\s*{re.escape(article_number)}\.\s*", "", text, flags=re.I).strip()
        return text or (title or "")


class MedicalDomainProfile:
    """Medicine package-insert / dosing documents."""

    name = "medical"

    def expand_queries(self, query: str) -> list[str]:
        if not _DOSE_QUERY_RE.search(query):
            return []
        drug_terms = [
            token for token in _TOKEN_RE.findall(query) if token.lower() in _DOSE_EXPANSION_DRUGS
        ]
        drug_prefix = " ".join(drug_terms) + " " if drug_terms else ""
        return [
            f"{drug_prefix}dosage and administration maximum recommended daily dose mg",
            f"{drug_prefix}adult dosage maximum dose mg tablets",
        ]

    def structured_answer(self, query: str, citations: Sequence) -> Optional[str]:
        # No deterministic structured answer for medicine yet; the generic
        # extractive path handles dose/contraindication queries.
        return None


# Registry. Order matters: it determines the order of appended expansions and
# which profile's structured answer wins, mirroring the previous inline order.
DOMAIN_PROFILES: list[DomainProfile] = [LegalDomainProfile(), MedicalDomainProfile()]


def expand_domain_queries(query: str) -> list[str]:
    """Aggregate every registered domain's retrieval expansions, in order."""
    expansions: list[str] = []
    for profile in DOMAIN_PROFILES:
        expansions.extend(profile.expand_queries(query))
    return expansions


def structured_domain_answer(query: str, citations: Sequence) -> Optional[str]:
    """First domain-shaped structured answer across registered profiles, or None."""
    for profile in DOMAIN_PROFILES:
        answer = profile.structured_answer(query, citations)
        if answer:
            return answer
    return None
