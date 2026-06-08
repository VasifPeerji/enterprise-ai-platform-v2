"""
Layer 8 — escalation ladder built from Layer 3's qualifying_models.

These exercise EscalationEngine.path_from_qualifiers: the ladder must start at the
model Layer 3 picked, climb the cost-sorted qualifiers (never downward), skip
rate-limited (cooling) targets, and stay within max_escalation_levels. Uses the
real legacy registry's active models so no Layer 3 adapter wiring is needed.
"""
from __future__ import annotations

import pytest

from src.layer0_model_infra.registry import get_registry
from src.layer0_model_infra.routing.escalation_engine import get_escalation_engine


class _FakeCooldown:
    def __init__(self, cooling=()):
        self._cooling = set(cooling)

    def is_cooling_down(self, model_id: str) -> bool:
        return model_id in self._cooling


def _active_ids(n: int = 3) -> list[str]:
    return [m.model_id for m in get_registry().list_models(only_active=True)][:n]


def test_path_from_qualifiers_starts_at_selected_and_climbs(all_keys_set):
    ids = _active_ids()
    if len(ids) < 2:
        pytest.skip("need >= 2 active legacy models")
    path = get_escalation_engine().path_from_qualifiers(ids, selected_model_id=ids[0])
    got = [m.model_id for m in path.models]
    assert got[0] == ids[0]                 # starts at the Layer 3 pick
    assert got == ids[: len(got)]           # climbs in the given (cost) order
    assert path.current_model.model_id == ids[0]


def test_path_from_qualifiers_skips_cooled_down(all_keys_set):
    ids = _active_ids()
    if len(ids) < 2:
        pytest.skip("need >= 2 active legacy models")
    cd = _FakeCooldown([ids[1]])            # rate-limit the first escalation target
    path = get_escalation_engine().path_from_qualifiers(
        ids, selected_model_id=ids[0], cooldown=cd
    )
    got = [m.model_id for m in path.models]
    assert ids[1] not in got               # cooling target excluded from the ladder
    assert got[0] == ids[0]


def test_path_from_qualifiers_never_escalates_downward(all_keys_set):
    ids = _active_ids()
    if len(ids) < 2:
        pytest.skip("need >= 2 active legacy models")
    # Pick the SECOND model as the start → the cheaper first one must not appear.
    path = get_escalation_engine().path_from_qualifiers(ids, selected_model_id=ids[1])
    got = [m.model_id for m in path.models]
    assert got[0] == ids[1]
    assert ids[0] not in got


def test_path_from_qualifiers_respects_max_levels(all_keys_set):
    ids = _active_ids(8)
    if len(ids) < 2:
        pytest.skip("need active legacy models")
    eng = get_escalation_engine()
    path = eng.path_from_qualifiers(ids, selected_model_id=ids[0])
    assert len(path.models) <= eng.max_levels
