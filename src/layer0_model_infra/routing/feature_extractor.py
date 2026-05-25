"""
📁 File: src/layer0_model_infra/routing/feature_extractor.py
Layer: Layer 0 — Layer 3 redesign (Stage B)
Purpose: Deterministic feature extraction for the kNN router.
Depends on: lingua-py (optional), src/layer0_model_infra/routing/layer3_types
Used by: knn_router (next batch), verdict_cache

Stage B's job is to produce a small ``QueryFeatures`` struct that the kNN
router uses for: (a) Qdrant attribute filtering, (b) safe-default dispatch,
(c) the length-adjusted similarity re-weighting (P3), (d) cost estimation,
and (e) the calibration feature_cell key.

Five outputs, all computed without any model inference:
  • language          → lingua-py with conf ≥ 0.55, else "multi"; non-Latin
                        scripts take a sub-100µs script-detection shortcut
  • modality          → text / code / math / vision / multimodal from
                        code-density regex + explicit attachment metadata
  • high_risk_domain  → narrow regex for medical / legal / financial
  • estimated_input_tokens / estimated_output_tokens → char-based estimates
  • difficulty_signal → trivial / normal / hard from length + pattern markers

Total budget: < 5 ms per query.

EXPLICITLY NOT IN SCOPE — the previous Layer 3 had a domain keyword classifier
("vision → MEDICAL → premium tier"). That entire mechanism is gone. Modality
is the only categorical signal we extract because it's the only one with a
clean operational use (safe-default dispatch). Intent / topic / complexity
classifiers are out — the kNN does that work in Stage C.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from typing import Optional

from src.layer0_model_infra.routing.layer3_types import (
    DifficultySignal,
    HighRiskDomain,
    Modality,
    QueryFeatures,
)
from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Language detection — script-first cascade, lingua-py for Latin scripts
# ============================================================================

# Unicode-range patterns for non-Latin scripts. Order matters: Japanese is
# checked before Chinese because hiragana/katakana are uniquely Japanese but
# Japanese also uses CJK kanji which would otherwise match Chinese.
_SCRIPT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[぀-ヿ]"), "ja"),     # hiragana + katakana = uniquely Japanese
    (re.compile(r"[가-힯]"), "ko"),     # hangul = uniquely Korean
    (re.compile(r"[一-鿿]"), "zh"),     # CJK ideographs (Japanese kanji also; ja was checked first)
    (re.compile(r"[؀-ۿ]"), "ar"),     # Arabic
    (re.compile(r"[ऀ-ॿ]"), "hi"),     # Devanagari (Hindi)
    (re.compile(r"[Ѐ-ӿ]"), "ru"),     # Cyrillic
    (re.compile(r"[ঀ-৿]"), "bn"),     # Bengali
    (re.compile(r"[஀-௿]"), "ta"),     # Tamil
]
_SCRIPT_MIN_HITS = 3


# Latin-script Hindi (Hinglish) marker lexicon. Two-marker rule confirms it's
# not just an English query that happened to contain one common Hinglish word.
_HINGLISH_MARKERS: frozenset[str] = frozenset({
    "kya", "hai", "aap", "mujhe", "tum", "kaise", "nahi", "accha", "bhai",
    "yaar", "kar", "karna", "kiya", "mera", "tera", "uska", "kuch", "bata",
    "matlab", "hain", "hu", "hoon", "raha", "rahi", "rahe", "namaste",
    "dhanyavad", "shukriya",
})

_LINGUA_LANGUAGES = [
    "ENGLISH", "SPANISH", "FRENCH", "GERMAN", "PORTUGUESE", "ITALIAN",
    "DUTCH", "TURKISH", "POLISH", "INDONESIAN", "VIETNAMESE",
]


def _maybe_build_lingua_detector(confidence_threshold: float):
    """Build the lingua-py detector lazily. Returns None on ImportError so
    Stage B still works with script + Hinglish detection only.
    """
    try:
        from lingua import Language, LanguageDetectorBuilder  # type: ignore
    except ImportError:
        logger.info(
            "layer3_feature_extractor_lingua_unavailable",
            fallback="script + hinglish markers only",
        )
        return None
    langs = [getattr(Language, name) for name in _LINGUA_LANGUAGES if hasattr(Language, name)]
    if not langs:
        return None
    try:
        return LanguageDetectorBuilder.from_languages(*langs).build()
    except Exception as exc:
        logger.warning("layer3_feature_extractor_lingua_init_failed", reason=str(exc))
        return None


# ============================================================================
# Code / math / vision pattern detection
# ============================================================================

# Strong code markers. A query containing any of these is treated as
# CODE modality with high confidence.
_CODE_FENCE_RE = re.compile(r"```[\w]*\n")
_CODE_SIGNATURE_RES = [
    # NOTE on the `[:\->]` char class: writing `[:->]` would be interpreted as
    # the range U+003A..U+003E (`:` to `>`), which silently EXCLUDES `-`. The
    # backslash escape on the dash forces it to be a literal. Layer 1's
    # modality_gate.py has the same bug — flag for a follow-up patch.
    re.compile(r"\bdef\s+\w+\s*\([^)]*\)\s*[:\->]"),               # Python def
    re.compile(r"\bclass\s+\w+(?:\([\w\s,.]*\))?\s*:"),            # Python class
    re.compile(r"\bfunction\s+\w+\s*\([^)]*\)\s*\{"),              # JS function
    re.compile(r"\bfn\s+\w+\s*(?:<[^>]*>)?\s*\("),                 # Rust fn
    re.compile(r"\bfunc\s+\w+\s*\("),                              # Go func
    re.compile(r"\bpublic\s+(?:static\s+)?(?:void|int|String)\s+\w+"),  # Java
    re.compile(r"#include\s*<\w+"),                                # C/C++
    # SQL — use non-greedy `.+?` between SELECT and FROM so column lists
    # containing function calls like COUNT(*) match correctly.
    re.compile(r"\bSELECT\s+.+?\s+FROM\s+\w+", re.IGNORECASE),
]

# Math signature patterns. A query is MATH if it has explicit math notation
# OR is clearly a math-word-problem phrasing.
#
# DELIBERATELY no bare "digit op digit op digit" regex — that pattern matched
# ISO dates ("2026-01-01") as math and over-routed SQL queries containing
# dates to MATH/MULTIMODAL. Math word problems use the keyword markers below;
# pure arithmetic without math context goes through Layer 0's fast path.
_MATH_RES = [
    re.compile(r"\$[^$]+\$"),                                       # inline LaTeX
    re.compile(r"\\(?:frac|sqrt|int|sum|prod)\b"),                  # LaTeX commands
    re.compile(r"\b(?:prove|derive|theorem|integral|derivative)\b", re.IGNORECASE),
    re.compile(r"\b(?:solve\s+for|equation|coefficient)\b", re.IGNORECASE),
    re.compile(r"\b(?:calculate|compute)\s+(?:the\s+)?(?:value|sum|product|"
               r"derivative|integral|limit|probability)\b", re.IGNORECASE),
    # Arithmetic with explicit `=` (a person asking for a result, not a date)
    re.compile(r"\d+\s*[\+\-\*/\^]\s*\d+\s*="),
]

# Vision-relevance phrases (used when has_image_attachment=True to decide
# whether the user actually references the image vs just having one attached).
_VISION_REFERENCE_RE = re.compile(
    r"\b(?:in\s+(?:this|the|attached)\s+(?:image|picture|photo|screenshot|figure|"
    r"diagram|chart)|describe\s+(?:this|the|it)|what(?:'s| is)\s+(?:in|shown)|"
    r"caption|alt[- ]text|ocr|transcribe)\b",
    re.IGNORECASE,
)


# ============================================================================
# High-risk domain detection — narrow patterns only
# ============================================================================
#
# The previous Layer 3 had wide keyword tables that catastrophically over-
# routed ("vision" → MEDICAL). These are intentionally narrow: each pattern
# requires either a multi-word phrase OR a word in an unambiguous context.
# We accept false negatives (some medical queries won't be flagged) in
# exchange for very few false positives.

_MEDICAL_RES = [
    # Dosage / medication patterns
    re.compile(r"\b(?:dosage|dose)\s+of\b", re.IGNORECASE),
    re.compile(r"\b(?:should\s+i\s+take|safe\s+to\s+take|take\s+with)\s+\w+", re.IGNORECASE),
    re.compile(r"\b(?:mg|ml|mcg)\s+(?:of|per|every|daily|once|twice)\b", re.IGNORECASE),
    re.compile(r"\b(?:prescription|diagnosis|symptoms?\s+of|treatment\s+for|"
               r"medication\s+for|drug\s+interaction)\b", re.IGNORECASE),
    re.compile(r"\b(?:medical\s+advice|see\s+a\s+doctor|seek\s+medical|emergency\s+room)\b", re.IGNORECASE),
    # Specific medical entities in clinical context
    re.compile(r"\b(?:ibuprofen|acetaminophen|metformin|insulin|antibiotic|"
               r"antidepressant|chemotherapy|blood\s+thinner)\b", re.IGNORECASE),
    # Vitamin / nutrient deficiency in medical context (kept narrow: requires
    # explicit "vitamin/mineral X deficiency" — "leadership deficiency"
    # doesn't match because "leadership" isn't a recognised nutrient term).
    re.compile(r"\b(?:vitamin|mineral|iron|calcium|magnesium|potassium)\s+\w*\s*deficiency\b",
               re.IGNORECASE),
]

_LEGAL_RES = [
    re.compile(r"\b(?:legal\s+rights|legal\s+advice|legal\s+protection|sue\s+\w+|"
               r"lawsuit|class\s+action|wrongful\s+\w+)\b", re.IGNORECASE),
    re.compile(r"\b(?:contract\s+(?:dispute|breach|review)|tenant\s+rights|"
               r"landlord\s+\w+|eviction)\b", re.IGNORECASE),
    re.compile(r"\b(?:hire\s+(?:a\s+)?lawyer|consult\s+(?:a\s+)?lawyer|"
               r"attorney\s+\w+|file\s+(?:a\s+)?suit)\b", re.IGNORECASE),
    re.compile(r"\b(?:gdpr|hipaa)\s+compliance\b", re.IGNORECASE),
]

_FINANCIAL_RES = [
    re.compile(r"\b(?:should\s+i\s+invest|investment\s+advice|financial\s+advice|"
               r"retirement\s+plan(?:ning)?)\b", re.IGNORECASE),
    re.compile(r"\b(?:tax\s+(?:advice|liability|deduction|refund|"
               r"return|fraud|evasion|loophole))\b", re.IGNORECASE),
    re.compile(r"\b(?:my\s+(?:portfolio|401k|ira|stocks|bonds)|"
               r"financial\s+planner|wealth\s+management)\b", re.IGNORECASE),
    re.compile(r"\b(?:credit\s+score|debt\s+(?:consolidation|relief)|bankruptcy)\b", re.IGNORECASE),
]


# ============================================================================
# Hard-difficulty markers (used only for difficulty_signal, which becomes a
# similarity re-weighting input — NOT a routing decision in itself)
# ============================================================================

_HARD_DIFFICULTY_MARKERS = [
    re.compile(r"\b(?:prove|derive|theorem|formal\s+proof)\b", re.IGNORECASE),
    re.compile(r"\b(?:design|architect)\s+(?:a|an|the)\s+(?:distributed|"
               r"fault[- ]tolerant|multi[- ]tenant|production[- ]grade)", re.IGNORECASE),
    re.compile(r"\b(?:novel|original|new)\s+(?:algorithm|architecture|approach|framework)\b", re.IGNORECASE),
    re.compile(r"\b(?:p\s*vs\s*np|riemann|np[- ]hard|np[- ]complete)\b", re.IGNORECASE),
]


# ============================================================================
# Output-token estimates per modality (used in cost estimation, not routing)
# ============================================================================

_OUTPUT_TOKEN_DEFAULTS = {
    Modality.TEXT: 400,
    Modality.CODE: 500,
    Modality.MATH: 600,
    Modality.VISION: 300,
    Modality.MULTIMODAL: 500,
}


# ============================================================================
# Extractor
# ============================================================================


class FeatureExtractor:
    """Stage B — extract QueryFeatures from a query + optional attachment hints.

    Stateless except for the cached lingua detector. Thread-safe.
    """

    def __init__(self, lingua_confidence_threshold: float = 0.55) -> None:
        self._lingua = _maybe_build_lingua_detector(lingua_confidence_threshold)
        self._lingua_threshold = lingua_confidence_threshold

    # ---------------- public ----------------

    def extract(
        self,
        query: str,
        *,
        has_image_attachment: bool = False,
        has_audio_attachment: bool = False,
        image_count: int = 0,
        attachment_mime_types: Optional[list[str]] = None,
    ) -> QueryFeatures:
        """Compute features for a single query."""
        if query is None:
            query = ""
        clean = self._sanitize(query)

        language = self._detect_language(clean)
        has_code_block = bool(_CODE_FENCE_RE.search(clean)) or any(
            r.search(clean) for r in _CODE_SIGNATURE_RES
        )
        is_math = any(r.search(clean) for r in _MATH_RES)
        text_references_image = bool(_VISION_REFERENCE_RE.search(clean))

        modality = self._determine_modality(
            has_code_block=has_code_block,
            is_math=is_math,
            has_image_attachment=has_image_attachment,
            has_audio_attachment=has_audio_attachment,
            text_references_image=text_references_image,
            attachment_mime_types=attachment_mime_types or [],
            query_word_count=len(clean.split()),
        )

        high_risk = self._detect_high_risk_domain(clean)

        char_count = len(clean)
        estimated_input_tokens = self._estimate_input_tokens(clean, language)
        estimated_output_tokens = _OUTPUT_TOKEN_DEFAULTS.get(modality, 400)

        difficulty = self._detect_difficulty(clean)

        return QueryFeatures(
            language=language,
            modality=modality,
            high_risk_domain=high_risk,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            difficulty_signal=difficulty,
            has_code_block=has_code_block,
            has_image_attachment=has_image_attachment,
            has_audio_attachment=has_audio_attachment,
            char_count=char_count,
        )

    # ---------------- internals ----------------

    @staticmethod
    def _sanitize(text: str) -> str:
        """Strip invisible Unicode format chars (Cf category) but keep newlines."""
        keep = {0x09, 0x0A, 0x0D, 0x20}
        out: list[str] = []
        for ch in text:
            if ord(ch) in keep:
                out.append(ch)
            elif unicodedata.category(ch) != "Cf":
                out.append(ch)
        return "".join(out).strip()

    def _detect_language(self, text: str) -> str:
        if not text:
            return "en"

        # Tier 1: non-Latin script regex
        for pattern, code in _SCRIPT_PATTERNS:
            if len(pattern.findall(text)) >= _SCRIPT_MIN_HITS:
                return code

        # Tier 1.5: Hinglish lexicon on Latin script
        tokens = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
        if len(tokens & _HINGLISH_MARKERS) >= 2:
            return "hi-Latn"

        # Tier 2: lingua-py with confidence threshold
        if self._lingua is not None:
            try:
                conf_values = self._lingua.compute_language_confidence_values(text)
            except Exception:
                conf_values = None
            if conf_values:
                top = conf_values[0]
                code = top.language.iso_code_639_1.name.lower()
                if top.value >= self._lingua_threshold and code != "en":
                    return code

        return "en"

    @staticmethod
    def _determine_modality(
        *,
        has_code_block: bool,
        is_math: bool,
        has_image_attachment: bool,
        has_audio_attachment: bool,
        text_references_image: bool,
        attachment_mime_types: list[str],
        query_word_count: int,
    ) -> Modality:
        # Count strong signals
        signals = 0
        if has_code_block:
            signals += 1
        if is_math:
            signals += 1
        vision_required = has_image_attachment and (
            text_references_image or query_word_count <= 15
        )
        if vision_required:
            signals += 1
        if has_audio_attachment or any(mt.startswith("audio/") for mt in attachment_mime_types):
            signals += 1

        if signals >= 2:
            return Modality.MULTIMODAL

        if vision_required:
            return Modality.VISION
        if has_audio_attachment:
            # No standalone AUDIO modality in this design — multimodal default
            return Modality.MULTIMODAL
        if is_math and not has_code_block:
            return Modality.MATH
        if has_code_block:
            return Modality.CODE
        return Modality.TEXT

    @staticmethod
    def _detect_high_risk_domain(text: str) -> Optional[HighRiskDomain]:
        if not text:
            return None
        if any(r.search(text) for r in _MEDICAL_RES):
            return HighRiskDomain.MEDICAL
        if any(r.search(text) for r in _LEGAL_RES):
            return HighRiskDomain.LEGAL
        if any(r.search(text) for r in _FINANCIAL_RES):
            return HighRiskDomain.FINANCIAL
        return None

    @staticmethod
    def _estimate_input_tokens(text: str, language: str) -> int:
        if not text:
            return 0
        char_count = len(text)
        # CJK ~ 1 char per token; Arabic / Devanagari ~ 0.8; default 4 chars/token
        if language in {"zh", "ja", "ko"}:
            return max(1, char_count)
        if language in {"ar", "hi", "bn", "ta"}:
            return max(1, int(char_count * 0.8))
        return max(1, (char_count + 3) // 4)

    @staticmethod
    def _detect_difficulty(text: str) -> DifficultySignal:
        if not text:
            return DifficultySignal.TRIVIAL

        stripped = text.strip()
        word_count = len(stripped.split())

        # Trivial: very short with no question structure
        if word_count <= 3 and "?" not in stripped and "." not in stripped:
            return DifficultySignal.TRIVIAL

        # Hard: explicit reasoning / proof / system-design markers
        if any(r.search(stripped) for r in _HARD_DIFFICULTY_MARKERS):
            return DifficultySignal.HARD

        # Hard by length (long, multi-sentence with code / math): coarse heuristic
        if word_count > 80 and any(r.search(stripped) for r in _MATH_RES + _CODE_SIGNATURE_RES):
            return DifficultySignal.HARD

        return DifficultySignal.NORMAL


# ============================================================================
# Singleton
# ============================================================================

_extractor: Optional[FeatureExtractor] = None
_extractor_lock = threading.Lock()


def get_feature_extractor() -> FeatureExtractor:
    """Process-wide FeatureExtractor. Thread-safe double-checked init."""
    global _extractor
    if _extractor is None:
        with _extractor_lock:
            if _extractor is None:
                _extractor = FeatureExtractor()
    return _extractor


def reset_feature_extractor() -> None:
    """Test helper — drop the singleton so the next get_feature_extractor()
    constructs a fresh one. Not for production use.
    """
    global _extractor
    with _extractor_lock:
        _extractor = None
