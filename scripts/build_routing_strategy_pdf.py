"""
Generate Routing_Strategy.pdf — a multi-page document explaining the
elite 9-layer adaptive routing pipeline in src/layer0_model_infra/.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(__file__).resolve().parent.parent / "Routing_Strategy.pdf"

# ───────────────────────── Styles ─────────────────────────
styles = getSampleStyleSheet()

H_TITLE = ParagraphStyle(
    "HTitle",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=26,
    leading=32,
    textColor=colors.HexColor("#0d2f5e"),
    spaceAfter=6,
)
H_SUB = ParagraphStyle(
    "HSub",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=12,
    leading=16,
    textColor=colors.HexColor("#5a5a5a"),
    spaceAfter=24,
)
H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=18,
    leading=22,
    textColor=colors.HexColor("#0d2f5e"),
    spaceBefore=14,
    spaceAfter=10,
)
H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=14,
    leading=18,
    textColor=colors.HexColor("#1a4d8f"),
    spaceBefore=12,
    spaceAfter=6,
)
H3 = ParagraphStyle(
    "H3",
    parent=styles["Heading3"],
    fontName="Helvetica-Bold",
    fontSize=11.5,
    leading=15,
    textColor=colors.HexColor("#2a5a8f"),
    spaceBefore=8,
    spaceAfter=4,
)
BODY = ParagraphStyle(
    "Body",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=10.5,
    leading=15,
    alignment=TA_LEFT,
    spaceAfter=6,
)
BULLET = ParagraphStyle(
    "Bullet",
    parent=BODY,
    leftIndent=18,
    bulletIndent=6,
    spaceAfter=3,
)
NOTE = ParagraphStyle(
    "Note",
    parent=BODY,
    fontSize=9.5,
    textColor=colors.HexColor("#6a6a6a"),
    leftIndent=12,
    rightIndent=12,
    spaceBefore=4,
    spaceAfter=10,
    borderPadding=6,
    backColor=colors.HexColor("#f4f6fa"),
    borderColor=colors.HexColor("#cdd5e3"),
    borderWidth=0.5,
)
CODE = ParagraphStyle(
    "Code",
    parent=styles["Code"],
    fontName="Courier",
    fontSize=8.5,
    leading=11,
    textColor=colors.HexColor("#1a1a1a"),
    backColor=colors.HexColor("#f6f6f6"),
    borderColor=colors.HexColor("#dddddd"),
    borderWidth=0.5,
    borderPadding=8,
    spaceBefore=4,
    spaceAfter=10,
)

# ───────────────────────── Helpers ─────────────────────────
def p(text):
    return Paragraph(text, BODY)


def h1(text):
    return Paragraph(text, H1)


def h2(text):
    return Paragraph(text, H2)


def h3(text):
    return Paragraph(text, H3)


def bullets(items):
    out = []
    for item in items:
        out.append(Paragraph(f"&bull;&nbsp;&nbsp;{item}", BULLET))
    return out


def note(text):
    return Paragraph(text, NOTE)


def code(text):
    return Preformatted(text, CODE)


def make_table(rows, col_widths, header=True):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3cf")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
    ]
    if header:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d2f5e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(cmds))
    return t


# ───────────────────────── Document body ─────────────────────────
story = []

# === Cover ===
story.append(Spacer(1, 4 * cm))
story.append(Paragraph("Enterprise AI Platform", H_SUB))
story.append(Paragraph("Model Routing Strategy", H_TITLE))
story.append(
    Paragraph(
        "The Elite 9-Layer Adaptive Routing Pipeline &mdash; "
        "complete technical walkthrough.",
        H_SUB,
    )
)
story.append(Spacer(1, 2 * cm))
story.append(
    Paragraph(
        "<b>Scope.</b> This document explains how the platform decides which "
        "LLM to call for each incoming request, how it validates the answer, "
        "and how it learns from every decision. It covers every layer of the "
        "pipeline in <font color='#0d2f5e'>src/layer0_model_infra/</font>, "
        "from the trivial-query bypass to the asynchronous telemetry feedback "
        "loop.",
        BODY,
    )
)
story.append(Spacer(1, 0.6 * cm))
story.append(
    Paragraph(
        "<b>Audience.</b> Engineers, reviewers and stakeholders who need to "
        "understand the routing decision chain in full &mdash; including the "
        "policy rules that override the learned policy.",
        BODY,
    )
)
story.append(PageBreak())

# === Table of contents (manual) ===
story.append(h1("Contents"))
toc_rows = [
    ["#", "Section", "Layer"],
    ["1", "The big picture", "&mdash;"],
    ["2", "Pipeline inputs", "Entry"],
    ["3", "Fast Path Bypass", "Layer 0"],
    ["4", "Modality Gate", "Layer 1"],
    ["5", "Input Signal Extractor", "Layer 1.5"],
    ["6", "Semantic Memory Cache", "Layer 2"],
    ["7", "Fast Triage &amp; Complexity Classifier", "Layer 3"],
    ["8", "Uncertainty Estimator", "Layer 4"],
    ["9", "Tier Selection &amp; Candidate Filtering", "Pre-bandit"],
    ["10", "Bandit Router (Thompson Sampling)", "Layer 5"],
    ["11", "Benchmark Router (advisor)", "Sidecar"],
    ["12", "Test-Time Compute", "Layer 6"],
    ["13", "Quality Evaluator", "Layer 7"],
    ["14", "Escalation Engine", "Layer 8"],
    ["15", "Telemetry &amp; Feedback Loop", "Layer 9"],
    ["16", "Model Registry &amp; Commercial Profiles", "Sidecar"],
    ["17", "End-to-end worked example", "&mdash;"],
    ["18", "Why this design", "&mdash;"],
]
toc_paragraphs = [[Paragraph(c, BODY) for c in row] for row in toc_rows]
story.append(make_table(toc_paragraphs, col_widths=[1.5 * cm, 11 * cm, 4 * cm]))
story.append(PageBreak())

# === 1. Big picture ===
story.append(h1("1. The big picture"))
story.append(
    p(
        "The router orchestrator lives in "
        "<font color='#0d2f5e'>src/layer0_model_infra/router.py</font>. "
        "Entry point: <font color='#0d2f5e'>ModelRouter.route(query, &hellip;)</font>. "
        "The pipeline runs every layer except when an upstream layer short-circuits "
        "the request &mdash; the Fast Path bypass and Semantic Memory cache are "
        "the two early exits."
    )
)
story.append(
    code(
        """USER QUERY + (images? audio? video? files?)
+ user_tier, budget_remaining, history, force_model_id
                       |
                       v
   force_model_id set? -- yes --> forced decision -> return
                       |
                       v
+-----------------------------------------------------------+
| LAYER 0   Fast Path Bypass     trivial? -> phi3-mini      |
| LAYER 1   Modality Gate        text/image/code/audio/...  |
| LAYER 1.5 Input Signals        task_type, depth, intents  |
| LAYER 2   Semantic Memory      cache hit -> reuse model   |
| LAYER 3   Fast Triage          intent + domain + complex. |
| LAYER 4   Uncertainty          total_uncertainty + level  |
|           _determine_target_tier()  -> cheap/mid/premium  |
|           _get_candidate_models()   -> filtered list      |
| LAYER 5   Bandit Router        Thompson Sampling picks 1  |
|   (Benchmark advisor runs in parallel as quality signal)  |
+-----------------------------------------------------------+
                       |
            Gateway calls the selected model
                       |
                       v
+-----------------------------------------------------------+
| LAYER 6   Test-Time Compute    best-of-N (prod only)      |
| LAYER 7   Quality Evaluator    score + refusal/halluc.    |
| LAYER 8   Escalation Engine    retry on stronger model    |
| LAYER 9   Telemetry            async log + bandit update  |
+-----------------------------------------------------------+
"""
    )
)
story.append(
    note(
        "The terms <i>layer</i> and <i>elite</i> here are not marketing &mdash; they are the "
        "formal names from <font color='#0d2f5e'>Synopsis_Layer0_Routing_System_V2</font>, "
        "which the implementation follows."
    )
)
story.append(PageBreak())

# === 2. Inputs ===
story.append(h1("2. Pipeline inputs"))
story.append(
    p(
        "<font color='#0d2f5e'>ModelRouter.route()</font> accepts the following parameters. "
        "Every layer below references these or values derived from them."
    )
)
rows = [
    [Paragraph(c, BODY) for c in ("Parameter", "Purpose")],
    [Paragraph("<b>query</b>", BODY), Paragraph("The user's text", BODY)],
    [
        Paragraph(
            "<b>has_images, has_audio, has_video,<br/>image_count, file_types, attachment_sizes_mb</b>",
            BODY,
        ),
        Paragraph("Modality signals from the request", BODY),
    ],
    [
        Paragraph("<b>force_model_id</b>", BODY),
        Paragraph(
            "Manual model override. V07's manual-mode picker sets this; the "
            "pipeline still runs for logging but selection is skipped.",
            BODY,
        ),
    ],
    [Paragraph("<b>user_tier</b>", BODY), Paragraph("free / standard / premium", BODY)],
    [
        Paragraph("<b>budget_remaining</b>", BODY),
        Paragraph("Fraction 0&ndash;1 of today's budget left", BODY),
    ],
    [
        Paragraph("<b>session_escalation_count</b>", BODY),
        Paragraph("How many times this session has had to escalate", BODY),
    ],
    [
        Paragraph("<b>session_complexity_avg</b>", BODY),
        Paragraph("Rolling avg query complexity for this session (0&ndash;1)", BODY),
    ],
    [
        Paragraph("<b>history</b>", BODY),
        Paragraph(
            "Prior conversation turns. Used to compute context-token density, which "
            "feeds the uncertainty estimator.",
            BODY,
        ),
    ],
    [
        Paragraph("<b>request_id</b>", BODY),
        Paragraph("Telemetry correlation id (auto-generated if not provided)", BODY),
    ],
]
story.append(make_table(rows, col_widths=[6 * cm, 10.5 * cm]))
story.append(Spacer(1, 6))
story.append(
    p(
        "<b>Output.</b> A <font color='#0d2f5e'>RoutingDecision</font> with the chosen model, "
        "ranked fallback list, full reasoning chain, estimated cost, confidence level "
        "and an escalation path."
    )
)
story.append(PageBreak())

# === 3. Fast Path ===
story.append(h1("3. Layer 0 &mdash; Fast Path Bypass"))
story.append(
    p(
        "File: <font color='#0d2f5e'>src/layer0_model_infra/routing/fast_path.py</font>. "
        "A pure regex / keyword matcher that short-circuits the entire pipeline "
        "for trivially-handled queries so they don't pay the ~80&ndash;150 ms routing tax."
    )
)
rows = [
    [Paragraph(c, BODY) for c in ("Trigger pattern", "Recommended model", "Confidence")],
    [Paragraph("Exact match in GREETINGS set (hi, hello, hey, &hellip;)", BODY), Paragraph("ollama-phi3-mini", BODY), Paragraph("0.95", BODY)],
    [Paragraph("Exact match in ACKNOWLEDGMENTS (thanks, ok, bye, &hellip;)", BODY), Paragraph("ollama-phi3-mini", BODY), Paragraph("0.95", BODY)],
    [Paragraph("Query &lt; 15 chars with no '?' or '.'", BODY), Paragraph("ollama-phi3-mini", BODY), Paragraph("0.80", BODY)],
    [
        Paragraph("Regex match: <font face='Courier' size='9'>^what is \\d+[+\\-*/]\\d+</font>, <font face='Courier' size='9'>^define \\w+</font>, etc.", BODY),
        Paragraph("ollama-llama3.1-8b", BODY),
        Paragraph("0.85", BODY),
    ],
]
story.append(make_table(rows, col_widths=[9 * cm, 5 * cm, 2.5 * cm]))
story.append(Spacer(1, 6))
story.append(
    p(
        "On a hit, layers 1&ndash;9 are skipped. The decision is wrapped in "
        "<font color='#0d2f5e'>_create_fast_path_decision()</font>, which still calls "
        "the modality / triage / uncertainty components on the side &mdash; for telemetry only, "
        "not for selection."
    )
)
story.append(PageBreak())

# === 4. Modality Gate ===
story.append(h1("4. Layer 1 &mdash; Modality Gate"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/modality_gate.py</font>. Determines "
        "<i>what kind of model</i> the query requires. Combines external attachment signals "
        "with content-based detection."
    )
)
story.append(h2("Output fields"))
story.append(
    code(
        """class ModalityAnalysis:
    primary_modality: TEXT_ONLY | IMAGE | AUDIO | VIDEO | CODE | STRUCTURED
    requires_vision: bool        # has_images OR text mentions images/OCR/diagrams
    requires_audio: bool         # has_audio
    requires_code_model: bool    # code_density > 0.3 in the text
    token_count: int
    language: str                # detected query language
"""
    )
)
story.append(h2("Detection inputs"))
story.extend(
    bullets(
        [
            "External: <b>has_images</b>, <b>has_audio</b>, file MIME types, attachment sizes (MB).",
            "Text analysis: <b>_calculate_code_density()</b> counts backticks/fences/keywords.",
            "Structured-data scoring: <b>_detect_table_density()</b> flags pipe-tables, JSON, CSV.",
            "Language detection: statistical signals for Hindi, Spanish, etc.",
        ]
    )
)
story.append(
    p(
        "This drives <font color='#0d2f5e'>_determine_model_type()</font> in the router: "
        "MULTIMODAL for vision, AUDIO for audio, otherwise TEXT. That's the first filter "
        "the registry will be queried with."
    )
)
story.append(PageBreak())

# === 5. Input Signals ===
story.append(h1("5. Layer 1.5 &mdash; Input Signal Extractor"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/input_signals.py</font>. Pure heuristic feature "
        "extraction &mdash; no LLM calls. Produces ~20 structured fields read by the tier "
        "selection logic as <b>tie-breakers</b>."
    )
)
rows = [
    [Paragraph(c, BODY) for c in ("Field", "Type / range", "What it captures")],
    [Paragraph("<b>task_type</b>", BODY), Paragraph("enum", BODY), Paragraph("QA | GENERATION | TRANSFORMATION | ANALYSIS | CONVERSATION | CODING", BODY)],
    [Paragraph("<b>requested_format</b>", BODY), Paragraph("enum", BODY), Paragraph("Detected output shape (JSON / TABLE / CODE / FREE_TEXT)", BODY)],
    [Paragraph("<b>requests_json / requests_table / requests_code / requests_detailed</b>", BODY), Paragraph("bool", BODY), Paragraph("Explicit format asks from query keywords", BODY)],
    [Paragraph("<b>instruction_count</b>", BODY), Paragraph("int", BODY), Paragraph("Number of imperative verbs / numbered steps", BODY)],
    [Paragraph("<b>has_multi_part</b>", BODY), Paragraph("bool", BODY), Paragraph("Multiple distinct sub-questions", BODY)],
    [Paragraph("<b>has_constraints</b>", BODY), Paragraph("bool", BODY), Paragraph("Words like 'without X', 'exactly Y', 'at most N'", BODY)],
    [Paragraph("<b>multi_intent_score</b>", BODY), Paragraph("0&ndash;1", BODY), Paragraph("How many distinct intents coexist in one query", BODY)],
    [Paragraph("<b>reasoning_depth</b>", BODY), Paragraph("0&ndash;1", BODY), Paragraph("Density of 'why / because / derive / prove' tokens", BODY)],
    [Paragraph("<b>numerical_reasoning_flag</b>", BODY), Paragraph("bool", BODY), Paragraph("Math / statistics keywords present", BODY)],
    [Paragraph("<b>code_generation_flag</b>", BODY), Paragraph("bool", BODY), Paragraph("Coding-task keywords present", BODY)],
    [Paragraph("<b>overall_difficulty</b>", BODY), Paragraph("0&ndash;1", BODY), Paragraph("Aggregate heuristic score", BODY)],
]
story.append(make_table(rows, col_widths=[5.5 * cm, 2.2 * cm, 8.5 * cm]))
story.append(
    note(
        "These signals never override the LLM-classifier band on their own. They only "
        "tip the tier for <i>moderate-band</i> queries where the cheap-vs-mid decision "
        "is on a knife edge."
    )
)
story.append(PageBreak())

# === 6. Semantic Memory ===
story.append(h1("6. Layer 2 &mdash; Semantic Memory Cache"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/semantic_memory.py</font>. An "
        "<b>outcome-aware</b> cache keyed by semantic similarity. The bet: if "
        "<i>'What is photosynthesis?'</i> got a good answer from a particular model 10 minutes "
        "ago, route a new <i>'Explain photosynthesis'</i> to the same model without re-running the pipeline."
    )
)
story.append(h2("Lookup algorithm"))
story.extend(
    bullets(
        [
            "Normalize the query (lowercase, strip punctuation).",
            "Compute embedding similarity vs every cached entry.",
            "If <b>best_sim &ge; similarity_threshold</b> (0.85 dev / 0.90 prod), run validation guards.",
            "<b>Negation guard</b>: reject if one query has 'not' and the other doesn't.",
            "<b>Entity novelty</b>: reject if new named entities appear in the new query.",
            "<b>Outcome check</b>: only reuse entries whose previous result was successful.",
            "On pass: return <b>hit=True</b>, <b>matched_model_id</b>, <b>similarity</b>, <b>novelty=0</b>.",
            "On miss: still compute novelty = 1 &minus; best_sim. Feeds the uncertainty estimator.",
        ]
    )
)
story.append(
    p(
        "On a hit, the router calls <font color='#0d2f5e'>_create_cached_decision()</font> "
        "and skips layers 3&ndash;5 (triage, uncertainty, bandit). Stale entries age out via "
        "<font color='#0d2f5e'>prune_stale_entries()</font> at 30 days (dev) / 60 days (prod)."
    )
)
story.append(PageBreak())

# === 7. Fast Triage ===
story.append(h1("7. Layer 3 &mdash; Fast Triage &amp; Complexity Classifier"))
story.append(
    p(
        "Files: <font color='#0d2f5e'>routing/fast_triage.py</font> + "
        "<font color='#0d2f5e'>routing/complexity_classifier.py</font>. The brain of the pipeline."
    )
)

story.append(h2("Sub-stage A &mdash; Intent &amp; Domain (heuristic)"))
story.append(
    p(
        "Pure keyword-table lookups. Each function returns the chosen label plus a confidence "
        "score (0.68&ndash;0.98) based on how many keywords matched."
    )
)
rows = [
    [Paragraph(c, BODY) for c in ("Output", "Values")],
    [Paragraph("<b>Intent</b>", BODY), Paragraph("QA / CODING / PLANNING / CREATIVE / ANALYSIS / CASUAL / TECHNICAL / REASONING", BODY)],
    [Paragraph("<b>Domain</b>", BODY), Paragraph("TECH / BUSINESS / MEDICAL / LEGAL / SCIENCE / EDUCATION / CASUAL / GENERAL", BODY)],
]
story.append(make_table(rows, col_widths=[3.5 * cm, 13 * cm]))
story.append(
    note(
        "MEDICAL and LEGAL are domain-sensitive &mdash; they immediately force the premium "
        "tier downstream as a hard safety rule, regardless of complexity or budget."
    )
)

story.append(h2("Sub-stage B &mdash; Complexity (LLM-based)"))
story.append(
    p(
        "An actual LLM call via <font color='#0d2f5e'>litellm.completion</font> to a small, "
        "free model (<font color='#0d2f5e'>groq-llama-3.3-70b-free</font> in dev, "
        "<font color='#0d2f5e'>google/gemma-3-12b</font> in prod). The system prompt asks the "
        "model to score the query on a <b>5-dimensional rubric</b> mapped to Bloom's Taxonomy "
        "and Webb's Depth of Knowledge."
    )
)

rows = [
    [Paragraph(c, BODY) for c in ("Dimension", "Weight", "What it measures")],
    [Paragraph("<b>task_count</b>", BODY), Paragraph("0.25", BODY), Paragraph("Atomic sub-tasks (single action &rarr; 10+)", BODY)],
    [Paragraph("<b>domain_depth</b>", BODY), Paragraph("0.20", BODY), Paragraph("Specialization (common &rarr; PhD)", BODY)],
    [Paragraph("<b>reasoning_hops</b>", BODY), Paragraph("0.25", BODY), Paragraph("Logical steps (lookup &rarr; multi-step proof)", BODY)],
    [Paragraph("<b>output_structure</b>", BODY), Paragraph("0.15", BODY), Paragraph("Output complexity (sentence &rarr; multi-component system)", BODY)],
    [Paragraph("<b>knowledge_breadth</b>", BODY), Paragraph("0.15", BODY), Paragraph("Topics to synthesize", BODY)],
]
story.append(make_table(rows, col_widths=[4 * cm, 2 * cm, 10.5 * cm]))

story.append(h3("From rubric to band"))
story.append(
    code(
        """raw_score = sum(dim_value * weight)

raw_score < 0.12  -> trivial
        < 0.20  -> simple    (lowered from 0.30 after calibration)
        < 0.55  -> moderate
        < 0.85  -> complex   (raised from 0.80 to prevent expert over-routes)
        else    -> expert
"""
    )
)
story.append(h3("Confidence is derived, not self-reported"))
story.append(
    p(
        "The system prompt explicitly forbids the model from reporting its own confidence. "
        "Two signals are combined post-hoc to produce a calibrated confidence:"
    )
)
story.extend(
    bullets(
        [
            "<b>Boundary distance</b> &mdash; queries far from band thresholds get high confidence; queries near a boundary get low confidence.",
            "<b>Rubric consistency</b> &mdash; if all 5 dimensions agree on a magnitude, confidence is high; wildly diverging dimensions mean low confidence.",
        ]
    )
)
story.append(
    note(
        "If the LLM call fails or returns garbage JSON, the classifier falls back to a "
        "heuristic scorer with confidence capped at 0.50 &mdash; never higher than a band-boundary case."
    )
)
story.append(PageBreak())

# === 8. Uncertainty ===
story.append(h1("8. Layer 4 &mdash; Uncertainty Estimator"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/uncertainty_estimator.py</font>. Produces a "
        "<b>total_uncertainty</b> &isin; [0, 1] from multiple sub-signals. This is "
        "<i>not</i> the same as classifier confidence: confidence asks &quot;how sure are we "
        "about the band?&quot;; uncertainty asks &quot;how risky is misrouting this query?&quot;"
    )
)
story.append(h2("Sub-scores"))
rows = [
    [Paragraph(c, BODY) for c in ("Signal", "What it detects")],
    [Paragraph("<b>classification_entropy</b>", BODY), Paragraph("Spread in intent / domain confidence", BODY)],
    [Paragraph("<b>instruction_conflict</b>", BODY), Paragraph("Incompatible commands (e.g. 'be brief' and 'very detailed')", BODY)],
    [Paragraph("<b>context_dependency</b>", BODY), Paragraph("Query needs prior context that is missing", BODY)],
    [Paragraph("<b>cross_domain_score</b>", BODY), Paragraph("Query spans 2+ domain vocabularies (legal + medical, tech + finance)", BODY)],
    [Paragraph("<b>linguistic_uncertainty</b>", BODY), Paragraph("Hedging language, vague phrasing", BODY)],
    [Paragraph("<b>complexity_uncertainty</b>", BODY), Paragraph("raw_score near a band boundary", BODY)],
    [Paragraph("<b>domain_uncertainty</b>", BODY), Paragraph("Domain confidence below threshold", BODY)],
    [Paragraph("<b>context_uncertainty</b>", BODY), Paragraph("Conversation density (ctx_token_density) high", BODY)],
]
story.append(make_table(rows, col_widths=[5 * cm, 11.5 * cm]))
story.append(
    p(
        "The total is a weighted sum with <b>tier-dependent weights</b> &mdash; premium users get "
        "a different uncertainty profile than free users (they tolerate slower-but-safer routing). "
        "Output: <font color='#0d2f5e'>UncertaintyScore</font> with <b>total_uncertainty</b> and "
        "<b>confidence_level</b> &isin; {HIGH, MEDIUM, LOW}."
    )
)
story.append(PageBreak())

# === 9. Tier selection ===
story.append(h1("9. Tier Selection &amp; Candidate Filtering"))
story.append(
    p(
        "Before model selection, the router commits to a <b>tier</b>: cheap, mid or premium. "
        "This is the central cost/quality knob. Implemented in "
        "<font color='#0d2f5e'>_determine_target_tier()</font>."
    )
)
story.append(h2("Hard rules (always premium)"))
story.append(
    code(
        """if modality.requires_vision:        return "premium"  # safest multimodal tier
if domain in {medical, legal}:      return "premium"  # high-risk domain
if cross_domain_score >= 0.35:      return "premium"  # cross-domain query
if total_uncertainty >= 0.7:        return "premium"  # high total uncertainty
"""
    )
)
story.append(h2("Classifier-primary routing"))
story.append(
    code(
        """if band == "expert":      return "premium"
if band == "complex":     return "premium"
if band == "trivial":     return "cheap"
if band == "simple":      return "cheap"
# moderate falls through to tie-breakers...
"""
    )
)
story.append(h2("Moderate &mdash; conservative escalation + tie-breakers"))
story.extend(
    bullets(
        [
            "<b>complexity_confidence &lt; 0.55</b> &rarr; mid (don't trust a low-confidence moderate)",
            "<b>raw_score within 0.05 of moderate-complex boundary</b> &rarr; mid",
            "<b>numerical_reasoning AND domain == science</b> &rarr; mid",
            "<b>code_generation AND has_constraints</b> &rarr; mid",
            "<b>reasoning_depth &ge; 0.55</b> &rarr; mid",
            "<b>domain in {tech, business, education}</b> &rarr; mid",
            "<b>user_tier == 'premium'</b> &rarr; mid (premium users get safer moderates)",
            "Otherwise &rarr; cheap (confident moderate)",
        ]
    )
)

story.append(h2("Candidate filtering pipeline"))
story.append(
    p(
        "Once the tier is fixed, <font color='#0d2f5e'>_get_candidate_models()</font> runs:"
    )
)
story.extend(
    bullets(
        [
            "<b>Registry lookup</b>: <font color='#0d2f5e'>list_models(model_type=&hellip;, only_active=True)</font>.",
            "<b>Capability filter</b>: keep CODING-capable models if code generation is needed; keep REASONING-capable if reasoning_depth &ge; 0.45.",
            "<b>Tier filter</b>: explicit routing_tier match; fallback to price-based heuristic (output &ge; $0.015 = premium; local &lt; 10B = cheap).",
            "<b>Free-API preference</b>: if <font color='#0d2f5e'>PREFER_FREE_API_PROVIDERS=true</font>, drop Ollama-only options when GROQ / GOOGLE / OPENROUTER / HUGGINGFACE / COHERE candidates exist.",
            "<b>Sort</b> by safety bias (REASONING-first for high-risk) and total cost.",
        ]
    )
)
story.append(
    note(
        "If the filter chain produces an empty set, <b>ModelNotFoundError</b> is raised. "
        "This is the only fatal exit point in the routing pipeline."
    )
)
story.append(PageBreak())

# === 10. Bandit Router ===
story.append(h1("10. Layer 5 &mdash; Bandit Router (Thompson Sampling)"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/bandit_router.py</font>. This is where the actual "
        "model is picked from the candidate list."
    )
)
story.append(h2("The model: contextual multi-armed bandit"))
story.append(
    p(
        "Each (context, model_id) pair is an <b>arm</b>. Each arm has Beta-distribution "
        "parameters that get updated with every observed outcome."
    )
)
story.append(
    code(
        """alpha = 1.0   # successes + 1   (uniform prior Beta(1,1))
beta_ = 1.0   # failures  + 1

expected_reward = alpha / (alpha + beta_)
theta_sample    = random.betavariate(alpha, beta_)   # in (0, 1)
"""
    )
)

story.append(h2("Context = bucketing key"))
story.append(
    p(
        "<font color='#0d2f5e'>BanditContext.to_key()</font> hashes the following fields. Same query "
        "type / user profile maps to the same arm history; very different requests have independent "
        "arms."
    )
)
story.extend(
    bullets(
        [
            "<b>intent, domain, complexity_band</b>",
            "<b>uncertainty_score, has_vision, has_code</b>",
            "<b>input_difficulty, has_multi_part, has_constraints</b>",
            "<b>user_tier, budget_remaining</b>",
            "<b>session_escalation_count, session_complexity_avg</b>",
        ]
    )
)

story.append(h2("Selection algorithm"))
story.append(
    code(
        """for each candidate model:
    arm = arms.get((ctx_key, model_id)) or BanditArm(alpha=1, beta_=1)
    theta = arm.sample_thompson()
selected = argmax(theta)
"""
    )
)
story.append(
    p(
        "Thompson Sampling naturally balances exploration and exploitation. High-confidence arms "
        "have spiked Beta distributions (consistent picks); low-data arms have flat distributions "
        "(near-random picks). New models get tried often; proven winners get picked often."
    )
)

story.append(h2("Reward shaping (applied later, by telemetry)"))
story.append(
    code(
        """reward  = quality_score - cost_penalty - latency_penalty
success = (reward > threshold) and (not escalated)

alpha += int(success)
beta_ += int(not success)
total_reward += reward
"""
    )
)
story.append(
    p(
        "The bandit therefore learns <i>jointly</i> across quality, cost and latency. "
        "A fast cheap model with acceptable quality eventually beats a slow expensive model "
        "with only marginally better quality."
    )
)

story.append(h2("Special operating modes"))
story.extend(
    bullets(
        [
            "<b>Full exploitation</b>: when exploration_rate is 0 (or after warmup is complete), pick argmax(expected_reward) instead of sampling.",
            "<b>Domain safety lock</b>: in medical / legal contexts, sample only among REASONING-capable models.",
            "<b>Budget lock</b>: if budget_remaining is below a threshold, premium arms are excluded from the sample.",
        ]
    )
)
story.append(PageBreak())

# === 11. Benchmark advisor ===
story.append(h1("11. Benchmark Router (advisor, runs in parallel)"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/benchmark_router.py</font>. <b>Advisory only.</b> "
        "Runs alongside the bandit but does not change the bandit's decision &mdash; its purpose "
        "is to provide a second opinion for telemetry-driven bandit tuning."
    )
)
story.append(h2("Two methods, in priority order"))
story.extend(
    bullets(
        [
            "<b>trained_gbc</b> &mdash; a Gradient Boosting Classifier trained on benchmark data plus "
            "sentence-transformer query embeddings. Loaded from "
            "<font color='#0d2f5e'>benchmark_router_model.joblib</font> if it exists.",
            "<b>benchmark_lookup</b> &mdash; rubric-weighted scoring fallback when no trained "
            "model is on disk.",
        ]
    )
)
story.append(h2("How the lookup works"))
story.extend(
    bullets(
        [
            "Load <font color='#0d2f5e'>model_benchmarks.json</font> &mdash; quality scores for ~22 "
            "industry LLMs across MMLU, HumanEval, GSM8K, MATH, BBH, GPQA, etc.",
            "The 5-dimensional rubric from the complexity classifier maps to benchmark relevance "
            "weights (reasoning_hops &rarr; GSM8K + BBH; domain_depth &rarr; MMLU + GPQA; "
            "output_structure &rarr; HumanEval; &hellip;).",
            "For each model: value_score = &Sigma;(benchmark_score &times; relevance_weight) &minus; cost_penalty.",
            "Return the top scorer as <font color='#0d2f5e'>BenchmarkRouterResult</font> on "
            "<font color='#0d2f5e'>RoutingDecision.benchmark_recommendation</font>.",
        ]
    )
)
story.append(
    note(
        "The benchmark recommendation is logged alongside the bandit's pick. Telemetry comparing "
        "the two over time is the signal used to decide whether the bandit's learned policy needs "
        "re-warming or whether benchmark weights need re-tuning."
    )
)
story.append(PageBreak())

# === 12. Test-Time Compute ===
story.append(h1("12. Layer 6 &mdash; Test-Time Compute"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/test_time_compute.py</font>. <b>Enabled in production, "
        "disabled in dev</b> via <font color='#0d2f5e'>enable_test_time_compute=False</font>."
    )
)
story.append(
    p(
        "For moderate-uncertainty queries &mdash; not high enough to trigger premium escalation, "
        "but not low enough for confident routing &mdash; the engine generates <b>N samples</b> "
        "from the selected model and picks the best one."
    )
)
rows = [
    [Paragraph(c, BODY) for c in ("Strategy", "How it picks the winner")],
    [Paragraph("<b>BEST_OF_N</b>", BODY), Paragraph("Score each sample with QualityEvaluator, return the highest scorer.", BODY)],
    [Paragraph("<b>SELF_CONSISTENCY</b>", BODY), Paragraph("Generate N at fixed temperature, return the majority-consensus answer.", BODY)],
    [Paragraph("<b>VERIFICATION</b>", BODY), Paragraph("Generate one, generate a verifier-style critique, regenerate with the critique in context.", BODY)],
]
story.append(make_table(rows, col_widths=[4.5 * cm, 12 * cm]))
story.append(
    p(
        "Premium users get N = 3; standard users N = 2. Only fires when "
        "<font color='#0d2f5e'>should_use_ttc()</font> returns true &mdash; low confidence AND "
        "budget OK AND not in a refusal loop."
    )
)
story.append(PageBreak())

# === 13. Quality Evaluator ===
story.append(h1("13. Layer 7 &mdash; Quality Evaluator"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/quality_evaluator.py</font>. Validates the response "
        "without necessarily calling another LLM &mdash; most of the signals are deterministic."
    )
)
story.append(h2("Multi-signal scoring"))
rows = [
    [Paragraph(c, BODY) for c in ("Signal", "What it checks")],
    [Paragraph("<b>JSON validity</b>", BODY), Paragraph("If the response should be JSON, does it parse?", BODY)],
    [Paragraph("<b>Code syntax</b>", BODY), Paragraph("If Python, does <font face='Courier' size='9'>ast.parse()</font> succeed?", BODY)],
    [Paragraph("<b>Format compliance</b>", BODY), Paragraph("Did the model produce a table when one was asked for?", BODY)],
    [Paragraph("<b>Schema validation</b>", BODY), Paragraph("If a schema was provided, does the JSON match?", BODY)],
    [Paragraph("<b>Completeness</b>", BODY), Paragraph("Does the response address the query's instructions?", BODY)],
    [Paragraph("<b>Coherence</b>", BODY), Paragraph("Repetition / contradiction / fluency heuristics", BODY)],
    [Paragraph("<b>Refusal detection</b>", BODY), Paragraph("'I can't help with that' / 'I'm just an AI' / safety boilerplate", BODY)],
    [Paragraph("<b>Hallucination risk</b>", BODY), Paragraph("Confident factual claims with no supporting evidence pattern", BODY)],
    [Paragraph("<b>Truncation</b>", BODY), Paragraph("Cut off mid-sentence; incomplete code blocks", BODY)],
]
story.append(make_table(rows, col_widths=[4 * cm, 12.5 * cm]))
story.append(
    p(
        "Returns <font color='#0d2f5e'>QualityScore</font> with <b>overall_quality</b> and a typed reason. "
        "An optional LLM-as-judge path is available &mdash; a Phi-4-mini-reasoning model rates accuracy / "
        "completeness / coherence / safety on 1&ndash;5 scales &mdash; but it's gated on cost."
    )
)
story.append(PageBreak())

# === 14. Escalation ===
story.append(h1("14. Layer 8 &mdash; Escalation Engine"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/escalation_engine.py</font>. Climbs the "
        "<b>escalation path</b> (the candidate list sorted ascending by cost) when quality fails. "
        "Each retry runs on the next-most-expensive model."
    )
)
story.append(h2("Per-tier quality thresholds"))
story.append(
    code(
        """ESCALATION_QUALITY_THRESHOLD = {
    "free":     1.01,   # never escalate on quality alone (only refusals)
    "standard": 0.65,
    "premium":  0.75,   # higher quality bar -> escalates sooner
}
"""
    )
)
story.append(
    p(
        "Refusal-detection always triggers escalation regardless of tier. Hard ceiling at "
        "<font color='#0d2f5e'>max_escalation_levels=3</font>. Each retry's cost and latency are "
        "rolled up into the cumulative bill that telemetry feeds back into the bandit reward."
    )
)
story.append(PageBreak())

# === 15. Telemetry ===
story.append(h1("15. Layer 9 &mdash; Telemetry &amp; Feedback Loop"))
story.append(
    p(
        "File: <font color='#0d2f5e'>routing/telemetry.py</font>. The continuous-learning "
        "feedback path. Fire-and-forget &mdash; <b>never blocks the user request</b>."
    )
)
story.append(h2("RoutingTelemetry payload"))
story.append(
    p(
        "A 25+ field dataclass: request_id, selected_model_id, final_model_id, intent, domain, "
        "complexity_band, quality_score, escalated, escalation_count, cost_usd, latency_ms, "
        "uncertainty_score, novelty_score, user_tier, budget_remaining, primary_modality, "
        "language, token_count, task_type, reasoning_depth, multi_intent_score, "
        "instruction_count, classification_entropy, cross_domain_score, &hellip;"
    )
)
story.append(h2("What the daemon thread does"))
story.extend(
    bullets(
        [
            "Persists the row to the <b>routing_telemetry</b> SQL table.",
            "Updates the matching bandit arm's &alpha;/&beta; based on the observed reward.",
            "Calls <font color='#0d2f5e'>update_semantic_memory_entries()</font> &mdash; records this query's outcome so the next similar query can short-circuit at Layer 2.",
            "Periodically calls <font color='#0d2f5e'>recalibrate_triage()</font> to propose threshold updates when the complexity classifier drifts vs the gold set.",
            "<font color='#0d2f5e'>compute_evaluation_statistics()</font> aggregates daily quality / cost / escalation rates for dashboards.",
        ]
    )
)
story.append(PageBreak())

# === 16. Sidecars ===
story.append(h1("16. Sidecars &mdash; Model Registry &amp; Commercial Profiles"))

story.append(h2("Model Registry"))
story.append(
    p(
        "File: <font color='#0d2f5e'>src/layer0_model_infra/registry.py</font> (~1050 lines). "
        "Source of truth for every model the platform can call."
    )
)
rows = [
    [Paragraph(c, BODY) for c in ("Field", "Purpose")],
    [Paragraph("<b>model_id</b>", BODY), Paragraph("Registry key, e.g. <font face='Courier' size='9'>groq-llama-3.3-70b-free</font>", BODY)],
    [Paragraph("<b>model_name</b>", BODY), Paragraph("String passed to LiteLLM, e.g. <font face='Courier' size='9'>groq/llama-3.3-70b-versatile</font>", BODY)],
    [Paragraph("<b>provider</b>", BODY), Paragraph("OPENAI / ANTHROPIC / GOOGLE / GROQ / OPENROUTER / HUGGINGFACE / COHERE / AZURE_OPENAI / LOCAL", BODY)],
    [Paragraph("<b>model_type</b>", BODY), Paragraph("TEXT / MULTIMODAL / AUDIO / EMBEDDING", BODY)],
    [Paragraph("<b>routing_tier</b>", BODY), Paragraph("CHEAP / MID / PREMIUM (used by tier filter)", BODY)],
    [Paragraph("<b>capabilities</b>", BODY), Paragraph("CODING / REASONING / FUNCTION_CALLING / VISION / &hellip;", BODY)],
    [Paragraph("<b>pricing</b>", BODY), Paragraph("Input + output cost per 1K tokens (used everywhere for cost calc)", BODY)],
    [Paragraph("<b>is_active</b>", BODY), Paragraph("Soft toggle without deletion", BODY)],
    [Paragraph("<b>context_window, max_output_tokens</b>", BODY), Paragraph("Capacity limits", BODY)],
]
story.append(make_table(rows, col_widths=[5 * cm, 11.5 * cm]))

story.append(h2("Commercial Profiles (V07 manual model picker)"))
story.append(
    p(
        "When the V07 frontend's ModelSelector picks a manual model, it sends "
        "<font color='#0d2f5e'>simulation_profile_id</font> (for example "
        "<font color='#0d2f5e'>gpt-5.4-flagship</font>) to the backend. The profile is a "
        "<b>commercial-facing brand name</b> mapped to a <i>pool</i> of real backing models:"
    )
)
story.append(
    code(
        """gpt-5.4-flagship  -> premium pool:
    [groq-llama-3.3-70b-free, openrouter-gpt-4o, anthropic-claude-3-5-sonnet, ...]

The router sees force_model_id set (via the pool's first entry) and skips
selection. Every other layer still runs for telemetry.
"""
    )
)
story.append(
    note(
        "This is why the V07 chat header shows 'gpt-5.4-flagship' even though the actual API call "
        "is to Groq. The commercial profile is a presentation-layer abstraction over the registry."
    )
)
story.append(PageBreak())

# === 17. Worked example ===
story.append(h1("17. End-to-end worked example"))
story.append(
    p(
        "User submits: <i>&quot;Write a Python function to check if a string is a palindrome&quot;</i> &mdash; "
        "no attachments, standard tier, full budget."
    )
)
story.append(
    code(
        """Layer 0 (Fast Path):    no bypass (60+ chars, no greeting/ack match)
Layer 1 (Modality):     primary_modality=CODE, requires_code_model=True,
                        requires_vision=False, language='en'
Layer 1.5 (Signals):    task_type=CODING, code_generation_flag=True,
                        has_constraints=False, reasoning_depth=0.18,
                        instruction_count=1
Layer 2 (Memory):       miss, novelty_score=0.65
Layer 3 (Triage):
   - intent=CODING (0.97), domain=TECH (0.9)
   - rubric: task_count=0.3, domain_depth=0.4, reasoning_hops=0.5,
             output_structure=0.3, knowledge_breadth=0.2
   - raw_score = 0.3*0.25 + 0.4*0.2 + 0.5*0.25 + 0.3*0.15 + 0.2*0.15 = 0.35
   - 0.20 < 0.35 < 0.55  =>  band=MODERATE, confidence=0.78
Layer 4 (Uncertainty):  total_uncertainty=0.32 (LOW), cross_domain=0.05

Tier decision:
   - Not vision; not medical/legal; cross_domain < 0.35; uncertainty < 0.7
   - band == moderate, confidence (0.78) > 0.55, raw_score not near boundary
   - code_generation_flag=True, but has_constraints=False -> tie-break skipped
   - reasoning_depth (0.18) < 0.55
   - domain=TECH -> "domain-sensitive moderate"
   ==> target_tier = MID

Candidates after filtering (TEXT + CODING + MID + free-API preference):
   - groq-llama-3.3-70b-free
   - openrouter-gemini-flash
   - ollama-qwen3-8b   (kept only for gateway-level fallback)

Layer 5 (Bandit):
   - context key = "intent=coding,domain=tech,complexity=moderate,..."
   - theta samples: groq=0.74, gemini=0.68, qwen=0.62
   - selected = groq-llama-3.3-70b-free

Benchmark advisor: groq-llama-3.3-70b-free with quality_score=0.82, cost=$0

Gateway call: litellm.acompletion(...)  -> response in 380 ms

Layer 7 (Quality): code parses, query addressed  -> overall_quality=0.86  PASS
Layer 8 (Escalation): not triggered
Layer 9 (Telemetry):
   - log row: selected=groq, quality=0.86, latency=380, cost=$0.0001
   - bandit update: (context, groq).alpha += 1
   - semantic memory: record outcome for future hits
"""
    )
)
story.append(
    p(
        "<b>Total pipeline overhead:</b> ~80&ndash;150 ms (dominated by the complexity-classifier "
        "LLM call). <b>Total cost:</b> ~$0.0001. The expensive part is the model call itself, and "
        "the routing system chose the cheapest acceptable model from a 22-strong fleet."
    )
)
story.append(PageBreak())

# === 18. Why this design ===
story.append(h1("18. Why this design"))
rows = [
    [Paragraph(c, BODY) for c in ("Property", "How it is achieved")],
    [Paragraph("<b>Cheap routing by default</b>", BODY), Paragraph("Fast Path + free-API preference + cheap-tier selection for trivial / simple / confident-moderate", BODY)],
    [Paragraph("<b>Safe routing for risky queries</b>", BODY), Paragraph("Hard-rule premium for medical / legal / cross-domain / high-uncertainty / vision", BODY)],
    [Paragraph("<b>Self-correcting</b>", BODY), Paragraph("Quality evaluator + escalation engine retries on bad outputs (refusal, low score)", BODY)],
    [Paragraph("<b>Self-learning</b>", BODY), Paragraph("Thompson Sampling bandit + telemetry feedback loop continuously updates arm rewards", BODY)],
    [Paragraph("<b>Calibrated complexity</b>", BODY), Paragraph("LLM judge with 5-dimensional rubric, derived (not self-reported) confidence, boundary-margin escalation", BODY)],
    [Paragraph("<b>Tiered escalation cost</b>", BODY), Paragraph("Free tier never escalates on quality alone; premium escalates sooner", BODY)],
    [Paragraph("<b>Auditability</b>", BODY), Paragraph("Every decision carries the full reasoning chain, candidate list, sub-scores, and policy reason", BODY)],
    [Paragraph("<b>Cost ceiling</b>", BODY), Paragraph("Budget-aware tier downgrades, per-tier escalation limits, estimated cost on every decision", BODY)],
]
story.append(make_table(rows, col_widths=[5 * cm, 11.5 * cm]))

story.append(Spacer(1, 12))
story.append(
    note(
        "<b>Single sentence summary.</b> A hybrid policy: <b>hard safety rules</b> (vision, "
        "medical/legal, cross-domain, high uncertainty) override the learned policy. Within the "
        "safe zone, an <b>LLM-judged 5-dimensional rubric</b> sets the cost tier, a "
        "<b>Thompson Sampling bandit</b> picks the actual model, and <b>quality evaluation + "
        "escalation</b> closes the loop with telemetry-driven re-learning."
    )
)


# ───────────────────────── Page chrome ─────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()
    if page_num > 1:
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#7a7a7a"))
        canvas.drawString(2 * cm, 1.2 * cm, "Enterprise AI Platform  -  Model Routing Strategy")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {page_num}")
        canvas.setStrokeColor(colors.HexColor("#cdd5e3"))
        canvas.setLineWidth(0.4)
        canvas.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
    canvas.restoreState()


def build():
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Model Routing Strategy",
        author="Enterprise AI Platform",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"Wrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build()
