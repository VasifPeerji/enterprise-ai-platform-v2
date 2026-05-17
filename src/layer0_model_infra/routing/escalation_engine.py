"""
📁 File: src/layer0_model_infra/routing/escalation_engine.py
Layer: Layer 0 - Routing Pipeline (Step 8)
Purpose: Auto-escalate to better models when quality fails
Depends on: src/layer0_model_infra/registry, quality_evaluator
Used by: Elite router

Flow: Cheap → Mid → Premium
User sees only final answer.

User-Aware Escalation (Section 4.2):
  - premium: lower threshold (escalate sooner for higher confidence)
  - free:    only escalate on refusal (never on quality score alone)

Safeguards (NEW):
  - max_latency_ms:  halt escalation if cumulative latency exceeds budget
  - max_cost_usd:    halt escalation if cumulative cost exceeds limit
"""

from typing import Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.layer0_model_infra.models import ModelDefinition
from src.layer0_model_infra.registry import get_registry
from src.shared.logger import get_logger

logger = get_logger(__name__)
config = get_routing_config()
registry = get_registry()

# Tier-specific escalation threshold overrides.
# Lower value → escalate sooner (better quality) | Higher → escalate less often (cheaper).
TIER_ESCALATION_THRESHOLD: dict[str, float] = {
    "premium":  0.80,   # Escalate if quality < 0.80 (very conservative)
    "standard": 0.60,   # Default from config
    "free":     1.01,   # Effectively never escalate on quality alone (only refusals)
}


class EscalationPath(BaseModel):
    """Escalation path from cheap to premium with cost/latency tracking."""

    models: list[ModelDefinition] = Field(..., description="Models in escalation order")
    current_level: int = Field(default=0, description="Current position in path")
    max_attempts: int = Field(..., description="Maximum escalation attempts")

    # ── Safeguard tracking (NEW) ───────────────────────────────────────────
    cumulative_cost: float = Field(default=0.0, description="Total cost across all attempts")
    cumulative_latency_ms: float = Field(default=0.0, description="Total latency across all attempts")
    halt_reason: Optional[str] = Field(default=None, description="Why escalation was halted")

    @property
    def can_escalate(self) -> bool:
        return self.current_level < len(self.models) - 1 and self.halt_reason is None

    @property
    def current_model(self) -> ModelDefinition:
        return self.models[self.current_level]

    def escalate(self) -> Optional[ModelDefinition]:
        if not self.can_escalate:
            return None
        self.current_level += 1
        return self.models[self.current_level]

    def record_attempt(self, cost_usd: float, latency_ms: float) -> None:
        """Record cost and latency for this attempt."""
        self.cumulative_cost += cost_usd
        self.cumulative_latency_ms += latency_ms


class EscalationEngine:
    """
    Layer 8: Auto-Escalation Loop.

    Safety net for misrouting. When output quality is poor, automatically
    tries a better model. The user only ever sees the final valid response.

    Safeguards:
      - Max latency enforcement: halt if cumulative latency > budget
      - Max cost enforcement: halt if cumulative cost > per-request limit
    """

    # ── Default safeguard limits ───────────────────────────────────────────
    DEFAULT_MAX_LATENCY_MS: float = 30_000.0   # 30 seconds total
    DEFAULT_MAX_COST_USD: float = 2.00          # $2 total across all attempts

    def __init__(self) -> None:
        self.max_levels = config.escalation.max_escalation_levels

    def create_escalation_path(
        self,
        initial_model_id: str,
        requires_vision: bool = False,
        requires_code: bool = False,
    ) -> EscalationPath:
        """
        Create escalation path starting from initial model.

        Args:
            initial_model_id: Starting model
            requires_vision:  Whether vision capability is required
            requires_code:    Whether coding capability is required

        Returns:
            EscalationPath with ordered models (cheap → expensive)
        """
        try:
            initial_model = registry.get_model(initial_model_id)
        except Exception:
            logger.warning(
                "escalation_unknown_initial_model",
                initial_model_id=initial_model_id,
                requires_vision=requires_vision,
                requires_code=requires_code,
            )
            from src.layer0_model_infra.models import ModelCapability, ModelType

            fallback_type = ModelType.MULTIMODAL if requires_vision else ModelType.TEXT
            candidate_models = registry.list_models(
                model_type=fallback_type,
                only_active=True,
            )
            if requires_code:
                candidate_models = [
                    m for m in candidate_models
                    if m.supports_capability(ModelCapability.CODING)
                ]
            if requires_vision:
                candidate_models = [
                    m for m in candidate_models
                    if m.supports_capability(ModelCapability.VISION)
                ]
            if not candidate_models:
                candidate_models = registry.list_models(only_active=True)

            candidate_models.sort(
                key=lambda m: m.pricing.input_cost_per_1k_tokens + m.pricing.output_cost_per_1k_tokens
            )
            initial_model = candidate_models[0]

        candidate_models = registry.list_models(
            model_type=initial_model.model_type,
            only_active=True,
        )

        if requires_vision:
            from src.layer0_model_infra.models import ModelCapability
            candidate_models = [
                m for m in candidate_models
                if m.supports_capability(ModelCapability.VISION)
            ]

        if requires_code:
            from src.layer0_model_infra.models import ModelCapability
            candidate_models = [
                m for m in candidate_models
                if m.supports_capability(ModelCapability.CODING)
            ]

        # Sort cheapest → most expensive
        candidate_models.sort(
            key=lambda m: m.pricing.input_cost_per_1k_tokens + m.pricing.output_cost_per_1k_tokens
        )

        # Build escalation path starting from the initial model
        escalation_models = [initial_model]
        for model in candidate_models:
            if model.model_id == initial_model_id:
                continue
            if (
                model.pricing.input_cost_per_1k_tokens
                > escalation_models[-1].pricing.input_cost_per_1k_tokens
            ):
                escalation_models.append(model)
            if len(escalation_models) >= self.max_levels:
                break

        path = EscalationPath(
            models=escalation_models,
            current_level=0,
            max_attempts=len(escalation_models),
        )

        logger.info(
            "escalation_path_created",
            initial_model=initial_model_id,
            levels=len(escalation_models),
            models=[m.model_id for m in escalation_models],
        )
        return path

    def should_escalate(
        self,
        quality_score: float,
        refusal_detected: bool,
        user_tier: str = "standard",
        # ── NEW safeguard params ───────────────────────────────────────────
        cumulative_latency_ms: float = 0.0,
        cumulative_cost_usd: float = 0.0,
        max_latency_ms: Optional[float] = None,
        max_cost_usd: Optional[float] = None,
        escalation_path: Optional[EscalationPath] = None,
    ) -> bool:
        """
        Determine if escalation is needed with safeguard checks.

        User-Aware Logic (Section 4.2):
          - premium:  lower quality threshold → escalates sooner
          - free:     only escalates on explicit refusal

        Safeguards (NEW):
          - Halt if cumulative latency exceeds max_latency_ms
          - Halt if cumulative cost exceeds max_cost_usd

        Args:
            quality_score:          Quality score from evaluator (0-1)
            refusal_detected:       Whether model explicitly refused to answer
            user_tier:              User tier: free / standard / premium
            cumulative_latency_ms:  Total latency so far across all attempts
            cumulative_cost_usd:    Total cost so far
            max_latency_ms:         Max allowed latency (defaults to DEFAULT_MAX_LATENCY_MS)
            max_cost_usd:           Max allowed total cost (defaults to DEFAULT_MAX_COST_USD)
            escalation_path:        Current escalation path (for recording halt reason)

        Returns:
            True if should escalate, False otherwise
        """
        if not config.escalation.enable_escalation:
            return False

        # ── Safeguard: Latency budget ──────────────────────────────────────
        latency_limit = max_latency_ms or self.DEFAULT_MAX_LATENCY_MS
        if cumulative_latency_ms >= latency_limit:
            logger.warning(
                "escalation_halted_latency",
                cumulative_ms=cumulative_latency_ms,
                limit_ms=latency_limit,
            )
            if escalation_path:
                escalation_path.halt_reason = (
                    f"Latency budget exceeded ({cumulative_latency_ms:.0f} >= {latency_limit:.0f} ms)"
                )
            return False

        # ── Safeguard: Cost budget ─────────────────────────────────────────
        cost_limit = max_cost_usd or self.DEFAULT_MAX_COST_USD
        if cumulative_cost_usd >= cost_limit:
            logger.warning(
                "escalation_halted_cost",
                cumulative_usd=cumulative_cost_usd,
                limit_usd=cost_limit,
            )
            if escalation_path:
                escalation_path.halt_reason = (
                    f"Cost budget exceeded (${cumulative_cost_usd:.4f} >= ${cost_limit:.2f})"
                )
            return False

        # ── Always escalate on refusal regardless of tier ──────────────────
        if refusal_detected:
            logger.info("escalation_triggered_refusal", user_tier=user_tier)
            return True

        # ── Free tier: never escalate on quality alone ─────────────────────
        if user_tier == "free":
            return False

        # ── Tier-adjusted quality threshold ────────────────────────────────
        threshold = TIER_ESCALATION_THRESHOLD.get(
            user_tier,
            config.escalation.escalation_threshold,
        )

        if quality_score < threshold:
            logger.info(
                "escalation_triggered_quality",
                quality=round(quality_score, 4),
                threshold=threshold,
                user_tier=user_tier,
            )
            return True

        return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_escalation_engine: Optional[EscalationEngine] = None


def get_escalation_engine() -> EscalationEngine:
    """Get global escalation engine instance."""
    global _escalation_engine
    if _escalation_engine is None:
        _escalation_engine = EscalationEngine()
    return _escalation_engine
