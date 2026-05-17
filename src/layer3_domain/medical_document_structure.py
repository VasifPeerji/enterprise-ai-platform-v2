"""
Metadata extraction helpers for RAG-optimized medicine documents.

The medicine PDFs used for citation demos are intentionally page-structured:
each page is a self-contained section with visible drug/section headers.  These
helpers extract that structure without making the rest of the RAG stack
medicine-only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


_KNOWN_DRUG_ALIASES = {
    "acetaminophen": "Acetaminophen",
    "albuterol": "Albuterol",
    "amlodipine": "Amlodipine",
    "norvasc": "Amlodipine (Norvasc)",
    "atorvastatin": "Atorvastatin",
    "levothyroxine": "Levothyroxine",
    "synthroid": "Levothyroxine",
    "metformin": "Metformin",
    "omeprazole": "Omeprazole",
    "sertraline": "Sertraline",
}


def detect_drug_names(text: str) -> set[str]:
    """Detect explicitly named demo drugs/brands in user text."""
    lowered = text.lower()
    detected: set[str] = set()
    for alias, display in _KNOWN_DRUG_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            detected.add(display)
    return detected

_SECTION_HINTS = [
    "boxed warning",
    "indications",
    "dosage",
    "administration",
    "contraindications",
    "warnings",
    "precautions",
    "adverse reactions",
    "drug interactions",
    "use in specific populations",
    "pregnancy",
    "lactation",
    "pediatric",
    "geriatric",
    "renal impairment",
    "hepatic impairment",
    "overdosage",
    "description",
    "clinical pharmacology",
    "patient counseling",
    "storage",
]


def infer_drug_name(title: str, text: str = "") -> str:
    """Infer a display drug name from filename/title first, then page text."""
    haystacks = [Path(title).stem.replace("_", " "), text[:500]]
    for haystack in haystacks:
        lowered = haystack.lower()
        for alias, display in _KNOWN_DRUG_ALIASES.items():
            if alias in lowered:
                return display
    cleaned = Path(title).stem.replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", cleaned).title() if cleaned else title


def _clean_header_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" :-\t")
    line = re.sub(r"^\d+(?:\.\d+)*\s+", "", line).strip()
    return line


def infer_section_name(text: str) -> Optional[str]:
    """Infer a section name from visible page headers or known label phrases."""
    lines = [_clean_header_line(line) for line in text.splitlines() if _clean_header_line(line)]
    for line in lines[:8]:
        lowered = line.lower()
        for hint in _SECTION_HINTS:
            if hint in lowered:
                return line

    joined = " ".join(lines[:12]).lower()
    for hint in _SECTION_HINTS:
        if hint in joined:
            return hint.title()
    return lines[1] if len(lines) > 1 and len(lines[1]) <= 90 else None


def infer_subsection_name(text: str, section_name: Optional[str]) -> Optional[str]:
    lines = [_clean_header_line(line) for line in text.splitlines() if _clean_header_line(line)]
    if not section_name:
        return None
    section_lower = section_name.lower()
    for line in lines[:10]:
        lowered = line.lower()
        if lowered != section_lower and any(word in lowered for word in ("renal", "hepatic", "dose", "maximum", "pediatric", "geriatric")):
            return line
    return None


def build_medical_page_metadata(title: str, text: str) -> dict[str, str]:
    drug_name = infer_drug_name(title, text)
    section_name = infer_section_name(text) or "Document Section"
    subsection_name = infer_subsection_name(text, section_name)
    metadata = {
        "drug_name": drug_name,
        "section_name": section_name,
        "rag_section_boundary": "page",
    }
    if subsection_name:
        metadata["subsection_name"] = subsection_name
    return metadata


def is_rag_optimized_page(text: str, metadata: dict[str, str] | None = None) -> bool:
    if metadata and metadata.get("rag_section_boundary") == "page":
        return True
    if not text.strip():
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return infer_section_name(text) is not None
