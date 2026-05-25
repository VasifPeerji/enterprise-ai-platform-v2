"""
📁 File: src/layer0_model_infra/config/routing_config.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Routing pipeline configuration (dev vs production)
Depends on: pydantic
Used by: All routing components

Defines model choices for each pipeline layer based on environment.
"""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.shared.config import get_settings

settings = get_settings()


class Environment(str, Enum):
    """Deployment environment."""
    
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class FastPathConfig(BaseModel):
    """
    Configuration for Layer 0 — Fast Path bypass.

    The Fast Path is the only place that decides which trivial queries can skip
    the full pipeline. Layer 3 (fast_triage) consults the Fast Path rather than
    duplicating greeting/arithmetic detection.

    Each *_chain is an ordered preference list. The first model_id in the list
    that exists in the registry AND is_active wins. If the entire chain is
    unavailable, the Fast Path returns no-bypass and the full pipeline runs —
    nothing crashes.
    """

    enabled: bool = Field(default=True, description="Master switch for Layer 0 bypass")

    # Preference chains per bypass category — first available wins
    chat_chain: list[str] = Field(
        default_factory=lambda: [
            "ollama-phi3-mini",
            "ollama-llama3.1-8b",
            "groq-llama-3.1-8b-free",
            "gemini-2.0-flash-lite-free",
        ],
        description="Models for greetings / acknowledgments / farewells (ordered by preference)",
    )
    arithmetic_chain: list[str] = Field(
        default_factory=lambda: [
            "ollama-phi3-mini",
            "ollama-llama3.1-8b",
            "groq-llama-3.1-8b-free",
        ],
        description="Models for pure arithmetic queries",
    )
    factual_chain: list[str] = Field(
        default_factory=lambda: [
            "ollama-llama3.1-8b",
            "groq-llama-3.1-8b-free",
            "gemini-2.0-flash-lite-free",
            "ollama-phi3-mini",
        ],
        description="Models for simple factual lookups / definitions",
    )

    # Per-category minimum confidence (decisions below this fall through to full pipeline)
    min_greeting_confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    min_arithmetic_confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    min_factual_confidence: float = Field(default=0.80, ge=0.0, le=1.0)

    # Bounded greeting-query length: longer queries that contain a greeting token
    # are NOT bypassed (e.g. "Hello, can you help me debug this 200-line script?")
    max_greeting_words: int = Field(default=8, ge=1, le=20)

    # ── Tier 2: semantic chitchat fallback (Model2Vec prototype similarity) ──
    # When the keyword/regex Tier 1 returns NONE, Tier 2 embeds the query and
    # compares against curated chitchat prototypes. Catches paraphrases the
    # keyword table misses ("yo whats good", "cheers mate", "no worries").
    #
    # Validated by experiments/layer_0_model2vec_vs_heuristic — on the
    # paraphrase corpus the hybrid (Tier 1 + Tier 2) improves F1 from 23.5%
    # to 71.4% at 96.2% precision with 0 new false positives.
    #
    # Gracefully degrades to no-op if model2vec isn't installed.
    enable_semantic_tier2: bool = Field(
        default=True,
        description="Enable Model2Vec semantic chitchat classifier as Tier 2 fallback",
    )
    semantic_model_name: str = Field(
        default="minishlab/potion-base-8M",
        description="HuggingFace model_id of the Model2Vec encoder (multilingual, 8MB)",
    )
    semantic_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Min cosine similarity to a chitchat prototype to bypass. "
                    "0.80 is the experiment-validated point: max precision (96%) "
                    "with substantial F1 lift over heuristic alone.",
    )
    semantic_max_words: int = Field(
        default=12,
        ge=1,
        le=30,
        description="Skip Tier 2 for queries longer than this — saves latency on "
                    "obviously-long queries where Tier 2 wouldn't help anyway.",
    )


class ModalityGateConfig(BaseModel):
    """Configuration for modality detection."""

    vision_model: str = Field(..., description="Vision model for multimodal analysis")
    vram_gb: float = Field(..., description="VRAM footprint in GB")

    # ── Modality threshold knobs (Layer 1 — all empirically calibrated) ────
    # Lower values bias toward classifying as that modality.
    vision_threshold: float = Field(default=0.6, ge=0.0, le=1.0,
        description="Vision weight required for primary_modality=IMAGE")
    audio_threshold: float = Field(default=0.6, ge=0.0, le=1.0,
        description="Audio weight required for primary_modality=AUDIO")
    code_threshold: float = Field(default=0.4, ge=0.0, le=1.0,
        description="Code density required for primary_modality=CODE_HEAVY")
    code_required_threshold: float = Field(default=0.3, ge=0.0, le=1.0,
        description="Code density required for requires_code_model=True")
    structured_threshold: float = Field(default=0.5, ge=0.0, le=1.0,
        description="Structured density required for primary_modality=STRUCTURED")
    multimodal_min_high_signals: int = Field(default=2, ge=2, le=5,
        description="How many signals must be 'high' to classify MULTIMODAL")

    # ── Tier 2 — semantic language detection (lingua-py) ───────────────────
    # The script-based detector (built-in) catches CJK/Arabic/Devanagari/Cyrillic.
    # For Latin-script non-English (Spanish, French, German, …) we need lingua.
    # Hinglish markers run before lingua because lingua can't detect Latin-script
    # Hindi at all. Validated by experiments/layer_1_language_detection/.
    enable_semantic_language_detection: bool = Field(
        default=True,
        description="Use lingua-py for Latin-script language detection fallback",
    )
    language_confidence_threshold: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Min lingua confidence to trust a non-English prediction. "
                    "Below this we default to 'en' (avoids 'login broken' → 'nl' style errors).",
    )

    # ── Tier 2 — code language detection (Pygments) ────────────────────────
    enable_semantic_code_detection: bool = Field(
        default=True,
        description="Use Pygments guess_lexer when fence + keyword detection misses",
    )
    code_detection_max_chars: int = Field(
        default=8000,
        ge=100,
        le=100_000,
        description="Cap snippet length sent to Pygments for latency hygiene",
    )

    # ── Tier 2 — structured-data detection (try-parse cascade) ─────────────
    enable_structured_parse_cascade: bool = Field(
        default=True,
        description="Use json/tomllib/xml stdlib parsers to verify structured data",
    )
    structured_parse_max_chars: int = Field(
        default=16_000,
        ge=100,
        le=200_000,
        description="Cap snippet length for try-parse",
    )

    # ── Vision-relevance heuristic ─────────────────────────────────────────
    # If has_images=True but text doesn't reference the image, vision capability
    # isn't actually needed. This catches "I attached a screenshot for context,
    # now please refactor this code" — text-only routing is fine.
    require_vision_reference: bool = Field(
        default=True,
        description="If True, requires_vision=True only when text references the image",
    )
    short_query_implies_vision: int = Field(
        default=15,
        ge=0,
        le=100,
        description="If has_images and word_count <= this, assume image is the subject",
    )


class SemanticMemoryConfig(BaseModel):
    """Configuration for semantic memory (Layer 2)."""

    embedding_model: str = Field(..., description="Embedding model")
    vector_db: str = Field(..., description="Vector database (qdrant/milvus)")
    similarity_threshold: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Min similarity for cache hit"
    )
    max_cache_age_days: int = Field(default=30, description="Max age for cached routes")

    # ── Tier 2 — local embedding (Model2Vec direct, no gateway) ────────────
    # The original code routed embeddings through the LLM gateway, which adds
    # 50-200ms per call. Model2Vec runs locally in ~200μs and is already in
    # the environment from Layer 0.
    enable_local_embedding: bool = Field(
        default=True,
        description="Use Model2Vec for direct in-process embeddings (no gateway)",
    )
    local_embedding_model_name: str = Field(
        default="minishlab/potion-base-8M",
        description="HuggingFace model_id for Model2Vec encoder",
    )

    # ── Persistence (SQLite, stdlib) ───────────────────────────────────────
    # The original cache was in-memory only — restart wiped it. SQLite gives
    # us crash-safe persistence without new dependencies.
    enable_persistence: bool = Field(default=True, description="Persist cache to SQLite")
    persistence_path: str = Field(
        default="artifacts/semantic_memory.db",
        description="SQLite file path (relative to repo root)",
    )

    # ── Validation guards ──────────────────────────────────────────────────
    enable_negation_guard: bool = Field(
        default=True,
        description="Reject cache hits where negation polarity differs (install vs uninstall)",
    )
    enable_pii_scrubbing: bool = Field(
        default=True,
        description="Mask emails / phone numbers / SSN / cards before storage",
    )

    # ── Quality + TTL tiers ────────────────────────────────────────────────
    # Replaces the flat is_reusable threshold and flat decay with tiered
    # policies (GPTCache pattern).
    high_quality_threshold: float = Field(default=0.85, description="Above this, full 14-day TTL")
    medium_quality_threshold: float = Field(default=0.70, description="Above this, 3-day TTL")
    escalated_ttl_seconds: float = Field(default=86_400.0, description="Escalated entries: 1 day")
    high_quality_ttl_seconds: float = Field(default=1_209_600.0, description="14 days")
    medium_quality_ttl_seconds: float = Field(default=259_200.0, description="3 days")

    # ── Storage knobs ──────────────────────────────────────────────────────
    max_entries: int = Field(default=10_000, ge=100, description="Cap on cached entries")
    decay_half_life_seconds: float = Field(
        default=604_800.0,  # 7 days
        description="Exponential decay half-life for similarity scoring",
    )


class FastTriageConfig(BaseModel):
    """Configuration for fast triage classifier."""
    
    model: str = Field(..., description="Small, fast classifier model")
    vram_gb: float = Field(..., description="VRAM footprint in GB")
    max_tokens: int = Field(default=500, description="Max output tokens")


class DeepJudgeConfig(BaseModel):
    """Configuration for deep reasoning judge."""
    
    model: str = Field(..., description="Reasoning model for complex queries")
    vram_gb: float = Field(..., description="VRAM footprint in GB")
    use_chain_of_thought: bool = Field(default=True, description="Enable CoT reasoning")


class QualityEvalConfig(BaseModel):
    """Configuration for output quality evaluation."""
    
    model: str = Field(..., description="Lightweight quality checker")
    vram_gb: float = Field(..., description="VRAM footprint in GB")
    min_quality_score: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Min score to pass"
    )


class BanditConfig(BaseModel):
    """Configuration for multi-armed bandit router."""
    
    exploration_rate: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Exploration vs exploitation"
    )
    learning_rate: float = Field(
        default=0.05, ge=0.0, le=1.0, description="Update rate for model scores"
    )
    warmup_samples: int = Field(default=100, description="Samples before optimization")


class EscalationConfig(BaseModel):
    """Configuration for auto-escalation."""
    
    enable_escalation: bool = Field(default=True, description="Enable auto-escalation")
    max_escalation_levels: int = Field(default=3, description="Max escalation attempts")
    escalation_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Quality threshold for escalation"
    )


class ComplexityThresholds(BaseModel):
    """Configurable complexity band thresholds (provisional defaults, calibrate on gold set).

    NOTE: Retained for backward compatibility with the legacy fast_triage /
    complexity_classifier path. The new Layer 3 (benchmark-driven kNN router)
    does not use these — see ``Layer3Config`` below.
    """

    trivial_simple: float = Field(default=0.12, description="Score boundary: trivial → simple")
    simple_moderate: float = Field(default=0.30, description="Score boundary: simple → moderate")
    moderate_complex: float = Field(default=0.55, description="Score boundary: moderate → complex")
    complex_expert: float = Field(default=0.80, description="Score boundary: complex → expert")
    boundary_margin: float = Field(
        default=0.05, description="If raw_score is within this margin of a threshold, escalate"
    )
    min_confidence_for_trust: float = Field(
        default=0.55, description="Below this confidence, upgrade tier by one level"
    )


# ============================================================================
# Layer 3 — Benchmark-driven kNN router (the new Layer 3)
# ============================================================================
#
# Every threshold, ratio, TTL, and rate that influences Layer 3 behaviour lives
# here so the router source has zero hardcoded magic numbers. Values can be
# overridden via env vars by the surrounding `Settings` plumbing where useful
# (LAYER3_ENABLED, LAYER3_QUALITY_FLOOR_DEFAULT, etc. — see shared/config.py).


class Layer3VerdictCacheConfig(BaseModel):
    """Stage A — verdict cache settings."""

    enable: bool = Field(default=True, description="Master switch for Stage A")
    persistence_path: str = Field(
        default="artifacts/triage_cache.db",
        description="SQLite path for cross-process cache persistence. Relative "
                    "to repo root.",
    )
    ttl_seconds: float = Field(
        default=168 * 3600.0,  # 7 days
        description="Entries older than this are treated as stale and recomputed.",
    )
    max_entries: int = Field(default=10_000, ge=100)
    semantic_threshold: float = Field(
        default=0.93,
        ge=0.0,
        le=1.0,
        description="Tier-2 Model2Vec cosine similarity threshold for a "
                    "near-duplicate cache hit.",
    )
    semantic_model_name: str = Field(default="minishlab/potion-base-8M")


class Layer3QualityFloorConfig(BaseModel):
    """Quality floor + low-coverage penalty configuration."""

    default: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Base quality floor a model must clear to qualify. Per the "
                    "revised plan §9 this is the pre-committed starting value; "
                    "scripts/calibrate_quality_floor.py auto-tunes after 30 "
                    "days of production telemetry.",
    )
    high_risk: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Elevated floor for medical / legal / financial queries.",
    )
    low_coverage_penalty: float = Field(
        default=0.10,
        ge=0.0,
        le=0.50,
        description="Added to the effective floor when a model is "
                    "coverage_quality=low. Prevents frontier models from "
                    "winning on inflated aggregate priors.",
    )
    floor_ceiling: float = Field(
        default=0.95,
        ge=0.5,
        le=1.0,
        description="Hard ceiling for the effective floor after penalty.",
    )


class Layer3KnnConfig(BaseModel):
    """Stage C — kNN + per-model quality prediction."""

    knn_k: int = Field(default=20, ge=1, le=100)
    min_similarity: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Cosine threshold for a benchmark question to count as a "
                    "neighbor at all.",
    )
    min_neighbors_for_trust: int = Field(
        default=5,
        description="Below this many neighbors, fall to Stage D (off-distribution).",
    )
    min_outcomes_per_model: int = Field(
        default=3,
        description="A model needs at least this many neighbor outcomes to "
                    "use the kNN-weighted prediction; otherwise the aggregate "
                    "prior takes over.",
    )

    # P3 — length-adjusted similarity
    length_adjustment_base: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity multiplier from length adjustment.",
    )
    length_adjustment_range: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Adds up to this amount when query/neighbor lengths match.",
    )


class Layer3ExplorationConfig(BaseModel):
    """P2 — ε-exploration of borderline models."""

    rate: float = Field(
        default=0.015,
        ge=0.0,
        le=0.1,
        description="Fraction of decisions where a borderline model is forced "
                    "for calibration coverage.",
    )
    borderline_band: float = Field(
        default=0.05,
        description="A borderline model is one whose predicted quality is "
                    "within this much below its effective floor.",
    )
    max_observations_for_borderline: int = Field(
        default=30,
        description="Stop exploring a model once it has accumulated this many "
                    "calibration observations in the active feature cell.",
    )


class Layer3WarmupConfig(BaseModel):
    """P4 — warmup period for newly-registered models."""

    max_age_days: int = Field(
        default=30,
        description="A model exits warmup after this many days even if it "
                    "hasn't accumulated enough observations.",
    )
    min_observations_to_exit: int = Field(
        default=100,
        description="A model exits warmup once it has accumulated this many "
                    "Layer-7 observations across all feature cells.",
    )
    forced_selection_rate: float = Field(
        default=0.05,
        ge=0.0,
        le=0.2,
        description="During warmup, this fraction of decisions force a random "
                    "warmup model to be selected (subject to it being in the "
                    "qualifying set — see knn_router.warmup_selection).",
    )


class Layer3CalibrationConfig(BaseModel):
    """Online EMA calibration over Layer-7 observed quality."""

    ema_alpha: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="EMA blend for the multiplier update: new = 0.9*old + α*ratio.",
    )
    confidence_observations_constant: float = Field(
        default=50.0,
        ge=1.0,
        description="Confidence at N observations = 1 - exp(-N/this). 50 means "
                    "a cell needs ~17 observations to reach 0.3 confidence.",
    )
    confidence_threshold_to_apply: float = Field(
        default=0.3,
        description="Multipliers below this confidence are not applied — "
                    "default 1.0 used instead.",
    )
    multiplier_min: float = Field(default=0.5, description="Clamp floor.")
    multiplier_max: float = Field(default=1.5, description="Clamp ceiling.")


class Layer3DriftConfig(BaseModel):
    """Per-class prediction-distribution KL drift detection."""

    kl_info: float = Field(default=0.10, description="Info log only.")
    kl_warn: float = Field(default=0.15, description="Alert + auto-refit temperature.")
    kl_halt: float = Field(default=0.30, description="Freeze auto-calibration; manual review.")
    window_days: int = Field(default=7, description="Rolling window for drift comparison.")


class Layer3EncoderConfig(BaseModel):
    """Stage B encoder used by Stage C (kNN search)."""

    model_name: str = Field(default="BAAI/bge-small-en-v1.5")
    device: Literal["cuda", "cpu"] = Field(
        default="cuda",
        description="Primary inference device. Auto-falls back to CPU+ONNX "
                    "int8 when CUDA unavailable — see knn_router._build_encoder.",
    )
    onnx_fallback_quantization: Literal["fp32", "int8"] = "int8"
    embedding_dim: int = Field(default=384)
    qdrant_collection: str = Field(default="layer3_benchmark_corpus")


class Layer3SuccessTargets(BaseModel):
    """Hard success criteria. Surface as a single dashboard panel."""

    p50_latency_ms: float = 50.0
    p99_latency_ms: float = 200.0
    fallback_rate_max: float = 0.05
    over_routing_rate_max: float = 0.02  # P9
    correctness_lift_pp_min: float = 10.0


class Layer3Config(BaseModel):
    """All Layer 3 settings in one place. No hardcoded numbers in the router."""

    verdict_cache: Layer3VerdictCacheConfig = Field(default_factory=Layer3VerdictCacheConfig)
    quality_floor: Layer3QualityFloorConfig = Field(default_factory=Layer3QualityFloorConfig)
    knn: Layer3KnnConfig = Field(default_factory=Layer3KnnConfig)
    exploration: Layer3ExplorationConfig = Field(default_factory=Layer3ExplorationConfig)
    warmup: Layer3WarmupConfig = Field(default_factory=Layer3WarmupConfig)
    calibration: Layer3CalibrationConfig = Field(default_factory=Layer3CalibrationConfig)
    drift: Layer3DriftConfig = Field(default_factory=Layer3DriftConfig)
    encoder: Layer3EncoderConfig = Field(default_factory=Layer3EncoderConfig)
    success_targets: Layer3SuccessTargets = Field(default_factory=Layer3SuccessTargets)

    registry_path: str = Field(
        default="src/layer0_model_infra/data/registry.json",
        description="Relative to repo root.",
    )
    aggregate_scores_path: str = Field(
        default="src/layer0_model_infra/data/model_aggregate_scores.json",
    )
    rate_limit_blacklist_seconds: int = Field(default=60)


class RoutingPipelineConfig(BaseModel):
    """Complete routing pipeline configuration."""

    environment: Environment

    # Pipeline layers
    fast_path: FastPathConfig = Field(
        default_factory=FastPathConfig,
        description="Layer 0 — Fast Path bypass configuration",
    )
    modality_gate: ModalityGateConfig
    semantic_memory: SemanticMemoryConfig
    fast_triage: FastTriageConfig
    deep_judge: DeepJudgeConfig
    quality_eval: QualityEvalConfig
    bandit: BanditConfig
    escalation: EscalationConfig
    complexity_thresholds: ComplexityThresholds = Field(
        default_factory=ComplexityThresholds,
        description="Complexity band thresholds (provisional defaults)"
    )
    layer3: Layer3Config = Field(
        default_factory=Layer3Config,
        description="Layer 3 — benchmark-driven kNN router configuration",
    )
    
    # Global settings
    enable_semantic_cache: bool = Field(
        default=True, description="Use semantic memory routing"
    )
    enable_uncertainty_estimation: bool = Field(
        default=True, description="Estimate routing confidence"
    )
    enable_test_time_compute: bool = Field(
        default=False, description="Use best-of-N for moderate complexity"
    )
    enable_continuous_learning: bool = Field(
        default=True, description="Log and learn from feedback"
    )


# ==========================================
# DEVELOPMENT CONFIGURATION (Laptop-Friendly)
# ==========================================

DEVELOPMENT_CONFIG = RoutingPipelineConfig(
    environment=Environment.DEVELOPMENT,
    modality_gate=ModalityGateConfig(
        vision_model="ollama-gemma3-4b",
        vram_gb=3.5,
    ),
    semantic_memory=SemanticMemoryConfig(
        embedding_model="ollama/qwen3-embedding:0.6b",  # 2026 upgrade: multilingual, instruction-aware
        vector_db="qdrant",
        similarity_threshold=0.85,
        max_cache_age_days=30,
    ),
    fast_triage=FastTriageConfig(
        model="groq-llama-3.3-70b-free",
        vram_gb=0.0,
        max_tokens=500,
    ),
    deep_judge=DeepJudgeConfig(
        model="ollama/deepseek-r1:7b",
        vram_gb=5.0,
        use_chain_of_thought=True,
    ),
    quality_eval=QualityEvalConfig(
        model="ollama-phi4-mini-reasoning-3.8b",
        vram_gb=3.2,
        min_quality_score=0.7,
    ),
    bandit=BanditConfig(
        exploration_rate=0.15,  # Higher exploration in dev
        learning_rate=0.05,
        warmup_samples=50,  # Faster warmup in dev
    ),
    escalation=EscalationConfig(
        enable_escalation=True,
        max_escalation_levels=3,
        escalation_threshold=0.6,
    ),
    enable_semantic_cache=True,
    enable_uncertainty_estimation=True,
    enable_test_time_compute=False,  # Disabled in dev for speed
    enable_continuous_learning=True,
)


# ==========================================
# PRODUCTION CONFIGURATION (Cloud-Optimized)
# ==========================================

PRODUCTION_CONFIG = RoutingPipelineConfig(
    environment=Environment.PRODUCTION,
    modality_gate=ModalityGateConfig(
        vision_model="qwen/qwen3-vl-7b",
        vram_gb=14.0,
    ),
    semantic_memory=SemanticMemoryConfig(
        embedding_model="ollama/qwen3-embedding:0.6b",  # 2026 upgrade: multilingual, instruction-aware
        vector_db="milvus",  # Production-grade vector DB
        similarity_threshold=0.90,  # Stricter in production
        max_cache_age_days=60,
    ),
    fast_triage=FastTriageConfig(
        model="google/gemma-3-12b",
        vram_gb=24.0,
        max_tokens=500,
    ),
    deep_judge=DeepJudgeConfig(
        model="deepseek/deepseek-r1-70b",
        vram_gb=140.0,
        use_chain_of_thought=True,
    ),
    quality_eval=QualityEvalConfig(
        model="meta/llama-4-scout-17b",
        vram_gb=34.0,
        min_quality_score=0.8,
    ),
    bandit=BanditConfig(
        exploration_rate=0.05,  # Lower exploration in production
        learning_rate=0.02,
        warmup_samples=1000,
    ),
    escalation=EscalationConfig(
        enable_escalation=True,
        max_escalation_levels=3,
        escalation_threshold=0.7,
    ),
    enable_semantic_cache=True,
    enable_uncertainty_estimation=True,
    enable_test_time_compute=True,  # Enabled in production
    enable_continuous_learning=True,
)


def get_routing_config() -> RoutingPipelineConfig:
    """
    Get routing configuration based on environment.
    
    Returns:
        Routing pipeline configuration
    """
    if settings.ENVIRONMENT == "production":
        return PRODUCTION_CONFIG
    else:
        return DEVELOPMENT_CONFIG
