"""
📁 File: src/layer0_model_infra/routing/legacy/uncertainty_estimator.py
Layer: Layer 0 - Routing Pipeline (Step 4)
Purpose: Estimate uncertainty in routing decisions
Depends on: pydantic
Used by: Elite router, bandit router

CRITICAL LAYER: High uncertainty → safer (more expensive) routing
Low uncertainty → cheaper routing

User-Aware Adjustments (Section 4.2):
  - premium: tighter bounds (lower threshold to escalate)
  - free:    wider tolerance (rely more on semantic cache/compute scaling)

NEW:
  - Shannon classification entropy H = -Σ p(x) log(p(x))
  - Instruction conflict detection
  - Cross-domain detection
  - Enhanced context dependency scoring
"""

import math
import re
from typing import Optional

from pydantic import BaseModel, Field

from src.shared.logger import get_logger

logger = get_logger(__name__)

# Tier-specific uncertainty bias applied AFTER all component scores are summed.
# Negative value = lower uncertainty (more conservative routing for premium).
USER_TIER_UNCERTAINTY_BIAS: dict[str, float] = {
    "premium":  -0.10,   # Tighter bounds → escalates sooner on premium tier
    "standard":  0.00,
    "free":      0.08,   # Wider tolerance → prefer cheaper models
}


class UncertaintyScore(BaseModel):
    """Uncertainty score breakdown."""

    total_uncertainty: float = Field(
        ..., ge=0.0, le=1.0, description="Overall uncertainty (0=certain, 1=very uncertain)"
    )

    # Component scores
    linguistic_uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    complexity_uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    domain_uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    context_uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)

    # ── New uncertainty components ─────────────────────────────────────────
    classification_entropy: float = Field(
        default=0.0, ge=0.0, description="Shannon entropy H = -Σ p log p"
    )
    instruction_conflict_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Contradictory instruction detection"
    )
    context_dependency_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="External context dependency"
    )
    cross_domain_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Multi-domain span detection"
    )

    confidence_level: str = Field(..., description="HIGH/MEDIUM/LOW confidence")
    reasoning: str = Field(..., description="Why this uncertainty level")
    user_tier: str = Field(default="standard", description="User tier used for adjustment")


class UncertaintyEstimator:
    """
    Layer 4: Uncertainty Estimation.

    Every routing decision must include confidence.
    This is the safety net that prevents catastrophic misroutes.
    """

    # Ambiguity indicators
    AMBIGUOUS_PATTERNS = [
        r'\?.*\?',
        r'maybe|perhaps|possibly|might|could be',
        r'not sure|unclear|confused',
        r'both.*and|either.*or',
    ]

    # Complex reasoning indicators
    REASONING_INDICATORS = [
        'because', 'therefore', 'however', 'although', 'nevertheless',
        'on the other hand', 'in contrast', 'similarly',
        'design', 'architecture', 'consensus', 'tradeoff', 'distributed',
    ]

    # Novel domain indicators
    NOVEL_DOMAIN_PATTERNS = [
        r'new\s+\w+', r'latest\s+\w+', r'recent\s+\w+',
        r'emerging', r'cutting-edge', r'state-of-the-art',
    ]

    # Instruction conflict indicators (contradictory requests)
    CONFLICT_PATTERNS = [
        (r'\bshort\b.*\bdetailed\b', 0.4),
        (r'\bsimple\b.*\bcomprehensive\b', 0.3),
        (r'\bbrief\b.*\bin\s+detail\b', 0.4),
        (r'\bdon\'t\b.*\bbut\s+also\b', 0.25),
        (r'\bwithout\b.*\binclude\b', 0.3),
        (r'\bignore\b.*\bconsider\b', 0.35),
        (r'\bonly\b.*\balso\b', 0.2),
    ]

    # Cross-domain indicators — domains that when combined signal high uncertainty
    DOMAIN_KEYWORDS = {
        "medical": ["medical", "health", "disease", "treatment", "diagnosis", "clinical", "patient"],
        "legal": ["law", "legal", "contract", "regulation", "court", "liability", "compliance"],
        "tech": ["software", "algorithm", "database", "API", "code", "programming", "ML", "AI"],
        "finance": ["finance", "stock", "investment", "banking", "trading", "portfolio"],
        "science": ["research", "experiment", "hypothesis", "theory", "physics", "chemistry"],
        "education": ["teach", "learn", "curriculum", "student", "course", "pedagogy"],
    }

    # Context dependency patterns (improved)
    CONTEXT_DEPENDENCY_PATTERNS = [
        (r'\b(it|this|that|these|those)\b', 0.05),           # pronoun density
        (r'\bas\s+mentioned\b|\blike\s+before\b', 0.3),      # explicit back-reference
        (r'\bpreviously\b|\bearlier\b|\babove\b', 0.25),     # temporal back-reference
        (r'\bfollowing\b|\bcontinuing\b|\bbuilding\s+on\b', 0.2),
        (r'\bthe\s+same\b|\bsimilar\s+to\b', 0.15),
        (r'\brefer\s+to\b|\bsee\s+(?:above|below|previous)\b', 0.3),
    ]

    def estimate(
        self,
        query: str,
        classifier_confidence: Optional[float] = None,
        classifier_probabilities: Optional[dict[str, float]] = None,
        query_length: Optional[int] = None,
        novelty_score: Optional[float] = None,
        input_signals: Optional[dict] = None,
        domain_risk: Optional[float] = None,
        user_tier: str = "standard",
        ctx_token_density: Optional[float] = None,
    ) -> UncertaintyScore:
        """
        Estimate routing uncertainty using multi-signal approach.

        Args:
            query:                    User query
            classifier_confidence:    Confidence from triage classifier
            classifier_probabilities: Full probability distribution from classifier (for entropy)
            query_length:             Length of query in tokens
            novelty_score:            Distance from nearest memory cluster (0-1)
            input_signals:            Raw input difficulty signals
            domain_risk:              Risk level of domain (0-1, medical/legal=high)
            user_tier:                User tier: free / standard / premium
            ctx_token_density:        Contextual density from conversation history (0-1)

        Returns:
            UncertaintyScore with components and aggregate confidence level
        """
        query_lower = query.lower()
        query_length = query_length or len(query.split())

        # ── Component 1: Linguistic uncertainty ────────────────────────────
        linguistic = self._estimate_linguistic_uncertainty(query_lower)

        # ── Component 2: Complexity uncertainty ────────────────────────────
        complexity = self._estimate_complexity_uncertainty(query_lower, query_length)

        # ── Component 3: Domain uncertainty ────────────────────────────────
        domain = self._estimate_domain_uncertainty(query_lower)

        # ── Component 4: Context uncertainty (query-level) ─────────────────
        context = self._estimate_context_uncertainty(query_lower, query_length)

        # ── Component 5: Novelty uncertainty ───────────────────────────────
        novelty_uncertainty = 0.0
        if novelty_score is not None and novelty_score > 0.7:
            novelty_uncertainty = novelty_score

        # ── Component 6: Input structure uncertainty ───────────────────────
        structure_uncertainty = 0.0
        if input_signals:
            if input_signals.get("has_multi_part"):
                structure_uncertainty += 0.18
            if input_signals.get("has_technical_terms"):
                structure_uncertainty += 0.12 if query_length < 50 else 0.08
            if input_signals.get("has_constraints"):
                structure_uncertainty += 0.12
            # New: reasoning depth contributes
            reasoning_depth = input_signals.get("reasoning_depth", 0.0)
            structure_uncertainty += reasoning_depth * 0.22
            # New: multi_intent_score (continuous)
            multi_intent = input_signals.get("multi_intent_score", 0.0)
            structure_uncertainty += multi_intent * 0.18
            if input_signals.get("instruction_count", 1) >= 3:
                structure_uncertainty += 0.08
            if input_signals.get("code_generation_flag"):
                structure_uncertainty += 0.08
            structure_uncertainty = min(structure_uncertainty, 1.0)

        # ── Component 7: Domain risk uncertainty ───────────────────────────
        domain_risk_uncertainty = 0.0
        if domain_risk is not None and domain_risk > 0.5:
            domain_risk_uncertainty = domain_risk * 0.5

        # ── Component 8: Conversational context token density ──────────────
        ctx_uncertainty = 0.0
        if ctx_token_density is not None and ctx_token_density > 0.5:
            ctx_uncertainty = (ctx_token_density - 0.5) * 0.4

        # ── Component 9 (NEW): Classification entropy ─────────────────────
        classification_entropy = self._compute_classification_entropy(
            classifier_probabilities, classifier_confidence
        )

        # ── Component 10 (NEW): Instruction conflict ──────────────────────
        instruction_conflict = self._detect_instruction_conflicts(query_lower)

        # ── Component 11 (NEW): Context dependency ────────────────────────
        context_dependency = self._compute_context_dependency(query_lower, query_length)

        # ── Component 12 (NEW): Cross-domain detection ────────────────────
        cross_domain = self._detect_cross_domain(query_lower)

        # ── Aggregate ──────────────────────────────────────────────────────
        if classifier_confidence is not None:
            classifier_uncertainty = 1.0 - classifier_confidence
            total = (
                linguistic               * 0.08
                + complexity             * 0.05      # reduced: was 0.10
                + domain                 * 0.06
                + context                * 0.05
                + novelty_uncertainty    * 0.10
                + structure_uncertainty  * 0.06      # reduced: was 0.12
                + domain_risk_uncertainty * 0.06
                + classifier_uncertainty * 0.20      # increased: was 0.15
                + ctx_uncertainty        * 0.08
                + classification_entropy * 0.10
                + instruction_conflict   * 0.07
                + context_dependency     * 0.05
                + cross_domain           * 0.08
            )
        else:
            total = (
                linguistic               * 0.10
                + complexity             * 0.05
                + domain                 * 0.08
                + context                * 0.07
                + novelty_uncertainty    * 0.12
                + structure_uncertainty  * 0.06
                + domain_risk_uncertainty * 0.06
                + ctx_uncertainty        * 0.07
                + classification_entropy * 0.12
                + instruction_conflict   * 0.08
                + context_dependency     * 0.08
                + cross_domain           * 0.10
            )

        # ── User-Tier Adjustment (Section 4.2) ────────────────────────────
        complexity_prior = 0.0
        if re.search(r'\b(explain|analyze|evaluate|assess|design|compare|neural)\b', query_lower):
            complexity_prior += 0.16
        if re.search(r'\bexplain\b', query_lower) and re.search(r'\b(neural|network)\b', query_lower):
            complexity_prior += 0.04
        if re.search(r'\b(distributed|consensus|architecture|quantum|causality|theoretical|prove|theorem|algorithm)\b', query_lower):
            complexity_prior += 0.28
        if classifier_confidence is not None and classifier_confidence < 0.45:
            complexity_prior += 0.14
        elif classifier_confidence is not None and classifier_confidence < 0.65:
            complexity_prior += 0.07
        total += complexity_prior

        tier_bias = USER_TIER_UNCERTAINTY_BIAS.get(user_tier, 0.0)
        total = max(0.0, min(1.0, total + tier_bias))

        # Determine confidence level
        if total < 0.3:
            confidence_level = "HIGH"
        elif total < 0.6:
            confidence_level = "MEDIUM"
        else:
            confidence_level = "LOW"

        reasoning = self._generate_reasoning(
            linguistic, complexity, domain, context, classifier_confidence, total,
            novelty_score, structure_uncertainty, domain_risk,
            user_tier, ctx_uncertainty,
            classification_entropy, instruction_conflict, context_dependency, cross_domain,
        )

        score = UncertaintyScore(
            total_uncertainty=round(total, 4),
            linguistic_uncertainty=linguistic,
            complexity_uncertainty=complexity,
            domain_uncertainty=domain,
            context_uncertainty=context,
            classification_entropy=round(classification_entropy, 4),
            instruction_conflict_score=round(instruction_conflict, 4),
            context_dependency_score=round(context_dependency, 4),
            cross_domain_score=round(cross_domain, 4),
            confidence_level=confidence_level,
            reasoning=reasoning,
            user_tier=user_tier,
        )

        logger.debug(
            "uncertainty_estimated",
            total=round(total, 4),
            confidence=confidence_level,
            tier=user_tier,
            novelty=novelty_score,
            entropy=round(classification_entropy, 4),
            conflict=round(instruction_conflict, 4),
            cross_domain=round(cross_domain, 4),
        )

        return score

    # ------------------------------------------------------------------
    # NEW component estimators
    # ------------------------------------------------------------------

    def _compute_classification_entropy(
        self,
        probabilities: Optional[dict[str, float]],
        confidence: Optional[float],
    ) -> float:
        """
        Compute Shannon entropy H = -Σ p(x) * log₂(p(x)).

        If the full probability distribution is available, compute exact entropy.
        Otherwise, approximate from the top-1 confidence value.
        """
        if probabilities:
            # Exact entropy from full distribution
            entropy = 0.0
            for p in probabilities.values():
                if p > 0:
                    entropy -= p * math.log2(p)

            # Normalise: max entropy for N classes = log2(N)
            max_entropy = math.log2(max(len(probabilities), 2))
            return min(entropy / max_entropy, 1.0) if max_entropy > 0 else 0.0

        if confidence is not None:
            # Approximate: model as binary (confident vs not)
            p = max(min(confidence, 0.999), 0.001)
            q = 1.0 - p
            entropy = -(p * math.log2(p) + q * math.log2(q))
            return entropy  # already in [0, 1] for binary

        return 0.5  # Unknown → moderate uncertainty

    def _detect_instruction_conflicts(self, query: str) -> float:
        """
        Detect contradictory instructions within the query.

        Returns 0-1 conflict score.
        """
        conflict_score = 0.0
        for pattern, weight in self.CONFLICT_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                conflict_score += weight

        return min(conflict_score, 1.0)

    def _compute_context_dependency(self, query: str, query_length: int) -> float:
        """
        Improved context dependency scoring with pronoun density analysis.

        High score means the query heavily depends on external context.
        """
        score = 0.0
        for pattern, weight in self.CONTEXT_DEPENDENCY_PATTERNS:
            matches = len(re.findall(pattern, query, re.IGNORECASE))
            if matches > 0:
                # Pronoun pattern gets weighted by density
                if weight < 0.1:
                    pronoun_density = matches / max(query_length, 1)
                    score += min(pronoun_density * 2.0, 0.3)
                else:
                    score += weight

        # Very long queries that reference external info
        if query_length > 150:
            score += 0.1

        return min(score, 1.0)

    def _detect_cross_domain(self, query: str) -> float:
        """
        Detect when a query spans multiple distinct domains.

        E.g., "legal implications of AI in healthcare" → legal + tech + medical
        """
        domains_hit: list[str] = []
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw.lower() in query)
            if hits >= 1:
                domains_hit.append(domain)

        if len(domains_hit) <= 1:
            return 0.0
        elif len(domains_hit) == 2:
            return 0.4
        elif len(domains_hit) == 3:
            return 0.7
        else:
            return 1.0

    # ------------------------------------------------------------------
    # Existing component estimators
    # ------------------------------------------------------------------

    def _estimate_linguistic_uncertainty(self, query: str) -> float:
        score = 0.0
        for pattern in self.AMBIGUOUS_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                score += 0.2
        question_marks = query.count('?')
        if question_marks > 1:
            score += 0.15 * min(question_marks - 1, 3)
        if re.search(r'\b(it|this|that|these|those)\b', query):
            score += 0.1
        return min(score, 1.0)

    def _estimate_complexity_uncertainty(self, query: str, query_length: int) -> float:
        score = 0.0
        if query_length < 5:
            score += 0.3
        if query_length > 100:
            score += 0.2
        elif query_length > 25:
            score += 0.1
        reasoning_count = sum(1 for ind in self.REASONING_INDICATORS if ind in query)
        if reasoning_count >= 2:
            score += 0.15
        if reasoning_count >= 4:
            score += 0.15
        if re.search(r'\bif\b.*\bthen\b', query, re.IGNORECASE):
            score += 0.2
        if re.search(r'\b(design|architecture|consensus|distributed|prove|theorem)\b', query, re.IGNORECASE):
            score += 0.2
        return min(score, 1.0)

    def _estimate_domain_uncertainty(self, query: str) -> float:
        score = 0.0
        for pattern in self.NOVEL_DOMAIN_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                score += 0.25
        if re.search(r'\b[A-Z]{3,}\b', query):
            score += 0.15
        return min(score, 1.0)

    def _estimate_context_uncertainty(self, query: str, query_length: int) -> float:
        score = 0.0
        context_refs = ['as mentioned', 'like before', 'previously', 'earlier', 'above', 'following']
        if any(ref in query for ref in context_refs):
            score += 0.3
        if query_length > 150:
            score += 0.2
        return min(score, 1.0)

    def _generate_reasoning(
        self,
        linguistic: float,
        complexity: float,
        domain: float,
        context: float,
        classifier_conf: Optional[float],
        total: float,
        novelty_score: Optional[float] = None,
        structure_uncertainty: Optional[float] = None,
        domain_risk: Optional[float] = None,
        user_tier: str = "standard",
        ctx_uncertainty: float = 0.0,
        entropy: float = 0.0,
        instruction_conflict: float = 0.0,
        context_dependency: float = 0.0,
        cross_domain: float = 0.0,
    ) -> str:
        reasons = []
        if linguistic > 0.3:
            reasons.append(f"ambiguous language ({linguistic:.2f})")
        if complexity > 0.3:
            reasons.append(f"unclear complexity ({complexity:.2f})")
        if domain > 0.3:
            reasons.append(f"novel domain ({domain:.2f})")
        if context > 0.3:
            reasons.append(f"context dependencies ({context:.2f})")
        if novelty_score and novelty_score > 0.7:
            reasons.append(f"HIGH novelty ({novelty_score:.2f})")
        if structure_uncertainty and structure_uncertainty > 0.3:
            reasons.append(f"complex structure ({structure_uncertainty:.2f})")
        if domain_risk and domain_risk > 0.5:
            reasons.append(f"high-risk domain ({domain_risk:.2f})")
        if classifier_conf is not None and classifier_conf < 0.7:
            reasons.append(f"low classifier confidence ({classifier_conf:.2f})")
        if ctx_uncertainty > 0.1:
            reasons.append(f"heavy conversational context ({ctx_uncertainty:.2f})")
        # New components
        if entropy > 0.5:
            reasons.append(f"high classification entropy ({entropy:.2f})")
        if instruction_conflict > 0.2:
            reasons.append(f"instruction conflicts ({instruction_conflict:.2f})")
        if context_dependency > 0.3:
            reasons.append(f"context-dependent ({context_dependency:.2f})")
        if cross_domain > 0.3:
            reasons.append(f"cross-domain query ({cross_domain:.2f})")

        if user_tier != "standard":
            bias = USER_TIER_UNCERTAINTY_BIAS.get(user_tier, 0.0)
            reasons.append(f"user_tier={user_tier} (bias={bias:+.2f})")
        if not reasons:
            reasons.append("high confidence in routing")
        return "; ".join(reasons)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_uncertainty_estimator: Optional[UncertaintyEstimator] = None


def get_uncertainty_estimator() -> UncertaintyEstimator:
    """Get global uncertainty estimator instance."""
    global _uncertainty_estimator
    if _uncertainty_estimator is None:
        _uncertainty_estimator = UncertaintyEstimator()
    return _uncertainty_estimator
