"""
📁 File: src/layer2_orchestrator/execution_loop.py
Layer: Layer 2 (Orchestrator) -> Driving Layer 0 (Model Infra)
Purpose: The "Body" that executes the "Brain's" plan.
Depends on: Layer 0 components (Router, Gateway, Checkers)

This component implements the ELITE EXECUTION LOOP:
1. Call Router (Plan)
2. Fast Path Check (Short-circuit)
3. Execution Loop (Try -> Check -> Escalate)
4. Feedback Loop (Update Memory & Layer 3 calibration)
"""

import time
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field

from src.layer0_model_infra.gateway import get_gateway, LLMRequest
from src.layer0_model_infra.router import get_router, RoutingDecision
from src.layer0_model_infra.routing.escalation_engine import get_escalation_engine
from src.layer0_model_infra.routing.semantic_memory import get_semantic_memory
from src.layer0_model_infra.routing.quality_evaluator import get_quality_evaluator
from src.shared.logger import get_logger
from src.shared.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

class ExecutionResult(BaseModel):
    """Result of the execution loop."""
    
    content: str
    model_used: str
    total_cost_usd: float
    total_latency_ms: float
    escalation_count: int
    quality_passed: bool
    quality_score: float
    quality_reasoning: str
    routing_decision: RoutingDecision
    execution_metadata: dict = Field(default_factory=dict)


class EliteExecutionOrchestrator:
    """
    Orchestrates the execution of a request through the Elite 9-Layer Pipeline.
    
    Handles:
    - Routing (Layer 0-3 kNN router)
    - Execution (Gateway)
    - Quality Check (Layer 7)
    - Auto-Escalation (Layer 8)
    - Continuous Learning (Layer 9)
    """
    
    def __init__(self):
        self.router = get_router()
        self.gateway = get_gateway()
        self.memory = get_semantic_memory()
        self.quality_evaluator = get_quality_evaluator()
        
    async def execute(
        self,
        query: str,
        # Context args
        user_id: str = "anonymous",
        user_tier: str = "standard",
        session_id: str = "default_session",
        budget_remaining: float = 1.0,
        has_images: bool = False,
        has_audio: bool = False,
        image_count: int = 0,
        has_video: bool = False,
        file_types: Optional[list[str]] = None,
        attachment_sizes_mb: Optional[list[float]] = None,
        # Testing/Override args
        force_model_id: Optional[str] = None,
        routing_decision: Optional[RoutingDecision] = None,
    ) -> ExecutionResult:
        """
        Execute a query with full Elite pipeline features.
        """
        start_time = time.time()
        logger.info("execution_started", user=user_id, query_len=len(query))
        
        # ========================================================
        # OPERATIONAL GUARDRAILS & LATENCY BUDGET (NEW)
        # ========================================================
        from src.layer2_orchestrator.latency_budget import create_latency_budget, LatencyTracker
        from src.layer2_orchestrator.guardrails import create_request_guardrails, get_session_guardrails
        
        # Create latency budget based on user tier
        latency_budget = create_latency_budget(user_tier)
        
        # Create request guardrails (will determine domain after triage)
        guardrails = create_request_guardrails(user_tier, domain="general")
        
        # Get session-level guardrails
        session_guardrails = get_session_guardrails()
        should_cooldown = session_guardrails.should_cooldown(session_id)
        
        # 1. PLAN: Get Routing Decision
        # ----------------------------------------------------
        with LatencyTracker(latency_budget, "routing"):
            # ESCALATION COOLDOWN: Use session-level tracking
            session_escalation_count_arg = session_guardrails.get_escalation_count(session_id)
            
            # If cooldown mode, increase starting complexity
            if should_cooldown:
                logger.info("session_cooldown_active", 
                           session_id=session_id,
                           escalation_count=session_escalation_count_arg)
            
            if routing_decision is not None:
                decision = routing_decision
                # The caller already routed (decision passed) but wants a specific
                # model executed (e.g. the demo's free backing model, run while
                # simulating a commercial tier). Swap the execution target on the
                # existing decision instead of routing a second time. We clear
                # layer3_raw_decision so Layer 8 escalates from the model actually
                # run and the kNN calibration loop is not fed an outcome under the
                # analyzed (non-executed) decision.
                if force_model_id and decision.selected_model.model_id != force_model_id:
                    decision = decision.model_copy(update={
                        "selected_model": self.router.registry.get_model(force_model_id),
                        "layer3_raw_decision": None,
                    })
            else:
                decision = self.router.route(
                    query=query,
                    has_images=has_images,
                    has_audio=has_audio,
                    image_count=image_count,
                    has_video=has_video,
                    file_types=file_types,
                    attachment_sizes_mb=attachment_sizes_mb,
                    force_model_id=force_model_id,
                    user_tier=user_tier,
                    budget_remaining=budget_remaining,
                    # ESCALATION COOLDOWN: Pass real session history
                    session_escalation_count=session_escalation_count_arg,
                    session_complexity_avg=0.5
                )
            
            # Update guardrails with domain info
            domain = decision.triage_result.get("domain", "general")
            guardrails = create_request_guardrails(user_tier, domain)
        
        # 2. FAST PATH: Short-circuit if possible
        # ----------------------------------------------------
        if decision.pipeline_metadata and decision.pipeline_metadata.get("fast_path_triggered"):
             # Execute fast path model immediately
             return await self._execute_simple(decision, query, start_time)
             
        if decision.pipeline_metadata and decision.pipeline_metadata.get("semantic_memory_hit"):
             # Execute cached model immediately
             return await self._execute_simple(decision, query, start_time)

        # ========================================================
        # LAYER 6: TEST-TIME COMPUTE SCALING (NEW)
        # ========================================================
        from src.layer0_model_infra.routing.test_time_compute import get_ttc_engine
        
        ttc_engine = get_ttc_engine()
        ttc_decision = ttc_engine.should_use_ttc(
            uncertainty_score=decision.uncertainty_score.get("total_uncertainty", 0.5),
            complexity_band=decision.triage_result.get("complexity_band", "moderate"),
            user_tier=user_tier,
            domain=decision.triage_result.get("domain", "general"),
        )
        
        # Check guardrails before using TTC
        if ttc_decision.should_use and not guardrails.can_use_ttc(ttc_decision.num_samples):
            logger.warning("ttc_blocked_by_guardrails", 
                          requested=ttc_decision.num_samples,
                          limit=guardrails.max_ttc_samples)
            ttc_decision.should_use = False
        
        if ttc_decision.should_use:
            logger.info(
                "test_time_compute_triggered",
                n=ttc_decision.num_samples,
                reasoning=ttc_decision.reasoning
            )
            
            # Record TTC usage in guardrails
            guardrails.record_ttc_samples(ttc_decision.num_samples)
            
            # Use strategy selected by the TTC policy.
            with LatencyTracker(latency_budget, "test_time_compute"):
                ttc_result = await ttc_engine.execute(
                    request=LLMRequest(
                        model_id=decision.selected_model.model_id,
                        messages=[{"role": "user", "content": query}],
                        temperature=0.7,
                    ),
                    decision=ttc_decision,
                    query=query
                )
            
            # Skip main execution loop, return TTC result
            total_latency = (time.time() - start_time) * 1000
            
            # Record in memory
            if ttc_result.best_quality > 0.7:
                self.memory.record(
                    query=query,
                    model_id=decision.selected_model.model_id,
                    quality_score=ttc_result.best_quality,
                    escalated=False,
                    intent=decision.triage_result.get("intent", ""),
                    domain=decision.triage_result.get("domain", ""),
                )
            
            return ExecutionResult(
                content=ttc_result.best_response,
                model_used=decision.selected_model.model_id,
                total_cost_usd=0.0,  # TODO: Track actual cost
                total_latency_ms=total_latency,
                escalation_count=0,
                quality_passed=True,
                quality_score=ttc_result.best_quality,
                quality_reasoning=f"TTC strategy={ttc_decision.strategy.value}; samples={ttc_result.samples_generated}",
                routing_decision=decision,
                execution_metadata={
                    "path": "ttc",
                    "ttc_used": True,
                    "ttc_strategy": ttc_decision.strategy.value,
                    "ttc_requested_samples": ttc_decision.num_samples,
                    "ttc_generated_samples": ttc_result.samples_generated,
                    "models_tried": [decision.selected_model.model_id],
                },
            )

        # 3. EXECUTION LOOP (Try -> Check -> Escalate)
        # ----------------------------------------------------
        
        escalation_engine = get_escalation_engine()
        # Layer 8: when Layer 3 routed this query, escalate along ITS cost-sorted
        # qualifying set (cheapest-correct first) rather than a fresh registry scan,
        # skipping any qualifier that just rate-limited. Falls back to the legacy
        # path builder for legacy-pipeline decisions.
        l3_raw = getattr(decision, "layer3_raw_decision", None)
        if l3_raw is not None and getattr(l3_raw, "qualifying_models", None):
            from src.layer0_model_infra.routing.rate_limit_cooldown import get_rate_limit_cooldown
            escalation_path = escalation_engine.path_from_qualifiers(
                qualifying_models=l3_raw.qualifying_models,
                selected_model_id=decision.selected_model.model_id,
                cooldown=get_rate_limit_cooldown(),
            )
        else:
            escalation_path = escalation_engine.create_escalation_path(
                initial_model_id=decision.selected_model.model_id,
                requires_vision=decision.modality_analysis.get("requires_vision", False),
                requires_code=decision.modality_analysis.get("requires_code_model", False),
            )
        current_model = escalation_path.current_model

        attempts = 0
        total_cost = 0.0
        
        final_response = None
        final_quality = 0.0
        final_reasoning = ""
        passed = False
        l3_first_quality = None  # observed quality of the Layer-3-selected model (attempt 1)

        # Track models used for feedback
        models_tried = []
        
        while attempts < escalation_path.max_attempts:
            attempts += 1
            attempt_start = time.time()
            
            # A. Call Model
            logger.info("executing_model", model=current_model.model_id, attempt=attempts)
            try:
                response = await self.gateway.complete(LLMRequest(
                    model_id=current_model.model_id,
                    messages=[{"role": "user", "content": query}],
                    temperature=0.7
                ))
                
                total_cost += response.cost_usd
                guardrails.record_cost(response.cost_usd)
                models_tried.append(current_model.model_id)
                
                # B. Quality Check (Layer 7) - CONDITIONAL + DOMAIN-AWARE
                # Only run deep quality check when needed:
                # - High uncertainty (risky routing)
                # - Long response (more room for hallucination)
                # - Domain policy requires it (medical, legal)
                # - Quality evaluation itself has cost!
                
                from src.layer0_model_infra.config.domain_policies import get_domain_policy
                
                domain = decision.triage_result.get("domain", "general")
                domain_policy = get_domain_policy(domain)
                
                should_evaluate_quality = (
                    # Domain requires it (medical, legal always check)
                    domain_policy.always_evaluate_quality
                    # High uncertainty
                    or decision.uncertainty_score.get("total_uncertainty", 0.5) > domain_policy.min_uncertainty_for_safe_routing
                    # Long responses
                    or len(response.content) > 500
                    # First attempt (safety net)
                    or attempts == 1
                )
                
                if should_evaluate_quality:
                    guardrails.record_quality_check()
                    quality_score = self.quality_evaluator.evaluate(
                        response=response.content,
                        query=query,
                        model_id=current_model.model_id
                    )
                    
                    final_response = response
                    final_quality = quality_score.overall_quality
                    final_reasoning = quality_score.reasoning
                    
                    # Use domain-specific threshold
                    passed = final_quality >= domain_policy.min_quality_threshold
                    
                    logger.info("quality_check_performed", 
                               score=final_quality, 
                               domain=domain,
                               threshold=domain_policy.min_quality_threshold)
                else:
                    # Assume pass for high-confidence simple queries
                    final_response = response
                    final_quality = 0.95  # Assume high quality
                    final_reasoning = "Quality check skipped (domain policy + high confidence)"
                    passed = True
                    
                    logger.info("quality_check_skipped", reason="domain_policy_allows", domain=domain)

                # First attempt ran the Layer-3-selected model — capture its
                # observed quality for the calibration EMA (online learning).
                if attempts == 1:
                    l3_first_quality = final_quality

                if passed:
                    logger.info("quality_check_passed", score=final_quality)
                    break

                # C. Auto-Escalation (Layer 8, policy-driven)
                elapsed_attempt_ms = (time.time() - attempt_start) * 1000
                escalation_path.record_attempt(
                    cost_usd=response.cost_usd,
                    latency_ms=elapsed_attempt_ms,
                )

                should_escalate = escalation_engine.should_escalate(
                    quality_score=final_quality,
                    refusal_detected=quality_score.refusal_detected,
                    user_tier=user_tier,
                    cumulative_latency_ms=escalation_path.cumulative_latency_ms,
                    cumulative_cost_usd=escalation_path.cumulative_cost,
                    max_cost_usd=guardrails.max_cost_usd,
                    escalation_path=escalation_path,
                )
                should_escalate = should_escalate or quality_score.needs_escalation

                if should_escalate and escalation_path.can_escalate and guardrails.can_escalate():
                    next_model = escalation_path.escalate()
                    if next_model is None:
                        break
                    guardrails.record_escalation()
                    logger.info(
                        "escalating_to_next_model",
                        from_model=current_model.model_id,
                        to_model=next_model.model_id,
                        level=escalation_path.current_level,
                        cumulative_cost=round(escalation_path.cumulative_cost, 6),
                        cumulative_latency_ms=round(escalation_path.cumulative_latency_ms, 2),
                    )
                    current_model = next_model
                else:
                    if escalation_path.halt_reason:
                        logger.warning("escalation_halted", reason=escalation_path.halt_reason)
                    else:
                        logger.info("escalation_not_triggered_or_not_possible")
                    break
                    
            except Exception as e:
                logger.error("execution_failed", error=str(e), model=current_model.model_id)
                # If execution fails, attempt immediate escalation if possible.
                if escalation_path.can_escalate and guardrails.can_escalate():
                    next_model = escalation_path.escalate()
                    if next_model is not None:
                        guardrails.record_escalation()
                        current_model = next_model
                        continue
                break

        # 4. FEEDBACK LOOP (Layer 9)
        # ----------------------------------------------------
        total_latency = (time.time() - start_time) * 1000
        
        # Log latency budget utilization
        logger.info(
            "latency_budget_summary",
            consumed_ms=latency_budget.consumed_ms,
            budget_ms=latency_budget.total_budget_ms,
            utilization=f"{latency_budget.utilization_percent:.1f}%",
            breakdown=latency_budget.layer_breakdown
        )
        
        # Log guardrails summary
        logger.info(
            "guardrails_summary",
            escalations=guardrails.escalation_count,
            quality_checks=guardrails.quality_check_count,
            ttc_samples=guardrails.ttc_samples_used,
            cost=guardrails.cost_consumed_usd
        )
        
        # Track session-level metrics
        session_guardrails.track_request(
            session_id=session_id,
            escalated=(len(models_tried) > 1),
            cost_usd=total_cost
        )
        
        # Update Memory
        if passed and final_response:
             self.memory.record(
                 query=query,
                 model_id=models_tried[-1],
                 quality_score=final_quality,
                 escalated=(len(models_tried) > 1),
                 intent=decision.triage_result.get("intent", ""),
                 domain=decision.triage_result.get("domain", ""),
             )

        # Layer 3 online calibration (the learning loop): fold the first-attempt
        # observed quality into the EMA for the kNN-predicted (model, feature_cell).
        # update() no-ops unless the decision came from the kNN corpus path.
        l3_raw = getattr(decision, "layer3_raw_decision", None)
        if l3_raw is not None and l3_first_quality is not None:
            try:
                from src.layer0_model_infra.routing.calibration_store import get_calibration_store
                if get_calibration_store().update(l3_raw, l3_first_quality):
                    logger.info(
                        "layer3_calibration_updated",
                        model_id=l3_raw.selected_model,
                        observed_quality=round(l3_first_quality, 3),
                    )
            except Exception as e:
                logger.warning("layer3_calibration_update_failed", error=str(e))

        return ExecutionResult(
            content=final_response.content if final_response else "Error: Execution failed",
            model_used=models_tried[-1] if models_tried else "none",
            total_cost_usd=total_cost,
            total_latency_ms=total_latency,
            escalation_count=len(models_tried) - 1,
            quality_passed=passed,
            quality_score=final_quality,
            quality_reasoning=final_reasoning,
            routing_decision=decision,
            execution_metadata={
                "path": "standard",
                "ttc_used": False,
                "models_tried": models_tried,
                "guardrails": {
                    "escalations": guardrails.escalation_count,
                    "quality_checks": guardrails.quality_check_count,
                    "ttc_samples_used": guardrails.ttc_samples_used,
                    "cost_consumed_usd": guardrails.cost_consumed_usd,
                },
                "latency_budget": {
                    "consumed_ms": latency_budget.consumed_ms,
                    "budget_ms": latency_budget.total_budget_ms,
                    "utilization_percent": latency_budget.utilization_percent,
                    "layer_breakdown": latency_budget.layer_breakdown,
                },
                "escalation_halt_reason": escalation_path.halt_reason,
            },
        )

    async def _execute_simple(self, decision, query, start_time):
        """Execute without complex loops (Fast step)."""
        model = decision.selected_model
        response = await self.gateway.complete(LLMRequest(
            model_id=model.model_id,
            messages=[{"role": "user", "content": query}]
        ))
        latency = (time.time() - start_time) * 1000
        return ExecutionResult(
            content=response.content,
            model_used=model.model_id,
            total_cost_usd=response.cost_usd,
            total_latency_ms=latency,
            escalation_count=0,
            quality_passed=True, # Assumed true for fast path
            quality_score=1.0,
            quality_reasoning="Fast Path / Cache Hit",
            routing_decision=decision,
            execution_metadata={
                "path": "simple",
                "ttc_used": False,
                "models_tried": [model.model_id],
                "fast_path": decision.pipeline_metadata.get("fast_path_triggered", False),
                "semantic_memory_hit": decision.pipeline_metadata.get("semantic_memory_hit", False),
            },
        )

# Global Instance
_orchestrator = None

def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EliteExecutionOrchestrator()
    return _orchestrator
