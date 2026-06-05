"""
📁 File: src/layer0_model_infra/routing/layer3_types.py
Layer: Layer 0 (Model Infrastructure) — Layer 3 redesign
Purpose: Pydantic schemas for the benchmark-driven kNN router
Depends on: pydantic
Used by: registry_loader, feature_extractor, verdict_cache, knn_router (next batch)

The new Layer 3 routes by predicting per-model quality from a corpus of public
benchmark outcomes, picking the cheapest model that clears a quality floor.
These types pin down the shape of every output so downstream code (Layer 4/5
telemetry, dashboard, Layer 8 escalation) has a stable contract to consume.

Schema versions follow semver. Bumping `RoutingDecision.version` invalidates
any persisted verdict-cache entries with the prior version on next lookup —
see `verdict_cache.is_stale` for the gating rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

LAYER3_SCHEMA_VERSION = "1.1.0"


# ---------------------------------------------------------------------------
# Feature extractor output (Stage B)
# ---------------------------------------------------------------------------

class Modality(str, Enum):
    """Coarse modality bucket the router uses for safe-default lookup
    and aggregate-prior weighting. Intentionally small; the router does NOT
    classify intent or domain — those concepts are gone from the new design.
    """
    TEXT = "text"
    CODE = "code"
    MATH = "math"
    VISION = "vision"
    MULTIMODAL = "multimodal"


class HighRiskDomain(str, Enum):
    """Three domains that earn an elevated quality floor (0.75 vs 0.65 default).
    Membership is decided by a narrow keyword + pattern check — false positives
    are preferred over false negatives here because the cost of routing a
    medical question to a cheap model is asymmetrically worse than the cost
    of slightly over-routing a non-medical question that happened to mention
    a body part.
    """
    MEDICAL = "medical"
    LEGAL = "legal"
    FINANCIAL = "financial"


class DifficultySignal(str, Enum):
    """Coarse difficulty hint used as a SIMILARITY RE-WEIGHTING input by the
    kNN router (see length_adjusted_similarity in knn_router). NOT used as a
    routing decision input on its own — the previous Layer 3 had a separate
    complexity classifier whose magic-number thresholds were a major source
    of error; we removed it.
    """
    TRIVIAL = "trivial"
    NORMAL = "normal"
    HARD = "hard"


class QueryFeatures(BaseModel):
    """Output of Stage B — lightweight feature extractor.

    Every field is computed deterministically from the query + attachment
    metadata. No model inference, no language LLM calls. The whole struct
    serialises in <50 bytes and is cheap to attach to telemetry.
    """

    model_config = ConfigDict(use_enum_values=False, frozen=True)

    language: str = Field(
        ...,
        description="ISO-639-1 code from lingua-py, OR 'multi' if confidence "
                    "< 0.55. Single-script CJK / Arabic / Devanagari take a "
                    "fast script-detection shortcut.",
    )
    modality: Modality = Field(
        ...,
        description="Primary modality bucket. Decided by code-density regex + "
                    "explicit attachment metadata. Defaults to TEXT.",
    )
    high_risk_domain: Optional[HighRiskDomain] = Field(
        default=None,
        description="One of medical / legal / financial when narrow patterns "
                    "fire. None for everything else.",
    )
    estimated_input_tokens: int = Field(
        ...,
        ge=0,
        description="Rough char-based estimate (len // 4 for Latin, adjusted "
                    "for CJK). Used by cost-estimation, not routing.",
    )
    estimated_output_tokens: int = Field(
        ...,
        ge=0,
        description="Modality-based default output length: text 400, code 500, "
                    "math 600, vision 300, multimodal 500.",
    )
    difficulty_signal: DifficultySignal = Field(
        default=DifficultySignal.NORMAL,
        description="Trivial / normal / hard hint. Consumed by the kNN router "
                    "via length-adjusted similarity (P3 of the patch list).",
    )
    has_code_block: bool = Field(default=False)
    has_image_attachment: bool = Field(default=False)
    has_audio_attachment: bool = Field(default=False)
    char_count: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Registry entry (loaded from data/registry.json)
# ---------------------------------------------------------------------------

class CoverageQuality(str, Enum):
    """How much per-question public benchmark data exists for this model.

    Drives two things:
    1. Whether kNN predictions are used (full/medium) or aggregate prior
       takes over (low — see knn_router.predict_quality).
    2. Whether the +0.10 anti-over-routing floor penalty applies (low only).
    """
    FULL = "full"      # >= 60% benchmark coverage; trust kNN
    MEDIUM = "medium"  # 20-60%; mix kNN + prior
    LOW = "low"        # < 20%; always use aggregate prior + +0.10 floor penalty


class RateLimits(BaseModel):
    """Per-minute and per-day rate caps. `null` means no cap."""
    rpm: Optional[int] = Field(default=None, ge=0)
    rpd: Optional[int] = Field(default=None, ge=0)
    tier: Literal["free", "paid"] = "paid"


class Pricing(BaseModel):
    """USD pricing per 1M tokens. Free models report 0.0/0.0."""
    input_per_1m_usd: float = Field(..., ge=0.0)
    output_per_1m_usd: float = Field(..., ge=0.0)


class RegistryEntry(BaseModel):
    """One model in the registry. Stable subset of fields the router needs.

    Compared with the existing ModelDefinition (src/layer0_model_infra/models.py)
    this adds: coverage_quality, benchmark_coverage_pct, last_benchmark_run,
    license_terms, rate_limits, required_env_var, added_at — all needed for
    the kNN router's behaviour (floor penalty, warmup, prior fallback).
    """

    model_config = ConfigDict(use_enum_values=False)

    model_id: str
    provider: str
    litellm_model_name: str
    display_name: str
    description: str = ""

    model_type: Literal["text", "multimodal", "audio", "vision", "embedding"] = "text"
    capabilities: list[str] = Field(default_factory=list)
    context_window: int = Field(..., ge=1)
    max_output_tokens: int = Field(..., ge=1)

    pricing: Pricing
    rate_limits: RateLimits = Field(default_factory=RateLimits)

    arena_elo: Optional[int] = None
    arena_elo_normalised: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    coverage_quality: CoverageQuality = CoverageQuality.LOW
    benchmark_coverage_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    last_benchmark_run: Optional[str] = None  # ISO date
    license_terms: str = ""

    required_env_var: Optional[str] = Field(
        default=None,
        description="Env var that must be set for is_active=True. When None, "
                    "the model is treated as always-active (e.g. local Ollama).",
    )
    added_at: datetime = Field(
        ...,
        description="When this model was added to the registry. Drives warmup "
                    "eligibility (model is in warmup for the first ~30 days "
                    "or 100 observations, whichever comes first — see "
                    "knn_router.is_in_warmup).",
    )

    is_active: bool = Field(
        default=True,
        description="Set by the registry loader based on required_env_var. "
                    "Routing skips inactive models entirely.",
    )
    is_recommended: bool = False

    @field_validator("added_at", mode="before")
    @classmethod
    def _parse_added_at(cls, value):
        if isinstance(value, str):
            # Accept either "YYYY-MM-DD" or full ISO timestamp
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                from datetime import date
                return datetime.combine(date.fromisoformat(value), datetime.min.time())
        return value

    def total_cost_per_1k(self, input_tokens: int, output_tokens: int) -> float:
        """Estimated USD cost for a request of the given shape."""
        in_cost = (input_tokens / 1_000_000) * self.pricing.input_per_1m_usd
        out_cost = (output_tokens / 1_000_000) * self.pricing.output_per_1m_usd
        return in_cost + out_cost


class SafeDefaults(BaseModel):
    """Per-modality safe defaults used by Stage D fallback."""
    text: str
    code: str
    math: str
    vision: str
    multimodal: str
    high_risk: str

    def for_features(self, features: QueryFeatures) -> str:
        """Pick the appropriate default based on extracted features."""
        if features.high_risk_domain is not None:
            return self.high_risk
        # features.modality may be a string when frozen=True deserialises;
        # normalise both sides for the lookup.
        mod = features.modality.value if isinstance(features.modality, Modality) else features.modality
        return {
            "text": self.text,
            "code": self.code,
            "math": self.math,
            "vision": self.vision,
            "multimodal": self.multimodal,
        }.get(mod, self.text)


# ---------------------------------------------------------------------------
# Verdict cache entry (Stage A)
# ---------------------------------------------------------------------------

class VerdictCacheEntry(BaseModel):
    """One cached routing decision keyed by query signature."""
    query_signature: str = Field(..., description="SHA256 of normalised query")
    normalised_query: str = Field(..., description="Lowercased + whitespace-stripped query for ANN lookup")
    decision: "RoutingDecision"
    cached_at: datetime
    hit_count: int = 0

    def is_stale(self, ttl_seconds: float, current_version: str) -> bool:
        """Stale if older than TTL OR schema version has bumped."""
        if self.decision.version != current_version:
            return True
        age = (datetime.now(timezone.utc) - self.cached_at).total_seconds()
        return age > ttl_seconds


# ---------------------------------------------------------------------------
# Routing decision (the output of Layer 3)
# ---------------------------------------------------------------------------

class RoutingSource(str, Enum):
    """How the decision was produced. Drives the calibration update rule —
    only KNN_CORPUS decisions feed the multiplier EMA; CACHE/FALLBACK/
    EXPLORATION/WARMUP decisions update separate counters but don't dilute
    quality predictions for the wrong cells.
    """
    CACHE_HIT = "cache_hit"
    KNN_CORPUS = "knn_corpus"
    PRIOR = "prior"              # benchmark aggregate-prior selection (no kNN neighbors) — still data-driven, NOT a hard-coded default
    FALLBACK = "fallback"
    EXPLORATION = "exploration"  # ε-exploration of borderline models (P2)
    WARMUP = "warmup"            # Forced selection of newly-registered model (P4)
    FORCED = "forced"            # Caller-supplied force_model_id (manual override)


class RoutingDecision(BaseModel):
    """The output of Layer 3.

    Stable contract for downstream layers (4, 5, 7, 8, 9) and the dashboard.
    Every routing path produces one of these — including cache hits, fallbacks,
    and exploration shots. The `source` field tells you how to interpret the
    rest.
    """

    model_config = ConfigDict(use_enum_values=False)

    # ── Identity ─────────────────────────────────────────────────────────
    request_id: str
    timestamp: datetime
    version: str = LAYER3_SCHEMA_VERSION

    # ── The choice ───────────────────────────────────────────────────────
    selected_model: str = Field(..., description="model_id from the registry")
    source: RoutingSource

    # ── Quality prediction ───────────────────────────────────────────────
    predicted_quality: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Predicted Layer-7 quality score for the selected model on "
                    "this query. None for cache hits (use the cached value) "
                    "and fallbacks (off-distribution, prediction not meaningful).",
    )
    prediction_confidence: Literal["high", "low"] = "low"

    # ── Cost ─────────────────────────────────────────────────────────────
    estimated_cost_usd: float = Field(..., ge=0.0)

    # ── Floor application ────────────────────────────────────────────────
    quality_floor_base: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    effective_floor: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Per-model floor after low-coverage penalty + high-risk "
                    "elevation. May exceed quality_floor_base by up to 0.10.",
    )

    # ── Inputs ───────────────────────────────────────────────────────────
    features: QueryFeatures

    # ── kNN audit trail ──────────────────────────────────────────────────
    neighbors_used: list[tuple[str, float]] = Field(
        default_factory=list,
        description="Top kNN neighbors as (question_global_id, similarity). "
                    "Truncated to ~10 for telemetry size.",
    )
    all_model_qualities: dict[str, float] = Field(
        default_factory=dict,
        description="Full per-model predicted quality. Includes models that "
                    "didn't qualify — useful for forensics and escalation.",
    )
    qualifying_models: list[str] = Field(
        default_factory=list,
        description="Models that cleared the floor, ordered cheapest first. "
                    "Layer 8 (escalation) uses this list directly.",
    )

    # ── Calibration trace ────────────────────────────────────────────────
    calibration_multiplier_applied: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Multiplier applied to the raw kNN-weighted quality. 1.0 "
                    "= untouched. <1.0 = past performance was worse than "
                    "predicted (model demoted). >1.0 = better than predicted.",
    )
    feature_cell: Optional[str] = Field(
        default=None,
        description="Key used to look up the calibration multiplier — typically "
                    "'{modality}:{language}:{high_risk}:{difficulty}'.",
    )

    # ── Fallback path ────────────────────────────────────────────────────
    fallback_reason: Optional[str] = Field(
        default=None,
        description="When source=FALLBACK, one of: 'insufficient_neighbors', "
                    "'no_model_above_floor', 'all_qualifying_rate_limited'.",
    )

    # ── Stage A cache provenance ─────────────────────────────────────────
    cache_hit_kind: Optional[Literal["exact", "semantic"]] = None

    # ── Performance ──────────────────────────────────────────────────────
    latency_ms: float = Field(default=0.0, ge=0.0)


# Forward-reference resolution for VerdictCacheEntry.decision
VerdictCacheEntry.model_rebuild()
