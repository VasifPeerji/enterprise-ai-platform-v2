"""
📁 File: src/layer1_intelligence/claim_verifier.py
Layer: Layer 1 (Intelligence) — pure read-only computation
Purpose: Verifiable Reasoning Engine — decompose an answer into atomic claims
         and verify each against retrieved evidence using embeddings + lexical
         signals. NO LLM calls in the default path (free-tier native).

This is the third pillar of the trust story:
  Layer 0 routing  → "we pick the right model"
  Layer 1 RAG      → "we ground in real sources"
  Layer 1 verifier → "we prove every fact in the answer"

Design principles:
  - Default path uses ONLY embeddings (already running locally) + lexical
    overlap + numeric/negation polarity checks. Zero per-call API cost.
  - Falls back gracefully to lexical-only if embedding generation fails
    (e.g. Ollama not running) so the demo never breaks.
  - Output is a per-claim verdict (supported / partial / contradicted /
    unsupported / inferred) plus an aggregate Verifiability Score 0-100.
  - Designed to be called *after* an answer is generated, on the same
    citation list the UI already renders. No new retrieval is performed.
"""

from __future__ import annotations

import math
import re
import time
from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from src.layer0_model_infra.gateway import EmbeddingRequest, ModelGateway, get_gateway
from src.layer3_domain.document_models import SourceCitation
from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Tokenisation helpers (consistent with grounded_answer.py / vector_index.py)
# ---------------------------------------------------------------------------

# Sentence splitter — same style used elsewhere in the codebase so we stay
# consistent with how the highlighter and grounded answer code carve text up.
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d\.)(?<!\d[A-Za-z]\.)(?<=[.!?])\s+|\n+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Numbers with optional thousands separators / decimals / percent. Commas are
# stripped on extraction so "4000" and "4,000" compare equal — a common
# medical/legal false-mismatch that used to knock SUPPORTED claims down to
# PARTIAL purely because of a thousands separator.
_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.])\d+(?:\.\d+)?%?")

# Stopwords — superset of those used in rag_service.py.
_STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "for", "from",
    "how", "i", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "this", "to", "was", "we", "what", "when", "where", "which",
    "who", "why", "with", "your", "you", "they", "them", "these", "those",
    "but", "so", "if", "than", "then", "into", "about", "such", "also",
    "may", "might", "can", "could", "would", "should", "shall", "will",
    "have", "has", "had", "been", "being", "do", "does", "did",
}

# Sentences starting with these words are usually transitions / meta-statements
# rather than verifiable factual claims. We skip them so the verifiability
# score isn't diluted by sentences like "However, this is important."
_META_SENTENCE_PATTERNS = [
    re.compile(r"^\s*(however|therefore|moreover|furthermore|in addition|"
               r"in summary|in conclusion|overall|note that|please note|"
               r"as mentioned|as stated|let me|i (will|can|would|hope|am))",
               re.I),
]

# Negation tokens. We only treat these as polarity-flippers when they appear
# in the immediate vicinity of overlapping content terms.
_NEGATIONS = {
    "not", "no", "never", "neither", "nor", "without", "cannot", "can't",
    "won't", "shouldn't", "wouldn't", "doesn't", "don't", "isn't", "aren't",
    "wasn't", "weren't",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ClaimVerdict(str, Enum):
    """Per-claim verdict from the verifier."""

    SUPPORTED = "supported"          # ✅ entailed by evidence
    PARTIAL = "partial"              # ⚠️ partial overlap, missing details
    CONTRADICTED = "contradicted"    # 🔴 evidence has opposite polarity
    UNSUPPORTED = "unsupported"      # ❌ no evidence found
    INFERRED = "inferred"            # 🔵 reasonable inference, no direct cite


class ClaimVerification(BaseModel):
    """Verification result for a single claim."""

    claim_id: int = Field(..., ge=0, description="0-based index in answer order")
    text: str = Field(..., description="The claim sentence")
    sentence_start: int = Field(..., ge=0, description="Char offset in answer text")
    sentence_end: int = Field(..., ge=0, description="Char offset (exclusive)")

    verdict: ClaimVerdict = Field(..., description="Verification verdict")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Verdict confidence 0-1")

    best_citation_index: Optional[int] = Field(
        default=None,
        description="Index of best-matching citation in citations[], or None",
    )
    similarity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Embedding cosine similarity to best citation",
    )
    token_overlap: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Significant-term Jaccard overlap with best citation",
    )
    numeric_match: bool = Field(
        default=True,
        description="Whether all numeric values in the claim appear in evidence",
    )
    reasoning: str = Field(..., description="Plain-English explanation of the verdict")
    match_type: str = Field(
        default="none",
        description=(
            "How the best citation matched the claim: 'verbatim' (claim is a "
            "literal substring of the evidence — extractive grounding), "
            "'semantic' (embedding similarity drove the match), 'lexical' "
            "(term overlap drove it), or 'none'."
        ),
    )


class VerificationReport(BaseModel):
    """Aggregate verification report for a full answer."""

    verifiability_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Overall verifiability percentage (0-100)",
    )
    total_claims: int = Field(..., ge=0)

    supported_count: int = Field(default=0, ge=0)
    partial_count: int = Field(default=0, ge=0)
    contradicted_count: int = Field(default=0, ge=0)
    unsupported_count: int = Field(default=0, ge=0)
    inferred_count: int = Field(default=0, ge=0)
    verbatim_supported_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Of the supported claims, how many were verbatim copies of the cited "
            "evidence (extractive grounding rather than synthesis). When this "
            "equals supported_count the answer is fully extractive, so a high "
            "verifiability_score reflects copying, not synthesis quality."
        ),
    )

    claims: list[ClaimVerification] = Field(default_factory=list)

    method: str = Field(
        default="embedding+lexical",
        description="Which signals were used (embedding+lexical | lexical-only | skipped_no_citations)",
    )
    latency_ms: float = Field(default=0.0, ge=0.0)

    auto_corrected: bool = Field(
        default=False,
        description="Reserved: the read-only verifier scores claims but never rewrites the answer, so this stays False",
    )
    correction_attempts: int = Field(
        default=0,
        ge=0,
        description="Reserved for a future self-correction pass; always 0 in the read-only verifier",
    )

    summary: str = Field(
        default="",
        description="Short human-readable summary like '7/9 claims verified'",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _significant_terms(text: str) -> set[str]:
    return {tok for tok in _tokenize(text) if tok not in _STOPWORDS and len(tok) > 1}


def _numeric_tokens(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMERIC_TOKEN_RE.findall((text or "").lower())}


def _has_negation(text: str) -> bool:
    return any(tok in _NEGATIONS for tok in _tokenize(text))


def _best_matching_sentence_polarity(
    claim_terms: set[str],
    evidence: str,
) -> tuple[bool, float]:
    """Find the highest-overlap SENTENCE in evidence and return (negation, overlap).

    This is critical for accuracy: long evidence chunks often contain unrelated
    "do not", "never", or "must not" tokens that are irrelevant to the
    sentence supporting the claim. Checking polarity at sentence level
    instead of chunk level avoids false-positive contradictions.
    """
    if not claim_terms or not evidence:
        return False, 0.0

    sentences = [s for s in _SENTENCE_SPLIT_RE.split(evidence) if s and s.strip()]
    if not sentences:
        return _has_negation(evidence), 0.0

    best_overlap = 0.0
    best_negated = False
    for sentence in sentences:
        sent_terms = _significant_terms(sentence)
        if not sent_terms:
            continue
        overlap_count = len(claim_terms & sent_terms)
        if overlap_count == 0:
            continue
        overlap_ratio = overlap_count / max(1, len(claim_terms))
        if overlap_ratio > best_overlap:
            best_overlap = overlap_ratio
            best_negated = _has_negation(sentence)

    return best_negated, best_overlap


def _is_verbatim_in_evidence(claim_text: str, evidence_text: str) -> bool:
    """Strong support fast-path: claim is a literal substring of evidence.

    Whitespace-normalised, case-insensitive. Only fires for substantive claims
    (>=30 chars) so short common phrases don't get a free pass.
    """
    if not claim_text or not evidence_text:
        return False
    claim_norm = re.sub(r"\s+", " ", claim_text.lower().strip())
    evidence_norm = re.sub(r"\s+", " ", evidence_text.lower().strip())
    if len(claim_norm) < 30:
        return False
    return claim_norm in evidence_norm


def _is_meaningful_claim(sentence: str) -> bool:
    """Skip sentences that aren't factual claims worth verifying."""
    s = (sentence or "").strip()
    if len(s) < 12:
        return False
    if any(pat.search(s) for pat in _META_SENTENCE_PATTERNS):
        return False
    # Must have at least 3 significant content terms
    if len(_significant_terms(s)) < 3:
        return False
    return True


def _cosine(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Cosine similarity, defensively handles unnormalised vectors."""
    if not v1 or not v2:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


# ---------------------------------------------------------------------------
# Claim decomposition (deterministic, no LLM)
# ---------------------------------------------------------------------------


class ClaimDecomposer:
    """
    Deterministically split an answer into atomic verifiable claims.

    A 'claim' is one sentence that:
      - is at least 12 characters long
      - contains at least 3 significant content terms (non-stopwords)
      - is not a meta/transition sentence

    Returns a list of (claim_text, sentence_start_char, sentence_end_char)
    tuples so the UI can render the verdict at the exact location in the
    original answer.
    """

    MAX_CLAIMS = 30  # safety cap so a 5-page essay doesn't blow up the verifier

    def decompose(self, answer: str) -> list[tuple[str, int, int]]:
        if not answer or not answer.strip():
            return []

        results: list[tuple[str, int, int]] = []
        cursor = 0

        # Walk all split positions and recover the spans between them.
        for match in _SENTENCE_SPLIT_RE.finditer(answer):
            end = match.start()
            raw = answer[cursor:end]
            sentence = raw.strip()
            if sentence and _is_meaningful_claim(sentence):
                start_offset = cursor + (len(raw) - len(raw.lstrip()))
                end_offset = start_offset + len(sentence)
                results.append((sentence, start_offset, end_offset))
            cursor = match.end()
            if len(results) >= self.MAX_CLAIMS:
                break

        # Tail segment after the last separator.
        if len(results) < self.MAX_CLAIMS:
            raw = answer[cursor:]
            sentence = raw.strip()
            if sentence and _is_meaningful_claim(sentence):
                start_offset = cursor + (len(raw) - len(raw.lstrip()))
                end_offset = start_offset + len(sentence)
                results.append((sentence, start_offset, end_offset))

        return results


# ---------------------------------------------------------------------------
# Claim verifier
# ---------------------------------------------------------------------------


class ClaimVerifier:
    """
    Free-tier-native claim verification engine.

    Combines four signals to assign a verdict to each claim:
      1. Embedding cosine similarity (claim ↔ best citation snippet)
      2. Significant-term Jaccard overlap
      3. Numeric-token preservation (numbers in the claim must appear in evidence)
      4. Negation polarity (high overlap + flipped polarity = contradiction)

    Combined score = 0.6 × similarity + 0.4 × overlap, with a 0.5x penalty
    when the claim has numerics that aren't found in the cited evidence.

    Thresholds are tuned conservatively so the demo doesn't oversell:
      - SUPPORT_THRESHOLD = 0.62  → "claim well backed by cited evidence"
      - PARTIAL_THRESHOLD = 0.40  → "evidence partially matches"
      - INFERRED_FLOOR    = 0.18  → below this we say "no evidence found"

    All computation is local. The only network call is the optional batch
    embedding request, which goes to the same Ollama-backed embedding model
    the rest of the RAG pipeline already uses.
    """

    SUPPORT_THRESHOLD: float = 0.62
    PARTIAL_THRESHOLD: float = 0.40
    INFERRED_FLOOR: float = 0.18
    CONTRADICTION_OVERLAP: float = 0.50

    SIMILARITY_WEIGHT: float = 0.6
    OVERLAP_WEIGHT: float = 0.4
    NUMERIC_MISMATCH_PENALTY: float = 0.5

    def __init__(
        self,
        gateway: Optional[ModelGateway] = None,
        embedding_model_id: Optional[str] = None,
    ) -> None:
        self.gateway = gateway or get_gateway()
        self.embedding_model_id = embedding_model_id or settings.DEFAULT_EMBEDDING_MODEL
        self.decomposer = ClaimDecomposer()

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def verify(
        self,
        answer: str,
        citations: Sequence[SourceCitation] | Sequence[dict],
        *,
        use_embeddings: bool = True,
    ) -> VerificationReport:
        """
        Verify each claim in `answer` against `citations`.

        Args:
            answer:          The generated answer text to be checked.
            citations:       Either a list of SourceCitation models OR a list
                             of dicts (the JSON-serialised form). We accept both
                             so this is callable from raw API payloads.
            use_embeddings:  When False, skip the embedding call and rely only
                             on lexical signals. Useful for demos/tests where
                             Ollama isn't available.

        Returns:
            VerificationReport with per-claim verdicts and aggregate score.
        """
        start = time.time()

        # Normalise citations to a uniform shape we can iterate over.
        normalised_citations = _normalise_citations(citations)

        if not answer or not answer.strip():
            return self._empty_report(start, method="lexical-only")

        claim_tuples = self.decomposer.decompose(answer)

        if not claim_tuples:
            # No verifiable claims — short non-factual answer.
            return self._empty_report(
                start,
                method="embedding+lexical" if use_embeddings else "lexical-only",
            )

        # Edge case: no citations at all → all claims are unsupported.
        if not normalised_citations:
            verifications = [
                ClaimVerification(
                    claim_id=i,
                    text=text,
                    sentence_start=s,
                    sentence_end=e,
                    verdict=ClaimVerdict.UNSUPPORTED,
                    confidence=0.0,
                    best_citation_index=None,
                    similarity_score=0.0,
                    token_overlap=0.0,
                    numeric_match=True,
                    reasoning="No citations provided — cannot verify",
                )
                for i, (text, s, e) in enumerate(claim_tuples)
            ]
            return self._build_report(
                verifications,
                method="skipped_no_citations",
                latency_ms=(time.time() - start) * 1000,
            )

        # Try to get embeddings in a single batch. If anything fails, we
        # fall back to lexical-only verification so the demo never breaks.
        claim_vecs: Optional[list[list[float]]] = None
        citation_vecs: Optional[list[list[float]]] = None
        method = "lexical-only"

        if use_embeddings:
            try:
                claim_texts = [t for t, _, _ in claim_tuples]
                citation_texts = [c["snippet"] for c in normalised_citations]
                emb_response = await self.gateway.embed(
                    EmbeddingRequest(
                        model_id=self.embedding_model_id,
                        texts=claim_texts + citation_texts,
                    )
                )
                n_claims = len(claim_tuples)
                claim_vecs = list(emb_response.embeddings[:n_claims])
                citation_vecs = list(emb_response.embeddings[n_claims:])
                method = "embedding+lexical"
                logger.info(
                    "claim_verifier_embeddings_ready",
                    n_claims=n_claims,
                    n_citations=len(normalised_citations),
                    latency_ms=round(emb_response.latency_ms, 2),
                )
            except Exception as exc:
                logger.warning(
                    "claim_verifier_embedding_failed_using_lexical_only",
                    error=str(exc),
                )
                claim_vecs = None
                citation_vecs = None
                method = "lexical-only"

        # Score each claim against all citations.
        verifications: list[ClaimVerification] = []
        for i, (text, s, e) in enumerate(claim_tuples):
            verifications.append(
                self._verify_one_claim(
                    claim_id=i,
                    claim_text=text,
                    sentence_start=s,
                    sentence_end=e,
                    citations=normalised_citations,
                    claim_vec=claim_vecs[i] if claim_vecs else None,
                    citation_vecs=citation_vecs,
                )
            )

        report = self._build_report(
            verifications,
            method=method,
            latency_ms=(time.time() - start) * 1000,
        )
        logger.info(
            "claim_verification_completed",
            total_claims=report.total_claims,
            supported=report.supported_count,
            partial=report.partial_count,
            contradicted=report.contradicted_count,
            unsupported=report.unsupported_count,
            inferred=report.inferred_count,
            score=report.verifiability_score,
            method=report.method,
            latency_ms=report.latency_ms,
        )
        return report

    # -----------------------------------------------------------------------
    # Per-claim scoring
    # -----------------------------------------------------------------------

    def _verify_one_claim(
        self,
        claim_id: int,
        claim_text: str,
        sentence_start: int,
        sentence_end: int,
        citations: list[dict],
        claim_vec: Optional[list[float]],
        citation_vecs: Optional[list[list[float]]],
    ) -> ClaimVerification:
        claim_terms = _significant_terms(claim_text)
        claim_numbers = _numeric_tokens(claim_text)
        claim_negated = _has_negation(claim_text)

        best_idx: int = -1
        best_combined: float = 0.0
        best_similarity: float = 0.0
        best_overlap: float = 0.0
        best_numeric_match: bool = True
        best_evidence_text: str = ""

        for c_idx, citation in enumerate(citations):
            evidence_text = citation.get("snippet", "") or ""
            evidence_terms = _significant_terms(evidence_text)
            evidence_numbers = _numeric_tokens(evidence_text)

            # Lexical overlap (Jaccard-ish: how much of the claim is in evidence).
            if claim_terms:
                overlap = len(claim_terms & evidence_terms) / len(claim_terms)
            else:
                overlap = 0.0

            # Numeric tokens must round-trip — otherwise the model may have
            # invented numbers (a common medical/legal failure mode).
            if claim_numbers:
                numeric_match = claim_numbers.issubset(evidence_numbers)
            else:
                numeric_match = True

            # Embedding cosine.
            if claim_vec is not None and citation_vecs is not None and c_idx < len(citation_vecs):
                similarity = max(0.0, _cosine(claim_vec, citation_vecs[c_idx]))
            else:
                similarity = 0.0

            # Combined: weighted blend, with numeric mismatch penalty.
            if claim_vec is not None:
                combined = (
                    self.SIMILARITY_WEIGHT * similarity
                    + self.OVERLAP_WEIGHT * overlap
                )
            else:
                combined = overlap

            if claim_numbers and not numeric_match:
                combined *= self.NUMERIC_MISMATCH_PENALTY

            if combined > best_combined:
                best_combined = combined
                best_idx = c_idx
                best_similarity = similarity
                best_overlap = overlap
                best_numeric_match = numeric_match
                best_evidence_text = evidence_text

        # Verbatim fast-path: if the claim is literally contained in the
        # winning citation, it is definitively supported regardless of any
        # polarity tokens elsewhere in the chunk. This handles the common
        # extractive-RAG case where the model copy-pastes from the source.
        if best_idx >= 0 and _is_verbatim_in_evidence(claim_text, best_evidence_text):
            return ClaimVerification(
                claim_id=claim_id,
                text=claim_text,
                sentence_start=sentence_start,
                sentence_end=sentence_end,
                verdict=ClaimVerdict.SUPPORTED,
                confidence=1.0,
                best_citation_index=best_idx,
                similarity_score=round(best_similarity, 3),
                token_overlap=round(best_overlap, 3),
                numeric_match=best_numeric_match,
                reasoning="Verbatim match — claim is contained in cited evidence",
                match_type="verbatim",
            )

        # Sentence-level polarity check (replaces old chunk-level check).
        # Long evidence chunks often contain unrelated negations like
        # "Never crush, cut, or chew" — those should NOT flip the polarity
        # of an unrelated supported claim. We restrict the check to the
        # sentence in the evidence that actually overlaps with the claim.
        sentence_negated, sentence_overlap = _best_matching_sentence_polarity(
            claim_terms, best_evidence_text
        )
        polarity_flipped = (
            (claim_negated != sentence_negated)
            and best_overlap >= self.CONTRADICTION_OVERLAP
            and sentence_overlap >= 0.5  # The matched sentence must itself overlap meaningfully
        )

        # Map the (combined, polarity, numeric) tuple to a verdict.
        if polarity_flipped:
            verdict = ClaimVerdict.CONTRADICTED
            confidence = min(1.0, max(0.5, best_combined))
            reasoning = (
                f"Evidence has opposite polarity (overlap={best_overlap:.2f}, "
                f"sim={best_similarity:.2f})"
            )
        elif best_combined >= self.SUPPORT_THRESHOLD and best_numeric_match:
            verdict = ClaimVerdict.SUPPORTED
            confidence = round(best_combined, 3)
            reasoning = (
                f"Strong support (sim={best_similarity:.2f}, "
                f"overlap={best_overlap:.2f})"
            )
        elif best_combined >= self.PARTIAL_THRESHOLD:
            verdict = ClaimVerdict.PARTIAL
            confidence = round(best_combined, 3)
            if claim_numbers and not best_numeric_match:
                missing = sorted(claim_numbers - _numeric_tokens(
                    citations[best_idx].get("snippet", "") if best_idx >= 0 else ""
                ))
                reasoning = (
                    f"Numeric value(s) not found in evidence: {', '.join(missing)} "
                    f"(sim={best_similarity:.2f})"
                )
            else:
                reasoning = (
                    f"Partial overlap with evidence (sim={best_similarity:.2f}, "
                    f"overlap={best_overlap:.2f})"
                )
        elif best_combined > self.INFERRED_FLOOR:
            verdict = ClaimVerdict.INFERRED
            confidence = round(best_combined, 3)
            reasoning = (
                f"Weak signal — likely inferred rather than directly cited "
                f"(sim={best_similarity:.2f}, overlap={best_overlap:.2f})"
            )
        else:
            verdict = ClaimVerdict.UNSUPPORTED
            confidence = round(1.0 - best_combined, 3)
            reasoning = "No matching evidence found in citations"

        if best_idx < 0 or verdict == ClaimVerdict.UNSUPPORTED:
            match_type = "none"
        elif claim_vec is not None and best_similarity >= best_overlap:
            match_type = "semantic"
        else:
            match_type = "lexical"

        return ClaimVerification(
            claim_id=claim_id,
            text=claim_text,
            sentence_start=sentence_start,
            sentence_end=sentence_end,
            verdict=verdict,
            confidence=confidence,
            best_citation_index=best_idx if best_idx >= 0 else None,
            similarity_score=round(best_similarity, 3),
            token_overlap=round(best_overlap, 3),
            numeric_match=best_numeric_match,
            reasoning=reasoning,
            match_type=match_type,
        )

    # -----------------------------------------------------------------------
    # Report assembly
    # -----------------------------------------------------------------------

    def _build_report(
        self,
        verifications: list[ClaimVerification],
        method: str,
        latency_ms: float,
    ) -> VerificationReport:
        # Verdict weights for the aggregate verifiability score.
        weights = {
            ClaimVerdict.SUPPORTED: 1.0,
            ClaimVerdict.PARTIAL: 0.6,
            ClaimVerdict.INFERRED: 0.3,
            ClaimVerdict.UNSUPPORTED: 0.0,
            ClaimVerdict.CONTRADICTED: 0.0,
        }
        total = len(verifications)
        if total == 0:
            score = 0.0
        else:
            score = (sum(weights.get(v.verdict, 0.0) for v in verifications) / total) * 100

        counts = {v: 0 for v in ClaimVerdict}
        for v in verifications:
            counts[v.verdict] += 1

        supported = counts[ClaimVerdict.SUPPORTED]
        verbatim_supported = sum(
            1
            for v in verifications
            if v.verdict == ClaimVerdict.SUPPORTED and v.match_type == "verbatim"
        )
        summary = (
            f"{supported}/{total} claims verified"
            if total > 0
            else "No verifiable claims found in answer"
        )
        # Be transparent when the "verified" claims are just extractive copies:
        # a 100% score on a copy-paste answer reflects grounding, not synthesis.
        if supported > 0 and verbatim_supported == supported:
            summary += " (all verbatim from source)"
        elif verbatim_supported > 0:
            summary += f" ({verbatim_supported} verbatim from source)"
        if counts[ClaimVerdict.CONTRADICTED] > 0:
            summary += f" · {counts[ClaimVerdict.CONTRADICTED]} contradicted"

        return VerificationReport(
            verifiability_score=round(score, 1),
            total_claims=total,
            supported_count=supported,
            partial_count=counts[ClaimVerdict.PARTIAL],
            contradicted_count=counts[ClaimVerdict.CONTRADICTED],
            unsupported_count=counts[ClaimVerdict.UNSUPPORTED],
            inferred_count=counts[ClaimVerdict.INFERRED],
            verbatim_supported_count=verbatim_supported,
            claims=verifications,
            method=method,
            latency_ms=round(latency_ms, 2),
            summary=summary,
        )

    def _empty_report(self, start: float, *, method: str) -> VerificationReport:
        return VerificationReport(
            verifiability_score=0.0,
            total_claims=0,
            claims=[],
            method=method,
            latency_ms=round((time.time() - start) * 1000, 2),
            summary="No verifiable claims found in answer",
        )


# ---------------------------------------------------------------------------
# Citation normalisation helper (accepts SourceCitation models or dicts)
# ---------------------------------------------------------------------------


def _normalise_citations(citations: Sequence) -> list[dict]:
    """Coerce a sequence of SourceCitation OR dict to a uniform list[dict].

    Tolerant of partial payloads — only the `snippet` field is strictly required;
    everything else is best-effort metadata.
    """
    normalised: list[dict] = []
    for raw in citations or []:
        if raw is None:
            continue
        if isinstance(raw, dict):
            snippet = raw.get("snippet") or ""
            if not snippet:
                continue
            normalised.append({
                "snippet": snippet,
                "title": raw.get("title", ""),
                "page_number": raw.get("page_number"),
                "section_title": raw.get("section_title"),
                "score": raw.get("score", 0.0),
            })
        else:
            snippet = getattr(raw, "snippet", "") or ""
            if not snippet:
                continue
            normalised.append({
                "snippet": snippet,
                "title": getattr(raw, "title", ""),
                "page_number": getattr(raw, "page_number", None),
                "section_title": getattr(raw, "section_title", None),
                "score": getattr(raw, "score", 0.0),
            })
    return normalised


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_verifier: Optional[ClaimVerifier] = None


def get_claim_verifier() -> ClaimVerifier:
    """Return the process-wide ClaimVerifier singleton."""
    global _verifier
    if _verifier is None:
        _verifier = ClaimVerifier()
    return _verifier
