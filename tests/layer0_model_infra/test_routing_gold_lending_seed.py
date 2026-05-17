"""
Validate the lending-focused Layer 0 routing gold set.

This file checks dataset shape and coverage so the seed set is safe to use
while the routing classifier is still being migrated from complexity-only
logic to richer routing intelligence signals.
"""

import json
import pathlib
from collections import Counter


GOLD_SET_PATH = pathlib.Path(__file__).parent / "routing_gold_lending_seed.json"

TASK_MODES = {"direct", "rag", "transactional", "agentic", "hybrid"}
RETRIEVAL_DEMANDS = {"none", "single_chunk", "single_doc", "multi_doc", "cross_doc_synthesis"}
REASONING_LEVELS = {"low", "medium", "high"}
RISK_LEVELS = {"low", "medium", "high", "regulated"}
ACTION_INTENSITIES = {"none", "read_only", "transactional", "irreversible"}
OUTPUT_COMPLEXITIES = {"short_text", "structured_text", "table_graph", "code_json", "workflow"}
MULTILINGUAL_LOADS = {"low", "medium", "high"}
EXPECTED_TIERS = {"cheap", "mid", "premium"}


def _load_gold_set() -> list[dict]:
    with open(GOLD_SET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


GOLD_SET = _load_gold_set()


def test_lending_routing_gold_set_has_required_fields():
    required_fields = {
        "query",
        "task_mode",
        "retrieval_demand",
        "reasoning_level",
        "risk_level",
        "action_intensity",
        "output_complexity",
        "multilingual_load",
        "expected_tier",
        "category",
    }

    for entry in GOLD_SET:
        assert required_fields.issubset(entry.keys()), f"Missing fields in entry: {entry}"


def test_lending_routing_gold_set_uses_valid_enums():
    for entry in GOLD_SET:
        assert entry["task_mode"] in TASK_MODES
        assert entry["retrieval_demand"] in RETRIEVAL_DEMANDS
        assert entry["reasoning_level"] in REASONING_LEVELS
        assert entry["risk_level"] in RISK_LEVELS
        assert entry["action_intensity"] in ACTION_INTENSITIES
        assert entry["output_complexity"] in OUTPUT_COMPLEXITIES
        assert entry["multilingual_load"] in MULTILINGUAL_LOADS
        assert entry["expected_tier"] in EXPECTED_TIERS


def test_lending_routing_gold_set_has_minimum_coverage():
    assert len(GOLD_SET) >= 20, "Seed set is too small to be useful"

    task_modes = Counter(entry["task_mode"] for entry in GOLD_SET)
    expected_tiers = Counter(entry["expected_tier"] for entry in GOLD_SET)
    categories = Counter(entry["category"] for entry in GOLD_SET)

    assert task_modes["rag"] >= 5
    assert task_modes["transactional"] >= 3
    assert task_modes["hybrid"] >= 3
    assert task_modes["agentic"] >= 1

    assert expected_tiers["cheap"] >= 2
    assert expected_tiers["mid"] >= 8
    assert expected_tiers["premium"] >= 5

    assert any(entry["multilingual_load"] != "low" for entry in GOLD_SET)
    assert any(entry["output_complexity"] == "table_graph" for entry in GOLD_SET)
    assert any(entry["action_intensity"] == "transactional" for entry in GOLD_SET)
    assert len(categories) >= 10
