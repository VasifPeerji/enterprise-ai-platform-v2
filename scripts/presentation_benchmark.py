"""
Presentation benchmark harness for the adaptive routing system.

Usage examples:
  python scripts/presentation_benchmark.py --mode analyze
  python scripts/presentation_benchmark.py --mode execute --output artifacts/demo_run.json

`analyze` mode runs the router only, which is useful when model providers are
not configured. `execute` mode runs the full orchestrator and produces
end-to-end evidence including quality and escalation details.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class DemoCase:
    case_id: str
    category: str
    expected_behavior: str
    query: str
    user_tier: str = "standard"


DEMO_CASES: list[DemoCase] = [
    DemoCase(
        case_id="simple_qa_01",
        category="simple",
        expected_behavior="cheap route, low uncertainty, no escalation",
        query="What is overfitting in machine learning?",
    ),
    DemoCase(
        case_id="coding_01",
        category="coding",
        expected_behavior="coding-aware routing with moderate complexity",
        query="Write a Python function for breadth-first search and explain its time complexity.",
    ),
    DemoCase(
        case_id="reasoning_01",
        category="reasoning",
        expected_behavior="higher uncertainty and stronger routing than simple QA",
        query="Compare the tradeoffs between Raft and Paxos for a distributed coordination system.",
    ),
    DemoCase(
        case_id="high_risk_01",
        category="cross_domain",
        expected_behavior="higher uncertainty, safer routing, possible escalation",
        query="Compare the legal and ethical implications of using AI diagnosis tools in hospitals.",
    ),
    DemoCase(
        case_id="casual_01",
        category="casual",
        expected_behavior="simple route, low latency path",
        query="Give me three quick tips for staying focused while studying.",
    ),
]


def _default_output_path(mode: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"presentation_{mode}_{timestamp}.json"


async def _run_analyze() -> list[dict[str, Any]]:
    from src.layer0_model_infra.router import get_router

    router = get_router()
    results: list[dict[str, Any]] = []

    for case in DEMO_CASES:
        decision = router.route(
            query=case.query,
            user_tier=case.user_tier,
        )
        results.append(
            {
                "case": asdict(case),
                "mode": "analyze",
                "selected_model": decision.selected_model.model_id,
                "confidence_level": decision.confidence_level,
                "estimated_cost_usd": decision.estimated_cost_usd,
                "modality": decision.modality_analysis,
                "triage": decision.triage_result,
                "uncertainty": decision.uncertainty_score,
                "bandit_context": decision.bandit_context,
                "pipeline_metadata": decision.pipeline_metadata,
                "routing_reasoning": decision.routing_reasoning,
            }
        )

    return results


async def _run_execute() -> list[dict[str, Any]]:
    from src.layer2_orchestrator.execution_loop import get_orchestrator

    orchestrator = get_orchestrator()
    results: list[dict[str, Any]] = []

    for case in DEMO_CASES:
        result = await orchestrator.execute(
            query=case.query,
            user_tier=case.user_tier,
            session_id=f"presentation_{case.case_id}",
        )
        results.append(
            {
                "case": asdict(case),
                "mode": "execute",
                "response_preview": result.content[:400],
                "model_used": result.model_used,
                "total_cost_usd": result.total_cost_usd,
                "total_latency_ms": result.total_latency_ms,
                "escalation_count": result.escalation_count,
                "quality_passed": result.quality_passed,
                "quality_score": result.quality_score,
                "quality_reasoning": result.quality_reasoning,
                "routing_decision": result.routing_decision.model_dump(),
                "execution_metadata": result.execution_metadata,
            }
        )

    return results


def _write_outputs(results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    csv_path = output_path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "category",
                "expected_behavior",
                "mode",
                "selected_or_final_model",
                "confidence_level",
                "quality_score",
                "escalation_count",
                "latency_ms",
                "cost_usd",
            ],
        )
        writer.writeheader()
        for item in results:
            case = item["case"]
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "expected_behavior": case["expected_behavior"],
                    "mode": item["mode"],
                    "selected_or_final_model": item.get("model_used") or item.get("selected_model"),
                    "confidence_level": item.get("confidence_level")
                    or item.get("routing_decision", {}).get("confidence_level"),
                    "quality_score": item.get("quality_score", ""),
                    "escalation_count": item.get("escalation_count", 0),
                    "latency_ms": item.get("total_latency_ms", ""),
                    "cost_usd": item.get("total_cost_usd", item.get("estimated_cost_usd", "")),
                }
            )

    print(f"Wrote JSON results to {output_path}")
    print(f"Wrote CSV summary to {csv_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run presentation benchmark cases.")
    parser.add_argument(
        "--mode",
        choices=("analyze", "execute"),
        default="analyze",
        help="Whether to run router-only analysis or full execution.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output JSON path.",
    )
    args = parser.parse_args()

    output_path = args.output or _default_output_path(args.mode)
    if args.mode == "analyze":
        results = await _run_analyze()
    else:
        results = await _run_execute()
    _write_outputs(results, output_path)


if __name__ == "__main__":
    asyncio.run(main())
