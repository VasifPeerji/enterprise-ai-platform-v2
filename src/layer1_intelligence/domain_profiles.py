"""
Pluggable per-domain RAG heuristics.

The grounded RAG engine stays domain-agnostic; domain-specific knowledge
(legal article structure, medicine dosing vocabulary, ...) lives here behind a
small profile interface. This is the seam that replaces domain literals that
used to be hardcoded inline in the engine.

Profiles are intentionally *content-triggered* — they inspect the query rather
than the declared domain — so this extraction is behavior-identical to the
previous inline heuristics. Scoping strictly by the declared domain is a
follow-up refinement that changes behavior and needs corpus validation.
"""

from __future__ import annotations

import re
from typing import Protocol

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DOSE_QUERY_RE = re.compile(r"\b(max(?:imum)?|dose|dosage|daily dose|mg|milligram)\b", re.I)
_PM_QUERY_RE = re.compile(r"\bpm\b|prime minister|contest for pm", re.I)

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


class DomainProfile(Protocol):
    """A pluggable bundle of domain-specific RAG heuristics."""

    name: str

    def expand_queries(self, query: str) -> list[str]:
        """Extra retrieval queries this domain wants to also search for."""


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


# Registry. Order matters: it determines the order of appended expansions, so
# this list mirrors the previous inline order (legal emergency/PM, then dose).
DOMAIN_PROFILES: list[DomainProfile] = [LegalDomainProfile(), MedicalDomainProfile()]


def expand_domain_queries(query: str) -> list[str]:
    """Aggregate every registered domain's retrieval expansions, in order."""
    expansions: list[str] = []
    for profile in DOMAIN_PROFILES:
        expansions.extend(profile.expand_queries(query))
    return expansions
