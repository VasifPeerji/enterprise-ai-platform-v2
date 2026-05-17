"""
📁 File: src/layer0_model_infra/routing/bandit_router.py
Layer: Layer 0 - Routing Pipeline (Step 5)
Purpose: Contextual multi-armed bandit with THOMPSON SAMPLING for continuous optimization
Depends on: src/layer0_model_infra/config, src/database
Used by: Elite router

Implements the contextual Thompson Sampling approach as specified in the synopsis:
  "the system employs a contextual Thompson Sampling approach rather than a simple
   epsilon-greedy strategy."

Bayesian update rule (Beta-Bernoulli conjugate):
  Prior:   arm ~ Beta(alpha=1, beta=1)   (uniform)
  Sample:  θ ~ Beta(alpha, beta)
  Select:  argmax θ
  Update:  alpha += success; beta += failure

Reward = QualityScore - (Cost × λ) - (Escalation × γ) - (NormLatency × β)

β normalises latency (ms → 0-1 by dividing by 10 000) so it competes
fairly with the other terms.
γ is doubled for high-risk domains (medical / legal) per domain-aware policy.

Budget Hard Lock (Section 4.4):
  When budget_remaining ≤ 0.20, routing is restricted to zero-cost (local/free)
  models only, regardless of bandit recommendation.

Domain Safety (Section 4.1):
  For medical / legal domains, exploration is completely suppressed. The arm with
  the highest *expected* reward (α / (α + β)) is always selected (full exploitation).
"""

import math
import random
import threading
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.layer0_model_infra.routing.fast_triage import ComplexityBand, Domain, Intent
from src.shared.logger import get_logger

logger = get_logger(__name__)
config = get_routing_config()

# Domains that require maximum safety — no exploration allowed.
HIGH_RISK_DOMAINS: set[str] = {Domain.MEDICAL.value, Domain.LEGAL.value}

# Budget threshold (0-1). Below this, hard-lock to free/utility models.
BUDGET_LOCK_THRESHOLD: float = 0.20

# Per-query max cost cap (USD).  Models costing more are excluded from selection.
MAX_COST_PER_QUERY_USD: float = 0.50

# Latency penalty coefficient for reward function
LATENCY_PENALTY_BETA: float = 0.001


class BanditContext(BaseModel):
    """Context for bandit routing decision."""

    # Core classification
    intent: Intent
    domain: Domain
    complexity_band: ComplexityBand
    uncertainty_score: float

    # Modality
    has_vision: bool = False
    has_code: bool = False

    # Input difficulty signals
    input_difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    has_multi_part: bool = False
    has_constraints: bool = False

    # Session history
    session_escalation_count: int = Field(default=0, ge=0)
    session_complexity_avg: float = Field(default=0.5, ge=0.0, le=1.0)

    # User / Budget context
    user_tier: str = Field(default="standard")   # free / standard / premium
    budget_remaining: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("intent", mode="before")
    @classmethod
    def _normalize_intent(cls, value):
        if isinstance(value, Intent):
            return value
        mapping = {
            "question_answering": Intent.QA,
            "qa": Intent.QA,
            "conversation": Intent.CASUAL,
            "chat": Intent.CASUAL,
            "general": Intent.QA,
        }
        return mapping.get(str(value).lower(), value)

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, value):
        if isinstance(value, Domain):
            return value
        mapping = {
            "coding": Domain.TECH,
            "technical": Domain.TECH,
            "technology": Domain.TECH,
            "finance": Domain.BUSINESS,
            "casual": Domain.CASUAL,
            "general": Domain.GENERAL,
        }
        return mapping.get(str(value).lower(), value)

    @field_validator("complexity_band", mode="before")
    @classmethod
    def _normalize_complexity(cls, value):
        if isinstance(value, ComplexityBand):
            return value
        mapping = {
            "medium": ComplexityBand.MODERATE,
            "hard": ComplexityBand.COMPLEX,
            "advanced": ComplexityBand.COMPLEX,
        }
        return mapping.get(str(value).lower(), value)

    def to_key(self) -> str:
        """Convert context to cache key (coarse granularity for better generalisation)."""
        return (
            f"{self.intent.value}_"
            f"{self.domain.value}_"
            f"{self.complexity_band.value}_"
            f"{'vision' if self.has_vision else 'text'}"
        )


class BanditArm(BaseModel):
    """
    A model choice (arm) in the Thompson Sampling bandit.

    Uses Beta-Bernoulli conjugate update:
        θ ~ Beta(alpha, beta)
        alpha += 1 on 'success' (high quality, no escalation)
        beta  += 1 on 'failure'
    """

    model_id: str

    # Beta distribution parameters (posterior over success probability)
    alpha: float = Field(default=1.0, ge=1.0)   # successes + 1 (prior = 1)
    beta_: float = Field(default=1.0, ge=1.0)   # failures  + 1 (prior = 1)

    # Statistics (for monitoring / persistence)
    pulls: int = 0
    successes: int = 0
    total_reward: float = 0.0
    avg_cost: float = 0.0
    escalation_count: int = 0
    avg_quality: float = 0.0
    avg_latency_ms: float = 0.0

    @property
    def expected_reward(self) -> float:
        """E[θ] = α / (α + β) — used for pure exploitation."""
        return self.alpha / (self.alpha + self.beta_)

    @property
    def success_rate(self) -> float:
        if self.pulls == 0:
            return 0.5
        return self.successes / self.pulls

    @property
    def escalation_rate(self) -> float:
        if self.pulls == 0:
            return 0.0
        return self.escalation_count / self.pulls

    @property
    def avg_reward(self) -> float:
        if self.pulls == 0:
            return 0.0
        return self.total_reward / self.pulls

    def sample_thompson(self) -> float:
        """Sample θ ~ Beta(alpha, beta_). Returns a float in (0, 1)."""
        return random.betavariate(self.alpha, self.beta_)


class BanditRouter:
    """
    Layer 5: Contextual Multi-Armed Bandit Router — Thompson Sampling.

    Continuously learns which models work best for different contexts.
    Replaces the previous epsilon-greedy approach per synopsis specification.
    """

    def __init__(self) -> None:
        """Initialise bandit router."""
        self.arms: dict[str, dict[str, BanditArm]] = {}  # context → model_id → arm
        self.learning_rate = config.bandit.learning_rate
        self.warmup_samples = config.bandit.warmup_samples
        self.total_pulls = 0
        self._lock = threading.Lock()   # guards concurrent arm updates

        # Load persisted state from database
        self.load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_model(
        self,
        context: BanditContext,
        available_models: list[str],
        registry=None,
        banned_models: Optional[set[str]] = None,
        max_cost_per_query: Optional[float] = None,
    ) -> str:
        """
        Select model using Thompson Sampling with domain safety, budget lock,
        per-query cost cap, and banned-model filtering.

        Args:
            context:            Current routing context
            available_models:   List of model IDs to choose from
            registry:           Optional registry reference (used for budget lock & cost cap)
            banned_models:      Optional set of model IDs to exclude from selection
            max_cost_per_query: Max estimated cost per query (USD); models above are excluded

        Returns:
            Selected model ID
        """
        with self._lock:
            # ── Filter banned models ───────────────────────────────────────────
            if banned_models:
                available_models = [m for m in available_models if m not in banned_models]
                if not available_models:
                    logger.warning("all_models_banned", fallback="reset")
                    # Can't proceed with empty list — should not happen in practice
                    raise ValueError("All available models are banned")

            # ── Per-query cost cap ─────────────────────────────────────────────
            cost_cap = max_cost_per_query or MAX_COST_PER_QUERY_USD
            if registry is not None:
                affordable_models = self._filter_by_cost_cap(available_models, registry, cost_cap)
                if affordable_models:
                    available_models = affordable_models
                else:
                    logger.warning(
                        "no_models_under_cost_cap",
                        cost_cap=cost_cap,
                        fallback="cheapest_available",
                    )
                    # Keep all and let cheapest win

            # ── Budget Hard Lock (Section 4.4) ─────────────────────────────────
            if context.budget_remaining <= BUDGET_LOCK_THRESHOLD:
                locked_models = self._filter_utility_models(available_models, registry)
                if locked_models:
                    selected = locked_models[0]
                    logger.info(
                        "budget_lock_engaged",
                        budget_remaining=context.budget_remaining,
                        selected=selected,
                        locked_pool=locked_models,
                    )
                    return selected
                logger.warning("budget_lock_no_utility_models", fallback="standard_selection")

            # ── Warmup Phase ──────────────────────────────────────────────────
            if self.total_pulls < self.warmup_samples:
                selected = random.choice(available_models)
                logger.debug("bandit_warmup_selection", model=selected)
                return selected

            # ── Initialise Arms ───────────────────────────────────────────────
            context_key = context.to_key()
            if context_key not in self.arms:
                self.arms[context_key] = {
                    model_id: BanditArm(model_id=model_id)
                    for model_id in available_models
                }

            arms = self.arms[context_key]

            # ── Domain Safety — Force Full Exploitation (Section 4.1) ─────────
            if context.domain.value in HIGH_RISK_DOMAINS:
                best_model = max(
                    available_models,
                    key=lambda m: arms.get(m, BanditArm(model_id=m)).expected_reward,
                )
                logger.info(
                    "domain_safety_exploitation",
                    domain=context.domain.value,
                    selected=best_model,
                    expected_reward=arms.get(best_model, BanditArm(model_id=best_model)).expected_reward,
                )
                return best_model

            # ── Thompson Sampling ─────────────────────────────────────────────
            sampled_rewards = {
                m: arms.get(m, BanditArm(model_id=m)).sample_thompson()
                for m in available_models
            }
            selected = max(sampled_rewards, key=sampled_rewards.get)

            logger.debug(
                "bandit_thompson_selection",
                selected=selected,
                sampled_rewards={m: round(v, 4) for m, v in sampled_rewards.items()},
                domain=context.domain.value,
            )
            return selected

    def update_reward(
        self,
        context: BanditContext,
        model_id: str,
        quality_score: float,
        cost: float,
        escalated: bool = False,
        latency_ms: float = 0.0,
        lambda_cost: float = 0.5,
        gamma_escalation: float = 0.3,
        beta_latency: Optional[float] = None,
    ) -> None:
        """
        Update bandit with feedback using enhanced reward + Bayesian posterior update.

        Reward = QualityScore - (Cost × λ) - (Escalation × γ) - (NormLatency × β)

        Domain-Aware Escalation Penalty (Section 4.1):
            γ is doubled for medical / legal domains.

        Latency Penalty (NEW):
            β (default LATENCY_PENALTY_BETA) normalises latency_ms by dividing by 10 000
            so a 5 000 ms response contributes −0.5 × β to the reward.
        """
        _beta = beta_latency if beta_latency is not None else LATENCY_PENALTY_BETA

        # ── Domain-aware escalation penalty adjustment ────────────────────────
        if context.domain.value in HIGH_RISK_DOMAINS:
            gamma_escalation = gamma_escalation * 2.0
            logger.debug(
                "domain_escalation_penalty_doubled",
                domain=context.domain.value,
                gamma=gamma_escalation,
            )

        context_key = context.to_key()

        with self._lock:
            if context_key not in self.arms:
                self.arms[context_key] = {}
            if model_id not in self.arms[context_key]:
                self.arms[context_key][model_id] = BanditArm(model_id=model_id)

            arm = self.arms[context_key][model_id]

            # ── Reward calculation (with latency penalty) ─────────────────────
            escalation_penalty = gamma_escalation if escalated else 0.0
            normalised_latency = latency_ms / 10_000.0  # 10s → 1.0
            latency_penalty = normalised_latency * _beta

            reward = (
                quality_score
                - (cost * lambda_cost)
                - escalation_penalty
                - latency_penalty
            )

            # ── Bayesian (Beta) posterior update ──────────────────────────────
            is_success = quality_score >= 0.7 and not escalated
            if is_success:
                arm.alpha += 1.0
                arm.successes += 1
            else:
                arm.beta_ += 1.0

            # ── Running statistics ────────────────────────────────────────────
            arm.pulls += 1
            arm.total_reward += reward
            if escalated:
                arm.escalation_count += 1
            arm.avg_cost = (arm.avg_cost * (arm.pulls - 1) + cost) / arm.pulls
            arm.avg_quality = (arm.avg_quality * (arm.pulls - 1) + quality_score) / arm.pulls
            arm.avg_latency_ms = (arm.avg_latency_ms * (arm.pulls - 1) + latency_ms) / arm.pulls

            self.total_pulls += 1

        logger.debug(
            "bandit_reward_updated_thompson",
            model=model_id,
            reward=round(reward, 4),
            alpha=arm.alpha,
            beta_=arm.beta_,
            expected_reward=round(arm.expected_reward, 4),
            escalation_rate=round(arm.escalation_rate, 4),
            latency_penalty=round(latency_penalty, 6),
        )

        # ── Async persistence — non-blocking ──────────────────────────────────
        threading.Thread(target=self._save_state_safe, daemon=True).start()

    def get_stats(self) -> dict:
        """Get bandit statistics."""
        total_escalations = sum(
            arm.escalation_count
            for arms_dict in self.arms.values()
            for arm in arms_dict.values()
        )
        return {
            "total_pulls": self.total_pulls,
            "exploration_strategy": "thompson_sampling",
            "contexts_learned": len(self.arms),
            "total_escalations": total_escalations,
        }

    def get_arm_stats(self, context_key: str) -> dict:
        """Get statistics for all arms in a specific context."""
        if context_key not in self.arms:
            return {}
        return {
            model_id: {
                "pulls":           arm.pulls,
                "alpha":           arm.alpha,
                "beta":            arm.beta_,
                "expected_reward": round(arm.expected_reward, 4),
                "success_rate":    round(arm.success_rate, 4),
                "escalation_rate": round(arm.escalation_rate, 4),
                "avg_quality":     round(arm.avg_quality, 4),
                "avg_cost":        round(arm.avg_cost, 6),
                "avg_latency_ms":  round(arm.avg_latency_ms, 1),
            }
            for model_id, arm in self.arms[context_key].items()
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """
        Save bandit arm states to database (synchronous).
        Called directly when a blocking save is needed (e.g. on shutdown).
        """
        from datetime import datetime

        from sqlmodel import Session, select

        from src.database.connection import get_engine
        from src.database.models.bandit_state import BanditArmState

        try:
            engine = get_engine()
            with Session(engine) as session:
                for context_key, arms_dict in self.arms.items():
                    for model_id, arm in arms_dict.items():
                        statement = select(BanditArmState).where(
                            BanditArmState.context_key == context_key,
                            BanditArmState.model_id == model_id,
                        )
                        existing = session.exec(statement).first()

                        if existing:
                            existing.pulls = arm.pulls
                            existing.successes = arm.successes
                            existing.total_reward = arm.total_reward
                            existing.escalation_count = arm.escalation_count
                            existing.avg_quality = arm.avg_quality
                            existing.avg_cost = arm.avg_cost
                            existing.avg_latency_ms = arm.avg_latency_ms
                            # New Thompson Sampling fields
                            existing.alpha = arm.alpha
                            existing.beta_ = arm.beta_
                            existing.updated_at = datetime.utcnow()
                        else:
                            new_state = BanditArmState(
                                context_key=context_key,
                                model_id=model_id,
                                pulls=arm.pulls,
                                successes=arm.successes,
                                total_reward=arm.total_reward,
                                escalation_count=arm.escalation_count,
                                avg_quality=arm.avg_quality,
                                avg_cost=arm.avg_cost,
                                avg_latency_ms=arm.avg_latency_ms,
                                alpha=arm.alpha,
                                beta_=arm.beta_,
                            )
                            session.add(new_state)

                        session.commit()

            logger.debug("bandit_state_saved", contexts=len(self.arms))
        except Exception as e:
            logger.error("bandit_save_failed", error=str(e))

    def _save_state_safe(self) -> None:
        """Wraps save_state() for use in background threads — swallows exceptions."""
        try:
            self.save_state()
        except Exception as e:
            logger.error("bandit_async_save_failed", error=str(e))

    def load_state(self) -> None:
        """Load bandit arm states from database on initialisation."""
        from sqlmodel import Session, select

        from src.database.connection import get_engine
        from src.database.models.bandit_state import BanditArmState

        try:
            engine = get_engine()
            with Session(engine) as session:
                states = session.exec(select(BanditArmState)).all()

                for state in states:
                    context_key = state.context_key
                    model_id = state.model_id

                    if context_key not in self.arms:
                        self.arms[context_key] = {}

                    # Restore Thompson Sampling parameters if present
                    alpha = getattr(state, "alpha", 1.0) or 1.0
                    beta_ = getattr(state, "beta_", 1.0) or 1.0

                    self.arms[context_key][model_id] = BanditArm(
                        model_id=model_id,
                        alpha=alpha,
                        beta_=beta_,
                        pulls=state.pulls,
                        successes=state.successes,
                        total_reward=state.total_reward,
                        escalation_count=state.escalation_count,
                        avg_quality=state.avg_quality,
                        avg_cost=state.avg_cost,
                        avg_latency_ms=state.avg_latency_ms,
                    )
                    self.total_pulls += state.pulls

            logger.info(
                "bandit_state_loaded",
                contexts=len(self.arms),
                total_pulls=self.total_pulls,
            )
        except Exception as e:
            logger.warning("bandit_load_failed", error=str(e))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_utility_models(
        available_models: list[str],
        registry=None,
    ) -> list[str]:
        """
        Return only free/local utility models from the available pool.
        Used during budget hard-lock.
        """
        if registry is None:
            return available_models

        utility = []
        for model_id in available_models:
            try:
                model = registry.get_model(model_id)
                cost = (
                    model.pricing.input_cost_per_1k_tokens
                    + model.pricing.output_cost_per_1k_tokens
                )
                if cost == 0.0:
                    utility.append(model_id)
            except Exception:
                pass
        return utility

    @staticmethod
    def _filter_by_cost_cap(
        available_models: list[str],
        registry,
        max_cost_usd: float,
    ) -> list[str]:
        """
        Return only models whose estimated per-query cost is below the cap.

        Estimate assumes a moderate-complexity request (200 input, 500 output tokens).
        """
        affordable = []
        for model_id in available_models:
            try:
                model = registry.get_model(model_id)
                est_cost = model.calculate_cost(input_tokens=200, output_tokens=500)
                if est_cost <= max_cost_usd:
                    affordable.append(model_id)
            except Exception:
                affordable.append(model_id)  # Can't estimate → keep
        return affordable


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_bandit_router: Optional[BanditRouter] = None


def get_bandit_router() -> BanditRouter:
    """Get global bandit router instance."""
    global _bandit_router
    if _bandit_router is None:
        _bandit_router = BanditRouter()
    return _bandit_router
