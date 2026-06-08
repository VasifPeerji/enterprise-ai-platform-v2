"""
📁 File: tests/test_elite_pipeline.py
Purpose: Comprehensive unit + integration tests for the full Phase 2 pipeline
Scope:  Every module, every edge case, every signal pathway

Run:  pytest tests/test_elite_pipeline.py -v
      (no external services needed – all heuristic-based)
"""

import sys, os, math, time

# ---------------------------------------------------------------------------
# Bootstrap: make sure 'src' is importable regardless of cwd
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Stub out heavy deps that won't be present in CI / sandbox
import types

# pydantic – real or stub
try:
    import pydantic  # noqa: F401
except ImportError:
    # Minimal stub so BaseModel / Field work for pure-logic tests
    class _Field:
        def __call__(self, *a, **kw): return kw.get("default")
    class _BaseModel:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
        def model_dump(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = _BaseModel
    pydantic.Field = _Field()
    sys.modules["pydantic"] = pydantic

# structlog stub
if "structlog" not in sys.modules:
    structlog = types.ModuleType("structlog")
    class _NullLogger:
        def __getattr__(self, n):
            return lambda *a, **kw: None
    structlog.get_logger = lambda *a, **kw: _NullLogger()
    structlog.contextvars = types.ModuleType("structlog.contextvars")
    structlog.contextvars.merge_contextvars = lambda l, m, e: e
    structlog.contextvars.clear_contextvars = lambda: None
    structlog.contextvars.bind_contextvars = lambda **kw: None
    structlog.contextvars.unbind_contextvars = lambda *k: None
    structlog.stdlib = types.ModuleType("structlog.stdlib")
    structlog.stdlib.add_logger_name = lambda l, m, e: e
    structlog.stdlib.add_log_level = lambda l, m, e: e
    structlog.stdlib.BoundLogger = _NullLogger
    structlog.stdlib.LoggerFactory = lambda: None
    structlog.processors = types.ModuleType("structlog.processors")
    structlog.processors.TimeStamper = lambda **kw: (lambda l, m, e: e)
    structlog.processors.StackInfoRenderer = lambda: (lambda l, m, e: e)
    structlog.processors.format_exc_info = lambda l, m, e: e
    structlog.processors.JSONRenderer = lambda: (lambda l, m, e: e)
    structlog.dev = types.ModuleType("structlog.dev")
    structlog.dev.ConsoleRenderer = lambda **kw: (lambda l, m, e: e)
    structlog.configure = lambda **kw: None
    sys.modules["structlog"] = structlog
    sys.modules["structlog.contextvars"] = structlog.contextvars
    sys.modules["structlog.stdlib"] = structlog.stdlib
    sys.modules["structlog.processors"] = structlog.processors
    sys.modules["structlog.dev"] = structlog.dev

# pydantic_settings stub
if "pydantic_settings" not in sys.modules:
    pydantic_settings = types.ModuleType("pydantic_settings")
    pydantic_settings.BaseSettings = type("BaseSettings", (), {
        "__init__": lambda self, **kw: None,
        "model_config": {},
    })
    pydantic_settings.SettingsConfigDict = lambda **kw: kw
    sys.modules["pydantic_settings"] = pydantic_settings

# litellm stub
if "litellm" not in sys.modules:
    litellm = types.ModuleType("litellm")
    litellm.telemetry = False
    litellm.drop_params = True
    litellm.set_verbose = False
    litellm.Timeout = Exception
    litellm.RateLimitError = Exception
    litellm.acompletion = None
    litellm.aembedding = None
    sys.modules["litellm"] = litellm

import pytest


# ===========================================================================
# 1.  FAST PATH
# ===========================================================================

class TestFastPath:
    """Every branch of FastPathAnalyzer (Layer 0 — true bypass, multilingual)."""

    def _get(self):
        from src.layer0_model_infra.routing.fast_path import FastPathAnalyzer
        return FastPathAnalyzer()

    def test_greeting_bypasses(self):
        fp = self._get()
        for g in ["hi", "hello", "hey", "good morning"]:
            d = fp.analyze(g)
            assert d.should_bypass is True, f"greeting '{g}' should bypass"
            # Resolved model must come from the configured chat_chain.
            # Default chain leads with groq-llama-3.1-8b-free (free tier).
            assert d.recommended_model == "groq-llama-3.1-8b-free"
            assert d.category.value == "trivial_greeting"

    def test_acknowledgment_bypasses(self):
        fp = self._get()
        for a in ["thanks", "ok", "got it", "understood"]:
            d = fp.analyze(a)
            assert d.should_bypass is True, f"ack '{a}' should bypass"
            assert d.category.value == "trivial_acknowledgment"

    def test_farewell_bypasses(self):
        fp = self._get()
        for a in ["bye", "goodbye", "cya"]:
            d = fp.analyze(a)
            assert d.should_bypass is True, f"farewell '{a}' should bypass"
            assert d.category.value == "trivial_farewell"

    def test_short_meaningless_does_not_bypass(self):
        """The old 'very short query without ?/.' heuristic falsely bypassed
        legitimate support questions like 'login broken' and 'docker oom'.
        Layer 0 no longer bypasses on length alone — only on category match."""
        fp = self._get()
        for short in ["quick", "login broken", "docker oom", "deploy failed"]:
            d = fp.analyze(short)
            assert d.should_bypass is False, (
                f"'{short}' should NOT bypass — full pipeline must classify it"
            )

    def test_greeting_with_attached_punctuation_still_bypasses(self):
        """Layer 0 now strips trailing punctuation when tokenising, so 'hi?',
        'hello!', 'hey…' all resolve to the underlying greeting token. This is
        the correct behaviour — they are greetings, not real questions."""
        fp = self._get()
        for q in ["hi?", "hello!", "hey.", "hi!!"]:
            d = fp.analyze(q)
            assert d.should_bypass is True, f"'{q}' should bypass — it's a greeting variant"

    def test_simple_factual_capital(self):
        fp = self._get()
        d = fp.analyze("What's the capital of France")
        assert d.should_bypass is True
        # Resolved from factual_chain (default leads with groq-llama-3.1-8b-free)
        assert d.recommended_model == "groq-llama-3.1-8b-free"
        assert d.category.value == "simple_factual"

    def test_complex_query_does_not_bypass(self):
        fp = self._get()
        d = fp.analyze("Explain the trade-offs between microservices and monoliths in detail.")
        assert d.should_bypass is False

    def test_math_pattern(self):
        fp = self._get()
        for q in ["what is 7+3", "calculate 5*7", "2+2", "(5 + 3) * 2"]:
            d = fp.analyze(q)
            assert d.should_bypass is True, f"arithmetic '{q}' should bypass"
            assert d.category.value == "pure_arithmetic"

    def test_arithmetic_with_letters_does_not_bypass(self):
        """Math word problems must NOT match the arithmetic fast path."""
        fp = self._get()
        d = fp.analyze("If Alice has 5 apples and Bob has 3, how many do they have?")
        assert d.should_bypass is False

    # ── Multilingual coverage ─────────────────────────────────────────────

    def test_spanish_greetings_bypass(self):
        fp = self._get()
        for g in ["hola", "gracias", "adios"]:
            d = fp.analyze(g)
            assert d.should_bypass is True, f"Spanish '{g}' should bypass"
            assert d.detected_language in {"es", "fr", "pt"}  # some tokens overlap

    def test_french_greetings_bypass(self):
        fp = self._get()
        for g in ["bonjour", "merci", "au revoir"]:
            d = fp.analyze(g)
            assert d.should_bypass is True, f"French '{g}' should bypass"

    def test_devanagari_greeting_bypasses(self):
        fp = self._get()
        d = fp.analyze("नमस्ते")
        assert d.should_bypass is True
        assert d.detected_language == "hi"

    def test_chinese_greeting_bypasses(self):
        fp = self._get()
        d = fp.analyze("你好")
        assert d.should_bypass is True

    # ── Provenance / decision shape ───────────────────────────────────────

    def test_decision_includes_fallback_chain(self):
        fp = self._get()
        d = fp.analyze("hi")
        assert isinstance(d.fallback_chain, list) and len(d.fallback_chain) >= 1
        assert d.recommended_model in d.fallback_chain

    def test_decision_includes_matched_pattern(self):
        fp = self._get()
        d = fp.analyze("hi")
        assert d.matched_pattern is not None and "token" in d.matched_pattern

    def test_no_bypass_decision_has_empty_chain(self):
        fp = self._get()
        d = fp.analyze("Explain the CAP theorem")
        assert d.should_bypass is False
        assert d.recommended_model is None
        assert d.fallback_chain == []


# ===========================================================================
# 2.  INPUT SIGNALS
# ===========================================================================

class TestInputSignals:
    def _get(self):
        from src.layer0_model_infra.routing.input_signals import InputSignalExtractor
        return InputSignalExtractor()

    def test_basic_counts(self):
        ext = self._get()
        s = ext.extract("Hello world. How are you?")
        assert s.word_count == 5
        assert s.question_count == 1

    def test_code_block_detection(self):
        ext = self._get()
        s = ext.extract("Here is code:\n```python\nprint('hi')\n```\nDone.")
        assert s.has_code_blocks is True
        assert s.code_block_count == 1

    def test_multi_part_via_keywords(self):
        ext = self._get()
        s = ext.extract("First do X, then do Y, and also Z.")
        assert s.has_multi_part is True

    def test_constraint_detection(self):
        ext = self._get()
        s = ext.extract("Write it without using recursion, must be O(n).")
        assert s.has_constraints is True

    def test_json_request_flag(self):
        ext = self._get()
        s = ext.extract("Return the data as JSON please.")
        assert s.requests_json is True

    def test_difficulty_range(self):
        ext = self._get()
        s = ext.extract("hi")
        assert 0.0 <= s.overall_difficulty <= 1.0


# ===========================================================================
# 3.  SEMANTIC MEMORY
# ===========================================================================

class TestSemanticMemory:
    def _get(self):
        from src.layer0_model_infra.routing.semantic_memory import SemanticMemory
        # Disable persistence + local embedding so this fixture matches the
        # legacy char-ngram-calibrated test semantics (sim_threshold=0.6,
        # half_life=3600s). The persistence/embedding paths are exercised by
        # the dedicated tests/layer0_model_infra/test_semantic_memory.py fixtures.
        return SemanticMemory(
            similarity_threshold=0.6,
            decay_half_life_seconds=3600,
            enable_local_embedding=False,
            enable_persistence=False,
        )

    def test_empty_cache_is_novel(self):
        mem = self._get()
        r = mem.lookup("brand new query")
        assert r.hit is False
        assert r.novelty_score == 1.0

    def test_record_and_hit(self):
        mem = self._get()
        mem.record(
            query="how do I sort a list in python",
            model_id="ollama-llama3.1-8b",
            quality_score=0.9,
            escalated=False,
        )
        r = mem.lookup("how do I sort a list in python")
        assert r.hit is True
        assert r.matched_model_id == "ollama-llama3.1-8b"

    def test_bad_quality_not_reusable(self):
        mem = self._get()
        mem.record(
            query="bad quality example query here",
            model_id="ollama-phi3-mini",
            quality_score=0.3,   # below 0.7
            escalated=False,
        )
        r = mem.lookup("bad quality example query here")
        assert r.hit is False   # not reusable

    def test_escalated_not_reusable(self):
        mem = self._get()
        mem.record(
            query="escalated example query test",
            model_id="gpt-3.5-turbo",
            quality_score=0.8,
            escalated=True,      # escalated → not reusable
        )
        r = mem.lookup("escalated example query test")
        assert r.hit is False

    def test_novelty_decreases_with_similar_entries(self):
        mem = self._get()
        mem.record(query="the quick brown fox jumps", model_id="m1", quality_score=0.8, escalated=False)
        r = mem.lookup("the quick brown fox runs")   # high overlap
        assert r.novelty_score < 1.0                 # less novel than empty cache

    def test_decay_reduces_similarity(self):
        mem = self._get()
        # Manually inject an old entry
        from src.layer0_model_infra.routing.semantic_memory import MemoryEntry
        old_entry = MemoryEntry(
            query_signature="old stale cached query example",
            model_id="ollama-mistral-7b",
            quality_score=0.9,
            escalated=False,
            timestamp=time.time() - 7200,   # 2 hours ago, half-life 1 hour
        )
        mem._store.append(old_entry)
        r = mem.lookup("old stale cached query example")
        # Decay factor after 2 half-lives = 0.25, so sim*0.25 < threshold
        assert r.hit is False

    def test_max_entries_eviction(self):
        mem = self._get()
        mem.max_entries = 3
        for i in range(5):
            mem.record(query=f"query number {i} unique", model_id="m", quality_score=0.9, escalated=False)
        assert len(mem._store) == 3   # capped

    def test_stats(self):
        mem = self._get()
        mem.record(query="good one here", model_id="m1", quality_score=0.9, escalated=False)
        mem.record(query="bad one here", model_id="m2", quality_score=0.2, escalated=False)
        s = mem.stats()
        assert s["total_entries"] == 2
        assert s["reusable_entries"] == 1


# ===========================================================================
# 4.  MODALITY GATE
# ===========================================================================

class TestModalityGate:
    def _get(self):
        from src.layer0_model_infra.routing.modality_gate import ModalityGate
        return ModalityGate()

    def test_text_only(self):
        mg = self._get()
        a = mg.analyze("Tell me about Python")
        assert a.primary_modality.value == "text_only"
        assert a.requires_vision is False

    def test_image_detected(self):
        mg = self._get()
        a = mg.analyze("Describe this image", has_images=True, image_count=1)
        assert a.requires_vision is True

    def test_code_heavy(self):
        mg = self._get()
        code = "```python\ndef foo():\n    pass\n```\nimport os\nfrom sys import argv\n"
        a = mg.analyze(code)
        assert a.requires_code_model is True or a.primary_modality.value == "code_heavy"


# ===========================================================================
# 5.  FAST TRIAGE  (including ambiguity flags)
# ===========================================================================

class TestFastTriage:
    def _get(self):
        from src.layer0_model_infra.routing.legacy.fast_triage import FastTriageClassifier
        return FastTriageClassifier()

    def test_basic_classification(self):
        tc = self._get()
        r = tc.classify("What is machine learning?")
        assert r.intent.value in ("qa", "technical")
        assert 0 < r.confidence <= 1.0

    def test_coding_intent(self):
        tc = self._get()
        r = tc.classify("Write a Python function to sort a list")
        assert r.intent.value == "coding"

    def test_multi_intent_flag(self):
        tc = self._get()
        r = tc.classify("Write the code and also explain how it works")
        assert r.ambiguity.is_multi_intent is True

    def test_vague_flag(self):
        tc = self._get()
        r = tc.classify("I want something kind of like a summary maybe")
        assert r.ambiguity.is_vague is True

    def test_underspecified_flag(self):
        tc = self._get()
        r = tc.classify("help me fix this")
        assert r.ambiguity.is_underspecified is True

    def test_ambiguity_lowers_confidence(self):
        tc = self._get()
        clean = tc.classify("Explain the concept of recursion in detail.")
        vague = tc.classify("help me with something kind of important")
        # vague query should have lower confidence
        assert vague.confidence <= clean.confidence

    def test_trivial_complexity(self):
        tc = self._get()
        r = tc.classify("hi")
        assert r.complexity_band.value == "trivial"

    def test_expert_complexity(self):
        tc = self._get()
        r = tc.classify("Prove the completeness theorem for first-order logic.")
        assert r.complexity_band.value == "expert"

    def test_medical_domain(self):
        tc = self._get()
        r = tc.classify("What is the treatment for hypertension?")
        assert r.domain.value == "medical"


# ===========================================================================
# 6.  UNCERTAINTY ESTIMATOR  (7-signal)
# ===========================================================================

class TestUncertaintyEstimator:
    def _get(self):
        from src.layer0_model_infra.routing.legacy.uncertainty_estimator import UncertaintyEstimator
        return UncertaintyEstimator()

    def test_clear_query_low_uncertainty(self):
        ue = self._get()
        s = ue.estimate(
            query="What is 2 + 2?",
            classifier_confidence=0.95,
            query_length=5,
            novelty_score=0.0,
            input_signals={"has_multi_part": False, "has_technical_terms": False, "has_constraints": False},
            domain_risk=0.1,
        )
        assert s.total_uncertainty < 0.4
        assert s.confidence_level == "HIGH"

    def test_high_novelty_raises_uncertainty(self):
        ue = self._get()
        s = ue.estimate(
            query="Explain quantum decoherence in simple terms",
            classifier_confidence=0.6,
            novelty_score=0.9,           # very novel
            input_signals={"has_multi_part": False, "has_technical_terms": True, "has_constraints": False},
            domain_risk=0.5,
        )
        assert s.total_uncertainty > 0.2

    def test_high_domain_risk_raises_uncertainty(self):
        ue = self._get()
        s = ue.estimate(
            query="Should I take ibuprofen with metformin?",
            classifier_confidence=0.7,
            domain_risk=0.9,             # medical
            input_signals={"has_multi_part": False, "has_technical_terms": False, "has_constraints": False},
        )
        # domain_risk=0.9 → domain_risk_uncertainty=0.45, weight=0.10 → +0.045
        # classifier_confidence=0.7 → classifier_uncertainty=0.3, weight=0.20 → +0.06
        # total should be meaningfully above zero
        assert s.total_uncertainty > 0.08, f"Expected >0.08, got {s.total_uncertainty}"

    def test_multi_part_raises_structure_uncertainty(self):
        ue = self._get()
        base = ue.estimate(
            query="First explain X, then compare it to Y, finally give pros and cons",
            classifier_confidence=0.5,
            input_signals={"has_multi_part": False, "has_technical_terms": False, "has_constraints": False},
            domain_risk=0.3,
        )
        multi = ue.estimate(
            query="First explain X, then compare it to Y, finally give pros and cons",
            classifier_confidence=0.5,
            input_signals={"has_multi_part": True, "has_technical_terms": True, "has_constraints": True},
            domain_risk=0.3,
        )
        # Structure signals (multi_part + technical + constraints) must raise uncertainty
        assert multi.total_uncertainty > base.total_uncertainty, \
            f"multi={multi.total_uncertainty:.4f} should > base={base.total_uncertainty:.4f}"

    def test_confidence_levels_are_valid(self):
        ue = self._get()
        for conf in [0.9, 0.5, 0.1]:
            s = ue.estimate(query="test query here", classifier_confidence=conf)
            assert s.confidence_level in ("HIGH", "MEDIUM", "LOW")


# ===========================================================================
# 7.  TEST-TIME COMPUTE
# ===========================================================================

class TestTestTimeCompute:
    def _get(self):
        from src.layer0_model_infra.routing.test_time_compute import TestTimeComputeEngine
        return TestTimeComputeEngine()

    def test_trivial_complexity_no_ttc(self):
        ttc = self._get()
        d = ttc.should_use_ttc(uncertainty_score=0.5, complexity_band="trivial", user_tier="standard", domain="general")
        assert d.should_use is False

    def test_expert_complexity_no_ttc(self):
        ttc = self._get()
        d = ttc.should_use_ttc(uncertainty_score=0.5, complexity_band="expert", user_tier="standard", domain="general")
        assert d.should_use is False

    def test_low_uncertainty_no_ttc(self):
        ttc = self._get()
        d = ttc.should_use_ttc(uncertainty_score=0.1, complexity_band="moderate", user_tier="standard", domain="general")
        assert d.should_use is False   # high confidence, single sample sufficient

    def test_high_uncertainty_no_ttc(self):
        ttc = self._get()
        d = ttc.should_use_ttc(uncertainty_score=0.9, complexity_band="moderate", user_tier="standard", domain="general")
        assert d.should_use is False   # too uncertain, escalation preferred

    def test_moderate_uncertainty_runs_ttc(self):
        ttc = self._get()
        d = ttc.should_use_ttc(uncertainty_score=0.5, complexity_band="moderate", user_tier="standard", domain="general")
        assert d.should_use is True
        assert d.num_samples >= 1

    def test_premium_gets_at_least_as_many_samples(self):
        ttc = self._get()
        std  = ttc.should_use_ttc(uncertainty_score=0.5, complexity_band="moderate", user_tier="standard", domain="general")
        prem = ttc.should_use_ttc(uncertainty_score=0.5, complexity_band="moderate", user_tier="premium", domain="general")
        if std.should_use and prem.should_use:
            assert prem.num_samples >= std.num_samples


# ===========================================================================
# 8.  DOMAIN POLICIES
# ===========================================================================

class TestDomainPolicies:
    def test_medical_is_strict(self):
        from src.layer0_model_infra.config.domain_policies import get_domain_policy
        p = get_domain_policy("medical")
        assert p.min_quality_threshold >= 0.80
        assert p.always_evaluate_quality is True
        assert p.prefer_cost_optimization is False

    def test_casual_is_lenient(self):
        from src.layer0_model_infra.config.domain_policies import get_domain_policy
        p = get_domain_policy("casual")
        assert p.min_quality_threshold <= 0.55
        assert p.prefer_cost_optimization is True
        assert p.enable_test_time_compute is False

    def test_unknown_domain_falls_back_to_general(self):
        from src.layer0_model_infra.config.domain_policies import get_domain_policy, DOMAIN_POLICIES
        p = get_domain_policy("xyzzy_not_a_real_domain")
        assert p is DOMAIN_POLICIES["general"]

    def test_all_domains_have_valid_ranges(self):
        from src.layer0_model_infra.config.domain_policies import DOMAIN_POLICIES
        for name, p in DOMAIN_POLICIES.items():
            assert 0.0 <= p.min_quality_threshold <= 1.0,            f"{name}: bad threshold"
            assert 0 <= p.max_escalation_attempts <= 5,             f"{name}: bad esc attempts"
            assert 0.0 <= p.min_uncertainty_for_safe_routing <= 1.0, f"{name}: bad uncertainty"


# ===========================================================================
# 9.  LATENCY BUDGET
# ===========================================================================

class TestLatencyBudget:
    def test_initial_remaining(self):
        from src.layer2_orchestrator.latency_budget import LatencyBudget
        b = LatencyBudget(total_budget_ms=5000)
        assert b.remaining_ms == 5000   # nothing consumed yet

    def test_record_layer_tracks_breakdown(self):
        from src.layer2_orchestrator.latency_budget import LatencyBudget
        b = LatencyBudget(total_budget_ms=5000)
        b.record_layer("test_layer", 12.0)
        assert b.consumed_ms == 12.0
        assert b.layer_breakdown["test_layer"] == 12.0
        assert b.remaining_ms == 4988.0

    def test_is_exhausted_when_depleted(self):
        from src.layer2_orchestrator.latency_budget import LatencyBudget
        b = LatencyBudget(total_budget_ms=50)
        b.record_layer("slow", 60.0)   # over budget
        assert b.is_exhausted is True
        assert b.remaining_ms == 0

    def test_utilization_percent(self):
        from src.layer2_orchestrator.latency_budget import LatencyBudget
        b = LatencyBudget(total_budget_ms=1000)
        b.record_layer("a", 250.0)
        assert b.utilization_percent == 25.0
        assert "a" in b.layer_breakdown


# ===========================================================================
# 10. ESCALATION ENGINE  (cooldown)
# ===========================================================================

class TestEscalationEngine:
    def _get(self):
        from src.layer0_model_infra.routing.escalation_engine import EscalationEngine
        return EscalationEngine()

    def test_should_escalate_on_refusal(self):
        ee = self._get()
        assert ee.should_escalate(quality_score=0.9, refusal_detected=True) is True

    def test_should_not_escalate_on_high_quality(self):
        ee = self._get()
        assert ee.should_escalate(quality_score=0.95, refusal_detected=False) is False


# ===========================================================================
# 11. QUALITY EVALUATOR
# ===========================================================================

class TestQualityEvaluator:
    def _get(self):
        from src.layer0_model_infra.routing.quality_evaluator import QualityEvaluator
        return QualityEvaluator()

    def test_good_response_passes(self):
        qe = self._get()
        q = qe.evaluate(
            response="Machine learning is a subset of AI that enables systems to learn from data.",
            query="What is machine learning?",
            model_id="test",
        )
        assert q.overall_quality >= 0.6
        assert q.refusal_detected is False

    def test_refusal_detected(self):
        qe = self._get()
        q = qe.evaluate(
            response="I cannot help with that request as an AI language model.",
            query="Tell me something",
            model_id="test",
        )
        assert q.refusal_detected is True
        assert q.overall_quality == 0.0

    def test_very_short_response_low_completeness(self):
        qe = self._get()
        q = qe.evaluate(response="ok", query="Explain quantum entanglement.", model_id="test")
        assert q.completeness_score < 0.5

    def test_truncated_response_detected(self):
        qe = self._get()
        q = qe.evaluate(
            response="The algorithm works by first sorting the array and then applying binary search...",
            query="Explain binary search",
            model_id="test",
        )
        # Ends with "..." → completeness < 1.0
        assert q.completeness_score < 1.0


# ===========================================================================
# 12. BANDIT ROUTER
# ===========================================================================

class TestBanditRouter:
    def _get(self):
        from src.layer0_model_infra.routing.legacy.bandit_router import BanditRouter, BanditContext
        from src.layer0_model_infra.routing.legacy.fast_triage import Intent, Domain, ComplexityBand
        br = BanditRouter()
        br.arms = {}            # start clean (ignore any persisted bandit state)
        br.total_pulls = 0
        br.warmup_samples = 0   # skip warmup for testing
        return br, Intent, Domain, ComplexityBand

    def _ctx(self, Intent, Domain, ComplexityBand, **overrides):
        from src.layer0_model_infra.routing.legacy.bandit_router import BanditContext
        defaults = dict(
            intent=Intent.QA,
            domain=Domain.TECH,
            complexity_band=ComplexityBand.SIMPLE,
            uncertainty_score=0.3,
        )
        defaults.update(overrides)
        return BanditContext(**defaults)

    def test_select_returns_valid_model(self):
        br, I, D, C = self._get()
        ctx = self._ctx(I, D, C)
        models = ["model-a", "model-b", "model-c"]
        chosen = br.select_model(ctx, models)
        assert chosen in models

    def test_reward_update_tracks_escalation(self):
        br, I, D, C = self._get()
        ctx = self._ctx(I, D, C)
        br.select_model(ctx, ["model-a"])
        br.update_reward(ctx, "model-a", quality_score=0.5, cost=0.01, escalated=True)
        arm = br.arms[ctx.to_key()]["model-a"]
        assert arm.escalation_count == 1
        assert arm.escalation_rate > 0   # escalated at least once

    def test_escalation_penalty_in_reward(self):
        br, I, D, C = self._get()
        ctx = self._ctx(I, D, C)
        br.select_model(ctx, ["model-a", "model-b"])
        # model-a: good quality, no escalation
        br.update_reward(ctx, "model-a", quality_score=0.9, cost=0.01, escalated=False)
        # model-b: same quality, but escalated
        br.update_reward(ctx, "model-b", quality_score=0.9, cost=0.01, escalated=True)
        arm_a = br.arms[ctx.to_key()]["model-a"]
        arm_b = br.arms[ctx.to_key()]["model-b"]
        assert arm_a.avg_reward > arm_b.avg_reward   # escalation penalty

    def test_adaptive_exploration_on_escalations(self):
        br, I, D, C = self._get()
        br.exploration_rate = 1.0   # force explore
        ctx = self._ctx(I, D, C, session_escalation_count=5)
        # With 5 escalations, adjusted rate should be halved → 0.5
        # We can't easily test randomness, but at least verify no crash
        chosen = br.select_model(ctx, ["m1", "m2"])
        assert chosen in ["m1", "m2"]

    def test_stats(self):
        br, I, D, C = self._get()
        ctx = self._ctx(I, D, C)
        br.select_model(ctx, ["m1"])
        br.update_reward(ctx, "m1", 0.8, 0.01, escalated=True)
        s = br.get_stats()
        assert s["total_pulls"] == 1
        assert s["total_escalations"] == 1


# ===========================================================================
# 13. FULL ROUTER  (integration: route() end-to-end)
# ===========================================================================

class TestFullRouterIntegration:
    """
    Integration tests that exercise the complete route() path.
    No LLM calls – purely the pre-LLM pipeline.
    """

    def _get_router(self):
        # Reset singletons so each test is clean
        import src.layer0_model_infra.router as rm
        rm._router = None
        from src.layer0_model_infra.router import ModelRouter
        return ModelRouter()

    def test_force_model_short_circuits(self):
        router = self._get_router()
        d = router.route("anything", force_model_id="gpt-3.5-turbo")
        assert d.selected_model.model_id == "gpt-3.5-turbo"
        assert d.confidence_level == "N/A"
        assert d.escalation_path_available is False

    def test_code_query_detects_code_modality(self):
        router = self._get_router()
        d = router.route("```python\ndef binary_search(arr, target):\n    pass\n```\nFix this function")
        assert d.modality_analysis.get("requires_code_model") is True or \
               d.modality_analysis.get("primary_modality") == "code_heavy"

    def test_model_not_found_raises(self):
        router = self._get_router()
        with pytest.raises(Exception):   # ModelNotFoundError
            router.route("test", force_model_id="nonexistent-model-xyz")


# ===========================================================================
# 14. EDGE CASES & REGRESSION GUARDS
# ===========================================================================

class TestEdgeCases:
    def test_empty_string_does_not_crash(self):
        # FastPath returns no-bypass on empty input; the full pipeline
        # downstream is responsible for empty-query handling.
        from src.layer0_model_infra.routing.fast_path import FastPathAnalyzer
        fp = FastPathAnalyzer()
        d = fp.analyze("")
        assert d.should_bypass is False
        assert d.recommended_model is None

    def test_unicode_query_does_not_crash(self):
        from src.layer0_model_infra.routing.input_signals import InputSignalExtractor
        ext = InputSignalExtractor()
        s = ext.extract("Cómo funciona el aprendizaje automático? 日本語テスト 🤖")
        assert s.word_count > 0

    def test_very_long_query(self):
        from src.layer0_model_infra.routing.input_signals import InputSignalExtractor
        ext = InputSignalExtractor()
        long_q = "word " * 5000
        s = ext.extract(long_q)
        assert s.word_count == 5000
        assert s.length_score == 0.95   # very long → 0.95

    def test_similarity_empty_strings(self):
        from src.layer0_model_infra.routing.semantic_memory import SemanticMemory
        mem = SemanticMemory()
        assert mem._similarity("", "") == 0.0
        assert mem._similarity("hello", "") == 0.0

    def test_decay_factor_fresh_entry(self):
        from src.layer0_model_infra.routing.semantic_memory import SemanticMemory
        mem = SemanticMemory(decay_half_life_seconds=3600)
        now = time.time()
        factor = mem._decay_factor(now, now)
        assert abs(factor - 1.0) < 0.001, f"Expected ~1.0, got {factor}"

    def test_decay_factor_one_half_life(self):
        from src.layer0_model_infra.routing.semantic_memory import SemanticMemory
        mem = SemanticMemory(decay_half_life_seconds=3600)
        factor = mem._decay_factor(time.time() - 3600, time.time())
        assert abs(factor - 0.5) < 0.01

    def test_bandit_arm_properties_when_zero_pulls(self):
        from src.layer0_model_infra.routing.legacy.bandit_router import BanditArm
        arm = BanditArm(model_id="test")
        assert arm.success_rate == 0.5   # neutral default
        assert arm.escalation_rate == 0.0
        assert arm.avg_reward == 0.0


# ===========================================================================
# 15. CROSS-MODULE SIGNAL FLOW
# ===========================================================================

class TestSignalFlow:
    """Verify that signals from early layers actually reach later layers."""

    def test_input_signals_feed_uncertainty(self):
        """InputSignals.has_multi_part should raise structure_uncertainty."""
        from src.layer0_model_infra.routing.legacy.uncertainty_estimator import UncertaintyEstimator
        ue = UncertaintyEstimator()
        base = ue.estimate(
            query="simple question",
            input_signals={"has_multi_part": False, "has_technical_terms": False, "has_constraints": False},
        )
        multi = ue.estimate(
            query="simple question",
            input_signals={"has_multi_part": True, "has_technical_terms": True, "has_constraints": True},
        )
        assert multi.total_uncertainty > base.total_uncertainty

    def test_novelty_feeds_uncertainty(self):
        from src.layer0_model_infra.routing.legacy.uncertainty_estimator import UncertaintyEstimator
        ue = UncertaintyEstimator()
        known = ue.estimate(query="test", novelty_score=0.1)
        novel = ue.estimate(query="test", novelty_score=0.95)
        assert novel.total_uncertainty > known.total_uncertainty

    def test_domain_risk_feeds_uncertainty(self):
        from src.layer0_model_infra.routing.legacy.uncertainty_estimator import UncertaintyEstimator
        ue = UncertaintyEstimator()
        low  = ue.estimate(query="test", domain_risk=0.1)
        high = ue.estimate(query="test", domain_risk=0.9)
        assert high.total_uncertainty > low.total_uncertainty

    def test_triage_confidence_feeds_uncertainty(self):
        from src.layer0_model_infra.routing.legacy.uncertainty_estimator import UncertaintyEstimator
        ue = UncertaintyEstimator()
        conf  = ue.estimate(query="test", classifier_confidence=0.95)
        unconf = ue.estimate(query="test", classifier_confidence=0.2)
        assert unconf.total_uncertainty > conf.total_uncertainty