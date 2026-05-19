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
# Pipeline page — Layer 0 → Layer 1
# ============================================================================

def render_pipeline(fp, gate):
    st.subheader("End-to-end: Layer 0 → Layer 1")
    st.caption(
        "If Layer 0 bypasses, downstream layers are skipped. Otherwise the "
        "modality gate runs. This is exactly what the orchestrator does."
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

        st.markdown(f"**Total latency:** {(l0_latency + l1_latency) / 1000:.2f} ms")
        st.markdown(f"**Pipeline would continue to:** Layer 2 (Semantic Memory) — not yet retrofitted.")

        with st.expander("L1 details"):
            st.json({
                "primary_modality": m.primary_modality.value,
                "language": m.language,
                "code_language": m.code_language,
                "structured_format": m.structured_format,
                "requires_vision": m.requires_vision,
                "requires_code_model": m.requires_code_model,
                "token_count": m.token_count,
                "reasoning": m.reasoning,
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
- ⏳ Layer 2 — Semantic Memory (next)
- ⏳ Layer 3 — Fast Triage (partial — delegates to Layer 0)
- ⏳ Layers 4-9

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
            "Pipeline (L0 → L1)",
            "Corpus runner — Layer 0",
            "Corpus runner — Layer 1",
            "A/B compare",
        ],
        index=1,
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Quick reference**")
    st.sidebar.caption(
        "Layer 0: sub-ms bypass for trivial queries\n\n"
        "Layer 1: modality + language + code + structured signals\n\n"
        "Pipeline: chain L0 → L1 (real router order)"
    )

    fp = get_fast_path()
    gate = get_modality_gate()

    if page == "About":
        render_about()
    elif page == "Layer 0 — manual":
        render_layer_0_manual(fp)
    elif page == "Layer 1 — manual":
        render_layer_1_manual(gate)
    elif page == "Pipeline (L0 → L1)":
        render_pipeline(fp, gate)
    elif page == "Corpus runner — Layer 0":
        render_corpus_runner(fp, gate, layer_idx=0)
    elif page == "Corpus runner — Layer 1":
        render_corpus_runner(fp, gate, layer_idx=1)
    elif page == "A/B compare":
        render_ab_compare(fp, gate)


if __name__ == "__main__":
    main()
