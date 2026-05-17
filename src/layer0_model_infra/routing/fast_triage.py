"""
📁 File: src/layer0_model_infra/routing/fast_triage.py
Layer: Layer 0 - Routing Pipeline (Step 3)
Purpose: Fast intent/domain/complexity classification
Depends on: src/layer0_model_infra/config
Used by: Elite router

This is a SMALL, FAST, CHEAP classifier that guides downstream routing.
It is intentionally lightweight, but it should still be directionally accurate.
"""

from enum import Enum
import re
from typing import Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.layer0_model_infra.routing.complexity_classifier import get_complexity_classifier
from src.layer0_model_infra.routing.fast_path import FastPathCategory, get_fast_path
from src.layer0_model_infra.routing.input_signals import InputSignals, get_input_extractor
from src.shared.logger import get_logger

logger = get_logger(__name__)
config = get_routing_config()


class Intent(str, Enum):
    """High-level intent categories."""

    QA = "qa"
    CODING = "coding"
    PLANNING = "planning"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    CASUAL = "casual"
    TECHNICAL = "technical"
    REASONING = "reasoning"


class Domain(str, Enum):
    """Domain categories."""

    TECH = "tech"
    BUSINESS = "business"
    MEDICAL = "medical"
    LEGAL = "legal"
    SCIENCE = "science"
    EDUCATION = "education"
    CASUAL = "casual"
    GENERAL = "general"


class ComplexityBand(str, Enum):
    """Rough complexity bands."""

    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    EXPERT = "expert"


class AmbiguityFlags(BaseModel):
    """Flags that strongly affect routing."""

    is_multi_intent: bool = False
    is_vague: bool = False
    is_underspecified: bool = False


class TriageResult(BaseModel):
    """Result from fast triage classifier."""

    intent: Intent = Field(..., description="Detected intent")
    domain: Domain = Field(..., description="Detected domain")
    complexity_band: ComplexityBand = Field(..., description="Rough complexity")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classifier confidence")
    ambiguity: AmbiguityFlags = Field(default_factory=AmbiguityFlags, description="Ambiguity flags")
    task_type: str = Field(default="qa", description="High-level task type")
    instruction_count: int = Field(default=1, description="Estimated instruction count")
    prompt_length: int = Field(default=0, description="Prompt byte length")
    reasoning: str = Field(..., description="Why this classification")

    # ── Rubric pass-through from ComplexityClassifier ─────────
    complexity_raw_score: float = Field(default=0.5, ge=0.0, le=1.0,
        description="Raw complexity score from classifier")
    complexity_rubric: dict = Field(default_factory=dict,
        description="5 rubric dimensions from classifier")


class FastTriageClassifier:
    """
    Layer 3: Fast triage.

    This remains lightweight by design, but it now combines:
    - direct pattern checks for clear cases
    - keyword scoring
    - input-structure signals from Layer 1.5
    """

    INTENT_KEYWORDS = {
        Intent.QA: ["what", "who", "when", "where", "why", "how", "explain"],
        Intent.CODING: ["code", "function", "debug", "implement", "python", "javascript", "bug"],
        Intent.PLANNING: ["plan", "strategy", "roadmap", "approach", "steps", "vacation", "itinerary"],
        Intent.CREATIVE: ["write", "story", "poem", "creative", "generate"],
        Intent.ANALYSIS: ["analyze", "compare", "evaluate", "assess", "tradeoff", "review"],
        Intent.CASUAL: ["hello", "hi", "thanks", "bye", "weather"],
        Intent.TECHNICAL: ["technical", "architecture", "system", "design"],
        Intent.REASONING: ["prove", "derive", "logic", "theorem", "hypothesis"],
    }

    DOMAIN_KEYWORDS = {
        Domain.TECH: [
            "software", "ai", "ml", "algorithm", "database", "python", "javascript",
            "code", "api", "distributed", "consensus", "neural",
        ],
        Domain.BUSINESS: [
            "business", "finance", "financial", "marketing", "sales", "stocks",
            "invest", "investment", "quarterly", "revenue", "profit", "portfolio",
            "banking", "fraud",
        ],
        Domain.MEDICAL: [
            "medical", "health", "disease", "treatment", "dosage", "symptom",
            "medication", "patient", "diagnosis", "prescription", "doctor",
            "hospital", "therapy", "drug", "clinical", "bone", "leg",
            "chest", "pain", "urgent", "dizziness", "blurred", "vision", "care", "medically",
        ],
        Domain.LEGAL: [
            "law", "legal", "contract", "regulation", "attorney", "lawsuit",
            "court", "statute", "liability", "compliance", "rights",
            "privacy", "consent", "gdpr", "obligations",
        ],
        Domain.SCIENCE: ["research", "experiment", "hypothesis", "theory", "physics", "quantum"],
        Domain.EDUCATION: ["learn", "teach", "study", "course", "student"],
        Domain.CASUAL: ["hello", "chat", "talk", "weather", "thanks"],
    }

    MULTI_INTENT_CONNECTORS = ["and also", "but also", "additionally", "moreover", "furthermore", "on top of that"]
    VAGUE_PATTERNS = ["something", "a bit", "kind of", "sort of", "maybe", "idk", "not sure"]
    UNDERSPECIFIED_PATTERNS = ["help me", "fix this", "do this", "handle it", "figure out"]
    EXPERT_PATTERNS = [
        "riemann hypothesis",
        "formal proof",
        "proof of",
        "prove",
        "derive",
        "completeness theorem",
        "np-hard",
        "computational complexity",
    ]
    COMPLEX_SYSTEM_PATTERNS = [
        "distributed system",
        "distributed consensus",
        "fault-tolerant",
        "multi-tenant",
        "event-driven architecture",
        "system design",
        "design an architecture",
    ]
    HIGH_STAKES_ACTION_PATTERNS = [
        "dosage",
        "treatment",
        "prescription",
        "diagnosis",
        "legal rights",
        "lawsuit",
        "sue",
        "contract dispute",
        "should i take",
        "is it safe",
        "what should i do",
    ]
    SIMPLE_FACTUAL_STARTERS = (
        "what is",
        "who is",
        "when is",
        "where is",
        "define",
        "meaning of",
    )

    def __init__(self) -> None:
        self._llm_triage_model = config.fast_triage.model
        self._llm_triage_available = True
        self._input_extractor = get_input_extractor()
        self._complexity_classifier = get_complexity_classifier()
        # Layer 3 delegates greeting / arithmetic detection to Layer 0. This
        # keeps the trivial-bypass rules in one place (fast_path.py) — if you
        # need to fix a greeting false positive, fix it there, not here.
        self._fast_path = get_fast_path()

    def classify(self, query: str, input_signals: Optional[InputSignals] = None) -> TriageResult:
        """Classify query intent, domain, and complexity.

        First defers to Layer 0 (Fast Path). If Fast Path bypasses, synthesise
        a minimal TRIVIAL TriageResult instead of running the LLM classifier —
        this keeps direct callers of `triage.classify("hello")` (e.g. tests,
        ad-hoc callers) cheap and consistent with the router's bypass.
        """
        # ── Layer 0 delegation: greetings / arithmetic / simple factual ────
        fp = self._fast_path.analyze(query)
        if fp.should_bypass:
            return self._build_fast_path_triage_result(query, fp)

        input_signals = input_signals or self._input_extractor.extract(query)
        query_lower = query.lower()
        tokens = set(re.findall(r"[a-zA-Z0-9_+\-]+", query_lower))

        intent, intent_conf = self._classify_intent(query_lower, query, tokens, input_signals)
        domain, domain_conf = self._classify_domain(query_lower, query, tokens, input_signals)
        complexity_band, complexity_conf, complexity_rubric = self._classify_complexity(
            query_lower, query, input_signals
        )
        ambiguity = self._detect_ambiguity(query_lower, input_signals)

        confidence = min(intent_conf, domain_conf, complexity_conf)
        if ambiguity.is_vague or ambiguity.is_underspecified:
            confidence = max(confidence - 0.18, 0.1)
        if ambiguity.is_multi_intent:
            confidence = max(confidence - 0.12, 0.1)

        task_type = input_signals.task_type.value if input_signals else "qa"
        instruction_count = input_signals.instruction_count if input_signals else 1
        prompt_length = input_signals.prompt_length if input_signals else len(query.encode("utf-8"))

        reasoning = (
            f"Intent: {intent.value} ({intent_conf:.2f}); "
            f"Domain: {domain.value} ({domain_conf:.2f}); "
            f"Complexity: {complexity_band.value} ({complexity_conf:.2f})"
        )
        if ambiguity.is_multi_intent or ambiguity.is_vague or ambiguity.is_underspecified:
            flags = []
            if ambiguity.is_multi_intent:
                flags.append("multi-intent")
            if ambiguity.is_vague:
                flags.append("vague")
            if ambiguity.is_underspecified:
                flags.append("underspecified")
            reasoning += f"; ambiguity=[{', '.join(flags)}]"

        result = TriageResult(
            intent=intent,
            domain=domain,
            complexity_band=complexity_band,
            confidence=round(confidence, 4),
            ambiguity=ambiguity,
            task_type=task_type,
            instruction_count=instruction_count,
            prompt_length=prompt_length,
            reasoning=reasoning,
            complexity_raw_score=complexity_rubric.get("raw_score", 0.5),
            complexity_rubric=complexity_rubric,
        )

        logger.debug(
            "triage_classification",
            intent=intent.value,
            domain=domain.value,
            complexity_band=complexity_band.value,
            confidence=result.confidence,
            ambiguity=ambiguity.model_dump(),
        )
        return result



    def _classify_intent(
        self,
        query: str,
        raw_query: str,
        tokens: set[str],
        input_signals: Optional[InputSignals],
    ) -> tuple[Intent, float]:
        if input_signals:
            if input_signals.code_generation_flag or input_signals.required_format.value == "code":
                return Intent.CODING, 0.93
            if input_signals.task_type.value == "analysis":
                return Intent.ANALYSIS, 0.84
            if (
                input_signals.task_type.value == "conversation"
                and len(query.split()) <= 10
                and tokens.intersection({"hello", "hi", "hey", "thanks", "bye"})
            ):
                return Intent.CASUAL, 0.94

        stripped = raw_query.strip()
        first_word = stripped.split()[0].lower() if stripped.split() else ""
        if stripped.startswith("def ") or stripped.startswith("class "):
            return Intent.CODING, 0.97
        if tokens.intersection({"python", "java", "javascript", "sql", "api", "rest", "c++"}) and (
            tokens.intersection({"function", "debug", "query", "client", "implement", "algorithm", "code"})
            or "sql query" in query
        ):
            return Intent.CODING, 0.92
        if any(kw in query for kw in ["vacation", "itinerary", "plan my", "approach this problem"]):
            return Intent.PLANNING, 0.84
        if any(kw in query for kw in ["compare", "tradeoff", "trade-off", "evaluate", "assess", "review"]):
            return Intent.ANALYSIS, 0.82
        if any(kw in query for kw in ["prove", "derive", "riemann hypothesis"]):
            return Intent.REASONING, 0.92
        if first_word == "explain" and not any(
            kw in query for kw in ["compare", "evaluate", "assess", "critique", "tradeoff", "trade-off"]
        ):
            return Intent.QA, 0.84
        if (
            len(query.split()) <= 12
            and (tokens.intersection({"hello", "hi", "thanks", "bye"}) or "thank you" in query)
        ):
            return Intent.CASUAL, 0.96
        if first_word in {"what", "who", "when", "where", "why", "how", "explain"}:
            return Intent.QA, 0.82

        scores = {
            intent: self._score_keywords(query, tokens, keywords)
            for intent, keywords in self.INTENT_KEYWORDS.items()
        }
        scores = {intent: score for intent, score in scores.items() if score > 0}
        if not scores:
            return Intent.QA, 0.68

        max_intent = max(scores, key=scores.get)
        confidence = min(0.6 + (scores[max_intent] * 0.12), 0.95)
        return max_intent, confidence

    def _classify_domain(
        self,
        query: str,
        raw_query: str,
        tokens: set[str],
        input_signals: Optional[InputSignals],
    ) -> tuple[Domain, float]:
        if input_signals and input_signals.code_generation_flag:
            return Domain.TECH, 0.9
        stripped = raw_query.strip()
        if stripped.startswith("def ") or "python" in query or "javascript" in query:
            return Domain.TECH, 0.96

        scores = {
            domain: self._score_keywords(query, tokens, keywords)
            for domain, keywords in self.DOMAIN_KEYWORDS.items()
        }
        scores = {domain: score for domain, score in scores.items() if score > 0}
        if not scores:
            return Domain.GENERAL, 0.74

        if scores.get(Domain.MEDICAL, 0) > 0:
            confidence = min(0.76 + (scores[Domain.MEDICAL] * 0.08), 0.98)
            return Domain.MEDICAL, confidence
        if scores.get(Domain.LEGAL, 0) > 0:
            confidence = min(0.76 + (scores[Domain.LEGAL] * 0.08), 0.98)
            return Domain.LEGAL, confidence

        max_domain = max(scores, key=scores.get)
        confidence = min(0.62 + (scores[max_domain] * 0.1), 0.96)
        return max_domain, confidence

    def _build_fast_path_triage_result(self, query: str, fp) -> TriageResult:
        """
        Synthesise a TRIVIAL TriageResult from a Layer 0 fast-path decision.

        Called when Layer 0 has already determined the query is bypass-eligible
        (greeting / arithmetic / simple factual / malformed). Returning here
        avoids invoking the LLM complexity classifier — that's the whole point
        of Layer 0.

        The detected_language from Fast Path is preserved in the reasoning
        string so downstream layers (telemetry, future locale-aware features)
        can recover the language hint without re-detecting it.
        """
        category = fp.category
        if category in (
            FastPathCategory.TRIVIAL_GREETING,
            FastPathCategory.TRIVIAL_ACK,
            FastPathCategory.TRIVIAL_FAREWELL,
        ):
            intent, domain, task_type = Intent.CASUAL, Domain.CASUAL, "conversation"
        elif category == FastPathCategory.MALFORMED:
            intent, domain, task_type = Intent.CASUAL, Domain.CASUAL, "conversation"
        else:
            intent, domain, task_type = Intent.QA, Domain.GENERAL, "qa"

        rubric = {
            "raw_score": 0.05,
            "task_count": 0.05,
            "domain_depth": 0.0,
            "reasoning_hops": 0.1 if category == FastPathCategory.PURE_ARITHMETIC else 0.0,
            "output_structure": 0.05,
            "knowledge_breadth": 0.0,
        }
        language = fp.detected_language or "en"
        return TriageResult(
            intent=intent,
            domain=domain,
            complexity_band=ComplexityBand.TRIVIAL,
            confidence=fp.confidence,
            ambiguity=AmbiguityFlags(),
            task_type=task_type,
            instruction_count=1,
            prompt_length=len(query.encode("utf-8")),
            reasoning=f"Layer 0 fast-path: {category.value} ({fp.matched_pattern}, lang={language})",
            complexity_raw_score=0.05,
            complexity_rubric=rubric,
        )

    def _classify_complexity(
        self,
        query: str,
        raw_query: str,
        input_signals: Optional[InputSignals],
    ) -> tuple[ComplexityBand, float, dict]:
        """
        Classify complexity via the LLM classifier.

        Greeting and arithmetic short-circuits live in Layer 0 (fast_path.py)
        and are caught at the top of `classify()` before this is reached.

        Returns (band, confidence, rubric_info_dict).
        """
        result = self._complexity_classifier.classify(raw_query, input_signals)
        try:
            band = ComplexityBand(result.complexity_band)
        except ValueError:
            band = ComplexityBand.MODERATE

        rubric = {
            "raw_score": result.raw_score,
            "task_count": result.task_count,
            "domain_depth": result.domain_depth,
            "reasoning_hops": result.reasoning_hops,
            "output_structure": result.output_structure,
            "knowledge_breadth": result.knowledge_breadth,
        }
        return band, result.confidence, rubric



    def _detect_ambiguity(
        self,
        query: str,
        input_signals: Optional[InputSignals] = None,
    ) -> AmbiguityFlags:
        """Detect multi-intent, vague, and underspecified queries."""
        mixed_intent_pattern = (
            ("explain" in query or "summarize" in query or "analyze" in query)
            and ("write code" in query or "implement" in query or "plan" in query)
            and " and " in query
        )
        is_multi_intent = (
            any(conn in query for conn in self.MULTI_INTENT_CONNECTORS)
            or (query.count("?") >= 2)
            or mixed_intent_pattern
            or bool(input_signals and input_signals.multi_intent_score >= 0.3)
        )
        is_vague = any(p in query for p in self.VAGUE_PATTERNS)
        is_underspecified = any(p in query for p in self.UNDERSPECIFIED_PATTERNS) and len(query.split()) < 25
        return AmbiguityFlags(
            is_multi_intent=is_multi_intent,
            is_vague=is_vague,
            is_underspecified=is_underspecified,
        )

    def _score_keywords(self, query: str, tokens: set[str], keywords: list[str]) -> int:
        score = 0
        for keyword in keywords:
            if " " in keyword or "-" in keyword:
                if keyword in query:
                    score += 1
            elif keyword in tokens:
                score += 1
        return score


_triage_classifier: Optional[FastTriageClassifier] = None


def get_triage_classifier() -> FastTriageClassifier:
    """Get global triage classifier instance."""
    global _triage_classifier
    if _triage_classifier is None:
        _triage_classifier = FastTriageClassifier()
    return _triage_classifier
