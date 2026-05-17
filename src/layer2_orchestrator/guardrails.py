"""
📁 File: src/layer2_orchestrator/guardrails.py
Layer: Layer 2 (Orchestrator)
Purpose: Operational guardrails to prevent runaway behavior
Depends on: Nothing
Used by: execution_loop.py

Implements safety limits:
- Max escalations per session
- Max compute per request
- Max quality checks per request
- Circuit breakers
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta

from src.shared.logger import get_logger

logger = get_logger(__name__)


class RequestGuardrails(BaseModel):
    """Guardrails for a single request."""
    
    # Escalation limits
    max_escalation_attempts: int = Field(default=3, description="Hard cap on escalations")
    escalation_count: int = Field(default=0, description="Current escalation count")
    
    # Quality check limits
    max_quality_checks: int = Field(default=5, description="Max quality evaluations")
    quality_check_count: int = Field(default=0, description="Current quality check count")
    
    # Compute limits
    max_ttc_samples: int = Field(default=5, description="Max test-time compute samples")
    ttc_samples_used: int = Field(default=0, description="TTC samples used")
    
    # Cost limits
    max_cost_usd: float = Field(default=1.0, description="Max cost per request")
    cost_consumed_usd: float = Field(default=0.0, description="Cost consumed so far")
    
    def can_escalate(self) -> bool:
        """Check if another escalation is allowed."""
        return self.escalation_count < self.max_escalation_attempts
    
    def can_check_quality(self) -> bool:
        """Check if another quality check is allowed."""
        return self.quality_check_count < self.max_quality_checks
    
    def can_use_ttc(self, n: int) -> bool:
        """Check if TTC with n samples is allowed."""
        return (self.ttc_samples_used + n) <= self.max_ttc_samples
    
    def can_spend(self, amount_usd: float) -> bool:
        """Check if more spending is allowed."""
        return (self.cost_consumed_usd + amount_usd) <= self.max_cost_usd
    
    def record_escalation(self):
        """Record an escalation attempt."""
        self.escalation_count += 1
        if self.escalation_count >= self.max_escalation_attempts:
            logger.warning("guardrail_escalation_limit_reached", count=self.escalation_count)
    
    def record_quality_check(self):
        """Record a quality check."""
        self.quality_check_count += 1
        if self.quality_check_count >= self.max_quality_checks:
            logger.warning("guardrail_quality_limit_reached", count=self.quality_check_count)
    
    def record_ttc_samples(self, n: int):
        """Record TTC samples used."""
        self.ttc_samples_used += n
        if self.ttc_samples_used >= self.max_ttc_samples:
            logger.warning("guardrail_ttc_limit_reached", count=self.ttc_samples_used)
    
    def record_cost(self, amount_usd: float):
        """Record cost consumed."""
        self.cost_consumed_usd += amount_usd
        if self.cost_consumed_usd >= self.max_cost_usd:
            logger.warning("guardrail_cost_limit_reached", cost=self.cost_consumed_usd)


class SessionGuardrails:
    """
    Session-level guardrails (circuit breakers).
    
    Tracks patterns across multiple requests in a session
    to detect abuse or system issues.
    """
    
    def __init__(self):
        # Session ID -> metrics
        self.session_metrics: Dict[str, Dict] = {}
    
    def track_request(self, session_id: str, escalated: bool, cost_usd: float):
        """Track a request for this session."""
        if session_id not in self.session_metrics:
            self.session_metrics[session_id] = {
                "total_requests": 0,
                "total_escalations": 0,
                "total_cost_usd": 0.0,
                "first_seen": datetime.now(),
            }
        
        metrics = self.session_metrics[session_id]
        metrics["total_requests"] += 1
        if escalated:
            metrics["total_escalations"] += 1
        metrics["total_cost_usd"] += cost_usd
    
    def should_cooldown(self, session_id: str) -> bool:
        """
        Check if session should be in cooldown mode.
        
        Returns True if:
        - Too many recent escalations (>50% of requests)
        - Spending too much
        """
        if session_id not in self.session_metrics:
            return False
        
        metrics = self.session_metrics[session_id]
        
        # Check escalation rate
        if metrics["total_requests"] > 5:
            escalation_rate = metrics["total_escalations"] / metrics["total_requests"]
            if escalation_rate > 0.5:
                logger.warning(
                    "session_cooldown_triggered",
                    session_id=session_id,
                    escalation_rate=escalation_rate,
                    reason="high_escalation_rate"
                )
                return True
        
        # Check cost
        if metrics["total_cost_usd"] > 10.0:  # $10 per session
            logger.warning(
                "session_cooldown_triggered",
                session_id=session_id,
                cost=metrics["total_cost_usd"],
                reason="high_cost"
            )
            return True
        
        return False
    
    def get_escalation_count(self, session_id: str) -> int:
        """Get total escalations for this session."""
        if session_id not in self.session_metrics:
            return 0
        return self.session_metrics[session_id]["total_escalations"]


# Global singleton
_session_guardrails: Optional[SessionGuardrails] = None


def get_session_guardrails() -> SessionGuardrails:
    """Get the global session guardrails."""
    global _session_guardrails
    if _session_guardrails is None:
        _session_guardrails = SessionGuardrails()
    return _session_guardrails


def create_request_guardrails(user_tier: str = "standard", domain: str = "general") -> RequestGuardrails:
    """
    Create guardrails for a request based on user tier and domain.
    
    Premium users get more generous limits.
    High-risk domains get more escalation attempts.
    """
    # Base limits
    max_escalations = 2
    max_quality_checks = 3
    max_cost = 0.5
    
    # Adjust for tier
    if user_tier == "premium":
        max_escalations = 3
        max_quality_checks = 5
        max_cost = 2.0
    elif user_tier == "enterprise":
        max_escalations = 5
        max_quality_checks = 10
        max_cost = 10.0
    
    # Adjust for domain
    if domain in ["medical", "legal", "finance"]:
        max_escalations += 1  # Allow one extra escalation for safety
        max_quality_checks += 2
    
    return RequestGuardrails(
        max_escalation_attempts=max_escalations,
        max_quality_checks=max_quality_checks,
        max_cost_usd=max_cost,
    )
