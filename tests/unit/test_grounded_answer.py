import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer1_intelligence.grounded_answer import GroundedAnswerAssembler  # noqa: E402
from src.layer3_domain.document_models import DocumentChunk, RetrievalResult  # noqa: E402


def _result(
    chunk_id: str,
    document_id: str,
    page_number: int,
    content: str,
    *,
    title: str = "Loan Agreement",
    section_title: str | None = None,
    score: float = 0.8,
) -> RetrievalResult:
    return RetrievalResult(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            tenant_id="tenant-a",
            domain="lending",
            title=title,
            source_uri=f"/docs/{document_id}.pdf",
            page_number=page_number,
            page_text=content,
            content=content,
            section_title=section_title,
            start_char=0,
            end_char=len(content),
        ),
        score=score,
        matched_terms=[],
    )


def test_grounded_answer_assembler_builds_multiple_citations():
    assembler = GroundedAnswerAssembler()
    results = [
        _result(
            "c1",
            "agreement",
            4,
            "Foreclosure charges are 2% of the outstanding principal plus taxes.",
            section_title="Foreclosure",
        ),
        _result(
            "c2",
            "sanction-letter",
            2,
            "Processing fee is collected at the time of disbursal.",
            title="Sanction Letter",
            section_title="Fees",
        ),
    ]

    context = assembler.assemble(
        "Compare foreclosure charges and processing fee.",
        results,
    )

    assert len(context.citations) == 2
    assert len(context.page_proofs) == 2
    assert len(context.evidence_groups) == 2
    assert context.context_blocks
    assert "User query" in context.context_blocks[0]


def test_grounded_answer_assembler_groups_same_page_citations_together():
    assembler = GroundedAnswerAssembler()
    results = [
        _result(
            "c1",
            "agreement",
            5,
            "Late payment fee is 500 rupees after the grace period.",
            section_title="Charges",
        ),
        _result(
            "c2",
            "agreement",
            5,
            "Foreclosure request takes seven working days to process.",
            section_title="Charges",
        ),
    ]

    context = assembler.assemble("What charges and timelines apply?", results)

    assert len(context.citations) == 2
    assert len(context.page_proofs) == 1
    assert len(context.evidence_groups) == 1
    assert context.evidence_groups[0].citation_indices == [0, 1]


def test_grounded_answer_assembler_trims_long_snippets():
    assembler = GroundedAnswerAssembler()
    long_content = (
        "This clause explains the repayment schedule in detail. " * 20
    ).strip()

    context = assembler.assemble(
        "Summarize the repayment schedule.",
        [_result("c1", "agreement", 3, long_content, section_title="Repayment Schedule")],
    )

    assert len(context.citations[0].snippet) <= assembler.config.snippet_char_limit
    assert context.citations[0].snippet_truncated is True


def test_grounded_answer_assembler_exposes_full_page_proof_payload():
    assembler = GroundedAnswerAssembler()
    result = _result(
        "c1",
        "agreement",
        4,
        "Foreclosure charges are 2% of the outstanding principal plus taxes.",
        section_title="Foreclosure",
    )

    context = assembler.assemble("What are the foreclosure charges?", [result])

    assert len(context.page_proofs) == 1
    proof = context.page_proofs[0]
    assert proof.page_number == 4
    assert proof.page_text == result.chunk.page_text
    assert proof.highlights
    assert proof.citation_indices == [0]


def test_grounded_answer_assembler_selects_query_focused_sentence_from_long_chunk():
    """The snippet must surface the focal answer-bearing sentence, but is now
    a multi-sentence window (Bug F fix) so adjacent context like a list
    continuation or follow-up clause travels with it. The test pins the
    *substantive* contract: the answer sentence is present and highlighted.
    """
    assembler = GroundedAnswerAssembler()
    content = (
        "Right against Exploitation 23. Traffic in human beings and forced labour are prohibited. "
        "24. No child below the age of fourteen years shall be employed to work in any factory or mine or engaged in any other hazardous employment. "
        "Right to Freedom of Religion 25. All persons are equally entitled to freedom of conscience."
    )

    context = assembler.assemble(
        "What is the minimum age of employment to work in any factory?",
        [_result("c1", "constitution", 13, content, title="Constitution of India")],
    )

    snippet = context.citations[0].snippet
    # The focal sentence — including its number "24." and the literal
    # "fourteen years" answer — must be in the snippet.
    assert "24. No child below" in snippet
    assert "fourteen years" in snippet
    # Page proof must still carry highlight spans, including one covering
    # the focal sentence.
    proof = context.page_proofs[0]
    assert proof.highlights
    assert any("fourteen years" in h.text for h in proof.highlights)


def test_grounded_answer_assembler_deduplicates_overlapping_same_page_snippets():
    assembler = GroundedAnswerAssembler()
    content = (
        "24. No child below the age of fourteen years shall be employed to work in any factory or mine."
    )

    context = assembler.assemble(
        "What is the minimum age of employment to work in any factory?",
        [
            _result("c1", "constitution", 13, content, title="Constitution of India", score=0.9),
            _result("c2", "constitution", 13, content, title="Constitution of India", score=0.86),
        ],
    )

    assert len(context.citations) == 1
    assert len(context.page_proofs) == 1


def test_grounded_answer_assembler_avoids_tiny_medical_highlight_fragments():
    assembler = GroundedAnswerAssembler()
    content = (
        "DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE). "
        "Metformin. "
        "The recommended starting dose is 500 mg twice daily with meals. "
        "The maximum recommended daily dose is 2,000 mg."
    )

    context = assembler.assemble(
        "What is the maximum dose of Metformin?",
        [_result("c1", "metformin", 5, content, title="Metformin.pdf", section_title="Dosage and Administration")],
    )

    assert "maximum recommended daily dose" in context.citations[0].snippet.lower()
    assert context.citations[0].snippet != "Metformin."
    assert context.page_proofs[0].highlights
    assert len(context.page_proofs[0].highlights[0].text.split()) > 3


def test_pharma_snippet_window_keeps_focal_and_neighbour_sentences():
    """Bug F regression: the previous single-sentence snippet would pick the
    section lead-in and discard the answer. The new multi-sentence window
    must surface BOTH the focal answer-bearing sentence and at least one
    neighbouring sentence so users see the answer in context.
    """
    assembler = GroundedAnswerAssembler()
    content = (
        "2.2 Recommended Dosage: Adults and Adolescents. "
        "Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. "
        "Maximum single dose: 1000 mg. "
        "Minimum dosing interval: 4 hours. "
        "Maximum daily dose: 4000 mg per day."
    )

    context = assembler.assemble(
        "What is the minimum dosing interval for acetaminophen injection in adults?",
        [
            _result(
                "c1",
                "acet",
                2,
                content,
                title="Acetaminophen.pdf",
                section_title="DOSAGE AND ADMINISTRATION",
            )
        ],
    )

    snippet = context.citations[0].snippet
    # Focal answer sentence is present
    assert "Minimum dosing interval: 4 hours" in snippet
    # AND at least one neighbour travels with it (multi-sentence window)
    has_neighbour = (
        "Maximum single dose" in snippet
        or "Maximum daily dose" in snippet
        or "every 6 hours" in snippet
    )
    assert has_neighbour, f"snippet did not include neighbouring context: {snippet!r}"


def test_pharma_chunker_does_not_emit_article_section_titles_for_general_domain():
    """Bug E regression: the chunker mislabelled pharma subsections like
    "2.5 Instructions for Intravenous Administration." as "Article 2".
    Verify the chunker now skips article-style chunking for non-legal
    domains so pharma section titles stay intact.
    """
    from src.layer3_domain.document_ingestion import DocumentChunker
    from src.layer3_domain.document_models import IngestedDocument, IngestedPage

    pharma_page = IngestedPage(
        document_id="omeprazole",
        tenant_id="default",
        domain="general",
        title="Omeprazole.pdf",
        source_uri="omeprazole.pdf",
        source_type="pdf",
        page_number=4,
        text=(
            "2. Open the capsule and carefully empty ALL pellets onto the applesauce. "
            "3. Mix the pellets with the applesauce and swallow IMMEDIATELY with a glass of cool water. "
            "4. Do not chew or crush the pellets. "
            "5. Do not store the mixture for future use."
        ),
        section_title="DOSAGE AND ADMINISTRATION",
    )
    document = IngestedDocument(
        document_id="omeprazole",
        tenant_id="default",
        domain="general",
        title="Omeprazole.pdf",
        source_uri="omeprazole.pdf",
        pages=[pharma_page],
    )
    chunks = DocumentChunker().chunk_document(document)

    assert chunks
    for chunk in chunks:
        assert not (chunk.section_title or "").startswith("Article "), (
            f"pharma chunk leaked Constitution-style article section title: "
            f"{chunk.section_title!r}"
        )


def test_pharma_chunker_still_emits_article_chunks_for_law_domain():
    """Counterpart to the previous test: legal documents must keep the
    article-style chunking so Constitution-of-India retrieval still works.
    """
    from src.layer3_domain.document_ingestion import DocumentChunker
    from src.layer3_domain.document_models import IngestedDocument, IngestedPage

    legal_page = IngestedPage(
        document_id="constitution",
        tenant_id="default",
        domain="law",
        title="Constitution of India",
        source_uri="constitution.pdf",
        source_type="pdf",
        page_number=10,
        text=(
            "352. Proclamation of Emergency. "
            "If the President is satisfied that a grave emergency exists whereby the security of "
            "India or of any part of the territory thereof is threatened, he may make a Proclamation "
            "to that effect."
        ),
    )
    document = IngestedDocument(
        document_id="constitution",
        tenant_id="default",
        domain="law",
        title="Constitution of India",
        source_uri="constitution.pdf",
        pages=[legal_page],
    )
    chunks = DocumentChunker().chunk_document(document)

    assert chunks
    assert any((chunk.section_title or "").startswith("Article 352") for chunk in chunks)


def test_pharma_table_answer_highlights_multiple_sentences():
    """Bug G regression: page proofs used to carry only the focal-snippet
    highlight (~one sentence). Verify multi-sentence highlights now cover
    every answer-bearing sentence in a table-like chunk so the UI shows
    meaningful highlight coverage instead of half a line.
    """
    assembler = GroundedAnswerAssembler()
    content = (
        "5.2 Serotonin Syndrome. "
        "SSRIs including sertraline can precipitate serotonin syndrome, a potentially life-threatening condition. "
        "Mental status: Agitation, hallucinations, delirium, coma. "
        "Autonomic instability: Tachycardia, labile blood pressure, dizziness, diaphoresis, flushing, hyperthermia. "
        "Neuromuscular: Tremor, rigidity, myoclonus, hyperreflexia, incoordination. "
        "Gastrointestinal: Nausea, vomiting, diarrhea."
    )

    context = assembler.assemble(
        "What are the neuromuscular and autonomic instability signs of Serotonin Syndrome?",
        [
            _result(
                "c1",
                "sertraline",
                6,
                content,
                title="Sertraline.pdf",
                section_title="WARNINGS AND PRECAUTIONS",
            )
        ],
    )

    proof = context.page_proofs[0]
    # Multi-sentence highlights — at minimum the autonomic and neuromuscular
    # rows of the table-like layout should both be highlighted.
    highlight_text = " ".join(h.text for h in proof.highlights).lower()
    assert "autonomic instability" in highlight_text or "tachycardia" in highlight_text
    assert "neuromuscular" in highlight_text or "myoclonus" in highlight_text
    # And there must be more than one highlight span, not just the focal one.
    assert len(proof.highlights) >= 2


def test_grounding_gate_no_longer_rejects_on_missing_numeric_attribute():
    """Bug A regression: previously, any numeric query token (e.g. "45" in
    "for a 45 kg patient") missing from the top-5 chunks hard-rejected the
    grounding gate. The number is a patient attribute that almost never
    appears verbatim in chunks (which contain thresholds like "<50 kg"),
    so the rule produced false negatives. The gate must now allow such
    queries through when the chunks are otherwise relevant.
    """
    from src.layer1_intelligence.rag_service import _has_grounded_support

    chunk_content = (
        "Adults and adolescents weighing under 50 kg: 15 mg/kg every 6 hours OR 12.5 mg/kg every 4 hours. "
        "Maximum single dose: 15 mg/kg. Minimum dosing interval: 4 hours. "
        "Maximum daily dose: 75 mg/kg per day (all routes + all acetaminophen-containing products)."
    )
    result = _result(
        "c1",
        "acet",
        2,
        chunk_content,
        title="Acetaminophen.pdf",
        section_title="DOSAGE AND ADMINISTRATION",
        score=0.85,
    )

    # The query asks about a 45 kg patient — "45" is NOT in the chunk
    # (chunk says "under 50 kg"). Pre-fix this hard-rejected. Post-fix the
    # threshold ladder evaluates the result on its score+coverage merits.
    assert _has_grounded_support(
        "What is the maximum daily dose of acetaminophen for an adult weighing 45 kg?",
        [result],
    ) is True


def test_weight_range_45kg_query_highlights_only_under_50kg_paragraph():
    """Bug H regression: a query about a 45 kg patient against a chunk
    that contains BOTH the ≥50 kg dosing paragraph AND the <50 kg dosing
    paragraph must produce highlights ONLY in the <50 kg section. The
    pre-fix behaviour highlighted both paragraphs because they share
    most query tokens (maximum, daily, dose, mg, kg).
    """
    assembler = GroundedAnswerAssembler()
    content = (
        "Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. "
        "Maximum single dose: 1000 mg. "
        "Minimum dosing interval: 4 hours. "
        "Maximum daily dose: 4000 mg per day (all routes + all acetaminophen-containing products). "
        "Adults and adolescents weighing under 50 kg: 15 mg/kg every 6 hours OR 12.5 mg/kg every 4 hours. "
        "Maximum single dose: 15 mg/kg. "
        "Minimum dosing interval: 4 hours. "
        "Maximum daily dose: 75 mg/kg per day (all routes + all acetaminophen-containing products)."
    )

    context = assembler.assemble(
        "What is the maximum daily dose of acetaminophen injection for an adult weighing 45 kg?",
        [
            _result(
                "c1",
                "acetaminophen",
                2,
                content,
                title="Acetaminophen.pdf",
                section_title="DOSAGE AND ADMINISTRATION",
            )
        ],
    )

    proof = context.page_proofs[0]
    assert proof.highlights, "expected at least one highlight on page 2"

    # The CORRECT-range answer ("75 mg/kg per day") must be highlighted.
    highlight_text = " | ".join(h.text for h in proof.highlights)
    assert "75 mg/kg per day" in highlight_text, (
        f"expected the <50 kg max daily dose to be highlighted, got: {highlight_text!r}"
    )
    # The WRONG-range answer ("4000 mg per day") must NOT be highlighted.
    assert "4000 mg per day" not in highlight_text, (
        f"≥50 kg dosing leaked into highlights for a 45 kg query: {highlight_text!r}"
    )


def test_weight_range_70kg_query_highlights_only_over_50kg_paragraph():
    """Counterpart to the previous test: a 70 kg query must select the
    ≥50 kg paragraph and exclude the <50 kg one. Verifies the weight-range
    direction works both ways.
    """
    assembler = GroundedAnswerAssembler()
    content = (
        "Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. "
        "Maximum single dose: 1000 mg. "
        "Minimum dosing interval: 4 hours. "
        "Maximum daily dose: 4000 mg per day (all routes + all acetaminophen-containing products). "
        "Adults and adolescents weighing under 50 kg: 15 mg/kg every 6 hours OR 12.5 mg/kg every 4 hours. "
        "Maximum single dose: 15 mg/kg. "
        "Minimum dosing interval: 4 hours. "
        "Maximum daily dose: 75 mg/kg per day (all routes + all acetaminophen-containing products)."
    )

    context = assembler.assemble(
        "What is the maximum daily dose of acetaminophen injection for an adult weighing 70 kg?",
        [
            _result(
                "c1",
                "acetaminophen",
                2,
                content,
                title="Acetaminophen.pdf",
                section_title="DOSAGE AND ADMINISTRATION",
            )
        ],
    )

    highlight_text = " | ".join(h.text for h in context.page_proofs[0].highlights)
    assert "4000 mg per day" in highlight_text, (
        f"expected the ≥50 kg max daily dose to be highlighted, got: {highlight_text!r}"
    )
    assert "75 mg/kg per day" not in highlight_text, (
        f"<50 kg dosing leaked into highlights for a 70 kg query: {highlight_text!r}"
    )


def test_highlight_count_capped_to_focused_top_n():
    """Bug H regression: highlights are capped at the configured
    max_highlights_per_proof (default 5) and only sentences scoring
    within `highlight_relative_score_floor` of the focal score qualify.
    Previous behaviour emitted up to 12 highlights per page including
    weakly-matching sentences, which carpeted most of the page.
    """
    assembler = GroundedAnswerAssembler()
    # 10 sentences, only a few should be answer-bearing for the query.
    content = " ".join(
        [
            "ZOLOFT is contraindicated in patients taking MAOIs.",
            "Pimozide is also contraindicated.",
            "Hypersensitivity reactions have been reported with sertraline.",
            "Concomitant use of disulfiram is contraindicated for the oral solution.",
            "Sertraline is a selective serotonin reuptake inhibitor.",
            "The drug is metabolised in the liver.",
            "Clinical trials enrolled over 3,000 adult patients.",
            "Common adverse reactions include nausea and insomnia.",
            "ZOLOFT may cause sexual dysfunction in some patients.",
            "The half-life of sertraline is approximately 26 hours.",
        ]
    )
    context = assembler.assemble(
        "Which drugs is ZOLOFT contraindicated with?",
        [
            _result(
                "c1",
                "sertraline",
                5,
                content,
                title="Sertraline.pdf",
                section_title="CONTRAINDICATIONS",
            )
        ],
    )

    proof = context.page_proofs[0]
    assert len(proof.highlights) <= assembler.config.max_highlights_per_proof
    # The contraindication sentences (focal area) must be highlighted.
    highlight_text = " | ".join(h.text for h in proof.highlights).lower()
    assert "maois" in highlight_text or "contraindicated" in highlight_text


def test_choose_model_id_prefers_free_api_when_active(monkeypatch):
    """Bug I regression: GatewayAnswerGenerator._choose_model_id must
    prefer an active free-API model (Groq / Gemini / OpenRouter) over
    the configured local default. Pre-fix the method returned
    settings.DEFAULT_TEXT_MODEL unconditionally, so users with valid
    free-API keys still saw every grounded answer routed to Ollama.
    """
    from src.layer1_intelligence.rag_service import GatewayAnswerGenerator

    # Build a fake registry that reports groq-llama-3.3-70b-free as
    # active and everything else as inactive.
    class _FakeModel:
        def __init__(self, model_id: str, is_active: bool) -> None:
            self.model_id = model_id
            self.is_active = is_active

    class _FakeRegistry:
        def __init__(self, active_id: str | None) -> None:
            self.active_id = active_id

        def get_model(self, model_id: str) -> _FakeModel:
            return _FakeModel(model_id, model_id == self.active_id)

    class _FakeGateway:
        def __init__(self, active_id: str | None) -> None:
            self.registry = _FakeRegistry(active_id)

        async def complete(self, request):  # pragma: no cover - not used here
            raise NotImplementedError

    # Force PREFER_FREE_API_PROVIDERS=True via the settings module the
    # rag_service module already imported at top.
    import src.layer1_intelligence.rag_service as rag_service
    monkeypatch.setattr(rag_service.settings, "PREFER_FREE_API_PROVIDERS", True)
    monkeypatch.setattr(rag_service.settings, "DEFAULT_TEXT_MODEL", "ollama-qwen3-8b")

    # Case 1: Groq 70B is active → it must be picked.
    gen = GatewayAnswerGenerator(gateway=_FakeGateway("groq-llama-3.3-70b-free"))
    assert gen._choose_model_id("any query") == "groq-llama-3.3-70b-free"

    # Case 2: only Gemini is active → it must be picked.
    gen = GatewayAnswerGenerator(gateway=_FakeGateway("gemini-2.0-flash-free"))
    assert gen._choose_model_id("any query") == "gemini-2.0-flash-free"

    # Case 3: nothing is active → fall back to DEFAULT_TEXT_MODEL.
    gen = GatewayAnswerGenerator(gateway=_FakeGateway(None))
    assert gen._choose_model_id("any query") == "ollama-qwen3-8b"


def test_choose_model_id_respects_explicit_model_id_argument():
    """When the caller passes an explicit model_id to GatewayAnswerGenerator,
    that wins over the auto-selection (used by the orchestrator to pin a
    specific model per request).
    """
    from src.layer1_intelligence.rag_service import GatewayAnswerGenerator

    class _FakeGateway:
        def __init__(self) -> None:
            self.registry = None

    gen = GatewayAnswerGenerator(gateway=_FakeGateway(), model_id="my-pinned-model")
    # generate() uses self.model_id when set, never calls _choose_model_id.
    # Verify by inspecting the attribute directly.
    assert gen.model_id == "my-pinned-model"


def test_grounded_answer_assembler_selects_absorption_food_sentence():
    assembler = GroundedAnswerAssembler()
    content = (
        "Drug: Levothyroxine Sodium (Synthroid). "
        "Drug interactions may require dose adjustment. "
        "T4 absorption is increased by fasting and decreased by certain foods such as soybeans."
    )

    context = assembler.assemble(
        "What food affects SYNTHROID absorption?",
        [_result("c1", "levothyroxine", 20, content, title="Levothyroxine.pdf", section_title="Clinical Pharmacology")],
    )

    assert "soybeans" in context.citations[0].snippet.lower()
    assert "absorption" in context.citations[0].snippet.lower()
    assert context.page_proofs[0].highlights
