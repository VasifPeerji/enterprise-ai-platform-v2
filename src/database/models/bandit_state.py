"""
📁 File: src/database/models/bandit_state.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Database model for persisting bandit arm statistics
Depends on: SQLModel, database base
Used by: bandit_router.py

Stores multi-armed bandit state to survive server restarts.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BanditArmState(SQLModel, table=True):
    """
    Persistent storage for bandit arm statistics.
    
    Each row represents one arm (model) in a specific context.
    Context key is a hash of: domain, intent, complexity, user_tier, etc.
    """
    
    __tablename__ = "bandit_arm_states"
    
    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Context identification
    context_key: str = Field(index=True, description="Hash of routing context")
    model_id: str = Field(index=True, description="Model identifier")
    
    # Bandit statistics
    pulls: int = Field(default=0, description="Number of times this arm was pulled")
    successes: int = Field(default=0, description="Number of successful outcomes")
    total_reward: float = Field(default=0.0, description="Cumulative reward")
    
    # Performance metrics
    escalation_count: int = Field(default=0, description="Times this model escalated")
    avg_quality: float = Field(default=0.0, description="Average quality score")
    avg_cost: float = Field(default=0.0, description="Average cost in USD")
    avg_latency_ms: float = Field(default=0.0, description="Average latency in ms")

    # Thompson Sampling: Beta distribution parameters
    alpha: float = Field(default=1.0, description="Beta dist alpha (successes+1)")
    beta_: float = Field(default=1.0, description="Beta dist beta (failures+1)")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        """SQLModel configuration."""
        json_schema_extra = {
            "example": {
                "context_key": "domain:tech_intent:qa_complexity:simple",
                "model_id": "gpt-3.5-turbo",
                "pulls": 150,
                "successes": 142,
                "total_reward": 128.5,
                "escalation_count": 8,
                "avg_quality": 0.89,
                "avg_cost": 0.0012,
                "avg_latency_ms": 850.0,
            }
        }
