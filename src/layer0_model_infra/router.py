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
  Layer 3:  kNN Router       → benchmark-driven model selection. Replaced the
            legacy Fast Triage / Uncertainty / Bandit chain (now archived under
            routing/legacy/). Self-sufficient: encoder/Qdrant failures degrade to
            its own prior-based fallback. The LAYER3_ENABLED kill switch drops
            routing to a minimal safe-default model.
  Layer 6:  Test-Time Compute→ Best-of-N for moderate-uncertainty queries
  Layer 7:  Quality Evaluation → Output validation (silent failure detection)
  Layer 8:  Auto-Escalation  → Retry with better model on quality failure
  Layer 9:  Telemetry        → Async continuous-learning feedback loop
"""

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.models import (
    ModelDefinition,
    ModelProvider,
    ModelType,
)
from src.layer0_model_infra.registry import get_registry
from src.layer0_model_infra.routing.escalation_engine import get_escalation_engine
from src.layer0_model_infra.routing.fast_path import get_fast_path
from src.layer0_model_infra.routing.input_signals import get_input_extractor
from src.layer0_model_infra.routing.modality_gate import get_modality_gate
from src.layer0_model_infra.routing.quality_evaluator import get_quality_evaluator
from src.layer0_model_infra.routing.semantic_memory import get_semantic_memory
from src.layer0_model_infra.routing.telemetry import RoutingTelemetry, TelemetryLogger
from src.shared.config import get_settings
from src.shared.errors import ModelNotFoundError
from src.shared.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


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

    # Raw Layer 3 decision (when the kNN router served this query), stashed so
    # the orchestrator can feed it to calibration_store.update() after Layer 7.
    # Excluded from serialization — it's an internal handle for the learning
    # loop, not part of the telemetry/wire contract.
    layer3_raw_decision: Optional[Any] = Field(default=None, exclude=True)


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
        self.quality_evaluator = get_quality_evaluator()      # Layer 7
        self.escalation_engine = get_escalation_engine()      # Layer 8

        # ── Layer 3 (benchmark-driven kNN router) — the production router ──
        # The legacy migration scaffolding (canary fraction + shadow mode) was
        # retired once the kNN router fully replaced the legacy L3-L5 pipeline:
        # with no second router to split against or shadow-compare, those knobs
        # were meaningless. LAYER3_ENABLED remains as a single kill switch / demo
        # toggle — off degrades routing to a minimal safe-default model; on (the
        # default) the kNN router serves every non-trivial query. Its models are
        # registered into the gateway registry up front so every execution path
        # (fast-path, forced, kNN) can resolve them by id.
        self._layer3_enabled = bool(settings.LAYER3_ENABLED)
        self._layer3_models_registered = False
        self._knn_router = None
        if self._layer3_enabled:
            try:
                from src.layer0_model_infra.routing.knn_router import get_knn_router
                self._knn_router = get_knn_router()
                self._ensure_layer3_models_registered()
            except Exception as exc:
                logger.error("layer3_init_failed_disabling", reason=str(exc))
                self._layer3_enabled = False
                self._knn_router = None

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
        # LAYER 3: benchmark-driven kNN router — the production router.
        # It is self-sufficient: encoder/Qdrant failures degrade to its own
        # prior-based Stage-D fallback internally, so it returns a valid decision
        # in every normal case. _route_via_layer3 only returns None if the router
        # raised unexpectedly; that case and the LAYER3_ENABLED kill switch both
        # fall through to the minimal safe-default below.
        # =======================================================
        if self._layer3_enabled and self._knn_router is not None:
            l3_decision = self._route_via_layer3(
                query, modality_analysis, input_signals, memory_result, request_id
            )
            if l3_decision is not None:
                self._emit_telemetry(
                    request_id=request_id, decision=l3_decision, user_tier=user_tier,
                    budget_remaining=budget_remaining,
                    novelty_score=memory_result.novelty_score, query=query,
                )
                return l3_decision

        # =======================================================
        # SAFE DEFAULT: kNN disabled (kill switch) or it crashed unexpectedly.
        # Route to a strong free default instead of the retired legacy pipeline.
        # =======================================================
        decision = self._create_safe_default_decision(
            query, modality_analysis, input_signals, memory_result
        )
        self._emit_telemetry(
            request_id=request_id, decision=decision, user_tier=user_tier,
            budget_remaining=budget_remaining,
            novelty_score=memory_result.novelty_score, query=query,
        )
        return decision

    # ------------------------------------------------------------------
    # Helper: create forced decision
    # ------------------------------------------------------------------

    def _create_forced_decision(self, model: ModelDefinition, query: str) -> RoutingDecision:
        """Create decision for forced model selection (still runs analysis for logging)."""
        modality_analysis = self.modality_gate.analyze(query, False, False, 0)
        neutral_triage = {
            "intent": "qa", "domain": "general", "complexity_band": "moderate",
            "confidence": 1.0,
            "ambiguity": {"is_multi_intent": False, "is_vague": False, "is_underspecified": False},
            "task_type": "qa", "instruction_count": 1, "prompt_length": len(query),
            "reasoning": "Model explicitly forced by user",
            "complexity_raw_score": 0.5,
            "complexity_rubric": {
                "raw_score": 0.5, "task_count": 0.5, "domain_depth": 0.5,
                "reasoning_hops": 0.5, "output_structure": 0.5, "knowledge_breadth": 0.5,
            },
            "synthesized": True, "synthesis_reason": "forced_model",
        }
        neutral_uncertainty = {
            "total_uncertainty": 0.0, "confidence_level": "N/A",
            "synthesized": True, "synthesis_reason": "forced_model",
        }

        return RoutingDecision(
            selected_model=model,
            fallback_models=[],
            modality_analysis=modality_analysis.model_dump(),
            triage_result=neutral_triage,
            uncertainty_score=neutral_uncertainty,
            routing_reasoning="Model explicitly forced by user",
            estimated_cost_usd=0.0,
            confidence_level="N/A",
            escalation_path_available=False,
            escalation_levels=0,
        )

    # ------------------------------------------------------------------
    # Helper: create safe-default decision (Layer 3 kill switch / crash net)
    # ------------------------------------------------------------------

    def _create_safe_default_decision(
        self, query, modality_analysis, input_signals, memory_result
    ) -> RoutingDecision:
        """Minimal last-resort decision, used only when the kNN router is off via
        the LAYER3_ENABLED kill switch or crashed unexpectedly. Routes to the
        strongest active free text model (a reliable default) and synthesizes the
        neutral triage / uncertainty metadata that telemetry + the orchestrator
        expect. The retired legacy triage/uncertainty/bandit pipeline previously
        filled this role; the kNN router's own prior-based fallback already covers
        the common infra-failure case, so this only fires in genuinely degraded
        conditions.
        """
        text_models = self.registry.list_models(model_type=ModelType.TEXT, only_active=True)
        if not text_models:
            raise ModelNotFoundError("No active text model available for safe-default routing")

        import re
        free_providers = {
            ModelProvider.GOOGLE, ModelProvider.GROQ, ModelProvider.OPENROUTER,
            ModelProvider.HUGGINGFACE, ModelProvider.COHERE,
        }

        def _size_b(m: ModelDefinition) -> float:
            match = re.search(r'(\d+(?:\.\d+)?)\s*[bB]', m.model_name or "")
            return float(match.group(1)) if match else 0.0

        # Prefer a free-API provider, then the largest (strongest) model.
        preferred = [m for m in text_models if m.provider in free_providers] or text_models
        model = max(preferred, key=_size_b)

        neutral_triage = {
            "intent": "qa", "domain": "general", "complexity_band": "moderate",
            "confidence": 0.5,
            "ambiguity": {"is_multi_intent": False, "is_vague": False, "is_underspecified": False},
            "task_type": "qa", "instruction_count": 1, "prompt_length": len(query),
            "reasoning": "Safe-default routing (Layer 3 kNN router disabled or unavailable)",
            "complexity_raw_score": 0.5,
            "complexity_rubric": {
                "raw_score": 0.5, "task_count": 0.5, "domain_depth": 0.5,
                "reasoning_hops": 0.5, "output_structure": 0.5, "knowledge_breadth": 0.5,
            },
            "synthesized": True, "synthesis_reason": "safe_default",
        }
        neutral_uncertainty = {
            "total_uncertainty": 0.5, "confidence_level": "MEDIUM",
            "cross_domain_score": 0.0, "classification_entropy": 0.0,
            "instruction_conflict_score": 0.0,
            "synthesized": True, "synthesis_reason": "safe_default",
        }

        return RoutingDecision(
            selected_model=model,
            fallback_models=[],
            modality_analysis=modality_analysis.model_dump(),
            triage_result=neutral_triage,
            uncertainty_score=neutral_uncertainty,
            routing_reasoning=(
                "Safe-default routing: the Layer 3 kNN router is disabled "
                "(LAYER3_ENABLED=false) or unavailable; routed to the strongest "
                f"active free model ({model.model_id})."
            ),
            estimated_cost_usd=self._estimate_cost(model, "moderate"),
            confidence_level="MEDIUM",
            escalation_path_available=False,
            escalation_levels=0,
            pipeline_metadata={
                "router": "safe_default",
                "reason": "layer3_disabled_or_unavailable",
                "novelty_score": getattr(memory_result, "novelty_score", 0.0),
                "task_type": getattr(getattr(input_signals, "task_type", None), "value", "qa"),
                "layers_skipped": [
                    "fast_triage", "uncertainty_estimator", "bandit_router",
                ],
            },
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
            l3 = getattr(decision, "layer3_raw_decision", None)
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
                routing_source=(getattr(getattr(l3, "source", None), "value", "") if l3 is not None else ""),
                predicted_quality=(l3.predicted_quality if (l3 is not None and l3.predicted_quality is not None) else 0.0),
                prediction_confidence_score=((getattr(l3, "prediction_confidence_score", None) or 0.0) if l3 is not None else 0.0),
                uncertainty_escalated=(bool(getattr(l3, "uncertainty_escalated", False)) if l3 is not None else False),
            )
            TelemetryLogger.log_async(telemetry)
        except Exception as e:
            logger.error("telemetry_emission_failed", error=str(e))

    # ------------------------------------------------------------------
    # NEW Layer 3 (kNN router) integration
    # ------------------------------------------------------------------

    _DIFFICULTY_TO_BAND = {"trivial": "trivial", "normal": "moderate", "hard": "complex"}

    def _ensure_layer3_models_registered(self) -> None:
        """Register Layer 3 models into the gateway registry so every execution
        path can resolve them by id. Idempotent — called once at router init
        when Layer 3 is enabled."""
        if self._layer3_models_registered:
            return
        from src.layer0_model_infra.routing.layer3_adapter import register_layer3_models
        from src.layer0_model_infra.routing.registry_loader import get_layer3_registry
        register_layer3_models(self.registry, get_layer3_registry())
        self._layer3_models_registered = True

    def _route_via_layer3(self, query, modality_analysis, input_signals, memory_result, request_id):
        """Run the kNN router and adapt its decision to the RoutingDecision schema.
        Returns None on any failure so route() falls back to the safe-default."""
        try:
            self._ensure_layer3_models_registered()
            l3 = self._knn_router.route(
                query, layer1_analysis=modality_analysis, request_id=request_id
            )
            model_def = self.registry.get_model(l3.selected_model)
            decision = self._adapt_layer3_decision(
                l3, model_def, modality_analysis, input_signals, memory_result
            )
            logger.info(
                "layer3_routing_completed",
                selected_model=l3.selected_model, source=l3.source.value,
                predicted_quality=l3.predicted_quality,
                latency_ms=round(l3.latency_ms, 1), request_id=request_id,
            )
            return decision
        except Exception as exc:
            logger.error("layer3_route_failed_fallback_legacy", reason=str(exc), request_id=request_id)
            return None

    def _adapt_layer3_decision(self, l3, model_def, modality_analysis, input_signals, memory_result):
        """Convert a Layer 3 RoutingDecision into the legacy RoutingDecision that
        Layer 7/8/9 + the orchestrator consume. The triage/uncertainty dicts are
        synthesized (the new design has no such layers) and flagged as such."""
        feats = l3.features
        difficulty = getattr(feats.difficulty_signal, "value", str(feats.difficulty_signal))
        complexity_band = self._DIFFICULTY_TO_BAND.get(difficulty, "moderate")
        domain = feats.high_risk_domain.value if feats.high_risk_domain else "general"
        predicted = l3.predicted_quality if l3.predicted_quality is not None else 0.5
        confidence_level = "HIGH" if l3.prediction_confidence == "high" else "MEDIUM"

        triage_result = {
            "intent": "qa", "domain": domain, "complexity_band": complexity_band,
            "confidence": predicted,
            "ambiguity": {"is_multi_intent": False, "is_vague": False, "is_underspecified": False},
            "task_type": "qa", "instruction_count": 1, "prompt_length": feats.char_count,
            "reasoning": f"Layer 3 kNN router ({l3.source.value})",
            "complexity_raw_score": round(1.0 - predicted, 4),
            "complexity_rubric": {
                "raw_score": round(1.0 - predicted, 4), "task_count": 0.5, "domain_depth": 0.5,
                "reasoning_hops": 0.5, "output_structure": 0.5, "knowledge_breadth": 0.5,
            },
            "synthesized": True, "synthesis_reason": "layer3_knn_router",
        }
        uncertainty_score = {
            "total_uncertainty": round(1.0 - predicted, 4),
            "confidence_level": confidence_level,
            "cross_domain_score": 0.0, "classification_entropy": 0.0,
            "instruction_conflict_score": 0.0,
            "synthesized": True, "synthesis_reason": "layer3_knn_router",
        }

        fallback_models = []
        for mid in l3.qualifying_models[1:3]:
            try:
                fallback_models.append(self.registry.get_model(mid))
            except Exception:
                pass

        return RoutingDecision(
            selected_model=model_def,
            layer3_raw_decision=l3,
            fallback_models=fallback_models,
            modality_analysis=modality_analysis.model_dump(),
            triage_result=triage_result,
            uncertainty_score=uncertainty_score,
            routing_reasoning=(
                f"Layer 3 kNN router: source={l3.source.value}, model={l3.selected_model}, "
                f"predicted_quality={l3.predicted_quality}, effective_floor={l3.effective_floor}"
            ),
            estimated_cost_usd=l3.estimated_cost_usd,
            confidence_level=confidence_level,
            escalation_path_available=len(l3.qualifying_models) > 1,
            escalation_levels=max(0, len(l3.qualifying_models) - 1),
            pipeline_metadata={
                "router": "layer3_knn",
                "layer3_source": l3.source.value,
                "layer3_predicted_quality": l3.predicted_quality,
                "layer3_prediction_confidence": l3.prediction_confidence,
                "layer3_feature_cell": l3.feature_cell,
                "layer3_quality_floor_base": l3.quality_floor_base,
                "layer3_effective_floor": l3.effective_floor,
                "layer3_fallback_reason": l3.fallback_reason,
                "layer3_qualifying_models": l3.qualifying_models,
                "layer3_neighbors_used": [list(n) for n in l3.neighbors_used[:5]],
                "layer3_calibration_multiplier": l3.calibration_multiplier_applied,
                "layer3_latency_ms": round(l3.latency_ms, 2),
                "layer3_request_id": l3.request_id,
                "novelty_score": getattr(memory_result, "novelty_score", 0.0),
                "task_type": getattr(getattr(input_signals, "task_type", None), "value", "qa"),
            },
        )


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
