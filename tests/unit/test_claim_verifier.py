"""
Unit tests for the Verifiable Reasoning engine
(src/layer1_intelligence/claim_verifier.py).

These tests deliberately use `use_embeddings=False` so they run with zero
network/Ollama dependency — the lexical-only path is enough to exercise
decomposition, scoring, polarity, and aggregation logic.
"""

from __future__ import annotations

import pytest

from src.layer1_intelligence.claim_verifier import (
    ClaimDecomposer,
    ClaimVerdict,
    ClaimVerifier,
    VerificationReport,
)
from src.layer3_domain.document_models import HighlightSpan, SourceCitation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _citation(snippet: str, *, title: str = "Doc", page: int = 1, score: float = 0.9) -> SourceCitation:
    """Build a minimal SourceCitation for tests."""
    return SourceCitation(
        document_id="doc-1",
        chunk_id=f"chunk-{hash(snippet) & 0xffff}",
        title=title,
        source_uri="memory://test",
        page_number=page,
        section_title=None,
        snippet=snippet,
        snippet_truncated=False,
        score=score,
        highlights=[HighlightSpan(start_char=0, end_char=min(20, len(snippet)), text=snippet[:20])],
    )


# ---------------------------------------------------------------------------
# ClaimDecomposer
# ---------------------------------------------------------------------------


class TestClaimDecomposer:
    def test_empty_answer_returns_no_claims(self) -> None:
        assert ClaimDecomposer().decompose("") == []
        assert ClaimDecomposer().decompose("   \n\n  ") == []

    def test_too_short_sentences_are_filtered(self) -> None:
        assert ClaimDecomposer().decompose("Yes.") == []
        assert ClaimDecomposer().decompose("OK.") == []

    def test_multi_sentence_split(self) -> None:
        # Each sentence must carry ≥3 significant content terms (post stopwords)
        # to count as a verifiable claim. Pronoun-led sentences are intentionally
        # filtered because they require coreference resolution to verify.
        answer = (
            "Article 360 deals with Financial Emergency in India. "
            "The President of India can proclaim such an emergency. "
            "The proclamation must be approved by Parliament within two months."
        )
        claims = ClaimDecomposer().decompose(answer)
        assert len(claims) == 3
        assert "Financial Emergency" in claims[0][0]
        assert "President" in claims[1][0]
        assert "Parliament" in claims[2][0]

    def test_pronoun_led_short_sentences_are_filtered(self) -> None:
        # "It can be proclaimed by the President" only has 2 significant terms
        # after stopwords (proclaimed, president), so the verifier treats it
        # as a non-claim — coreference is left to upstream stages.
        answer = (
            "Article 360 deals with Financial Emergency in India. "
            "It can be proclaimed by the President."
        )
        claims = ClaimDecomposer().decompose(answer)
        assert len(claims) == 1
        assert "Financial Emergency" in claims[0][0]

    def test_meta_sentences_are_filtered(self) -> None:
        answer = (
            "However, this might be relevant. "
            "In conclusion, the answer follows the rule. "
            "Article 360 deals with Financial Emergency in India."
        )
        claims = ClaimDecomposer().decompose(answer)
        # The transition sentences should be skipped, only the factual claim kept.
        assert len(claims) == 1
        assert "Financial Emergency" in claims[0][0]

    def test_offsets_round_trip_into_original_text(self) -> None:
        answer = (
            "Article 360 deals with Financial Emergency in India. "
            "It can be proclaimed by the President."
        )
        claims = ClaimDecomposer().decompose(answer)
        for text, start, end in claims:
            assert answer[start:end] == text

    def test_max_claims_cap_is_enforced(self) -> None:
        # 50 short factual sentences
        sentence = "The committee adopted resolution number {n} on the matter."
        answer = " ".join(sentence.format(n=i) for i in range(50))
        claims = ClaimDecomposer().decompose(answer)
        assert len(claims) <= ClaimDecomposer.MAX_CLAIMS


# ---------------------------------------------------------------------------
# ClaimVerifier — lexical-only path (no embedding/network needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestClaimVerifierLexical:
    async def _verify(self, answer: str, citations: list) -> VerificationReport:
        return await ClaimVerifier().verify(
            answer=answer,
            citations=citations,
            use_embeddings=False,
        )

    async def test_empty_answer_returns_empty_report(self) -> None:
        report = await self._verify("", [_citation("anything goes here")])
        assert report.total_claims == 0
        assert report.verifiability_score == 0.0
        assert report.method == "lexical-only"

    async def test_no_citations_marks_all_claims_unsupported(self) -> None:
        answer = "Article 360 deals with Financial Emergency in India."
        report = await self._verify(answer, [])
        assert report.total_claims == 1
        assert report.unsupported_count == 1
        assert report.method == "skipped_no_citations"
        assert report.claims[0].verdict == ClaimVerdict.UNSUPPORTED
        assert report.claims[0].best_citation_index is None

    async def test_supported_claim_is_recognised(self) -> None:
        answer = "Article 360 deals with Financial Emergency in India."
        citations = [
            _citation(
                "Article 360 deals with Financial Emergency in India and "
                "describes how the President may proclaim it."
            )
        ]
        report = await self._verify(answer, citations)
        assert report.total_claims == 1
        verdict = report.claims[0].verdict
        # Lexical overlap is very high (~all significant terms present).
        assert verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.PARTIAL}
        assert report.claims[0].best_citation_index == 0
        assert report.claims[0].token_overlap >= 0.7

    async def test_unsupported_claim_when_evidence_unrelated(self) -> None:
        answer = "Quantum entanglement allows faster-than-light communication."
        citations = [
            _citation("Article 360 deals with Financial Emergency in India.")
        ]
        report = await self._verify(answer, citations)
        assert report.total_claims == 1
        assert report.claims[0].verdict in {ClaimVerdict.UNSUPPORTED, ClaimVerdict.INFERRED}
        # Token overlap should be near zero.
        assert report.claims[0].token_overlap <= 0.2

    async def test_numeric_mismatch_dampens_score(self) -> None:
        # The claim invents a wrong number. Even with high textual overlap,
        # the numeric mismatch should knock it out of SUPPORTED into PARTIAL.
        answer = "The maximum daily dose of paracetamol is 8000 milligrams for adults."
        citations = [
            _citation(
                "The maximum daily dose of paracetamol is 4000 milligrams "
                "for adults under standard guidelines."
            )
        ]
        report = await self._verify(answer, citations)
        claim = report.claims[0]
        assert claim.verdict in {ClaimVerdict.PARTIAL, ClaimVerdict.UNSUPPORTED, ClaimVerdict.INFERRED}
        assert claim.numeric_match is False

    async def test_negation_polarity_flip_is_contradiction(self) -> None:
        # Claim has high overlap with evidence BUT opposite polarity → contradicted.
        answer = "The proclamation cannot be approved by Parliament within two months."
        citations = [
            _citation(
                "The proclamation must be approved by Parliament within two months "
                "after the proclamation is issued."
            )
        ]
        report = await self._verify(answer, citations)
        verdict = report.claims[0].verdict
        # Either contradicted (preferred) or partial — both acceptable, but
        # NOT supported.
        assert verdict in {ClaimVerdict.CONTRADICTED, ClaimVerdict.PARTIAL}
        assert verdict != ClaimVerdict.SUPPORTED

    async def test_unrelated_negation_in_long_chunk_does_not_falsely_contradict(self) -> None:
        """
        Regression: a long evidence chunk containing negations elsewhere
        (e.g. drug labels with 'Never crush', 'Do not take') must NOT flip
        the polarity of an unrelated supported claim. The polarity check
        is restricted to the best-matching sentence within the evidence.

        Scenario from a real demo run (paracetamol/metformin/Lipitor RAG)
        where claims were verbatim copies of chunks but were being marked
        contradicted because of unrelated 'Never crush, cut, or chew'
        sentences elsewhere in the same chunk.
        """
        answer = (
            "The recommended starting dosage of LIPITOR is 10 mg to 20 mg once daily."
        )
        citations = [_citation(
            "Adult Dosage and Administration. Starting dose: 500 mg orally once daily. "
            "Administration: Swallow tablets whole. Never crush, cut, or chew. "
            "The recommended starting dosage of LIPITOR is 10 mg to 20 mg once daily. "
            "Missed dose: Do not take two doses the same day."
        )]
        report = await self._verify(answer, citations)
        # The claim is verbatim-supported by the LIPITOR sentence in the chunk.
        # The unrelated 'Never crush' / 'Do not take' negations elsewhere in
        # the chunk must not flip the polarity.
        assert report.claims[0].verdict == ClaimVerdict.SUPPORTED
        assert report.claims[0].verdict != ClaimVerdict.CONTRADICTED
        assert "Verbatim match" in report.claims[0].reasoning or report.claims[0].verdict == ClaimVerdict.SUPPORTED

    async def test_verbatim_match_overrides_polarity_noise(self) -> None:
        """
        Verbatim fast-path: when a claim is a literal substring of the
        evidence, it is supported regardless of any negation tokens
        elsewhere in the chunk.
        """
        claim = "Therapeutic response is seen within 2 weeks; maximum response is usually achieved within 4 weeks."
        evidence = (
            "Background section. Do not exceed recommended dose. "
            f"{claim} "
            "If side effects occur, discontinue use immediately."
        )
        report = await self._verify(claim, [_citation(evidence)])
        assert report.claims[0].verdict == ClaimVerdict.SUPPORTED
        assert "Verbatim" in report.claims[0].reasoning

    async def test_mixed_answer_yields_mixed_verdicts(self) -> None:
        answer = (
            "Article 360 deals with Financial Emergency in India. "
            "Quantum entanglement allows faster-than-light communication."
        )
        citations = [
            _citation(
                "Article 360 deals with Financial Emergency in India and "
                "describes how the President may proclaim it."
            )
        ]
        report = await self._verify(answer, citations)
        assert report.total_claims == 2
        # One supported / partial, one unsupported / inferred.
        verdicts = {c.verdict for c in report.claims}
        assert ClaimVerdict.UNSUPPORTED in verdicts or ClaimVerdict.INFERRED in verdicts

    async def test_score_aggregation_and_summary(self) -> None:
        answer = (
            "Article 360 deals with Financial Emergency in India. "
            "Quantum entanglement allows faster-than-light communication."
        )
        citations = [
            _citation(
                "Article 360 deals with Financial Emergency in India and "
                "describes how the President may proclaim it."
            )
        ]
        report = await self._verify(answer, citations)
        # Score should be between 0 and 100, and the summary should reference
        # the supported/total format.
        assert 0.0 <= report.verifiability_score <= 100.0
        assert "/" in report.summary
        # Counts must add up to total.
        total = (
            report.supported_count + report.partial_count + report.contradicted_count
            + report.unsupported_count + report.inferred_count
        )
        assert total == report.total_claims


# ---------------------------------------------------------------------------
# ClaimVerifier — accepts both SourceCitation models AND raw dicts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestClaimVerifierShapeFlexibility:
    async def test_accepts_dict_citations(self) -> None:
        answer = "Article 360 deals with Financial Emergency in India."
        dict_citations = [
            {"snippet": "Article 360 deals with Financial Emergency in India.",
             "title": "Constitution", "page_number": 14, "score": 0.9},
        ]
        report = await ClaimVerifier().verify(
            answer=answer,
            citations=dict_citations,
            use_embeddings=False,
        )
        assert report.total_claims == 1
        assert report.claims[0].best_citation_index == 0

    async def test_skips_citations_without_snippet(self) -> None:
        answer = "Article 360 deals with Financial Emergency in India."
        bad_citations = [{"title": "no snippet here"}, {"snippet": ""}]
        report = await ClaimVerifier().verify(
            answer=answer,
            citations=bad_citations,
            use_embeddings=False,
        )
        # Empty/snippet-less citations are dropped → falls back to "no citations".
        assert report.method == "skipped_no_citations"
        assert report.unsupported_count == 1
