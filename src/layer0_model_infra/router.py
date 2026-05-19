"""
📁 File: src/layer0_model_infra/router.py
Layer: Layer 0 (Model Infrastructure)
Purpose: ELITE 9-layer adaptive routing pipeline
Depends on: All routing components
Used by: API routes, orchestrator

ELITE ROUTING PIPELINE:
  Layer 0 (bypass): Fast Path → trivial single-line queries skip the pipeline
  Layer 1:  Modality Gate    → Detect capabilities required
  Layer 1.5: Input Signals   → Extract difficulty signals from query structure
  Layer 2:  Semantic Memory  → Cache lookup (short-circuit on hit)
  Layer 3:  Fast Triage      → Intent / domain / complexity classification
  Layer 4:  Uncertainty      → Calibrated uncertainty estimation
  Layer 5:  Bandit Router    → Thompson Sampling model selection
  Layer 6:  Test-Time Compute→ Best-of-N for moderate-uncertainty queries
  Layer 7:  Quality Evaluation → Output validation (silent failure detection)
  Layer 8:  Auto-Escalation  → Retry with better model on quality failure
  Layer 9:  Telemetry        → Async continuous-learning feedback loop
"""

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.layer0_model_infra.models import (
    ModelCapability,
    ModelDefinition,
    ModelProvider,
    ModelRoutingTier,
    ModelType,
)
from src.layer0_model_infra.registry import get_registry
from src.layer0_model_infra.routing.bandit_router import BanditContext, get_bandit_router
from src.layer0_model_infra.routing.escalation_engine import get_escalation_engine
from src.layer0_model_infra.routing.fast_path import get_fast_path
from src.layer0_model_infra.routing.fast_triage import get_triage_classifier
from src.layer0_model_infra.routing.input_signals import get_input_extractor
from src.layer0_model_infra.routing.modality_gate import get_modality_gate
from src.layer0_model_infra.routing.quality_evaluator import get_quality_evaluator
from src.layer0_model_infra.routing.semantic_memory import get_semantic_memory
from src.layer0_model_infra.routing.telemetry import RoutingTelemetry, TelemetryLogger
from src.layer0_model_infra.routing.uncertainty_estimator import get_uncertainty_estimator
from src.layer0_model_infra.routing.benchmark_router import get_benchmark_router
from src.shared.config import get_settings
from src.shared.errors import ModelNotFoundError
from src.shared.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()
routing_config = get_routing_config()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    """Decision made by elite routing pipeline."""

    selected_model: ModelDefinition = Field(..., description="Selected model")
    fallback_models: list[ModelDefinition] = Field(
        default_factory=list, description="Fallback models in order"
    )

    # Pipeline results
    modality_analysis: dict = Field(..., description="Modality gate results")
    triage_result: dict = Field(..., description="Fast triage classification")
    uncertainty_score: dict = Field(..., description="Uncertainty estimation")
    bandit_context: Optional[dict] = Field(default=None, description="Context used for bandit")

    # Decision metadata
    routing_reasoning: str = Field(..., description="Complete routing reasoning")
    estimated_cost_usd: float = Field(..., description="Estimated cost for request")
    confidence_level: str = Field(..., description="HIGH/MEDIUM/LOW confidence")

    # Layer 0 — Fast Path provenance. These are top-level so callers can branch
    # without reaching into pipeline_metadata. They duplicate the legacy keys
    # inside pipeline_metadata for backwards compatibility with chat.py / orchestrator.
    fast_path_triggered: bool = Field(
        default=False, description="True when Layer 0 bypassed the full pipeline"
    )
    fast_path_category: Optional[str] = Field(
        default=None,
        description="Which Layer 0 category fired (greeting, arithmetic, factual, …)",
    )

    # Escalation info
    escalation_path_available: bool = Field(default=True)
    escalation_levels: int = Field(default=0)

    # Pipeline metadata
    pipeline_metadata: dict = Field(default_factory=dict)
    benchmark_recommendation: Optional[dict] = Field(
        default=None,
        description="Benchmark router advisory signal (quality/cost optimised)",
    )


class EliteRoutingResult(BaseModel):
    """Complete result from elite routing including quality check."""

    decision: RoutingDecision
    quality_score: Optional[dict] = None
    escalated: bool = False
    escalation_count: int = 0
    final_model_used: str = Field(..., description="Final model after any escalations")


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """
    Elite 9-layer adaptive routing pipeline.

    Self-correcting, cost-aware, feedback-driven routing system that
    implements the full specification from Synopsis_Layer0_Routing_System_V2.
    """

    def __init__(self) -> None:
        """Initialise router with all pipeline components."""
        self.registry = get_registry()
        self.fast_path = get_fast_path()                      # Layer 0 – bypass
        self.modality_gate = get_modality_gate()              # Layer 1
        self.input_extractor = get_input_extractor()          # Layer 1.5
        self.semantic_memory = get_semantic_memory()           # Layer 2
        self.triage_classifier = get_triage_classifier()      # Layer 3
        self.uncertainty_estimator = get_uncertainty_estimator()  # Layer 4
        self.bandit_router = get_bandit_router()              # Layer 5
        self.quality_evaluator = get_quality_evaluator()      # Layer 7
        self.escalation_engine = get_escalation_engine()      # Layer 8
        self.benchmark_router = get_benchmark_router()        # Benchmark advisor

    def route(
        self,
        query: str,
        has_images: bool = False,
        has_audio: bool = False,
        image_count: int = 0,
        has_video: bool = False,
        file_types: Optional[list[str]] = None,
        attachment_sizes_mb: Optional[list[float]] = None,
        force_model_id: Optional[str] = None,
        # User / budget context (Sections 4.2 and 4.4)
        user_tier: str = "standard",
        budget_remaining: float = 1.0,
        session_escalation_count: int = 0,
        session_complexity_avg: float = 0.5,
        # Context-aware routing (Section 4.3)
        history: Optional[list[dict]] = None,
        # Request tracking
        request_id: Optional[str] = None,
    ) -> RoutingDecision:
        """
        Route query through the elite 9-layer pipeline.

        Args:
            query:                  User's query text
            has_images:             Whether images are attached
            has_audio:              Whether audio is attached
            image_count:            Number of images
            force_model_id:         Force specific model (bypasses routing)
            user_tier:              User tier: free / standard / premium
            budget_remaining:       Fraction of daily budget remaining (0-1)
            session_escalation_count: Number of escalations in this session
            session_complexity_avg: Rolling average query complexity (0-1)
            history:                Previous conversation turns for context density
            request_id:             Optional request identifier for telemetry

        Returns:
            RoutingDecision with complete pipeline results
        """
        request_id = request_id or str(uuid.uuid4())
        logger.info("elite_routing_started", query_length=len(query), request_id=request_id)

        # If model is forced, skip pipeline
        if force_model_id:
            model = self.registry.get_model(force_model_id)
            decision = self._create_forced_decision(model, query)
            self._emit_telemetry(
                request_id=request_id,
                decision=decision,
                user_tier=user_tier,
                budget_remaining=budget_remaining,
                query=query,
            )
            return decision

        # =======================================================
        # LAYER 0: FAST PATH BYPASS
        # The Fast Path is the only place that decides bypass. When it fires
        # NO downstream layer (modality / triage / uncertainty / bandit) is
        # invoked — _create_fast_path_decision synthesises neutral metadata.
        # =======================================================
        fast_path_decision = self.fast_path.analyze(query)
        if fast_path_decision.should_bypass and fast_path_decision.recommended_model:
            logger.info(
                "fast_path_triggered",
                category=fast_path_decision.category.value,
                model=fast_path_decision.recommended_model,
                pattern=fast_path_decision.matched_pattern,
                language=fast_path_decision.detected_language,
                confidence=fast_path_decision.confidence,
                request_id=request_id,
            )
            model = self._resolve_fast_path_model_with_fallback(
                fast_path_decision, request_id
            )
            if model is not None:
                decision = self._create_fast_path_decision(model, query, fast_path_decision)
                self._emit_telemetry(
                    request_id=request_id,
                    decision=decision,
                    user_tier=user_tier,
                    budget_remaining=budget_remaining,
                    query=query,
                )
                return decision
            # Else: model resolution failed all chain attempts — fall through
            # to the full pipeline. This is rare (requires the entire chain
            # to become inactive between Fast Path resolution and router call).

        # =======================================================
        # LAYER 1: MODALITY GATE
        # The gate also runs input validation (size, MIME, injection patterns).
        # If validation fails, the gate returns validation_passed=False and we
        # MUST surface that as an error — silently proceeding routes potentially
        # hostile or oversized inputs through the full pipeline.
        # =======================================================
        modality_analysis = self.modality_gate.analyze(
            text=query,
            has_images=has_images,
            has_audio=has_audio,
            image_count=image_count,
            has_video=has_video,
            file_types=file_types,
            attachment_sizes_mb=attachment_sizes_mb,
        )
        if not modality_analysis.validation_passed:
            logger.error(
                "layer1_validation_blocked",
                reason=modality_analysis.reasoning,
                injection_risk=modality_analysis.contains_injection_risk,
                request_id=request_id,
            )
            # We don't have a clean "rejected" return type yet (would need a
            # broader API change). For now: raise so the route handler can map
            # to HTTP 400 / structured rejection. This is intentionally LOUD —
            # silently degrading was the old bug.
            from src.shared.errors import ValidationError
            raise ValidationError(
                f"Input validation failed at modality gate: {modality_analysis.reasoning}"
            )

        attachments_count = image_count + int(has_audio) + int(has_video)
        logger.info(
            "layer1_input_analysis",
            query_id=request_id,
            modality=modality_analysis.primary_modality.value,
            input_tokens=modality_analysis.token_count,
            attachments_count=attachments_count,
            detected_language=modality_analysis.language,
        )
        logger.debug(
            "layer1_modality_gate",
            modality=modality_analysis.primary_modality,
            requires_vision=modality_analysis.requires_vision,
        )

        # =======================================================
        # LAYER 1.5: INPUT SIGNAL EXTRACTION
        # =======================================================
        input_signals = self.input_extractor.extract(query)

        # =======================================================
        # LAYER 2: SEMANTIC MEMORY CACHE
        # =======================================================
        memory_result = self.semantic_memory.lookup(query)
        if memory_result.hit:
            logger.info(
                "semantic_memory_hit",
                model=memory_result.matched_model_id,
                similarity=memory_result.similarity,
            )
            model = self.registry.get_model(memory_result.matched_model_id)
            decision = self._create_cached_decision(model, query, memory_result, modality_analysis)
            self._emit_telemetry(
                request_id=request_id,
                decision=decision,
                user_tier=user_tier,
                budget_remaining=budget_remaining,
                novelty_score=memory_result.novelty_score,
                query=query,
            )
            return decision

        # =======================================================
        # LAYER 3: FAST TRIAGE
        # =======================================================
        triage_result = self.triage_classifier.classify(query, input_signals=input_signals)
        logger.debug(
            "layer3_fast_triage",
            intent=triage_result.intent,
            domain=triage_result.domain,
            complexity=triage_result.complexity_band,
            confidence=triage_result.confidence,
        )

        # =======================================================
        # LAYER 4: UNCERTAINTY ESTIMATION
        # Context-Aware: compute token density from conversational history
        # =======================================================
        ctx_token_density = self._compute_ctx_token_density(history)

        uncertainty_score = self.uncertainty_estimator.estimate(
            query=query,
            classifier_confidence=triage_result.confidence,
            query_length=len(query.split()),
            novelty_score=memory_result.novelty_score,
            input_signals=input_signals.model_dump(),
            user_tier=user_tier,
            ctx_token_density=ctx_token_density,
        )
        logger.debug(
            "layer4_uncertainty",
            total=uncertainty_score.total_uncertainty,
            confidence=uncertainty_score.confidence_level,
            tier=user_tier,
            ctx_density=ctx_token_density,
        )

        # =======================================================
        # LAYER 5: BANDIT-BASED MODEL SELECTION
        # =======================================================
        required_type = self._determine_model_type(modality_analysis)
        target_tier, routing_policy_reason = self._determine_target_tier(
            triage_result=triage_result,
            uncertainty_score=uncertainty_score.total_uncertainty,
            uncertainty_details=uncertainty_score,
            input_signals=input_signals,
            modality_analysis=modality_analysis,
            user_tier=user_tier,
            budget_remaining=budget_remaining,
        )
        candidates = self._get_candidate_models(
            model_type=required_type,
            modality_analysis=modality_analysis,
            triage_result=triage_result,
            uncertainty_score=uncertainty_score.total_uncertainty,
            input_signals=input_signals,
            target_tier=target_tier,
        )

        if not candidates:
            raise ModelNotFoundError(f"No models found for type={required_type}")

        bandit_context = BanditContext(
            intent=triage_result.intent,
            domain=triage_result.domain,
            complexity_band=triage_result.complexity_band,
            uncertainty_score=uncertainty_score.total_uncertainty,
            has_vision=modality_analysis.requires_vision,
            has_code=modality_analysis.requires_code_model,
            input_difficulty=input_signals.overall_difficulty,
            has_multi_part=input_signals.has_multi_part,
            has_constraints=input_signals.has_constraints,
            user_tier=user_tier,
            budget_remaining=budget_remaining,
            session_escalation_count=session_escalation_count,
            session_complexity_avg=session_complexity_avg,
        )

        candidate_ids = [m.model_id for m in candidates]
        selected_model_id = self.bandit_router.select_model(
            context=bandit_context,
            available_models=candidate_ids,
            registry=self.registry,
        )
        selected_model = self.registry.get_model(selected_model_id)

        logger.info(
            "layer5_bandit_selection",
            selected_model=selected_model_id,
            uncertainty=uncertainty_score.total_uncertainty,
        )

        # =======================================================
        # BUILD ROUTING DECISION
        # =======================================================
        fallback_models = [m for m in candidates if m.model_id != selected_model_id][:2]
        estimated_cost = self._estimate_cost(selected_model, triage_result.complexity_band.value)
        routing_reasoning = self._generate_elite_reasoning(
            modality_analysis, triage_result, uncertainty_score, selected_model
        )
        escalation_path = self.escalation_engine.create_escalation_path(
            initial_model_id=selected_model_id,
            requires_vision=modality_analysis.requires_vision,
            requires_code=modality_analysis.requires_code_model,
        )

        # =======================================================
        # BENCHMARK ADVISOR: Quality/cost-optimised recommendation
        # =======================================================
        try:
            rubric_for_bench = {
                "task_count": triage_result.complexity_rubric.get("task_count", 0.5),
                "domain_depth": triage_result.complexity_rubric.get("domain_depth", 0.5),
                "reasoning_hops": triage_result.complexity_rubric.get("reasoning_hops", 0.5),
                "output_structure": triage_result.complexity_rubric.get("output_structure", 0.5),
                "knowledge_breadth": triage_result.complexity_rubric.get("knowledge_breadth", 0.5),
                "raw_score": triage_result.complexity_raw_score,
            }

            bench_result = self.benchmark_router.recommend(
                query,
                rubric=rubric_for_bench,
                available_model_ids=[m.model_id for m in candidates],
                complexity_band=triage_result.complexity_band.value,
            )
            benchmark_rec = {
                "model_id": bench_result.recommended_model_id,
                "quality": bench_result.quality_score,
                "cost": bench_result.cost_per_1k,
                "value": bench_result.value_score,
                "tier": bench_result.tier,
                "method": bench_result.method,
            }
        except Exception as exc:
            logger.debug("benchmark_router_skipped", error=str(exc))
            benchmark_rec = None

        decision = RoutingDecision(
            selected_model=selected_model,
            fallback_models=fallback_models,
            modality_analysis=modality_analysis.model_dump(),
            triage_result=triage_result.model_dump(),
            uncertainty_score=uncertainty_score.model_dump(),
            bandit_context=bandit_context.model_dump(),
            routing_reasoning=routing_reasoning,
            estimated_cost_usd=estimated_cost,
            confidence_level=uncertainty_score.confidence_level,
            escalation_path_available=escalation_path.can_escalate,
            escalation_levels=len(escalation_path.models),
            benchmark_recommendation=benchmark_rec,
            pipeline_metadata={
                "user_tier": user_tier,
                "budget_remaining": budget_remaining,
                "ctx_token_density": ctx_token_density,
                "novelty_score": memory_result.novelty_score,
                "session_escalation_count": session_escalation_count,
                "task_type": input_signals.task_type.value,
                "instruction_count": input_signals.instruction_count,
                "multi_intent_score": input_signals.multi_intent_score,
                "reasoning_depth": input_signals.reasoning_depth,
                "attachments_count": attachments_count,
                "target_tier": target_tier,
                "routing_policy_reason": routing_policy_reason,
                "candidate_model_ids": [m.model_id for m in candidates],
                "benchmark_model_id": benchmark_rec["model_id"] if benchmark_rec else None,
            },
        )

        # =======================================================
        # LAYER 9: ASYNC TELEMETRY
        # =======================================================
        self._emit_telemetry(
            request_id=request_id,
            decision=decision,
            user_tier=user_tier,
            budget_remaining=budget_remaining,
            novelty_score=memory_result.novelty_score,
            uncertainty_score=uncertainty_score.total_uncertainty,
            confidence_level=uncertainty_score.confidence_level,
            query=query,
        )

        logger.info(
            "elite_routing_completed",
            selected_model=selected_model_id,
            confidence=uncertainty_score.confidence_level,
            estimated_cost=estimated_cost,
        )
        return decision

    # ------------------------------------------------------------------
    # Context-Aware Routing Helper (Section 4.3)
    # ------------------------------------------------------------------

    def _compute_ctx_token_density(
        self, history: Optional[list[dict]]
    ) -> Optional[float]:
        """
        Compute conversational context token density from history.

        Density = total_history_tokens / 4096 (a reasonable context window).
        Returns None if no history provided (no adjustment applied).

        Per Section 4.3: "Recent dialogue turns are aggregated, and contextual
        token density is measured. When the cumulative context exceeds predefined
        thresholds, complexity estimates are adjusted accordingly."
        """
        if not history:
            return None

        total_tokens = 0
        for turn in history:
            content = turn.get("content", "") or ""
            # Rough approximation: 4 chars ≈ 1 token
            total_tokens += len(content) // 4

        # Normalise against a 4 096-token context window
        density = min(total_tokens / 4096, 1.0)
        logger.debug("ctx_token_density", total_tokens=total_tokens, density=round(density, 4))
        return density

    # ------------------------------------------------------------------
    # Helper: create forced decision
    # ------------------------------------------------------------------

    def _create_forced_decision(self, model: ModelDefinition, query: str) -> RoutingDecision:
        """Create decision for forced model selection (still runs analysis for logging)."""
        modality_analysis = self.modality_gate.analyze(query, False, False, 0)
        input_signals = self.input_extractor.extract(query)
        triage_result = self.triage_classifier.classify(query, input_signals=input_signals)
        uncertainty_score = self.uncertainty_estimator.estimate(query)

        return RoutingDecision(
            selected_model=model,
            fallback_models=[],
            modality_analysis=modality_analysis.model_dump(),
            triage_result=triage_result.model_dump(),
            uncertainty_score=uncertainty_score.model_dump(),
            routing_reasoning="Model explicitly forced by user",
            estimated_cost_usd=0.0,
            confidence_level="N/A",
            escalation_path_available=False,
            escalation_levels=0,
        )

    # ------------------------------------------------------------------
    # Helper: create fast-path decision
    # ------------------------------------------------------------------

    def _resolve_fast_path_model_with_fallback(
        self, fast_path_decision, request_id: str
    ) -> Optional[ModelDefinition]:
        """Try the recommended model, then walk the fallback chain on failure.

        Handles the race window where Fast Path resolved a model but
        registry.get_model raises (e.g. because dynamic env-var refresh
        deactivated it between resolution and use). Instead of falling through
        to the full pipeline immediately, we try the next available chain
        member — keeps bypass latency low on transient credential issues.
        """
        candidates = [fast_path_decision.recommended_model] + [
            mid for mid in fast_path_decision.fallback_chain
            if mid != fast_path_decision.recommended_model
        ]
        for model_id in candidates:
            try:
                model = self.registry.get_model(model_id)
            except ModelNotFoundError:
                continue
            if model is None or not getattr(model, "is_active", True):
                continue
            if model_id != fast_path_decision.recommended_model:
                logger.warning(
                    "fast_path_used_chain_fallback",
                    primary=fast_path_decision.recommended_model,
                    fallback=model_id,
                    request_id=request_id,
                )
            return model
        logger.warning(
            "fast_path_chain_exhausted",
            chain=fast_path_decision.fallback_chain,
            request_id=request_id,
        )
        return None

    def _create_fast_path_decision(
        self,
        model: ModelDefinition,
        query: str,
        fast_path_result,
    ) -> RoutingDecision:
        """
        Build a RoutingDecision for a Layer 0 bypass without invoking any other
        layer. By contract, Fast Path means "we already know the cheap answer" —
        running triage / uncertainty / modality here would defeat the purpose
        and reintroduce the latency we're trying to avoid.

        The downstream telemetry path expects modality_analysis / triage_result /
        uncertainty_score dicts to exist, so we synthesize minimal neutral
        placeholders flagged as `synthesized=True` for honest observability.
        """
        category_value = fast_path_result.category.value
        detected_language = fast_path_result.detected_language or "en"
        neutral_modality = {
            "primary_modality": "text_only",
            "requires_vision": False,
            "requires_audio": False,
            "requires_code_model": False,
            "token_count": len(query) // 4,
            "language": detected_language,
            "synthesized": True,
            "synthesis_reason": "fast_path_bypass",
        }
        neutral_triage = {
            "intent": "casual" if category_value.startswith("trivial") else "qa",
            "domain": "casual" if category_value.startswith("trivial") else "general",
            "complexity_band": "trivial",
            "confidence": fast_path_result.confidence,
            "ambiguity": {
                "is_multi_intent": False, "is_vague": False, "is_underspecified": False
            },
            "task_type": "conversation" if category_value.startswith("trivial") else "qa",
            "instruction_count": 1,
            "prompt_length": len(query),
            "reasoning": f"Layer 0 fast-path: {category_value} ({detected_language})",
            "complexity_raw_score": 0.05,
            "complexity_rubric": {
                "raw_score": 0.05, "task_count": 0.05, "domain_depth": 0.0,
                "reasoning_hops": 0.0, "output_structure": 0.05, "knowledge_breadth": 0.0,
            },
            "detected_language": detected_language,
            "synthesized": True,
            "synthesis_reason": "fast_path_bypass",
        }
        neutral_uncertainty = {
            "total_uncertainty": 0.05,
            "confidence_level": "HIGH",
            "synthesized": True,
            "synthesis_reason": "fast_path_bypass",
        }

        return RoutingDecision(
            selected_model=model,
            fallback_models=[],
            modality_analysis=neutral_modality,
            triage_result=neutral_triage,
            uncertainty_score=neutral_uncertainty,
            routing_reasoning=f"Layer 0 fast-path bypass: {fast_path_result.reasoning}",
            estimated_cost_usd=self._estimate_cost(model, "trivial"),
            confidence_level="HIGH",
            fast_path_triggered=True,
            fast_path_category=category_value,
            escalation_path_available=False,
            escalation_levels=0,
            pipeline_metadata={
                "fast_path_triggered": True,
                "fast_path_category": category_value,
                "fast_path_pattern": fast_path_result.matched_pattern,
                "fast_path_language": fast_path_result.detected_language,
                "fast_path_chain": fast_path_result.fallback_chain,
                "bypass_reason": fast_path_result.reasoning,
                "layers_skipped": [
                    "modality_gate", "input_signals", "semantic_memory",
                    "fast_triage", "uncertainty_estimator", "bandit_router",
                ],
            },
        )

    # ------------------------------------------------------------------
    # Helper: create cached decision
    # ------------------------------------------------------------------

    def _create_cached_decision(
        self,
        model: ModelDefinition,
        query: str,
        memory_result,
        modality_analysis=None,
    ) -> RoutingDecision:
        """Build a RoutingDecision for a Layer 2 cache hit WITHOUT invoking
        triage / uncertainty / bandit.

        Previously this method called `triage_classifier.classify()` (which
        makes an LLM call) and `uncertainty_estimator.estimate()` on every
        cache hit — defeating the whole point of having a cache. The
        `layers_skipped` field even lied that they were skipped.

        Now: synthesize neutral metadata from the cached MemoryEntry's
        stored intent / domain / complexity_band, exactly the same pattern
        Layer 0 uses for fast-path bypasses.
        """
        # Best-effort modality (cheap — deterministic regex, no LLM)
        if modality_analysis is None:
            modality_analysis = self.modality_gate.analyze(query, False, False, 0)

        # Pull cached classification fields straight from the MemoryEntry.
        # If they're absent (legacy entries pre-refactor), fall back to neutral.
        cached_intent = memory_result.cached_intent or "qa"
        cached_domain = memory_result.cached_domain or "general"
        cached_complexity = memory_result.cached_complexity_band or "moderate"

        neutral_triage = {
            "intent": cached_intent,
            "domain": cached_domain,
            "complexity_band": cached_complexity,
            "confidence": memory_result.similarity,  # use cache similarity as proxy
            "ambiguity": {"is_multi_intent": False, "is_vague": False, "is_underspecified": False},
            "task_type": "qa",
            "instruction_count": 1,
            "prompt_length": len(query),
            "reasoning": f"Layer 2 cache hit — reusing prior classification ({memory_result.reasoning})",
            "complexity_raw_score": 0.5,
            "complexity_rubric": {
                "raw_score": 0.5, "task_count": 0.5, "domain_depth": 0.5,
                "reasoning_hops": 0.5, "output_structure": 0.5, "knowledge_breadth": 0.5,
            },
            "synthesized": True,
            "synthesis_reason": "semantic_memory_cache_hit",
        }
        neutral_uncertainty = {
            "total_uncertainty": max(0.0, 1.0 - memory_result.similarity),
            "confidence_level": "HIGH",
            "synthesized": True,
            "synthesis_reason": "semantic_memory_cache_hit",
        }

        return RoutingDecision(
            selected_model=model,
            fallback_models=[],
            modality_analysis=modality_analysis.model_dump(),
            triage_result=neutral_triage,
            uncertainty_score=neutral_uncertainty,
            routing_reasoning=f"Layer 2 cache hit — {memory_result.reasoning}",
            estimated_cost_usd=self._estimate_cost(model, cached_complexity),
            confidence_level="HIGH",
            escalation_path_available=False,
            escalation_levels=0,
            pipeline_metadata={
                "semantic_memory_hit": True,
                "similarity_score": memory_result.similarity,
                "novelty_score": memory_result.novelty_score,
                "detector_used": memory_result.detector_used,
                "cached_intent": memory_result.cached_intent,
                "cached_domain": memory_result.cached_domain,
                "cached_complexity_band": memory_result.cached_complexity_band,
                "embedding_id": memory_result.embedding_id,
                "layers_skipped": [
                    "input_signals", "fast_triage", "uncertainty_estimator",
                    "bandit_router",
                ],
            },
        )

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def _determine_model_type(self, modality_analysis) -> ModelType:
        if modality_analysis.requires_vision:
            return ModelType.MULTIMODAL
        if modality_analysis.requires_audio:
            return ModelType.AUDIO
        return ModelType.TEXT

    def _get_candidate_models(
        self,
        model_type: ModelType,
        modality_analysis,
        triage_result,
        uncertainty_score: float,
        input_signals,
        target_tier: str,
    ) -> list[ModelDefinition]:
        candidates = self.registry.list_models(model_type=model_type, only_active=True)
        candidates = self._filter_candidates_for_capabilities(candidates, modality_analysis, input_signals)
        candidates = self._filter_candidates_for_tier(candidates, target_tier)
        candidates = self._prefer_free_api_candidates(candidates)
        candidates.sort(
            key=lambda m: self._candidate_sort_key(m, triage_result, uncertainty_score)
        )
        return candidates

    def _determine_target_tier(
        self,
        triage_result,
        uncertainty_score: float,
        uncertainty_details,
        input_signals,
        modality_analysis,
        user_tier: str,
        budget_remaining: float,
    ) -> tuple[str, str]:
        """
        Determine target model tier using classifier as primary signal.

        Priority order:
          1. Vision / domain safety / cross-domain → premium (hard rules)
          2. Classifier complexity_band + raw_score → primary routing
          3. Low confidence / boundary proximity → conservative escalation
          4. input_signals → tie-breaker for moderate queries only
        """
        domain = triage_result.domain.value
        complexity = triage_result.complexity_band.value
        raw_score = getattr(triage_result, "complexity_raw_score", 0.5)
        complexity_conf = triage_result.confidence
        thresholds = routing_config.complexity_thresholds

        # ══════════════════════════════════════════════════════════
        # HARD RULES — always premium (unchanged)
        # ══════════════════════════════════════════════════════════
        if modality_analysis.requires_vision:
            return "premium", "vision requests use safest multimodal tier"
        if domain in {"medical", "legal"}:
            return "premium", "high-risk domain always gets premium"
        if uncertainty_details.cross_domain_score >= 0.35:
            return "premium", "cross-domain query gets premium"
        if uncertainty_score >= 0.7:
            return "premium", "high total uncertainty gets premium"

        # ══════════════════════════════════════════════════════════
        # CLASSIFIER AS PRIMARY SIGNAL
        # ══════════════════════════════════════════════════════════
        if complexity == "expert":
            return "premium", "expert complexity → strongest tier"
        if complexity == "complex":
            return "premium", "complex query → premium tier"
        if complexity == "trivial":
            return "cheap", "trivial query → cost-efficient routing"
        if complexity == "simple":
            return "cheap", "simple query → cost-efficient routing"

        # ══════════════════════════════════════════════════════════
        # MODERATE — apply conservative escalation + tie-breakers
        # ══════════════════════════════════════════════════════════

        # Low confidence escalation: if classifier isn't confident, go higher
        if complexity_conf < thresholds.min_confidence_for_trust:
            return "mid", f"moderate query with low confidence ({complexity_conf:.2f}) → mid tier"

        # Boundary proximity escalation: near moderate-complex threshold
        dist_to_complex = abs(raw_score - thresholds.moderate_complex)
        if dist_to_complex < thresholds.boundary_margin:
            return "mid", f"raw_score {raw_score:.2f} near complex boundary → mid tier"

        # ── Tie-breakers (input_signals) — only for confident moderate ──
        if input_signals.numerical_reasoning_flag and domain == "science":
            return "mid", "science numerical reasoning (tie-breaker) → mid"
        if input_signals.code_generation_flag and input_signals.has_constraints:
            return "mid", "constrained code generation (tie-breaker) → mid"
        if input_signals.reasoning_depth >= 0.55:
            return "mid", "deep reasoning (tie-breaker) → mid"

        # Domain-sensitive moderate: tech/business/education
        if domain in {"tech", "business", "education"}:
            return "mid", "domain-sensitive moderate → mid"

        # Premium users get safer routing for moderate
        if user_tier == "premium":
            return "mid", "premium user moderate → mid"

        return "cheap", "confident moderate query → cost-efficient routing"

    def _filter_candidates_for_capabilities(
        self,
        candidates: list[ModelDefinition],
        modality_analysis,
        input_signals,
    ) -> list[ModelDefinition]:
        filtered = candidates
        if modality_analysis.requires_code_model or input_signals.code_generation_flag:
            coding = [m for m in filtered if m.supports_capability(ModelCapability.CODING)]
            if coding:
                filtered = coding
        if input_signals.reasoning_depth >= 0.45 or input_signals.numerical_reasoning_flag:
            reasoning = [m for m in filtered if m.supports_capability(ModelCapability.REASONING)]
            if reasoning:
                filtered = reasoning
        return filtered

    def _prefer_free_api_candidates(
        self,
        candidates: list[ModelDefinition],
    ) -> list[ModelDefinition]:
        """Prefer configured free API providers and keep Ollama for gateway fallback."""
        if not settings.PREFER_FREE_API_PROVIDERS or not candidates:
            return candidates

        free_api_providers = {
            ModelProvider.GOOGLE,
            ModelProvider.GROQ,
            ModelProvider.OPENROUTER,
            ModelProvider.HUGGINGFACE,
            ModelProvider.COHERE,
        }
        preferred = [m for m in candidates if m.provider in free_api_providers]
        if preferred:
            return preferred
        return candidates

    def _filter_candidates_for_tier(
        self,
        candidates: list[ModelDefinition],
        target_tier: str,
    ) -> list[ModelDefinition]:
        if not candidates:
            return candidates

        explicit_tier_matches = [
            m for m in candidates
            if m.routing_tier and m.routing_tier.value == target_tier
        ]
        if explicit_tier_matches:
            return explicit_tier_matches

        def is_local(model: ModelDefinition) -> bool:
            return model.provider.value == "local"

        def get_model_size_b(model: ModelDefinition) -> float:
            import re
            match = re.search(r'(\d+(?:\.\d+)?)[bB]', model.model_name)
            if match:
                return float(match.group(1))
            return 0.0

        def is_premium(m: ModelDefinition) -> bool:
            if m.pricing.output_cost_per_1k_tokens >= 0.015:
                return True
            if is_local(m) and get_model_size_b(m) >= 30.0:
                return True
            return False

        def is_mid(m: ModelDefinition) -> bool:
            if 0.0 < m.pricing.output_cost_per_1k_tokens < 0.015:
                return True
            if is_local(m):
                size = get_model_size_b(m)
                if 10.0 <= size < 30.0:
                    return True
            return False

        def is_cheap(m: ModelDefinition) -> bool:
            if is_local(m) and get_model_size_b(m) < 10.0:
                return True
            if m.pricing.output_cost_per_1k_tokens < 0.001:
                return True
            return False

        if target_tier == "cheap":
            filtered = [m for m in candidates if is_cheap(m)]
            return filtered or candidates
        if target_tier == "mid":
            filtered = [m for m in candidates if is_mid(m)]
            return filtered or candidates
        if target_tier == "premium":
            filtered = [m for m in candidates if is_premium(m)]
            return filtered or candidates
            
        return candidates

    def _prioritize_safer_models(
        self,
        candidates: list[ModelDefinition],
        triage_result,
        uncertainty_score: float,
    ) -> list[ModelDefinition]:
        if not candidates:
            return candidates

        domain = triage_result.domain.value
        if domain in {"medical", "legal"} or uncertainty_score >= 0.7:
            candidates = sorted(
                candidates,
                key=lambda m: (
                    not m.supports_capability(ModelCapability.REASONING),
                    m.pricing.input_cost_per_1k_tokens + m.pricing.output_cost_per_1k_tokens,
                ),
            )
        return candidates

    def _candidate_sort_key(
        self,
        model: ModelDefinition,
        triage_result,
        uncertainty_score: float,
    ) -> tuple[float, float]:
        domain = triage_result.domain.value
        safety_bias = 0.0
        if domain in {"medical", "legal"} or uncertainty_score >= 0.7:
            safety_bias = 0.0 if model.supports_capability(ModelCapability.REASONING) else 1.0
        return (
            safety_bias,
            model.pricing.input_cost_per_1k_tokens + model.pricing.output_cost_per_1k_tokens,
        )

    def _estimate_cost(self, model: ModelDefinition, complexity: str) -> float:
        token_estimates = {
            "trivial":  (20,  30),
            "simple":   (50,  100),
            "moderate": (100, 300),
            "complex":  (200, 500),
            "expert":   (300, 800),
        }
        input_tokens, output_tokens = token_estimates.get(complexity, (100, 200))
        return model.calculate_cost(input_tokens, output_tokens)

    def _generate_elite_reasoning(
        self,
        modality_analysis,
        triage_result,
        uncertainty_score,
        selected_model: ModelDefinition,
    ) -> str:
        parts = [
            f"Modality: {modality_analysis.primary_modality}",
            f"Intent: {triage_result.intent.value} | Domain: {triage_result.domain.value}",
            f"Complexity: {triage_result.complexity_band.value} | Uncertainty: {uncertainty_score.confidence_level}",
            f"Selected: {selected_model.display_name} "
            f"(${selected_model.pricing.input_cost_per_1k_tokens + selected_model.pricing.output_cost_per_1k_tokens:.4f}/1K tokens)",
        ]
        if uncertainty_score.total_uncertainty > 0.6:
            parts.append("HIGH uncertainty → safer model chosen")
        elif uncertainty_score.total_uncertainty < 0.3:
            parts.append("HIGH confidence → cost-optimized model")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Layer 9: Telemetry emission
    # ------------------------------------------------------------------

    def _emit_telemetry(
        self,
        request_id: str,
        decision: RoutingDecision,
        user_tier: str = "standard",
        budget_remaining: float = 1.0,
        novelty_score: float = 0.0,
        uncertainty_score: float = 0.0,
        confidence_level: str = "",
        quality_score: float = 0.0,
        escalated: bool = False,
        escalation_count: int = 0,
        latency_ms: float = 0.0,
        query: str = "",
    ) -> None:
        """Fire-and-forget telemetry log (Layer 9)."""
        try:
            triage = decision.triage_result or {}
            telemetry = RoutingTelemetry(
                request_id=request_id,
                selected_model_id=decision.selected_model.model_id,
                final_model_id=decision.selected_model.model_id,
                domain=triage.get("domain", ""),
                intent=triage.get("intent", ""),
                complexity_band=triage.get("complexity_band", ""),
                quality_score=quality_score,
                escalated=escalated,
                escalation_count=escalation_count,
                cost_usd=decision.estimated_cost_usd,
                latency_ms=latency_ms,
                uncertainty_score=uncertainty_score,
                confidence_level=confidence_level or decision.confidence_level,
                novelty_score=novelty_score,
                user_tier=user_tier,
                budget_remaining=budget_remaining,
                query=query,
                primary_modality=decision.modality_analysis.get("primary_modality", ""),
                language=decision.modality_analysis.get("language", "en"),
                token_count=decision.modality_analysis.get("token_count", 0),
                task_type=decision.pipeline_metadata.get("task_type", ""),
                reasoning_depth=decision.pipeline_metadata.get("reasoning_depth", 0.0),
                multi_intent_score=decision.pipeline_metadata.get("multi_intent_score", 0.0),
                instruction_count=decision.pipeline_metadata.get("instruction_count", 0),
                classification_entropy=decision.uncertainty_score.get("classification_entropy", 0.0),
                instruction_conflict_score=decision.uncertainty_score.get("instruction_conflict_score", 0.0),
                cross_domain_score=decision.uncertainty_score.get("cross_domain_score", 0.0),
            )
            TelemetryLogger.log_async(telemetry)
        except Exception as e:
            logger.error("telemetry_emission_failed", error=str(e))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Get the global model router instance."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
