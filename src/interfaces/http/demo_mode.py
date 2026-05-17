"""
Demo-mode helpers for presentation-safe simulation.

This module lets the app:
- execute requests on free/local backing models,
- simulate commercial model tiers with transparent labels,
- maintain a mock wallet per demo session.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from threading import Lock
from typing import Optional

from src.layer0_model_infra.router import RoutingDecision
from src.layer0_model_infra.registry import get_registry
from src.shared.config import get_settings

settings = get_settings()
registry = get_registry()


@dataclass(frozen=True)
class DemoProfile:
    """Commercial model profile simulated during demos."""

    profile_id: str
    tier: str
    family: str
    display_name: str
    provider: str
    input_cost_per_1m_tokens: float
    output_cost_per_1m_tokens: float
    best_for: str
    backing_model_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["backing_model_display_names"] = [
            registry.get_model(model_id).display_name for model_id in self.backing_model_ids
        ]
        data["primary_backing_model_id"] = self.backing_model_ids[0]
        return data


class DemoWalletManager:
    """Simple in-memory wallet for presentation sessions."""

    def __init__(self, initial_balance_usd: float) -> None:
        self._initial_balance_usd = initial_balance_usd
        self._wallets: dict[str, float] = {}
        self._lock = Lock()

    def get_balance(self, session_id: str) -> float:
        with self._lock:
            return round(self._wallets.setdefault(session_id, self._initial_balance_usd), 6)

    def charge(self, session_id: str, amount_usd: float) -> dict[str, float]:
        with self._lock:
            before = self._wallets.setdefault(session_id, self._initial_balance_usd)
            after = max(before - amount_usd, 0.0)
            self._wallets[session_id] = after
        return {
            "balance_before_usd": round(before, 6),
            "charged_usd": round(amount_usd, 6),
            "balance_after_usd": round(after, 6),
        }

    def reset(self, session_id: str) -> float:
        with self._lock:
            self._wallets[session_id] = self._initial_balance_usd
            return round(self._initial_balance_usd, 6)


PROFILES: dict[str, DemoProfile] = {
    "gemini-2.5-flash-lite": DemoProfile(
        profile_id="gemini-2.5-flash-lite",
        tier="cheap",
        family="Google Gemini",
        display_name="Gemini 2.5 Flash-Lite",
        provider="google",
        input_cost_per_1m_tokens=0.10,
        output_cost_per_1m_tokens=0.40,
        best_for="Ultra-fast routing logic, basic intent classification, high-volume parsing",
        backing_model_ids=("gemini-2.0-flash-lite-free", "groq-llama-3.1-8b-free", "ollama-llama3.1-8b"),
    ),
    "gemini-1.5-flash": DemoProfile(
        profile_id="gemini-1.5-flash",
        tier="cheap",
        family="Google Gemini",
        display_name="Gemini 1.5 Flash",
        provider="google",
        input_cost_per_1m_tokens=0.08,
        output_cost_per_1m_tokens=0.30,
        best_for="Fast triage, summaries, high-throughput document work",
        backing_model_ids=("gemini-2.0-flash-lite-free", "groq-llama-3.1-8b-free", "ollama-qwen3-8b"),
    ),
    "gpt-5.4-nano": DemoProfile(
        profile_id="gpt-5.4-nano",
        tier="cheap",
        family="OpenAI GPT",
        display_name="GPT-5.4 Nano",
        provider="openai",
        input_cost_per_1m_tokens=0.20,
        output_cost_per_1m_tokens=1.25,
        best_for="Fast categorization, lightweight sub-agents, triage layers",
        backing_model_ids=("groq-llama-3.1-8b-free", "gemini-2.0-flash-lite-free", "ollama-qwen3-8b"),
    ),
    "gpt-4o-mini": DemoProfile(
        profile_id="gpt-4o-mini",
        tier="cheap",
        family="OpenAI GPT",
        display_name="GPT-4o mini",
        provider="openai",
        input_cost_per_1m_tokens=0.15,
        output_cost_per_1m_tokens=0.60,
        best_for="Reliable low-cost execution for simple general tasks",
        backing_model_ids=("groq-llama-3.1-8b-free", "gemini-2.0-flash-lite-free", "ollama-qwen3-8b"),
    ),
    "claude-3-haiku": DemoProfile(
        profile_id="claude-3-haiku",
        tier="cheap",
        family="Anthropic Claude",
        display_name="Claude 3 Haiku",
        provider="anthropic",
        input_cost_per_1m_tokens=0.25,
        output_cost_per_1m_tokens=1.25,
        best_for="Fast document scanning and high-throughput summarization",
        backing_model_ids=("gemini-2.0-flash-lite-free", "openrouter-free-router", "ollama-llama3.1-8b"),
    ),
    "deepseek-v3.2": DemoProfile(
        profile_id="deepseek-v3.2",
        tier="cheap",
        family="DeepSeek",
        display_name="DeepSeek V3.2",
        provider="deepseek",
        input_cost_per_1m_tokens=0.27,
        output_cost_per_1m_tokens=0.40,
        best_for="Strong multi-turn conversational agents on a budget",
        backing_model_ids=("openrouter-free-router", "groq-llama-3.1-8b-free", "ollama-qwen3-8b"),
    ),
    "gemini-2.5-pro": DemoProfile(
        profile_id="gemini-2.5-pro",
        tier="moderate",
        family="Google Gemini",
        display_name="Gemini 2.5 Pro",
        provider="google",
        input_cost_per_1m_tokens=1.25,
        output_cost_per_1m_tokens=10.00,
        best_for="Large-context document analysis and codebase reasoning",
        backing_model_ids=("gemini-2.0-flash-free", "groq-llama-3.3-70b-free", "ollama-qwen3-8b"),
    ),
    "gpt-5.4-mini": DemoProfile(
        profile_id="gpt-5.4-mini",
        tier="moderate",
        family="OpenAI GPT",
        display_name="GPT-5.4 Mini",
        provider="openai",
        input_cost_per_1m_tokens=0.75,
        output_cost_per_1m_tokens=4.50,
        best_for="General-purpose reasoning, coding assistance, core logic tasks",
        backing_model_ids=("gemini-2.0-flash-free", "groq-llama-3.1-8b-free", "ollama-qwen3-8b"),
    ),
    "claude-4.6-sonnet": DemoProfile(
        profile_id="claude-4.6-sonnet",
        tier="moderate",
        family="Anthropic Claude",
        display_name="Claude 4.6 Sonnet",
        provider="anthropic",
        input_cost_per_1m_tokens=3.00,
        output_cost_per_1m_tokens=15.00,
        best_for="Multi-step workflows, structured generation, complex tool use",
        backing_model_ids=("gemini-2.0-flash-free", "groq-llama-3.3-70b-free", "ollama/deepseek-r1:7b"),
    ),
    "deepseek-r1": DemoProfile(
        profile_id="deepseek-r1",
        tier="moderate",
        family="DeepSeek",
        display_name="DeepSeek R1",
        provider="deepseek",
        input_cost_per_1m_tokens=0.55,
        output_cost_per_1m_tokens=2.19,
        best_for="Reasoning and algorithmic work with balanced cost",
        backing_model_ids=("gemini-2.0-flash-free", "huggingface-qwen2.5-7b-experimental", "ollama/deepseek-r1:7b"),
    ),
    "gpt-5.4-flagship": DemoProfile(
        profile_id="gpt-5.4-flagship",
        tier="premium",
        family="OpenAI GPT",
        display_name="GPT-5.4 Flagship",
        provider="openai",
        input_cost_per_1m_tokens=2.50,
        output_cost_per_1m_tokens=15.00,
        best_for="Maximum-capability logic, deep software architecture, expert coding",
        backing_model_ids=("groq-llama-3.3-70b-free", "gemini-2.0-flash-free", "ollama/deepseek-r1:7b"),
    ),
    "claude-4.6-opus": DemoProfile(
        profile_id="claude-4.6-opus",
        tier="premium",
        family="Anthropic Claude",
        display_name="Claude 4.6 Opus",
        provider="anthropic",
        input_cost_per_1m_tokens=5.00,
        output_cost_per_1m_tokens=25.00,
        best_for="High-end synthesis, deep reasoning, advanced documentation",
        backing_model_ids=("groq-llama-3.3-70b-free", "gemini-2.0-flash-free", "ollama/deepseek-r1:7b"),
    ),
}

_wallets = DemoWalletManager(settings.DEMO_SIMULATION_DEFAULT_WALLET_USD)

# ──────────────────────────────────────────────────────────────────────────
# Backing model pools per tier (used when creating profiles from benchmarks)
# ──────────────────────────────────────────────────────────────────────────

_BACKING_POOLS = {
    "premium": ("groq-llama-3.3-70b-free", "gemini-2.0-flash-free", "ollama/deepseek-r1:7b"),
    "moderate": ("gemini-2.0-flash-free", "groq-llama-3.1-8b-free", "ollama-qwen3-8b"),
    "cheap": ("gemini-2.0-flash-lite-free", "groq-llama-3.1-8b-free", "ollama-llama3.1-8b"),
}


def _load_benchmark_models() -> dict:
    """Load commercial model data from benchmarks JSON."""
    import json
    from pathlib import Path
    # demo_mode.py is at src/interfaces/http/demo_mode.py
    # need to reach src/layer0_model_infra/data/model_benchmarks.json
    src_dir = Path(__file__).resolve().parent.parent.parent  # → src/
    path = src_dir / "layer0_model_infra" / "data" / "model_benchmarks.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("models", {})


def get_or_create_profile(model_id: str) -> DemoProfile:
    """
    Get a demo profile by model_id.  Checks existing PROFILES first,
    then dynamically creates one from benchmark data.
    """
    if model_id in PROFILES:
        return PROFILES[model_id]

    benchmarks = _load_benchmark_models()
    if model_id not in benchmarks:
        raise ValueError(f"Unknown commercial model: {model_id}")

    info = benchmarks[model_id]
    cost_per_1k = info.get("cost_per_1k_tokens", 0.001)
    tier = info.get("tier", "moderate")

    # Convert cost_per_1k → per_1m  (input ≈ 40%, output ≈ 60% split)
    input_per_1m = round(cost_per_1k * 1000 * 0.40, 2)
    output_per_1m = round(cost_per_1k * 1000 * 0.60, 2)

    profile = DemoProfile(
        profile_id=model_id,
        tier=tier,
        family=info.get("provider", "unknown").title(),
        display_name=info.get("display_name", model_id),
        provider=info.get("provider", "unknown"),
        input_cost_per_1m_tokens=input_per_1m,
        output_cost_per_1m_tokens=output_per_1m,
        best_for=", ".join(info.get("strengths", ["general"])),
        backing_model_ids=_BACKING_POOLS.get(tier, _BACKING_POOLS["moderate"]),
    )
    return profile


def list_commercial_models() -> list[dict]:
    """
    Return all commercial models from benchmark data for the demo dropdown.
    Grouped by tier with pricing info.
    """
    benchmarks = _load_benchmark_models()
    models = []
    for model_id, info in benchmarks.items():
        models.append({
            "model_id": model_id,
            "display_name": info.get("display_name", model_id),
            "provider": info.get("provider", "unknown"),
            "tier": info.get("tier", "moderate"),
            "cost_per_1k_tokens": info.get("cost_per_1k_tokens", 0.0),
            "strengths": info.get("strengths", []),
        })

    tier_order = {"premium": 0, "moderate": 1, "cheap": 2}
    models.sort(key=lambda m: (tier_order.get(m["tier"], 9), m["provider"], m["display_name"]))
    return models


def estimate_tokens(text: str) -> int:
    """Cheap approximation for demo billing."""
    return max(1, ceil(len(text) / 4))


def list_demo_profiles() -> list[dict]:
    """Return all demo profiles in a stable order."""
    profiles = sorted(PROFILES.values(), key=lambda p: (p.tier, p.family, p.display_name))
    return [profile.to_dict() for profile in profiles]


def get_demo_profile(profile_id: str) -> DemoProfile:
    """Fetch a single profile by id."""
    if profile_id not in PROFILES:
        raise ValueError(f"Unknown demo simulation profile: {profile_id}")
    return PROFILES[profile_id]


def choose_backing_model_id(profile: DemoProfile) -> str:
    """Pick the first active backing model for a demo profile."""
    for model_id in profile.backing_model_ids:
        try:
            model = registry.get_model(model_id)
            if model.is_active:
                return model_id
        except Exception:
            continue
    return profile.backing_model_ids[-1]


def choose_demo_profile(
    requested_profile_id: Optional[str],
    decision: RoutingDecision,
) -> DemoProfile:
    """Select a commercial model profile for the demo.

    When Smart Routing is active (no explicit selection), this uses the
    benchmark router recommendation to pick the optimal commercial model
    based on rubric-weighted benchmark scoring.

    Architecture:
      1. Explicit selection → direct lookup
      2. Benchmark router recommendation → use its model_id
      3. Rubric-based scoring → deterministic best-value selection
    """
    if requested_profile_id:
        try:
            return get_or_create_profile(requested_profile_id)
        except ValueError:
            return get_demo_profile(requested_profile_id)

    # ── Use benchmark router recommendation (preferred) ──────────
    bench_rec = decision.benchmark_recommendation
    if bench_rec and bench_rec.get("model_id"):
        try:
            return get_or_create_profile(bench_rec["model_id"])
        except ValueError:
            pass

    # ── Rubric-based deterministic selection ──────────────────────
    # Use the routing pipeline's rubric scores to find the best-value
    # commercial model from benchmark data.
    import math

    complexity = str(decision.triage_result.get("complexity_band", "moderate")).lower()
    rubric = decision.triage_result.get("complexity_rubric", {})
    benchmarks = _load_benchmark_models()

    if not benchmarks:
        # No benchmark data — use legacy profiles
        return PROFILES.get("gpt-5.4-mini", list(PROFILES.values())[0])

    # Compute rubric-weighted benchmark relevance
    rubric_defaults = {
        "task_count": 0.5, "domain_depth": 0.5,
        "reasoning_hops": 0.5, "output_structure": 0.5,
        "knowledge_breadth": 0.5,
    }
    r = {k: rubric.get(k, rubric_defaults[k]) for k in rubric_defaults}

    bench_weights = {
        "mmlu":          r["knowledge_breadth"] * 0.65 + r["domain_depth"] * 0.35,
        "humaneval":     r["task_count"] * 0.65 + r["output_structure"] * 0.35,
        "gsm8k":         r["reasoning_hops"] * 0.65 + r["task_count"] * 0.35,
        "arc_challenge": r["reasoning_hops"] * 0.65 + r["knowledge_breadth"] * 0.35,
        "mt_bench":      r["output_structure"] * 0.65 + r["knowledge_breadth"] * 0.35,
        "ifeval":        r["output_structure"] * 0.65 + r["task_count"] * 0.35,
        "bbh":           r["reasoning_hops"] * 0.65 + r["domain_depth"] * 0.35,
    }
    total_w = sum(bench_weights.values()) or 1.0
    bench_weights = {b: w / total_w for b, w in bench_weights.items()}

    # Score each commercial model
    best_model_id = None
    best_score = -float("inf")

    for model_id, info in benchmarks.items():
        model_benchmarks = info.get("benchmarks", {})
        quality = sum(
            model_benchmarks.get(b, 0.5) * w
            for b, w in bench_weights.items()
        )
        cost = info.get("cost_per_1k_tokens", 0.01)
        tier = info.get("tier", "moderate")

        # Tier-aware scoring (same logic as benchmark_router._benchmark_scoring)
        if complexity in ("trivial", "simple"):
            score = quality - cost * 50  # minimize cost
        elif complexity == "moderate":
            cost_factor = math.log(cost * 1000 + 1) + 0.1
            score = quality / cost_factor  # balance quality/cost
        elif complexity in ("complex", "expert"):
            score = quality * 10 - cost  # quality is king
        else:
            cost_factor = math.log(cost * 1000 + 1) + 0.1
            score = quality / cost_factor

        if score > best_score:
            best_score = score
            best_model_id = model_id

    if best_model_id:
        return get_or_create_profile(best_model_id)

    return PROFILES.get("gpt-5.4-mini", list(PROFILES.values())[0])


def preview_simulated_charge(profile: DemoProfile, prompt: str, response: str) -> dict[str, float | int]:
    """Estimate billing using the commercial profile prices."""
    input_tokens = estimate_tokens(prompt)
    output_tokens = estimate_tokens(response)
    charge = (
        (input_tokens / 1_000_000) * profile.input_cost_per_1m_tokens
        + (output_tokens / 1_000_000) * profile.output_cost_per_1m_tokens
    )
    return {
        "input_tokens_est": input_tokens,
        "output_tokens_est": output_tokens,
        "simulated_cost_usd": round(charge, 6),
    }


def charge_demo_wallet(session_id: str, profile: DemoProfile, prompt: str, response: str) -> dict:
    """Debit the wallet and return full simulated billing metadata."""
    preview = preview_simulated_charge(profile, prompt, response)
    wallet = _wallets.charge(session_id, float(preview["simulated_cost_usd"]))
    return {
        **preview,
        **wallet,
        "session_id": session_id,
    }


def get_demo_wallet_balance(session_id: str) -> float:
    """Get current wallet balance for a session."""
    return _wallets.get_balance(session_id)


def reset_demo_wallet(session_id: str) -> dict:
    """Reset a wallet to the configured starting balance."""
    return {
        "session_id": session_id,
        "balance_after_reset_usd": _wallets.reset(session_id),
    }
