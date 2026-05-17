"""Test the new demo mode functions."""
from src.interfaces.http.demo_mode import list_commercial_models, get_or_create_profile

models = list_commercial_models()
print(f"Total models in dropdown: {len(models)}")
print()
print("Model dropdown (grouped by tier):")
current_tier = ""
for m in models:
    if m["tier"] != current_tier:
        current_tier = m["tier"]
        emoji = {"premium": "🔴", "moderate": "🟡", "cheap": "🟢"}.get(current_tier, "⚪")
        print(f"\n  {emoji} {current_tier.upper()}")
    print(f"    {m['display_name']:28s} ${m['cost_per_1k_tokens']:.4f}/1K  ({m['provider']})")

print()

# Test creating a profile from benchmark data
p = get_or_create_profile("claude-opus-4.6")
print(f"Profile created: {p.display_name}")
print(f"  Input cost/1M: ${p.input_cost_per_1m_tokens}")
print(f"  Output cost/1M: ${p.output_cost_per_1m_tokens}")
print(f"  Backing models: {p.backing_model_ids}")
print(f"  Tier: {p.tier}")
