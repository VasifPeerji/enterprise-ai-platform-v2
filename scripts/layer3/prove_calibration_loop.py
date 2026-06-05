"""
scripts/layer3/prove_calibration_loop.py  (WORKING TOOL — not committed yet)

Prove the Layer 3 ONLINE LEARNING LOOP is wired end-to-end: run queries through
the real orchestrator (router -> kNN Layer 3 -> Layer 7 quality) and show that
calibration observations accumulate and the per-(model, feature_cell) multipliers
move off 1.0. The gateway is STUBBED so this is $0 and makes no real LLM calls
(no competition with the grounding batch for provider rate limits) — what we're
proving is the FEEDBACK WIRING, not answer quality.

Run: python scripts/layer3/prove_calibration_loop.py
"""
from __future__ import annotations

import os
# Canary ON must be set BEFORE importing src (Settings is read once at import).
os.environ["LAYER3_CANARY_FRACTION"] = "1.0"

from pathlib import Path
import sys
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import dotenv_values
for _k, _v in dotenv_values(REPO_ROOT / ".env").items():
    if _k.endswith("_API_KEY") and _v:
        os.environ.setdefault(_k, _v.strip())

import asyncio  # noqa: E402

from src.layer0_model_infra import gateway as gwmod  # noqa: E402
from src.layer0_model_infra.gateway import LLMResponse  # noqa: E402
from src.layer2_orchestrator.execution_loop import EliteExecutionOrchestrator  # noqa: E402
from src.layer0_model_infra.routing.calibration_store import get_calibration_store  # noqa: E402


_ANSWER = (
    "The photoelectric effect shows light is quantized: a photon of energy E=hf "
    "ejects an electron only when hf exceeds the metal's work function, and the "
    "ejected electron's kinetic energy is hf minus that work function. This is "
    "the same reasoning that applies across the question; the explanation is "
    "complete, internally consistent, and addresses each part of the prompt. "
) * 2


async def _fake_complete(self, request, **kw):
    """Stub: a plausible, complete answer — no real provider call."""
    return LLMResponse(
        content=_ANSWER, model_id=request.model_id,
        input_tokens=30, output_tokens=150, total_tokens=180,
        cost_usd=0.0, latency_ms=12.0, finish_reason="stop",
    )


def main() -> int:
    gwmod.ModelGateway.complete = _fake_complete  # stub the whole gateway

    cal = get_calibration_store()
    print("calibration BEFORE:", cal.stats())

    orch = EliteExecutionOrchestrator()
    queries = [
        "Which of the following best explains the photoelectric effect in quantum mechanics?",
        "Explain the difference between TCP and UDP transport protocols.",
        "What is the average-case time complexity of quicksort and why?",
        "Describe how natural selection drives evolutionary change.",
        "What macroeconomic factors most directly cause inflation?",
        "Explain the central dogma of molecular biology.",
        "What distinguishes supervised from unsupervised machine learning?",
        "How does a proof-of-work blockchain reach distributed consensus?",
        "Explain the CAP theorem and its implications for distributed databases.",
        "What is the role of mitochondria in cellular respiration?",
    ]
    print(f"\nrouting {len(queries)} queries through the full orchestrator (gateway stubbed):\n")
    fired = 0
    for q in queries:
        before = cal.stats()["total_observations"]
        res = asyncio.run(orch.execute(q))
        after = cal.stats()["total_observations"]
        md = res.routing_decision.pipeline_metadata or {}
        src = md.get("layer3_source", md.get("router", "?"))
        delta = after - before
        fired += 1 if delta else 0
        print(f"  src={str(src):11} model={res.model_used:30} q={round(res.quality_score,3):<5} "
              f"calibration_fired={'YES' if delta else 'no'}")

    print(f"\ncalibration AFTER : {cal.stats()}")
    print(f"calibration fired on {fired}/{len(queries)} queries\n")
    print("per-cell multipliers (model_id | feature_cell | n_obs | multiplier | confidence):")
    for (mid, cell), c in sorted(cal._cells.items()):
        moved = "  <-- moved off 1.0" if abs(c.multiplier - 1.0) > 1e-6 else ""
        print(f"  {mid:30} {cell:28} n={c.n_observations:<3} mult={c.multiplier:.4f} conf={c.confidence:.3f}{moved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
