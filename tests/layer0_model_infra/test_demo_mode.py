from src.interfaces.http.demo_mode import (
    charge_demo_wallet,
    choose_demo_profile,
    get_demo_wallet_balance,
    preview_simulated_charge,
    reset_demo_wallet,
)
from src.layer0_model_infra.router import RoutingDecision
from src.layer0_model_infra.registry import get_registry


def _build_decision(model_id: str, complexity: str = "simple", intent: str = "chat", domain: str = "general", uncertainty: float = 0.2) -> RoutingDecision:
    registry = get_registry()
    model = registry.get_model(model_id)
    return RoutingDecision(
        selected_model=model,
        fallback_models=[],
        modality_analysis={"primary_modality": "text"},
        triage_result={
            "intent": intent,
            "domain": domain,
            "complexity_band": complexity,
        },
        uncertainty_score={"total_uncertainty": uncertainty},
        bandit_context={},
        routing_reasoning="test",
        estimated_cost_usd=0.0,
        confidence_level="HIGH",
        escalation_path_available=True,
        escalation_levels=0,
        pipeline_metadata={},
    )


def test_choose_demo_profile_prefers_premium_for_high_uncertainty() -> None:
    decision = _build_decision("ollama-phi3-mini", complexity="complex", uncertainty=0.9)
    profile = choose_demo_profile(None, decision)
    assert profile.profile_id == "gpt-5.4-flagship"


def test_preview_simulated_charge_returns_positive_estimates() -> None:
    decision = _build_decision("ollama-phi3-mini")
    profile = choose_demo_profile("gpt-4o-mini", decision)
    preview = preview_simulated_charge(profile, "hello world", "response")
    assert preview["input_tokens_est"] > 0
    assert preview["output_tokens_est"] > 0
    assert preview["simulated_cost_usd"] >= 0.0


def test_demo_wallet_charge_and_reset() -> None:
    session_id = "pytest-demo-wallet"
    reset_demo_wallet(session_id)
    starting_balance = get_demo_wallet_balance(session_id)
    decision = _build_decision("ollama-phi3-mini")
    profile = choose_demo_profile("gpt-4o-mini", decision)
    charge = charge_demo_wallet(session_id, profile, "short prompt", "short response")
    assert charge["balance_after_usd"] <= starting_balance
    reset = reset_demo_wallet(session_id)
    assert reset["balance_after_reset_usd"] == starting_balance
