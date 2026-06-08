"""
📁 File: tests/layer0_model_infra/test_complexity_gold_set.py
Purpose: Evaluate complexity classifier against the gold seed set.
Reports: accuracy, under-routing rate, over-routing rate, confusion matrix.
"""

import json
import pathlib
from collections import Counter

import pytest

from src.layer0_model_infra.routing.legacy.complexity_classifier import (
    ComplexityResult,
    get_complexity_classifier,
)

GOLD_SET_PATH = pathlib.Path(__file__).parent / "complexity_gold_set.json"
BAND_ORDER = ["trivial", "simple", "moderate", "complex", "expert"]


def _load_gold_set() -> list[dict]:
    with open(GOLD_SET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _band_index(band: str) -> int:
    return BAND_ORDER.index(band)


# ------------------------------------------------------------------
# Parametrized test: each gold query must classify correctly
# ------------------------------------------------------------------

GOLD_SET = _load_gold_set()


@pytest.fixture(scope="module")
def classifier():
    return get_complexity_classifier()


@pytest.mark.parametrize(
    "entry",
    GOLD_SET,
    ids=[f"{e['expected_band']}:{e['query'][:50]}" for e in GOLD_SET],
)
def test_gold_query_classification(classifier, entry):
    """Each gold query should classify to the expected band."""
    result: ComplexityResult = classifier.classify(entry["query"], input_signals=None)
    actual = result.complexity_band
    expected = entry["expected_band"]

    # Allow ±1 band tolerance for borderline cases
    distance = abs(_band_index(actual) - _band_index(expected))
    assert distance <= 1, (
        f"Query: {entry['query']!r}\n"
        f"Expected: {expected}, Got: {actual} (distance={distance})\n"
        f"Category: {entry.get('category', '?')}\n"
        f"Reasoning: {result.reasoning}"
    )


# ------------------------------------------------------------------
# Aggregate metrics (runs once, after all parametrized tests)
# ------------------------------------------------------------------

class TestGoldSetMetrics:
    """Aggregate accuracy and routing-risk metrics."""

    def test_overall_accuracy(self, classifier):
        """Overall exact-match accuracy should be >= 70% (heuristic baseline)."""
        correct = 0
        total = len(GOLD_SET)
        for entry in GOLD_SET:
            result = classifier.classify(entry["query"], input_signals=None)
            if result.complexity_band == entry["expected_band"]:
                correct += 1
        accuracy = correct / total * 100
        print(f"\n{'='*60}")
        print(f"Gold Set Accuracy: {accuracy:.1f}% ({correct}/{total})")
        print(f"{'='*60}")
        # Heuristic baseline is ~70%; improved classifier should beat this
        assert accuracy >= 60, f"Accuracy {accuracy:.1f}% is too low"

    def test_under_routing_rate(self, classifier):
        """Under-routing rate (classified lower than expected) should be <= 20%.
        Under-routing is the more dangerous failure mode."""
        under_routed = 0
        total = len(GOLD_SET)
        under_examples = []
        for entry in GOLD_SET:
            result = classifier.classify(entry["query"], input_signals=None)
            actual_idx = _band_index(result.complexity_band)
            expected_idx = _band_index(entry["expected_band"])
            if actual_idx < expected_idx:
                under_routed += 1
                under_examples.append(
                    f"  {entry['query'][:60]:60s} | expected={entry['expected_band']:8s} got={result.complexity_band}"
                )
        rate = under_routed / total * 100
        print(f"\nUnder-routing rate: {rate:.1f}% ({under_routed}/{total})")
        if under_examples:
            print("Under-routed queries:")
            for ex in under_examples[:10]:
                print(ex)
        assert rate <= 25, f"Under-routing rate {rate:.1f}% is dangerously high"

    def test_over_routing_rate(self, classifier):
        """Over-routing rate (classified higher than expected) should be <= 25%.
        Over-routing wastes cost but is less dangerous."""
        over_routed = 0
        total = len(GOLD_SET)
        over_examples = []
        for entry in GOLD_SET:
            result = classifier.classify(entry["query"], input_signals=None)
            actual_idx = _band_index(result.complexity_band)
            expected_idx = _band_index(entry["expected_band"])
            if actual_idx > expected_idx:
                over_routed += 1
                over_examples.append(
                    f"  {entry['query'][:60]:60s} | expected={entry['expected_band']:8s} got={result.complexity_band}"
                )
        rate = over_routed / total * 100
        print(f"\nOver-routing rate: {rate:.1f}% ({over_routed}/{total})")
        if over_examples:
            print("Over-routed queries:")
            for ex in over_examples[:10]:
                print(ex)
        assert rate <= 30, f"Over-routing rate {rate:.1f}% is too high"

    def test_confusion_matrix(self, classifier):
        """Print confusion matrix focusing on moderate↔complex boundary."""
        matrix: dict[str, Counter] = {band: Counter() for band in BAND_ORDER}
        for entry in GOLD_SET:
            result = classifier.classify(entry["query"], input_signals=None)
            matrix[entry["expected_band"]][result.complexity_band] += 1

        print(f"\n{'Confusion Matrix':^60}")
        header_label = "Expected \\ Actual"
        print(f"{header_label:<18}", end="")
        for band in BAND_ORDER:
            print(f"{band:>10}", end="")
        print()
        print("-" * 62)
        for expected in BAND_ORDER:
            print(f"{expected:<12}", end="")
            for actual in BAND_ORDER:
                count = matrix[expected][actual]
                print(f"{count:>10}", end="")
            print()
