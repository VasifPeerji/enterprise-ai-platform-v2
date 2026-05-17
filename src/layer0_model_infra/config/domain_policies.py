"""
📁 File: src/layer0_model_infra/config/domain_policies.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Domain-specific routing policies
Depends on: routing_config.py
Used by: router.py, uncertainty_estimator.py

Different domains require different safety/cost tradeoffs:
- Medical/Legal: Safety first (stricter thresholds)
- Casual Chat: Cost first (aggressive optimization)
- Coding: Balance (quality matters but budget-conscious)
"""

from typing import Dict
from pydantic import BaseModel, Field


class DomainPolicy(BaseModel):
    """Policy overrides for a specific domain."""
    
    # Uncertainty thresholds
    min_uncertainty_for_safe_routing: float = Field(
        default=0.5,
        description="Uncertainty level that triggers safer model selection"
    )
    
    # Quality evaluation
    always_evaluate_quality: bool = Field(
        default=False,
        description="If True, always run quality checks regardless of confidence"
    )
    
    min_quality_threshold: float = Field(
        default=0.6,
        description="Minimum quality score to accept response"
    )
    
    # Escalation
    max_escalation_attempts: int = Field(
        default=2,
        description="Maximum times to escalate before giving up"
    )
    
    # Cost
    prefer_cost_optimization: bool = Field(
        default=True,
        description="If True, prioritize cheap models (exploration rate high)"
    )
    
    # Test-time compute
    enable_test_time_compute: bool = Field(
        default=True,
        description="Allow Best-of-N sampling for this domain"
    )


# Domain-specific policies
DOMAIN_POLICIES: Dict[str, DomainPolicy] = {
    # HIGH-STAKES DOMAINS
    "medical": DomainPolicy(
        min_uncertainty_for_safe_routing=0.3,  # Very conservative
        always_evaluate_quality=True,          # Always check
        min_quality_threshold=0.8,             # High bar
        max_escalation_attempts=3,             # More chances
        prefer_cost_optimization=False,        # Safety > cost
        enable_test_time_compute=True,         # Use TTC
    ),
    
    "legal": DomainPolicy(
        min_uncertainty_for_safe_routing=0.3,
        always_evaluate_quality=True,
        min_quality_threshold=0.8,
        max_escalation_attempts=3,
        prefer_cost_optimization=False,
        enable_test_time_compute=True,
    ),
    
    "finance": DomainPolicy(
        min_uncertainty_for_safe_routing=0.4,
        always_evaluate_quality=True,
        min_quality_threshold=0.75,
        max_escalation_attempts=2,
        prefer_cost_optimization=False,
        enable_test_time_compute=True,
    ),
    
    # BALANCED DOMAINS
    "coding": DomainPolicy(
        min_uncertainty_for_safe_routing=0.5,
        always_evaluate_quality=False,
        min_quality_threshold=0.7,
        max_escalation_attempts=2,
        prefer_cost_optimization=True,          # Code can be iterated
        enable_test_time_compute=True,
    ),
    
    "business": DomainPolicy(
        min_uncertainty_for_safe_routing=0.5,
        always_evaluate_quality=False,
        min_quality_threshold=0.65,
        max_escalation_attempts=2,
        prefer_cost_optimization=True,
        enable_test_time_compute=True,
    ),
    
    # COST-OPTIMIZED DOMAINS
    "casual": DomainPolicy(
        min_uncertainty_for_safe_routing=0.6,  # Aggressive
        always_evaluate_quality=False,         # Skip checks
        min_quality_threshold=0.5,             # Lower bar
        max_escalation_attempts=1,             # One retry max
        prefer_cost_optimization=True,         # Cost first
        enable_test_time_compute=False,        # No TTC (waste)
    ),
    
    "general": DomainPolicy(
        min_uncertainty_for_safe_routing=0.55,
        always_evaluate_quality=False,
        min_quality_threshold=0.6,
        max_escalation_attempts=2,
        prefer_cost_optimization=True,
        enable_test_time_compute=True,
    ),
}


def get_domain_policy(domain: str) -> DomainPolicy:
    """
    Get policy for a domain.
    
    Falls back to 'general' if domain not found.
    """
    return DOMAIN_POLICIES.get(domain, DOMAIN_POLICIES["general"])
