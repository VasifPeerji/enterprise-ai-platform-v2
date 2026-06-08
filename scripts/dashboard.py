"""
Per-layer testing dashboard for the routing system.

Run:
    streamlit run scripts/dashboard.py

What it does:
- Lets you test any individual layer with arbitrary input
- Shows every signal each layer extracts, including detector provenance
- Loads the golden set + wild corpus and shows per-query verdicts
- A/B compare: same query, two configs side by side
- Save to corpus: take an interesting result and pin it as a permanent test case

Same call paths as the production code, so what you see here is what real
users would get.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---- Streamlit page config (must be first st.* call) -----------------------
st.set_page_config(
    page_title="Routing System — Per-Layer Lab",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# Cached detector instances (one per process)
# ============================================================================

@st.cache_resource
def get_fast_path():
    from src.layer0_model_infra.routing.fast_path import FastPathAnalyzer
    fp = FastPathAnalyzer()
    fp.analyze("warmup")
    return fp


@st.cache_resource
def get_modality_gate():
    from src.layer0_model_infra.routing.modality_gate import ModalityGate
    gate = ModalityGate()
    gate.analyze("warmup")
    return gate


@st.cache_resource
def get_semantic_memory():
    from src.layer0_model_infra.routing.semantic_memory import SemanticMemory
    # Use a fresh in-memory instance for the dashboard so users can experiment
    # without contaminating the production SQLite cache.
    mem = SemanticMemory(
        similarity_threshold=0.75,
        enable_local_embedding=True,
        enable_persistence=False,
    )
    return mem


@st.cache_resource
def get_knn_router():
    """Layer 3 benchmark kNN router (production singleton). Warmed up on first
    load so the first manual route doesn't pay the ~20-40s encoder cold-start.
    Loaded lazily — only when an L3 page is opened — so other pages stay snappy.
    """
    from src.layer0_model_infra.routing.knn_router import get_knn_router as _get
    router = _get()
    router.warmup()
    return router


@st.cache_resource
def get_question_text_lookup() -> dict:
    """Map question_global_id -> question_text so the manual page can show the
    actual text of each kNN neighbor (the RoutingDecision only carries the ids).
    """
    path = REPO_ROOT / "data/processed/questions.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path, columns=["question_global_id", "question_text"])
    return dict(zip(df["question_global_id"], df["question_text"]))


# ============================================================================
# Helpers
# ============================================================================

ARTIFACTS = REPO_ROOT / "artifacts"

def load_json(path: Path) -> dict:
    if not path.exists():
        return {"queries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def color_badge(label: str, value: Any, ok: bool = True) -> str:
    """Render a colored badge for a single result field."""
    color = "#22c55e" if ok else "#ef4444"
    return f'<span style="background:{color}22; color:{color}; padding:2px 8px; border-radius:6px; font-family:monospace; font-size:0.85em;">{label}: {value}</span>'


def latency_metric(label: str, microseconds: float):
    """Show a latency metric with auto-scaled units."""
    if microseconds < 1000:
        st.metric(label, f"{microseconds:.0f} μs")
    else:
        st.metric(label, f"{microseconds / 1000:.2f} ms")


def _mod_value(features) -> str:
    """QueryFeatures.modality may be an enum or a bare string — normalise it."""
    m = features.modality
    return m.value if hasattr(m, "value") else str(m)


# ============================================================================
# Layer 0 page
# ============================================================================

def render_layer_0_manual(fp):
    st.subheader("Layer 0 — Fast Path (manual)")
    st.caption(
        "Sub-millisecond bypass for trivial queries. Returns should_bypass + "
        "category + recommended model. No LLM calls."
    )

    col_q, col_btn = st.columns([5, 1])
    with col_q:
        query = st.text_area(
            "Query",
            value=st.session_state.get("l0_query", "hi"),
            height=80,
            key="l0_query_input",
        )
    with col_btn:
        st.write("")
        st.write("")
        run = st.button("Run ▶", type="primary", key="l0_run", use_container_width=True)

    if run or st.session_state.get("l0_query") != query:
        st.session_state["l0_query"] = query
        t0 = time.perf_counter_ns()
        decision = fp.analyze(query)
        t1 = time.perf_counter_ns()
        latency_us = (t1 - t0) / 1000

        # Top row: 4 metric cards
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(color_badge(
                "should_bypass",
                str(decision.should_bypass).upper(),
                ok=decision.should_bypass,
            ), unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge("category", decision.category.value), unsafe_allow_html=True)
        with c3:
            st.markdown(color_badge("language", decision.detected_language or "(none)"), unsafe_allow_html=True)
        with c4:
            latency_metric("Latency", latency_us)

        st.markdown("---")

        col_l, col_r = st.columns([1, 1])
        with col_l:
            st.markdown("**Decision**")
            st.json({
                "should_bypass": decision.should_bypass,
                "category": decision.category.value,
                "recommended_model": decision.recommended_model,
                "matched_pattern": decision.matched_pattern,
                "detected_language": decision.detected_language,
                "confidence": decision.confidence,
            })
        with col_r:
            st.markdown("**Fallback chain (registry-walked)**")
            st.json(decision.fallback_chain)
            st.markdown("**Reasoning**")
            st.code(decision.reasoning, language="text")

        # Save-to-corpus action
        with st.expander("📌 Save this query to wild corpus"):
            with st.form("l0_save_form", clear_on_submit=True):
                category_options = ["paraphrase", "negative", "adversarial", "edge_cases", "other"]
                cat = st.selectbox("Category", category_options)
                note = st.text_input("Optional note", placeholder="why is this interesting?")
                expected = st.text_input("Expected bypass label (true/false/leave blank)", value="")
                submitted = st.form_submit_button("Append to artifacts/layer_0/wild_corpus.json")
                if submitted:
                    path = ARTIFACTS / "layer_0" / "wild_corpus.json"
                    payload = load_json(path)
                    payload.setdefault("queries", []).append({
                        "query": query,
                        "category": cat,
                        "note": note,
                        "expected_bypass": expected.lower().strip() if expected else None,
                        "source": "dashboard_saved",
                    })
                    payload.setdefault("_meta", {})["last_updated"] = time.strftime("%Y-%m-%d")
                    save_json(path, payload)
                    st.success(f"Saved. Corpus now has {len(payload['queries'])} entries.")


def render_layer_1_manual(gate):
    st.subheader("Layer 1 — Modality Gate (manual)")
    st.caption(
        "Extracts orthogonal signals: language, code, structured data, "
        "vision relevance, injection risk. Sub-50ms."
    )

    col_q, col_btn = st.columns([5, 1])
    with col_q:
        query = st.text_area(
            "Query",
            value=st.session_state.get("l1_query", "Hola amigo, ¿cómo estás?"),
            height=120,
            key="l1_query_input",
        )
    with col_btn:
        st.write("")
        st.write("")
        run = st.button("Run ▶", type="primary", key="l1_run", use_container_width=True)

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        has_images = st.checkbox("has_images", value=False, key="l1_img")
    with col_b:
        image_count = st.number_input("image_count", min_value=0, max_value=10,
                                       value=1 if has_images else 0, key="l1_imgn")
    with col_c:
        has_audio = st.checkbox("has_audio", value=False, key="l1_audio")
    with col_d:
        has_video = st.checkbox("has_video", value=False, key="l1_video")

    if run or st.session_state.get("l1_query") != query:
        st.session_state["l1_query"] = query
        t0 = time.perf_counter_ns()
        result = gate.analyze(
            text=query, has_images=has_images, image_count=image_count,
            has_audio=has_audio, has_video=has_video,
        )
        t1 = time.perf_counter_ns()
        latency_us = (t1 - t0) / 1000

        # Top badges
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(color_badge("modality", result.primary_modality.value),
                       unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge(
                "language", f"{result.language} ({result.language_detector_used})",
            ), unsafe_allow_html=True)
        with c3:
            st.markdown(color_badge(
                "validation",
                "PASSED" if result.validation_passed else "BLOCKED",
                ok=result.validation_passed,
            ), unsafe_allow_html=True)
        with c4:
            latency_metric("Latency", latency_us)

        # Requirement flags
        st.markdown("##### Capability requirements")
        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            st.markdown(color_badge(
                "requires_vision",
                str(result.requires_vision).upper(),
                ok=not result.requires_vision,
            ), unsafe_allow_html=True)
        with rc2:
            st.markdown(color_badge(
                "requires_audio",
                str(result.requires_audio).upper(),
                ok=not result.requires_audio,
            ), unsafe_allow_html=True)
        with rc3:
            st.markdown(color_badge(
                "requires_code_model",
                str(result.requires_code_model).upper(),
                ok=not result.requires_code_model,
            ), unsafe_allow_html=True)
        with rc4:
            st.markdown(color_badge(
                "multimodal_required",
                str(result.multimodal_required).upper(),
                ok=not result.multimodal_required,
            ), unsafe_allow_html=True)

        st.markdown("---")

        col_l, col_r = st.columns([1, 1])
        with col_l:
            st.markdown("**Extracted signals**")
            st.json({
                "primary_modality": result.primary_modality.value,
                "language": result.language,
                "language_confidence": round(result.language_confidence, 3),
                "language_detector_used": result.language_detector_used,
                "code_density": result.code_density,
                "code_language": result.code_language,
                "code_detector_used": result.code_detector_used,
                "structured_format": result.structured_format,
                "table_density": result.table_density,
                "token_count": result.token_count,
                "contains_injection_risk": result.contains_injection_risk,
            })
        with col_r:
            st.markdown("**Weights**")
            st.json(result.weights.model_dump())
            st.markdown("**Reasoning**")
            st.code(result.reasoning, language="text")

        with st.expander("📌 Save this query to wild corpus"):
            with st.form("l1_save_form", clear_on_submit=True):
                category_options = ["casual_voice_to_text", "customer_support",
                                    "code_with_stacktrace", "mixed_language",
                                    "edge_cases", "injection_attempts", "other"]
                cat = st.selectbox("Category", category_options, key="l1_save_cat")
                expected_mod = st.text_input("acceptable_modalities (comma-separated)",
                                              value=result.primary_modality.value)
                expected_lang = st.text_input("acceptable_languages (comma-separated)",
                                               value=result.language)
                submitted = st.form_submit_button("Append to artifacts/layer_1/wild_corpus.json")
                if submitted:
                    path = ARTIFACTS / "layer_1" / "wild_corpus.json"
                    payload = load_json(path)
                    next_id = f"ad_hoc_{len(payload.get('queries', [])):04d}"
                    payload.setdefault("queries", []).append({
                        "id": next_id,
                        "category": cat,
                        "query": query,
                        "acceptable_modalities": [x.strip() for x in expected_mod.split(",") if x.strip()],
                        "acceptable_languages": [x.strip() for x in expected_lang.split(",") if x.strip()],
                        "must_validate": True,
                        "source": "dashboard_saved",
                    })
                    save_json(path, payload)
                    st.success(f"Saved as {next_id}. Corpus now has {len(payload['queries'])} entries.")


# ============================================================================
# Layer 2 — Semantic Memory
# ============================================================================

def render_layer_2_manual(mem):
    st.subheader("Layer 2 — Semantic Memory (manual)")
    st.caption(
        "Outcome-aware cache. Use the **record** tab to populate, then **lookup** "
        "to test what hits and what doesn't. Provenance shows which guard fired (if any)."
    )

    cache_tab, lookup_tab, stats_tab = st.tabs(["📝 Record", "🔎 Lookup", "📊 Stats"])

    with cache_tab:
        col_q, col_btn = st.columns([5, 1])
        with col_q:
            record_q = st.text_area(
                "Query to cache",
                value=st.session_state.get("l2_record_q", "How do I sort a list in Python?"),
                height=80, key="l2_record_q_in",
            )

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            model_id = st.text_input("model_id", value="ollama-llama3.1-8b", key="l2_model")
            tenant_id = st.text_input("tenant_id (optional)", value="", key="l2_tenant")
        with col_b:
            quality = st.slider("quality_score", 0.0, 1.0, 0.9, step=0.05, key="l2_qual")
            escalated = st.checkbox("escalated", value=False, key="l2_esc")
        with col_c:
            intent = st.text_input("intent", value="coding", key="l2_intent")
            domain = st.text_input("domain", value="tech", key="l2_domain")

        if col_btn.button("Record", type="primary", key="l2_record_btn", use_container_width=True):
            mem.record(
                query=record_q, model_id=model_id, quality_score=quality,
                escalated=escalated, intent=intent, domain=domain,
                tenant_id=tenant_id,
            )
            st.success(f"Recorded. Cache now has {mem.stats()['total_entries']} entries.")
            st.session_state["l2_record_q"] = record_q

    with lookup_tab:
        col_q, col_btn = st.columns([5, 1])
        with col_q:
            lookup_q = st.text_area(
                "Lookup query",
                value=st.session_state.get("l2_lookup_q", "What's the python way to sort a list?"),
                height=80, key="l2_lookup_q_in",
            )

        col_a, col_b = st.columns(2)
        with col_a:
            lookup_intent = st.text_input("query_intent (optional)", value="", key="l2_lookup_intent")
        with col_b:
            lookup_tenant = st.text_input("tenant_id (optional)", value="", key="l2_lookup_tenant")

        if col_btn.button("Lookup ▶", type="primary", key="l2_lookup_btn", use_container_width=True):
            import time as _time
            t0 = _time.perf_counter_ns()
            result = mem.lookup(lookup_q, query_intent=lookup_intent, tenant_id=lookup_tenant)
            t1 = _time.perf_counter_ns()
            latency_us = (t1 - t0) / 1000
            st.session_state["l2_lookup_q"] = lookup_q

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(color_badge(
                    "verdict", "HIT" if result.hit else "MISS", ok=result.hit,
                ), unsafe_allow_html=True)
            with c2:
                st.markdown(color_badge(
                    "similarity", f"{result.similarity:.3f}"
                ), unsafe_allow_html=True)
            with c3:
                st.markdown(color_badge("detector", result.detector_used),
                           unsafe_allow_html=True)
            with c4:
                latency_metric("Latency", latency_us)

            st.markdown("---")

            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown("**Lookup result**")
                st.json({
                    "hit": result.hit,
                    "matched_model_id": result.matched_model_id,
                    "similarity": round(result.similarity, 4),
                    "novelty_score": round(result.novelty_score, 4),
                    "detector_used": result.detector_used,
                    "guard_rejected": result.guard_rejected,
                    "embedding_id": result.embedding_id,
                    "cached_intent": result.cached_intent,
                    "cached_domain": result.cached_domain,
                    "cached_complexity_band": result.cached_complexity_band,
                })
            with col_r:
                st.markdown("**Reasoning**")
                st.code(result.reasoning, language="text")
                if result.guard_rejected:
                    st.warning(f"⚠️ Guard fired: `{result.guard_rejected}`")
                elif result.hit:
                    st.success(f"✓ Cache hit → reuses model `{result.matched_model_id}`")
                else:
                    st.info("Not in cache. Full pipeline would run.")

    with stats_tab:
        s = mem.stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total entries", s["total_entries"])
        c2.metric("Reusable entries", s["reusable_entries"])
        c3.metric("Lookups", s["lookup_count"])
        c4.metric("Hit rate (actual)", f"{s['hit_rate_actual']:.1%}",
                   f"{s['hit_count']} hits")

        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Latency saved", f"{s['latency_saved_us']/1000:.1f} ms")
        cc2.metric("Embedder available", "✓" if s["embedder_available"] else "✗")
        cc3.metric("Persistence enabled", "✓" if s["persistence_enabled"] else "✗")

        if s["guard_rejections"]:
            st.markdown("##### Guard rejection breakdown")
            st.json(s["guard_rejections"])

        if st.button("🗑️  Clear in-memory cache"):
            mem._store.clear()
            mem._embeddings.clear()
            mem._lookup_count = 0
            mem._hit_count = 0
            mem._latency_saved_us = 0.0
            mem._guard_rejection_counts.clear()
            st.success("Cache cleared.")


# ============================================================================
# Layer 3 — Benchmark kNN Router
# ============================================================================

def render_layer_3_manual(router, qtext):
    st.subheader("Layer 3 — Benchmark kNN Router (manual)")
    st.caption(
        "Predicts per-model quality from the benchmark corpus and picks the "
        "cheapest model clearing the quality floor. Stage A cache → B features → "
        "C kNN/prior + calibration → D fallback. First route warms the encoder (~20-40s)."
    )

    col_q, col_btn = st.columns([5, 1])
    with col_q:
        query = st.text_area(
            "Query",
            value=st.session_state.get("l3_query", "What is the derivative of x^2 * sin(x)?"),
            height=100,
            key="l3_query_input",
        )
    with col_btn:
        st.write("")
        st.write("")
        run = st.button("Route ▶", type="primary", key="l3_run", use_container_width=True)

    if run or st.session_state.get("l3_query") != query:
        st.session_state["l3_query"] = query
        with st.spinner("Routing (first call warms the encoder)…"):
            d = router.route(query)
        feats = d.features

        # Top badges
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(color_badge("selected", d.selected_model,
                        ok=(d.source.value != "fallback")), unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge("source", d.source.value,
                        ok=(d.source.value == "knn_corpus")), unsafe_allow_html=True)
        with c3:
            pq = f"{d.predicted_quality:.3f}" if d.predicted_quality is not None else "—"
            st.markdown(color_badge("pred_quality", pq), unsafe_allow_html=True)
        with c4:
            st.metric("Latency", f"{d.latency_ms:.0f} ms")

        # Second row: confidence / floor / cost / high-risk
        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.markdown(color_badge("confidence", d.prediction_confidence,
                        ok=(d.prediction_confidence == "high")), unsafe_allow_html=True)
        with c6:
            ef = f"{d.effective_floor:.2f}" if d.effective_floor is not None else "—"
            st.markdown(color_badge("eff_floor", ef), unsafe_allow_html=True)
        with c7:
            st.markdown(color_badge("est_cost", f"${d.estimated_cost_usd:.6f}"), unsafe_allow_html=True)
        with c8:
            hr = feats.high_risk_domain.value if feats.high_risk_domain else "none"
            st.markdown(color_badge("high_risk", hr, ok=(feats.high_risk_domain is None)),
                        unsafe_allow_html=True)

        if d.source.value == "fallback":
            st.warning(
                f"⚠️ Stage D fallback — reason `{d.fallback_reason}`. Routed to the safe "
                f"default for modality `{_mod_value(feats)}`. Answer quality is preserved; "
                f"only cost-optimization is limited (off-distribution / thin corpus coverage)."
            )
        elif d.source.value == "knn_corpus":
            st.success(
                f"✓ kNN-grounded route. {len(d.qualifying_models)} model(s) cleared the "
                f"floor; the cheapest was selected."
            )
        else:
            st.info(f"Source `{d.source.value}` — off-policy (ε-exploration / warmup / forced).")

        st.markdown("---")
        col_l, col_r = st.columns([1, 1])
        with col_l:
            st.markdown("**Extracted features (Stage B)**")
            st.json({
                "modality": _mod_value(feats),
                "language": feats.language,
                "high_risk_domain": feats.high_risk_domain.value if feats.high_risk_domain else None,
                "difficulty_signal": getattr(feats.difficulty_signal, "value", str(feats.difficulty_signal)),
                "estimated_input_tokens": feats.estimated_input_tokens,
                "estimated_output_tokens": feats.estimated_output_tokens,
                "char_count": feats.char_count,
            })
        with col_r:
            st.markdown("**Quality floor & calibration**")
            st.json({
                "quality_floor_base": d.quality_floor_base,
                "effective_floor": d.effective_floor,
                "feature_cell": d.feature_cell,
                "calibration_multiplier_applied": d.calibration_multiplier_applied,
            })

        # kNN neighbors (top 5) with their question text
        st.markdown("##### kNN neighbors (top 5)")
        if d.neighbors_used:
            nrows = [{
                "question_global_id": qid,
                "similarity": round(s, 4),
                "question_text": (qtext.get(qid, "(text unavailable)") or "")[:140],
            } for qid, s in d.neighbors_used[:5]]
            st.dataframe(pd.DataFrame(nrows), use_container_width=True, hide_index=True)
        else:
            st.caption("No neighbors — fallback fired before search, or search returned none.")

        # Per-model predicted quality
        st.markdown("##### Per-model predicted quality")
        if d.all_model_qualities:
            qualifying = set(d.qualifying_models)
            qual_rows = [{
                "model_id": mid,
                "predicted_quality": round(q, 4),
                "qualifies": "✓" if mid in qualifying else "",
                "selected": "★" if mid == d.selected_model else "",
            } for mid, q in sorted(d.all_model_qualities.items(), key=lambda kv: -kv[1])]
            st.dataframe(pd.DataFrame(qual_rows), use_container_width=True, hide_index=True, height=320)
            st.caption(f"Qualifying (cheapest-first): {d.qualifying_models}")
        else:
            st.caption("No per-model qualities computed (fallback path skips Stage C scoring).")


def render_layer_3_corpus(router, qtext):
    st.subheader("Corpus runner — Layer 3")
    st.caption(
        "Route a sample of the 650-query locked validation set through the kNN "
        "router. Surfaces kNN-engagement vs fallback rate, latency, and a "
        "per-modality engagement breakdown."
    )
    val_path = REPO_ROOT / "data/processed/validation_set.parquet"
    if not val_path.exists():
        st.warning(f"validation_set.parquet not found at {val_path}.")
        return
    df_val = pd.read_parquet(val_path)
    n_max = len(df_val)
    n = st.slider("Sample size (first N, for reproducibility)", min_value=5,
                  max_value=min(n_max, 300), value=30, step=5, key="l3_corpus_n")
    st.caption(f"{n_max} validation queries available; routing the first {n}.")

    if st.button("Run on Layer 3", type="primary", key="l3_corpus_run"):
        sample = df_val.head(n)
        rows = []
        prog = st.progress(0.0)
        with st.spinner("Routing sample (first call warms the encoder)…"):
            for i, (_, row) in enumerate(sample.iterrows()):
                q = str(row["question_text"])
                d = router.route(q)
                rows.append({
                    "id": row["question_global_id"],
                    "query": q[:60] + ("…" if len(q) > 60 else ""),
                    "modality": _mod_value(d.features),
                    "source": d.source.value,
                    "selected_model": d.selected_model,
                    "pred_quality": round(d.predicted_quality, 3) if d.predicted_quality is not None else None,
                    "fallback_reason": d.fallback_reason or "",
                    "latency_ms": round(d.latency_ms, 1),
                })
                prog.progress((i + 1) / n)
        prog.empty()
        df = pd.DataFrame(rows)

        knn_n = int((df["source"] == "knn_corpus").sum())
        fb_n = int((df["source"] == "fallback").sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Queries", len(df))
        c2.metric("kNN-engaged", f"{knn_n/len(df):.0%}", f"{knn_n}")
        c3.metric("Fallback", f"{fb_n/len(df):.0%}", f"{fb_n}")
        c4.metric("p50 / p99 latency",
                  f"{df['latency_ms'].median():.0f} / {df['latency_ms'].quantile(0.99):.0f} ms")

        src = df["source"].value_counts().reset_index()
        src.columns = ["source", "count"]
        fig = px.bar(src, x="source", y="count", title="Routing-source distribution",
                     color="source", color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(height=280, showlegend=False, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

        if df["modality"].nunique() > 1:
            mod_eng = df.assign(_knn=(df["source"] == "knn_corpus")).groupby("modality").agg(
                total=("modality", "count"), knn=("_knn", "sum")).reset_index()
            mod_eng["knn_rate"] = mod_eng["knn"] / mod_eng["total"]
            fig2 = px.bar(mod_eng, x="modality", y="knn_rate", title="kNN engagement by modality",
                          hover_data=["knn", "total"], color="knn_rate",
                          color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"], range_color=[0, 1])
            fig2.update_layout(height=280, yaxis_tickformat=".0%")
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("##### All results")
        st.dataframe(df, use_container_width=True, height=400)
        st.download_button(
            "📥 Download results.json",
            data=df.to_json(orient="records", indent=2),
            file_name="layer_3_validation_dashboard_run.json",
            mime="application/json",
        )


# ============================================================================
# Pipeline page — Layer 0 → Layer 3
# ============================================================================

def render_pipeline(fp, gate, mem, router, qtext):
    st.subheader("End-to-end: Layer 0 → Layer 1 → Layer 2 → Layer 3")
    st.caption(
        "Real orchestrator order. Layer 0 bypass short-circuits everything; a "
        "Layer 2 cache hit serves the cached model and stops; otherwise Layer 3 "
        "(the kNN router) makes the call. First L3 route warms the encoder (~20-40s)."
    )

    query = st.text_area("Query", value="Hi, can you help me debug this Python function: def add(a, b): return a + b",
                         height=100, key="pipe_q")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        has_images = st.checkbox("has_images", value=False, key="pipe_img")
    with col_b:
        has_audio = st.checkbox("has_audio", value=False, key="pipe_audio")
    with col_c:
        run = st.button("Run pipeline ▶", type="primary", key="pipe_run", use_container_width=True)

    if run or "pipe_last" not in st.session_state:
        st.session_state["pipe_last"] = query

        # Step 1: Layer 0
        t0 = time.perf_counter_ns()
        fp_decision = fp.analyze(query)
        t1 = time.perf_counter_ns()
        l0_latency = (t1 - t0) / 1000

        st.markdown("##### 🚪 Layer 0 — Fast Path")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(color_badge("bypass", str(fp_decision.should_bypass).upper(),
                                     ok=fp_decision.should_bypass), unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge("category", fp_decision.category.value),
                       unsafe_allow_html=True)
        with c3:
            latency_metric("L0 latency", l0_latency)

        if fp_decision.should_bypass:
            st.success(
                f"✓ Bypassed. Recommended model: **{fp_decision.recommended_model}**. "
                f"Downstream layers skipped."
            )
            with st.expander("L0 details"):
                st.json({
                    "should_bypass": fp_decision.should_bypass,
                    "category": fp_decision.category.value,
                    "recommended_model": fp_decision.recommended_model,
                    "matched_pattern": fp_decision.matched_pattern,
                    "language": fp_decision.detected_language,
                    "reasoning": fp_decision.reasoning,
                })
            return

        # Step 2: Layer 1
        st.info("Layer 0 did not bypass → running Layer 1.")
        t0 = time.perf_counter_ns()
        m = gate.analyze(text=query, has_images=has_images, image_count=1 if has_images else 0,
                          has_audio=has_audio)
        t1 = time.perf_counter_ns()
        l1_latency = (t1 - t0) / 1000

        st.markdown("##### 🔎 Layer 1 — Modality Gate")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(color_badge("modality", m.primary_modality.value),
                       unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge("language", f"{m.language} ({m.language_detector_used})"),
                       unsafe_allow_html=True)
        with c3:
            st.markdown(color_badge("validation",
                                     "PASSED" if m.validation_passed else "BLOCKED",
                                     ok=m.validation_passed), unsafe_allow_html=True)
        with c4:
            latency_metric("L1 latency", l1_latency)

        # Step 3: Layer 2 — semantic memory
        st.markdown("##### 🧠 Layer 2 — Semantic Memory")
        t0 = time.perf_counter_ns()
        l2 = mem.lookup(query)
        t1 = time.perf_counter_ns()
        l2_latency = (t1 - t0) / 1000
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(color_badge("verdict", "HIT" if l2.hit else "MISS", ok=l2.hit),
                        unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge("similarity", f"{l2.similarity:.3f}"), unsafe_allow_html=True)
        with c3:
            latency_metric("L2 latency", l2_latency)

        if l2.hit:
            st.success(
                f"✓ Cache hit → the router serves cached model `{l2.matched_model_id}` and stops. "
                f"(This dashboard's L2 cache starts empty — populate it on the Layer 2 page to see hits.)"
            )
            st.markdown(f"**Total latency:** {(l0_latency + l1_latency + l2_latency) / 1000:.2f} ms")
            return
        st.info("Layer 2 miss → running Layer 3.")

        # Step 4: Layer 3 — benchmark kNN router (reuses Layer 1's analysis)
        l3 = router.route(query, layer1_analysis=m)
        st.markdown("##### 🎯 Layer 3 — Benchmark kNN Router")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(color_badge("selected", l3.selected_model,
                        ok=(l3.source.value != "fallback")), unsafe_allow_html=True)
        with c2:
            st.markdown(color_badge("source", l3.source.value,
                        ok=(l3.source.value == "knn_corpus")), unsafe_allow_html=True)
        with c3:
            pq = f"{l3.predicted_quality:.3f}" if l3.predicted_quality is not None else "—"
            st.markdown(color_badge("pred_quality", pq), unsafe_allow_html=True)
        with c4:
            st.metric("L3 latency", f"{l3.latency_ms:.0f} ms")

        if l3.source.value == "fallback":
            st.warning(f"⚠️ Stage D fallback — `{l3.fallback_reason}` → safe default `{l3.selected_model}`.")
        else:
            st.success(
                f"✓ Routed to **{l3.selected_model}** — {len(l3.qualifying_models)} cleared the "
                f"floor, cheapest selected."
            )

        cpu_ms = (l0_latency + l1_latency + l2_latency) / 1000
        st.markdown(
            f"**Total pipeline latency:** {cpu_ms + l3.latency_ms:.1f} ms "
            f"(L0+L1+L2 {cpu_ms:.2f} ms + L3 {l3.latency_ms:.0f} ms)"
        )

        with st.expander("Layer details (L1 + L3)"):
            st.markdown("**Layer 1 — Modality Gate**")
            st.json({
                "primary_modality": m.primary_modality.value,
                "language": m.language,
                "code_language": m.code_language,
                "structured_format": m.structured_format,
                "requires_vision": m.requires_vision,
                "requires_code_model": m.requires_code_model,
                "token_count": m.token_count,
            })
            st.markdown("**Layer 3 — kNN Router**")
            st.json({
                "selected_model": l3.selected_model,
                "source": l3.source.value,
                "predicted_quality": l3.predicted_quality,
                "effective_floor": l3.effective_floor,
                "fallback_reason": l3.fallback_reason,
                "qualifying_models": l3.qualifying_models,
                "feature_cell": l3.feature_cell,
            })


# ============================================================================
# Batch runner — Golden set / Wild corpus / arbitrary
# ============================================================================

def run_layer_0_on_corpus(fp, queries: list[dict]) -> pd.DataFrame:
    rows = []
    for q in queries:
        query = q.get("query", "")
        t0 = time.perf_counter_ns()
        d = fp.analyze(query)
        t1 = time.perf_counter_ns()
        rows.append({
            "id": q.get("id", q.get("query", "")[:30]),
            "category": q.get("category", q.get("source", "")),
            "query": query[:60] + ("…" if len(query) > 60 else ""),
            "expected_bypass": q.get("expected_bypass"),
            "actual_bypass": d.should_bypass,
            "actual_category": d.category.value,
            "model": d.recommended_model,
            "lang": d.detected_language or "",
            "latency_us": round((t1 - t0) / 1000, 1),
            "match": (q.get("expected_bypass") is None) or (d.should_bypass == q.get("expected_bypass")),
        })
    return pd.DataFrame(rows)


def run_layer_1_on_corpus(gate, queries: list[dict]) -> pd.DataFrame:
    rows = []
    for q in queries:
        query = q.get("query", "")
        t0 = time.perf_counter_ns()
        m = gate.analyze(
            text=query,
            has_images=q.get("has_images", False),
            has_audio=q.get("has_audio", False),
            image_count=q.get("image_count", 0),
        )
        t1 = time.perf_counter_ns()

        # Verdict
        acceptable_mod = q.get("acceptable_modalities") or (
            [q["expected_modality"]] if q.get("expected_modality") else None
        )
        acceptable_lang = q.get("acceptable_languages") or (
            [q["expected_language"]] if q.get("expected_language") else None
        )
        modality_ok = (acceptable_mod is None) or (m.primary_modality.value in acceptable_mod)
        language_ok = (acceptable_lang is None) or (m.language in acceptable_lang)
        validation_ok = (
            (q.get("should_block") and not m.validation_passed)
            or (not q.get("should_block") and m.validation_passed)
        )
        ok = modality_ok and language_ok and validation_ok

        rows.append({
            "id": q.get("id", q.get("query", "")[:30]),
            "category": q.get("category", q.get("source", "")),
            "query": query[:60] + ("…" if len(query) > 60 else ""),
            "modality": m.primary_modality.value,
            "lang": m.language,
            "lang_method": m.language_detector_used,
            "code_lang": m.code_language,
            "structured": m.structured_format,
            "validation": m.validation_passed,
            "latency_us": round((t1 - t0) / 1000, 1),
            "pass": ok,
            "modality_ok": modality_ok,
            "language_ok": language_ok,
            "validation_ok": validation_ok,
        })
    return pd.DataFrame(rows)


def render_corpus_runner(fp, gate, layer_idx: int):
    st.subheader(f"Corpus runner — Layer {layer_idx}")
    corpus_dir = ARTIFACTS / f"layer_{layer_idx}"
    available = sorted(p.name for p in corpus_dir.glob("*.json")
                        if p.name in ("golden_set.json", "wild_corpus.json"))
    if not available:
        st.warning(f"No corpus files found under {corpus_dir}.")
        return

    selected = st.selectbox("Corpus", available, key=f"cr_corpus_l{layer_idx}")
    payload = load_json(corpus_dir / selected)
    queries = payload.get("queries", [])
    st.caption(f"{len(queries)} queries loaded")

    if st.button(f"Run on Layer {layer_idx}", type="primary", key=f"cr_run_l{layer_idx}"):
        with st.spinner("Running..."):
            if layer_idx == 0:
                df = run_layer_0_on_corpus(fp, queries)
            else:
                df = run_layer_1_on_corpus(gate, queries)

        # Aggregate metrics
        passes = df["match" if layer_idx == 0 else "pass"].sum()
        total = len(df)
        pass_rate = passes / total if total else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total cases", total)
        c2.metric("Passing", f"{passes}/{total}", f"{pass_rate:.1%}")
        c3.metric("p50 latency", f"{df['latency_us'].median():.0f} μs")
        c4.metric("p99 latency", f"{df['latency_us'].quantile(0.99):.0f} μs")

        # Latency distribution chart
        fig = px.histogram(df, x="latency_us", nbins=20,
                            title="Latency distribution (μs)",
                            color_discrete_sequence=["#3b82f6"])
        fig.update_layout(showlegend=False, height=250, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

        # Per-category pass rate
        if "category" in df.columns and df["category"].nunique() > 1:
            cat_pass = df.groupby("category").agg(
                total=("category", "count"),
                passing=("match" if layer_idx == 0 else "pass", "sum"),
            ).reset_index()
            cat_pass["pass_rate"] = cat_pass["passing"] / cat_pass["total"]
            fig2 = px.bar(cat_pass, x="category", y="pass_rate",
                           title="Per-category pass rate",
                           hover_data=["passing", "total"],
                           color="pass_rate",
                           color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"],
                           range_color=[0, 1])
            fig2.update_layout(height=300, xaxis_tickangle=-30, yaxis_tickformat=".0%")
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("##### All results")
        # Highlight failures
        def highlight_fail(row):
            col = "match" if layer_idx == 0 else "pass"
            if not row[col]:
                return ["background-color: #fef2f2"] * len(row)
            return [""] * len(row)

        st.dataframe(df.style.apply(highlight_fail, axis=1), use_container_width=True, height=400)

        # Download as JSON
        st.download_button(
            "📥 Download results.json",
            data=df.to_json(orient="records", indent=2),
            file_name=f"layer_{layer_idx}_{selected.replace('.json','')}_dashboard_run.json",
            mime="application/json",
        )


# ============================================================================
# A/B Compare
# ============================================================================

def render_ab_compare(fp, gate):
    st.subheader("A/B compare — same query, two configs")
    st.caption(
        "Useful for tuning thresholds, deciding whether a Tier 2 library helps, "
        "or comparing language-detector confidence thresholds."
    )

    query = st.text_area("Query", value="login broken", height=80, key="ab_query")

    st.markdown("##### Configurations")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**A: current production**")
        a_use_tier2 = st.checkbox("enable Tier 2 (lingua + pygments)", value=True, key="ab_a_tier2")
        a_conf_thr = st.slider("language confidence threshold", 0.0, 1.0, 0.55, step=0.05, key="ab_a_thr")
    with col_b:
        st.markdown("**B: experimental**")
        b_use_tier2 = st.checkbox("enable Tier 2 (lingua + pygments)", value=False, key="ab_b_tier2")
        b_conf_thr = st.slider("language confidence threshold", 0.0, 1.0, 0.55, step=0.05, key="ab_b_thr")

    if st.button("Compare ▶", type="primary", key="ab_run"):
        from src.layer0_model_infra.routing.modality_gate import ModalityGate
        # Build two gates with different config overrides
        def build_gate(use_tier2: bool, conf_thr: float):
            g = ModalityGate()
            # Reach into the config — for this A/B we override at the instance level
            g._cfg.enable_semantic_language_detection = use_tier2
            g._cfg.language_confidence_threshold = conf_thr
            # Re-link detector to honor new config
            if not use_tier2:
                g._language_detector = None
            return g

        gate_a = build_gate(a_use_tier2, a_conf_thr)
        gate_b = build_gate(b_use_tier2, b_conf_thr)

        col_a, col_b = st.columns(2)
        for col, g, label in [(col_a, gate_a, "A"), (col_b, gate_b, "B")]:
            with col:
                st.markdown(f"##### Result {label}")
                t0 = time.perf_counter_ns()
                m = g.analyze(text=query)
                t1 = time.perf_counter_ns()
                latency_us = (t1 - t0) / 1000
                st.markdown(color_badge("modality", m.primary_modality.value),
                           unsafe_allow_html=True)
                st.markdown(color_badge(
                    "language", f"{m.language} (conf {m.language_confidence:.2f})"
                ), unsafe_allow_html=True)
                st.markdown(color_badge(
                    "detector", m.language_detector_used,
                ), unsafe_allow_html=True)
                latency_metric("Latency", latency_us)
                st.code(m.reasoning, language="text")

        # Restore the cached gate (the cached instance shares config with both
        # arms otherwise; rebuild the cache resource)
        get_modality_gate.clear()


# ============================================================================
# Layer 9 — Telemetry & Drift Observability
# ============================================================================

def render_layer_9_observability():
    st.subheader("Layer 9 — Telemetry & Drift Observability")
    st.caption(
        "Live view of the in-process routing telemetry buffer and the Layer 3 "
        "prediction-drift detector. The buffer fills as you route queries on the "
        "Layer 3 / Pipeline / Corpus pages (same process), so route a few first."
    )
    from src.layer0_model_infra.routing.telemetry import TelemetryLogger
    from src.layer0_model_infra.routing.drift_detector import get_drift_detector

    with TelemetryLogger._lock:
        buf = list(TelemetryLogger._buffer)
    stats = TelemetryLogger.get_buffer_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Buffered events", stats.get("buffer_size", 0))
    c2.metric("Escalation rate", f"{stats.get('escalation_rate', 0):.0%}" if buf else "—")
    c3.metric("Avg quality", f"{stats.get('avg_quality', 0):.3f}" if buf else "—")
    c4.metric("Avg latency", f"{stats.get('avg_latency_ms', 0):.0f} ms" if buf else "—")

    if not buf:
        st.info(
            "Telemetry buffer is empty. Route a few queries on the **Layer 3 — manual**, "
            "**Pipeline**, or **Corpus runner — Layer 3** pages (this same process), then "
            "return here. In production the buffer fills from live traffic and is also "
            "persisted to the routing_telemetry table for offline analysis."
        )
        return

    df = pd.DataFrame([{
        "request_id": t.request_id,
        "selected_model": t.selected_model_id,
        "routing_source": t.routing_source or "(n/a)",
        "predicted_quality": round(t.predicted_quality, 3),
        "prediction_confidence": round(t.prediction_confidence_score, 3),
        "uncertainty_escalated": t.uncertainty_escalated,
        "domain": t.domain,
        "cost_usd": round(t.cost_usd, 6),
        "latency_ms": round(t.latency_ms, 1),
    } for t in buf])

    st.markdown("##### Routing-source distribution")
    src = df["routing_source"].value_counts().reset_index()
    src.columns = ["routing_source", "count"]
    fig = px.bar(src, x="routing_source", y="count", color="routing_source",
                 color_discrete_sequence=px.colors.qualitative.Set2)
    fig.update_layout(height=280, showlegend=False, margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("##### Predicted-quality distribution")
        kn = df[df["routing_source"] != "(n/a)"]
        if not kn.empty:
            figq = px.histogram(kn, x="predicted_quality", nbins=20,
                                color_discrete_sequence=["#3b82f6"])
            figq.update_layout(height=260, showlegend=False, margin=dict(t=20, b=20))
            st.plotly_chart(figq, use_container_width=True)
        else:
            st.caption("No Layer 3 predicted-quality yet (only fast-path / cache routes buffered).")
    with cc2:
        st.markdown("##### Uncertainty escalation")
        st.metric("Risk-aware escalation rate", f"{df['uncertainty_escalated'].mean():.0%}")
        st.caption(
            "Share of Layer 3 routes where neighbour-confidence was low enough to "
            "escalate to a stronger executable model instead of the cheapest pick."
        )

    st.markdown("##### Layer 3 prediction-drift scan")
    st.caption(
        "Per model, compares the recent vs an earlier reference window of predicted "
        "quality (KL divergence). A halt-level shift freezes that model's online "
        "calibration so the EMA stops chasing a non-stationary signal. Needs ~40+ "
        "events per model to act."
    )
    if st.button("Run drift scan", type="primary", key="l9_drift"):
        results = get_drift_detector().scan(buf, freeze_on_halt=False)
        if not results:
            st.info("Not enough events per model yet (need ~40+ per model). Route more queries.")
        else:
            drows = [{
                "model_id": r.model_id, "kl_divergence": round(r.kl_divergence, 4),
                "level": r.level, "n_reference": r.n_reference, "n_recent": r.n_recent,
            } for r in results]

            def _hl(row):
                c = {"halt": "#fef2f2", "warn": "#fffbeb", "info": "#eff6ff"}.get(row["level"], "")
                return [f"background-color: {c}"] * len(row) if c else [""] * len(row)

            st.dataframe(pd.DataFrame(drows).style.apply(_hl, axis=1),
                         use_container_width=True, hide_index=True)

    st.markdown("##### Recent telemetry events")
    st.dataframe(df.tail(50), use_container_width=True, height=320)


# ============================================================================
# About / Help
# ============================================================================

def render_about():
    st.subheader("About")
    st.markdown("""
This dashboard is for testing the routing system one layer at a time. It uses
the same call paths as production, so what you see here is what real users get.

**Layers retrofitted so far:**
- ✅ **Layer 0 — Fast Path** ([report](../docs/layers/LAYER_0_REPORT.md))
- ✅ **Layer 1 — Modality Gate** ([report](../docs/layers/LAYER_1_REPORT.md))
- ✅ **Layer 2 — Semantic Memory** ([report](../docs/layers/LAYER_2_REPORT.md))
- ✅ **Layer 3 — Benchmark kNN Router** (new design; replaces the legacy fast-triage / uncertainty / bandit)
- ✅ **Layer 9 — Telemetry & Drift** (observability page: routing-source mix, predicted-quality, prediction-drift scan)
- ⏳ Layers 4-8

**Layer 3 note:** the kNN router needs Qdrant up (the `layer3_benchmark_corpus`
collection) and loads a sentence-transformer encoder — the first L3 route warms
it (~20-40s), then routes are ~50-150ms. Its corpus runner reads the 650-query
locked validation set, not the `artifacts/layer_N/*.json` files the L0/L1 runners use.

**How to use:**

1. **Manual tab** — type a query, see what each layer extracts. Toggle image / audio / video.
2. **Corpus runner** — run the golden set or wild corpus, see per-query verdicts, latency distribution, per-category pass rate.
3. **A/B compare** — same query, two configs side by side. Use it to tune thresholds before pushing a config change.
4. **Save to corpus** — when a manual query gives an interesting result, one click adds it to the wild corpus.

**Files this dashboard reads:**
- `artifacts/layer_N/golden_set.json` — curated evaluation set
- `artifacts/layer_N/wild_corpus.json` — realistic user-style queries
- `artifacts/layer_N/benchmark_results.json` — last benchmark run

**Reproducibility:**
- `python scripts/benchmark_layer_N.py` — same metrics as the dashboard's corpus runner
- `python scripts/robustness_test_layer_1.py` — wild corpus verdicts
""")

    st.markdown("---")
    st.caption("v0.1.0 — extending this dashboard for new layers is one function per page.")


# ============================================================================
# Main router
# ============================================================================

def main():
    st.sidebar.title("🧪 Routing Lab")
    st.sidebar.caption("Per-layer test bench")

    page = st.sidebar.radio(
        "Page",
        [
            "About",
            "Layer 0 — manual",
            "Layer 1 — manual",
            "Layer 2 — manual",
            "Layer 3 — manual",
            "Pipeline (L0 → L3)",
            "Corpus runner — Layer 0",
            "Corpus runner — Layer 1",
            "Corpus runner — Layer 3",
            "A/B compare",
            "Layer 9 — Observability",
        ],
        index=1,
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Quick reference**")
    st.sidebar.caption(
        "Layer 0: sub-ms bypass for trivial queries\n\n"
        "Layer 1: modality + language + code + structured signals\n\n"
        "Layer 2: outcome-aware semantic cache\n\n"
        "Layer 3: benchmark kNN router — cheapest model above the quality floor\n\n"
        "Pipeline: chain L0 → L1 → L2 → L3 (real router order)"
    )

    fp = get_fast_path()
    gate = get_modality_gate()
    mem = get_semantic_memory()

    if page == "About":
        render_about()
    elif page == "Layer 0 — manual":
        render_layer_0_manual(fp)
    elif page == "Layer 1 — manual":
        render_layer_1_manual(gate)
    elif page == "Layer 2 — manual":
        render_layer_2_manual(mem)
    elif page == "Layer 3 — manual":
        # Loaded lazily (encoder warmup ~20-40s) so other pages stay snappy.
        render_layer_3_manual(get_knn_router(), get_question_text_lookup())
    elif page == "Pipeline (L0 → L3)":
        render_pipeline(fp, gate, mem, get_knn_router(), get_question_text_lookup())
    elif page == "Corpus runner — Layer 0":
        render_corpus_runner(fp, gate, layer_idx=0)
    elif page == "Corpus runner — Layer 1":
        render_corpus_runner(fp, gate, layer_idx=1)
    elif page == "Corpus runner — Layer 3":
        render_layer_3_corpus(get_knn_router(), get_question_text_lookup())
    elif page == "A/B compare":
        render_ab_compare(fp, gate)
    elif page == "Layer 9 — Observability":
        render_layer_9_observability()


if __name__ == "__main__":
    main()
