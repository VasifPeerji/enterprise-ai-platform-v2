"""
Multi-LLM Consensus Labeler for Router Training Queries
========================================================

This script re-labels training queries using multi-model consensus,
grounding each classification in Bloom's Revised Taxonomy (Anderson &
Krathwohl, 2001) and Webb's Depth of Knowledge (Webb, 1997).

Methodology:
  1. Each query is sent to 3 independent LLMs
  2. Each LLM scores 5 rubric dimensions (0.0-1.0)
  3. Median scores across models are computed
  4. Complexity band is derived from the weighted aggregate score
  5. Full audit trail is preserved for defensibility

Usage:
  python scripts/consensus_labeler.py [--dry-run] [--output path]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.layer0_model_infra.registry import get_registry
from src.layer0_model_infra.routing.complexity_classifier import (
    _RUBRIC_WEIGHTS,
    _SYSTEM_PROMPT,
    VALID_BANDS,
)
from src.shared.config import get_settings

settings = get_settings()
registry = get_registry()

# Try to import litellm
try:
    from litellm import completion
except ImportError:
    print("ERROR: litellm not installed. Run: pip install litellm")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR = _PROJECT_ROOT / "src" / "layer0_model_infra" / "data"
_TRAINING_PATH = _DATA_DIR / "router_training_queries.json"
_OUTPUT_PATH = _DATA_DIR / "router_training_queries.json"


# ---------------------------------------------------------------------------
# Judge models (in priority order — use first 3 available)
# ---------------------------------------------------------------------------

_JUDGE_CANDIDATES = [
    "groq-llama-3.3-70b-free",
    "groq-llama-3.1-8b-free",
    "gemini-2.0-flash-lite-free",
    "gemini-2.0-flash-free",
    "ollama-qwen3-8b",
    "ollama-llama-3.1-8b",
]


# ---------------------------------------------------------------------------
# Bloom's × Webb's framework documentation
# ---------------------------------------------------------------------------

_FRAMEWORK_DOC = {
    "trivial": {
        "blooms_level": "Remember",
        "webbs_dok": 1,
        "description": "Single fact recall, greeting, basic arithmetic",
        "criteria": "Requires only retrieval of memorized information",
    },
    "simple": {
        "blooms_level": "Understand",
        "webbs_dok": "1-2",
        "description": "Single concept explanation, definition, simple procedure",
        "criteria": "Requires comprehension of a single concept without multi-step reasoning",
    },
    "moderate": {
        "blooms_level": "Apply/Analyze",
        "webbs_dok": "2-3",
        "description": "Multi-step reasoning, comparison, standard coding",
        "criteria": "Requires application of knowledge or analysis of relationships",
    },
    "complex": {
        "blooms_level": "Evaluate/Create",
        "webbs_dok": "3-4",
        "description": "System design, multi-domain synthesis, high-stakes advice",
        "criteria": "Requires judgment, creation, or synthesis across domains",
    },
    "expert": {
        "blooms_level": "Create (novel)",
        "webbs_dok": "4+",
        "description": "Open research problems, formal proofs, novel algorithms",
        "criteria": "Requires novel intellectual contribution beyond existing knowledge",
    },
}


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------

def _apply_auth(model_def, kwargs: dict) -> None:
    """Apply provider auth to completion kwargs."""
    from src.layer0_model_infra.models import ModelProvider

    if model_def.provider == ModelProvider.LOCAL:
        kwargs["api_base"] = settings.OLLAMA_BASE_URL
    elif model_def.provider == ModelProvider.GOOGLE and settings.GEMINI_API_KEY:
        kwargs["api_key"] = settings.GEMINI_API_KEY
    elif model_def.provider == ModelProvider.GROQ and settings.GROQ_API_KEY:
        kwargs["api_key"] = settings.GROQ_API_KEY
    elif model_def.provider == ModelProvider.OPENROUTER and settings.OPENROUTER_API_KEY:
        kwargs["api_key"] = settings.OPENROUTER_API_KEY


def classify_with_model(query: str, model_id: str) -> Optional[dict]:
    """Classify a single query using one LLM. Returns rubric dict or None."""
    import re

    model_def = registry.get_model(model_id)
    user_msg = f'Classify this query:\n\n"{query}"'

    kwargs = {
        "model": model_def.model_name,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.0,
        "max_tokens": 400,
    }
    _apply_auth(model_def, kwargs)

    try:
        response = completion(**kwargs)
        content = (response.choices[0].message.content or "").strip()

        # Parse JSON from response
        payload = None
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            # Try code fences
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if match:
                try:
                    payload = json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            if payload is None:
                # Try finding any JSON object
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    try:
                        payload = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        pass

        if payload is None:
            return None

        def clamp(v, lo=0.0, hi=1.0):
            try:
                return max(lo, min(float(v), hi))
            except (TypeError, ValueError):
                return 0.5

        return {
            "task_count": clamp(payload.get("task_count", 0.5)),
            "domain_depth": clamp(payload.get("domain_depth", 0.5)),
            "reasoning_hops": clamp(payload.get("reasoning_hops", 0.5)),
            "output_structure": clamp(payload.get("output_structure", 0.5)),
            "knowledge_breadth": clamp(payload.get("knowledge_breadth", 0.5)),
            "band": str(payload.get("band", "")).lower().strip(),
            "reasoning_summary": str(payload.get("reasoning_summary", "")),
        }
    except Exception as exc:
        print(f"  [WARN] {model_id} failed: {exc}")
        return None


def compute_consensus(results: list[dict]) -> dict:
    """Compute median consensus from multiple model results."""
    dims = ["task_count", "domain_depth", "reasoning_hops",
            "output_structure", "knowledge_breadth"]

    consensus = {}
    for dim in dims:
        values = [r[dim] for r in results if dim in r]
        consensus[dim] = round(statistics.median(values), 4) if values else 0.5

    # Compute raw_score
    raw_score = sum(
        consensus[dim] * _RUBRIC_WEIGHTS[dim]
        for dim in dims
    )
    raw_score = max(0.0, min(1.0, raw_score))
    consensus["raw_score"] = round(raw_score, 4)

    # Derive band from raw_score
    if raw_score < 0.12:
        consensus["band"] = "trivial"
    elif raw_score < 0.30:
        consensus["band"] = "simple"
    elif raw_score < 0.55:
        consensus["band"] = "moderate"
    elif raw_score < 0.80:
        consensus["band"] = "complex"
    else:
        consensus["band"] = "expert"

    return consensus


def get_dominant_rubric(consensus: dict) -> str:
    """Find the rubric dimension with the highest score."""
    dims = ["task_count", "domain_depth", "reasoning_hops",
            "output_structure", "knowledge_breadth"]
    best_dim = max(dims, key=lambda d: consensus.get(d, 0))
    return best_dim


def get_framework_label(band: str) -> str:
    """Generate Bloom's × Webb's framework label."""
    info = _FRAMEWORK_DOC.get(band, _FRAMEWORK_DOC["moderate"])
    return f"blooms_{info['blooms_level'].lower().replace('/', '_')}_x_webbs_dok_{info['webbs_dok']}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multi-LLM Consensus Labeler")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries to process")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else _OUTPUT_PATH

    # Load training queries
    with open(_TRAINING_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    queries = data.get("queries", [])
    print(f"Loaded {len(queries)} training queries")

    # Find available judge models
    judge_models = []
    for model_id in _JUDGE_CANDIDATES:
        try:
            model = registry.get_model(model_id)
            if model.is_active:
                judge_models.append(model_id)
                if len(judge_models) >= 3:
                    break
        except Exception:
            pass

    if not judge_models:
        print("ERROR: No judge models available. Check API keys.")
        sys.exit(1)

    print(f"Using {len(judge_models)} judge models: {judge_models}")
    print()

    # Process each query
    labeled = []
    changes = 0
    limit = args.limit or len(queries)

    for i, q in enumerate(queries[:limit]):
        text = q["text"]
        old_complexity = q.get("complexity", "unknown")
        print(f"[{i+1}/{min(limit, len(queries))}] {text[:60]}...")

        # Get classifications from each model
        model_results = {}
        valid_results = []
        for model_id in judge_models:
            result = classify_with_model(text, model_id)
            if result:
                model_results[model_id] = result
                valid_results.append(result)
                print(f"  {model_id}: band={result['band']}, "
                      f"score={sum(result[d] * _RUBRIC_WEIGHTS[d] for d in ['task_count','domain_depth','reasoning_hops','output_structure','knowledge_breadth']):.3f}")
            time.sleep(0.3)  # Rate limit

        if len(valid_results) < 1:
            print(f"  [SKIP] No valid results, keeping original")
            labeled.append(q)
            continue

        # Compute consensus
        consensus = compute_consensus(valid_results)
        new_complexity = consensus["band"]
        dominant = get_dominant_rubric(consensus)
        framework = get_framework_label(new_complexity)

        changed = new_complexity != old_complexity
        if changed:
            changes += 1
            print(f"  >> CHANGED: {old_complexity} -> {new_complexity} "
                  f"(raw_score={consensus['raw_score']:.3f})")
        else:
            print(f"  OK Confirmed: {new_complexity} "
                  f"(raw_score={consensus['raw_score']:.3f})")

        labeled.append({
            "text": text,
            "complexity": new_complexity,
            "dominant_rubric": dominant,
            "labeling_method": "multi_llm_consensus",
            "framework": framework,
            "consensus_scores": {
                k: consensus[k] for k in
                ["task_count", "domain_depth", "reasoning_hops",
                 "output_structure", "knowledge_breadth", "raw_score"]
            },
            "individual_model_scores": model_results,
        })
        print()

    # Keep unlabeled queries as-is
    for q in queries[limit:]:
        labeled.append(q)

    print(f"\n{'='*60}")
    print(f"Processed: {min(limit, len(queries))} queries")
    print(f"Changed: {changes} labels")
    print(f"Total output: {len(labeled)} queries")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    # Update meta
    data["_meta"]["total_queries"] = len(labeled)
    data["_meta"]["labeling_method"] = "multi_llm_consensus"
    data["_meta"]["labeling_framework"] = (
        "Bloom's Revised Taxonomy (Anderson & Krathwohl, 2001) × "
        "Webb's Depth of Knowledge (Webb, 1997)"
    )
    data["_meta"]["judge_models"] = judge_models
    data["_meta"]["framework_mapping"] = _FRAMEWORK_DOC
    data["queries"] = labeled

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nWritten to {output_path}")


if __name__ == "__main__":
    main()
