"""
📁 File: src/layer2_orchestrator/latency_budget.py
Layer: Layer 2 (Orchestrator)
Purpose: Latency budget tracking and enforcement
Depends on: Nothing
Used by: execution_loop.py

Tracks latency consumed by each layer and enforces global budget.
Prevents runaway pipelines.
"""

import time
from typing import Optional, Dict
from pydantic import BaseModel, Field

from src.shared.logger import get_logger

logger = get_logger(__name__)


class LatencyBudget(BaseModel):
    """Tracks latency budget for a request."""
    
    total_budget_ms: float = Field(..., description="Total allowed latency")
    consumed_ms: float = Field(default=0.0, description="Latency consumed so far")
    layer_breakdown: Dict[str, float] = Field(
        default_factory=dict,
        description="Latency consumed by each layer"
    )
    
    @property
    def remaining_ms(self) -> float:
        """Remaining budget."""
        return max(0, self.total_budget_ms - self.consumed_ms)
    
    @property
    def is_exhausted(self) -> bool:
        """Check if budget is exhausted."""
        return self.consumed_ms >= self.total_budget_ms
    
    @property
    def utilization_percent(self) -> float:
        """Percentage of budget consumed."""
        return (self.consumed_ms / self.total_budget_ms) * 100
    
    def record_layer(self, layer_name: str, latency_ms: float):
        """Record latency for a specific layer."""
        self.consumed_ms += latency_ms
        self.layer_breakdown[layer_name] = self.layer_breakdown.get(layer_name, 0) + latency_ms
        
        if self.consumed_ms > self.total_budget_ms:
            logger.warning(
                "latency_budget_exceeded",
                layer=layer_name,
                consumed=self.consumed_ms,
                budget=self.total_budget_ms
            )


class LatencyTracker:
    """Context manager for tracking layer latency."""
    
    def __init__(self, budget: LatencyBudget, layer_name: str):
        self.budget = budget
        self.layer_name = layer_name
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            elapsed_ms = (time.time() - self.start_time) * 1000
            self.budget.record_layer(self.layer_name, elapsed_ms)
            
            logger.debug(
                "layer_latency_recorded",
                layer=self.layer_name,
                latency_ms=elapsed_ms,
                remaining_ms=self.budget.remaining_ms
            )


def create_latency_budget(user_tier: str = "standard") -> LatencyBudget:
    """
    Create a latency budget based on user tier.
    
    Premium users get more generous budgets.
    Free users get tight budgets.
    """
    budgets = {
        "free": 1000,      # 1 second
        "standard": 3000,  # 3 seconds
        "premium": 5000,   # 5 seconds
        "enterprise": 10000  # 10 seconds
    }
    
    budget_ms = budgets.get(user_tier, 3000)
    
    return LatencyBudget(total_budget_ms=budget_ms)
