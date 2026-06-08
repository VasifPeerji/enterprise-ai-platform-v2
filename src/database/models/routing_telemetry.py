"""
📁 File: src/database/models/routing_telemetry.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Database model for async routing telemetry (Layer 9 Continuous Learning)
Depends on: SQLModel
Used by: telemetry.py

Stores one record per routing decision. Used by offline MLOps pipelines for:
  - Triage classifier recalibration
  - Bandit prior update
  - Routing threshold adjustment
  - Semantic memory pruning
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class RoutingTelemetryRecord(SQLModel, table=True):
    """
    Persistent storage for per-request routing telemetry.

    Each row represents one routing decision event.
    Allows offline analysis of escalation rates, cost, quality,
    and policy drift over time.
    """

    __tablename__ = "routing_telemetry"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Request identification
    request_id: str = Field(index=True, description="Unique request identifier")
    timestamp: float = Field(description="Unix epoch of routing event")

    # Routing decision
    selected_model_id: str = Field(index=True, description="Model initially selected")
    final_model_id: str = Field(index=True, description="Final model used (after escalation)")

    # Classification signals (from Layer 3)
    domain: str = Field(default="", index=True, description="Query domain")
    intent: str = Field(default="", description="Query intent")
    complexity_band: str = Field(default="", description="Query complexity band")

    # Quality & outcome (from Layer 7-8)
    quality_score: float = Field(default=0.0, description="Post-generation quality score")
    escalated: bool = Field(default=False, index=True, description="Whether escalation occurred")
    escalation_count: int = Field(default=0, description="Number of escalation hops")
    refusal_detected: bool = Field(default=False, description="Whether model refused")

    # Economic signals
    cost_usd: float = Field(default=0.0, description="Estimated cost in USD")
    latency_ms: float = Field(default=0.0, description="End-to-end latency in ms")

    # Confidence signals (from Layer 4)
    uncertainty_score: float = Field(default=0.0, description="Total uncertainty score")
    confidence_level: str = Field(default="", description="HIGH/MEDIUM/LOW")
    novelty_score: float = Field(default=0.0, description="Semantic novelty (0-1)")

    # User context (Sections 4.2 and 4.4)
    user_tier: str = Field(default="standard", description="User tier at request time")
    budget_remaining: float = Field(default=1.0, description="Budget fraction remaining")

    # Layer 3 routing signals (Layer 9 observability + drift detection)
    routing_source: str = Field(default="", index=True, description="Layer 3 routing source (knn_corpus/prior/fallback/...)")
    predicted_quality: float = Field(default=0.0, description="Layer 3 predicted quality for the selected model")
    prediction_confidence_score: float = Field(default=0.0, description="Neighbour-derived prediction confidence (0-1)")
    uncertainty_escalated: bool = Field(default=False, description="Whether risk-aware (uncertainty) escalation fired")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req-abc123",
                "selected_model_id": "ollama-llama3.1-8b",
                "final_model_id": "gpt-4-turbo",
                "domain": "tech",
                "intent": "coding",
                "complexity_band": "moderate",
                "quality_score": 0.88,
                "escalated": True,
                "escalation_count": 1,
                "cost_usd": 0.0042,
                "latency_ms": 1850.0,
                "uncertainty_score": 0.42,
                "confidence_level": "MEDIUM",
                "user_tier": "premium",
            }
        }
