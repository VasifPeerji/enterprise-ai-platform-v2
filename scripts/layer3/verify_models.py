"""
📁 File: scripts/layer3/verify_models.py
Layer: Layer 0 — Layer 3 redesign (registry freshness)
Purpose: Catch provider catalog drift before it breaks routing. Pings every
         active registry model with a real (tiny) completion and reports which
         actually work, which are decommissioned / 404, and which are merely
         rate-limited. With --catalog it also lists current provider models that
         are NOT in the registry (candidates to add). This is the
         verify_provider_catalogs.py the registry _meta has long promised.
Depends on: litellm, httpx, the registry, provider keys in .env
Used by: run before trusting the registry / before activating the router.

Why: a real ping on 2026-06-04 found ~65% of the registry was dead (Cohere
command-r removed, Groq deepseek-r1-distill decommissioned, OpenRouter :free
endpoints gone, Gemini 1.5 off the free API). Free-tier catalogs churn monthly;
a stale registry routes to models that no longer exist. Run this monthly.

$0: the ping is an 8-token completion per model on free tiers.

Usage:
  python scripts/layer3/verify_models.py
  python scripts/layer3/verify_models.py --catalog --out artifacts/layer3/model_verification.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

_KEY = {
    "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY",
    "google": "GEMINI_API_KEY", "cohere": "COHERE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY", "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _load_env_keys() -> None:
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(REPO_ROOT / ".env")
    except Exception:
        return
    for k, v in vals.items():
        if isinstance(k, str) and k.endswith("_API_KEY") and v and k not in os.environ:
            os.environ[k] = v


def _classify(exc: Exception) -> str:
    s = str(exc).lower()
    if "rate" in s or "quota" in s or "429" in s or "resource_exhausted" in s:
        return "rate_limited"
    if "not found" in s or "404" in s or "decommission" in s or "removed" in s or "no endpoints" in s:
        return "dead"
    return "error"


async def _ping(entry) -> dict:
    import litellm
    prov = entry.provider
    params = {
        "model": entry.litellm_model_name,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "max_tokens": 8, "temperature": 0.0, "timeout": 25,
        "api_key": os.environ.get(_KEY.get(prov, ""), ""),
    }
    if prov == "openrouter":
        params["extra_headers"] = {"HTTP-Referer": "http://localhost", "X-Title": "verify"}
    try:
        await litellm.acompletion(**params)
        return {"model_id": entry.model_id, "litellm": entry.litellm_model_name, "status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {
            "model_id": entry.model_id, "litellm": entry.litellm_model_name,
            "status": _classify(exc), "error": str(exc)[:120],
        }


def _catalog_candidates(reg) -> dict:
    """List current provider models NOT already in the registry (add-candidates)."""
    import httpx
    in_registry = {e.litellm_model_name for e in reg.all_models()}
    out: dict[str, list[str]] = {}

    def names(url, headers=None, params=None, key="data", idkey="id"):
        try:
            r = httpx.get(url, headers=headers or {}, params=params or {}, timeout=30).json()
            rows = r.get(key, []) if isinstance(r, dict) else []
            return [x.get(idkey, "") for x in rows]
        except Exception:
            return []

    gk, ok, gem = (os.environ.get("GROQ_API_KEY", ""), os.environ.get("OPENROUTER_API_KEY", ""),
                   os.environ.get("GEMINI_API_KEY", ""))
    groq = [f"groq/{m}" for m in names("https://api.groq.com/openai/v1/models",
                                       {"Authorization": f"Bearer {gk}"})]
    gemini = [f"gemini/{m.replace('models/', '')}" for m in names(
        "https://generativelanguage.googleapis.com/v1beta/models", params={"key": gem, "pageSize": 200},
        key="models", idkey="name")]
    out["groq"] = sorted(m for m in groq if m not in in_registry)
    out["google"] = sorted(m for m in gemini if m not in in_registry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Ping registry models + check catalog drift")
    ap.add_argument("--catalog", action="store_true", help="also list current provider models not in the registry")
    ap.add_argument("--out", default="artifacts/layer3/model_verification.json")
    args = ap.parse_args()

    _load_env_keys()
    logging.disable(logging.CRITICAL)
    from src.layer0_model_infra.routing.registry_loader import get_layer3_registry

    reg = get_layer3_registry()
    reg.refresh_activation()
    actives = sorted(reg.active_models(), key=lambda e: e.model_id)
    print(f"pinging {len(actives)} active models...\n")

    async def _gather():
        return await asyncio.gather(*[_ping(e) for e in actives])
    results = asyncio.run(_gather())
    by_status: dict[str, list[str]] = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["model_id"])
        mark = {"ok": "OK  ", "rate_limited": "RATE", "dead": "DEAD", "error": "ERR "}.get(r["status"], "??? ")
        line = f"  {mark} {r['model_id']}"
        if r["status"] != "ok":
            line += f"  :: {r.get('error', '')}"
        print(line)

    print("\n=== summary ===")
    for status in ("ok", "rate_limited", "dead", "error"):
        ids = by_status.get(status, [])
        if ids:
            print(f"  {status}: {len(ids)}  {ids}")
    if by_status.get("dead"):
        print("\n  ⚠ DEAD models are in the registry — remove or replace them.")

    report = {"pinged": len(actives), "by_status": by_status, "results": results}
    if args.catalog:
        report["catalog_candidates"] = _catalog_candidates(reg)
        print("\n=== catalog models NOT in registry (add-candidates) ===")
        for prov, models in report["catalog_candidates"].items():
            print(f"  {prov}: {models}")

    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 1 if by_status.get("dead") else 0


if __name__ == "__main__":
    sys.exit(main())
