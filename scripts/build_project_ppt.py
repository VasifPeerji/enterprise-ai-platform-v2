from __future__ import annotations

import json
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts' / 'project_ppt'
ASSETS = ARTIFACTS / 'assets'
TEMPLATE = Path(r'D:\College\AI_ML_Sem4\Project_Docs\Sample PPT for Project AIML - IV.pptx')
BENCHMARK_JSON = ROOT / 'artifacts' / 'routing_benchmark_20260319_013016.json'
OUTPUT_PPT = ARTIFACTS / 'Enterprise_AI_Platform_Project_Presentation.pptx'
OUTPUT_MD = ARTIFACTS / 'presentation.md'


def read_benchmark() -> list[dict]:
    return json.loads(BENCHMARK_JSON.read_text(encoding='utf-8'))


def summarize_results(rows: list[dict]) -> dict:
    total = len(rows)
    passed = sum(1 for row in rows if row['pass'])
    accuracy = round((passed / total) * 100, 1)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row['category']].append(row)

    category_stats = []
    for category, items in sorted(by_category.items()):
        ok = sum(1 for item in items if item['pass'])
        category_stats.append(
            {
                'category': category.replace('_', ' ').title(),
                'accuracy': round((ok / len(items)) * 100, 1),
                'count': len(items),
            }
        )

    tier_counts = Counter(row['selected_tier'].title() for row in rows)
    confidence_counts = Counter(row['confidence_level'].title() for row in rows)
    avg_uncertainty = round(statistics.mean(row['uncertainty'] for row in rows), 2)

    return {
        'total': total,
        'passed': passed,
        'accuracy': accuracy,
        'tier_counts': tier_counts,
        'confidence_counts': confidence_counts,
        'avg_uncertainty': avg_uncertainty,
        'category_stats': category_stats,
    }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def make_architecture_svg(path: Path) -> None:
    layers = [
        ('Layer 0', 'Model Infra', '#264653'),
        ('Layer 1', 'Core Intelligence', '#2a9d8f'),
        ('Layer 2', 'Orchestrator', '#52b788'),
        ('Layer 3', 'Domain Engine', '#8ab17d'),
        ('Layer 4', 'Platform Engine', '#e9c46a'),
        ('Layer 5', 'Governance', '#f4a261'),
        ('Layer 6', 'AI Ops & Eval', '#e76f51'),
    ]
    boxes = []
    y = 30
    for code, label, color in reversed(layers):
        boxes.append(
            f'<rect x="60" y="{y}" width="900" height="68" rx="18" fill="{color}" opacity="0.96"/>'
            f'<text x="110" y="{y + 28}" font-family="Segoe UI, Arial" font-size="24" font-weight="700" fill="white">{code}</text>'
            f'<text x="290" y="{y + 28}" font-family="Segoe UI, Arial" font-size="22" fill="white">{label}</text>'
        )
        y += 82

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1020" height="640" viewBox="0 0 1020 640">
  <rect width="1020" height="640" fill="#f7f2ea"/>
  <text x="60" y="22" font-family="Segoe UI, Arial" font-size="18" font-weight="700" fill="#1f2937">
    Seven-layer enterprise AI architecture with strict dependency boundaries
  </text>
  {''.join(boxes)}
  <text x="690" y="614" font-family="Segoe UI, Arial" font-size="18" fill="#374151">
    Only Layer 2 performs side effects
  </text>
</svg>'''
    _write(path, svg)


def make_pipeline_svg(path: Path) -> None:
    stages = [
        ('Fast Path', '#335c67'),
        ('Modality Gate', '#457b9d'),
        ('Semantic Memory', '#5c7cfa'),
        ('Fast Triage', '#2a9d8f'),
        ('Uncertainty', '#52b788'),
        ('Bandit Router', '#e9c46a'),
        ('Test-Time Compute', '#f4a261'),
        ('Quality Check', '#e76f51'),
        ('Escalation + Telemetry', '#bc4749'),
    ]
    nodes = []
    arrows = []
    x = 30
    for index, (label, color) in enumerate(stages):
        nodes.append(
            f'<rect x="{x}" y="90" width="155" height="86" rx="18" fill="{color}"/>'
            f'<text x="{x + 77.5}" y="126" text-anchor="middle" font-family="Segoe UI, Arial" font-size="20" font-weight="700" fill="white">{label}</text>'
        )
        if index < len(stages) - 1:
            ax = x + 155
            arrows.append(
                f'<line x1="{ax}" y1="133" x2="{ax + 26}" y2="133" stroke="#334155" stroke-width="4"/>'
                f'<polygon points="{ax + 26},133 {ax + 14},126 {ax + 14},140" fill="#334155"/>'
            )
        x += 165

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1520" height="260" viewBox="0 0 1520 260">
  <rect width="1520" height="260" fill="#f7f2ea"/>
  <text x="30" y="42" font-family="Segoe UI, Arial" font-size="28" font-weight="700" fill="#1f2937">
    Adaptive routing pipeline implemented in Layer 0 and executed by Layer 2
  </text>
  <text x="30" y="68" font-family="Segoe UI, Arial" font-size="18" fill="#475569">
    Each stage adds signal, constrains risk, or improves quality before final response delivery
  </text>
  {''.join(arrows)}
  {''.join(nodes)}
</svg>'''
    _write(path, svg)


def make_results_svg(path: Path, summary: dict) -> None:
    categories = summary['category_stats']
    width = 1080
    height = 620
    chart_left = 120
    chart_bottom = 520
    chart_top = 110
    bar_width = 70
    gap = 34
    usable_height = chart_bottom - chart_top

    bars = []
    labels = []
    for idx, item in enumerate(categories):
        x = chart_left + idx * (bar_width + gap)
        bar_height = (item['accuracy'] / 100) * usable_height
        y = chart_bottom - bar_height
        color = '#2a9d8f' if item['accuracy'] >= 80 else '#e9c46a' if item['accuracy'] >= 60 else '#e76f51'
        bars.append(f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" rx="10" fill="{color}"/>')
        labels.append(
            f'<text x="{x + bar_width/2}" y="{y - 10}" text-anchor="middle" font-family="Segoe UI, Arial" font-size="18" font-weight="700" fill="#1f2937">{item["accuracy"]:.0f}%</text>'
            f'<text x="{x + bar_width/2}" y="{chart_bottom + 26}" text-anchor="middle" font-family="Segoe UI, Arial" font-size="14" fill="#475569">{item["category"].replace(" ", "-")}</text>'
        )

    grid = []
    for pct in (0, 20, 40, 60, 80, 100):
        y = chart_bottom - (pct / 100) * usable_height
        grid.append(f'<line x1="{chart_left - 20}" y1="{y}" x2="1000" y2="{y}" stroke="#d6d3d1" stroke-width="1"/>')
        grid.append(f'<text x="{chart_left - 30}" y="{y + 6}" text-anchor="end" font-family="Segoe UI, Arial" font-size="14" fill="#64748b">{pct}</text>')

    kpi_boxes = []
    kpis = [
        ('Tier-match accuracy', f'{summary["accuracy"]}%'),
        ('Evaluation cases', str(summary['total'])),
        ('Avg uncertainty', str(summary['avg_uncertainty'])),
    ]
    for i, (label, value) in enumerate(kpis):
        x = 690 + i * 120
        kpi_boxes.append(
            f'<rect x="{x}" y="18" width="110" height="66" rx="14" fill="#fff7ed" stroke="#fdba74"/>'
            f'<text x="{x + 55}" y="42" text-anchor="middle" font-family="Segoe UI, Arial" font-size="12" fill="#7c2d12">{label}</text>'
            f'<text x="{x + 55}" y="67" text-anchor="middle" font-family="Segoe UI, Arial" font-size="22" font-weight="700" fill="#9a3412">{value}</text>'
        )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="#f7f2ea"/>
  <text x="34" y="42" font-family="Segoe UI, Arial" font-size="30" font-weight="700" fill="#1f2937">
    Benchmark evidence from repository artifact: routing_benchmark_20260319_013016.json
  </text>
  <text x="34" y="74" font-family="Segoe UI, Arial" font-size="18" fill="#475569">
    Category-wise tier-match accuracy after routing policy refinements
  </text>
  {''.join(kpi_boxes)}
  {''.join(grid)}
  <line x1="{chart_left - 10}" y1="{chart_top}" x2="{chart_left - 10}" y2="{chart_bottom}" stroke="#475569" stroke-width="2"/>
  <line x1="{chart_left - 10}" y1="{chart_bottom}" x2="1000" y2="{chart_bottom}" stroke="#475569" stroke-width="2"/>
  {''.join(bars)}
  {''.join(labels)}
</svg>'''
    _write(path, svg)


def build_markdown(summary: dict) -> str:
    tier_dist = ', '.join(f'{k}: {v}' for k, v in summary['tier_counts'].items())
    conf_dist = ', '.join(f'{k}: {v}' for k, v in summary['confidence_counts'].items())
    return dedent(
        f'''
        # Enterprise AI Platform

        - **Adaptive, Multi-Tenant, Cost-Aware AI Assistant System**
        - **M.Sc. (Artificial Intelligence & Machine Learning), Semester IV**
        - **Presented by: Vasif M. Peerji (40012)**
        - **Department of Computer Science, Gujarat University**

        # Introduction

        - Enterprise AI systems need **quality, safety, cost control, and scale** at the same time.
        - Static single-model deployment wastes budget on simple queries and increases latency.
        - This project implements a **production-style adaptive routing platform** using layered architecture.
        - Core stack: **FastAPI, LiteLLM, LangGraph, SQLModel, Redis, Qdrant, PostgreSQL**.

        ![]({(ASSETS / 'architecture.svg').as_posix()}){{width=84%}}

        # Research Problem

        - Traditional AI assistants route too many requests to **expensive frontier models**.
        - Heuristic routing based only on prompt length or keywords is **fragile and non-adaptive**.
        - Enterprise deployments also require **multi-tenancy, auditability, RBAC, and safe escalation**.
        - Research gap: few systems jointly optimize **cost, latency, quality, and reliability under uncertainty**.

        # Objectives of the Research

        - Design a **vendor-agnostic enterprise AI platform** with strict layer boundaries.
        - Implement **adaptive inference routing** using contextual signals and Thompson-sampling bandits.
        - Reduce unnecessary premium-model usage while preserving **response quality**.
        - Provide **bounded escalation, quality checks, telemetry, and continuous learning hooks**.
        - Support **multi-tenant onboarding** without code changes for every client.

        # Literature Review

        - **Static LLM serving** offers simplicity but causes higher recurring inference cost.
        - **RAG systems** improve grounding, but retrieval alone does not solve routing economics.
        - **Contextual multi-armed bandits** are suited to non-stationary decision problems with exploration-exploitation trade-offs.
        - **Test-time compute scaling** improves smaller-model reliability for medium-complexity tasks.
        - Existing work rarely combines **routing, escalation, governance, and enterprise platform controls** in one deployable stack.

        # Research Methodology

        - Research style: **design science + systems engineering + benchmark-driven evaluation**.
        - Primary approach: implement the architecture, validate rules, and test routing decisions on curated prompts.
        - Decision flow combines modality analysis, semantic memory, fast triage, uncertainty estimation, bandit routing, quality validation, and escalation.
        - Evaluation basis: architecture inspection, code tracing, and benchmark artifacts from the repository.

        ![]({(ASSETS / 'pipeline.svg').as_posix()}){{width=92%}}

        # Data Collection

        - Input data includes **user queries, modality flags, user tier, budget state, and session history**.
        - Historical and synthetic query sets support **cold-start calibration** and policy initialization.
        - Runtime telemetry captures selected model, confidence, cost, latency, quality score, and escalation events.
        - Storage layers include **PostgreSQL for state** and **Qdrant/Redis for memory and fast context**.

        # Data Analysis

        - Query features are converted into **intent, domain, complexity, novelty, and risk signals**.
        - The router forms a **context vector** for model selection rather than using hard-coded rules.
        - Reward updates combine **quality, cost, latency, and escalation penalties**.
        - High-risk domains suppress exploration and shift policy toward **safer model choices**.
        - Analytics support **continuous tuning** instead of one-time routing configuration.

        # Implementation

        - HTTP interface exposes `/chat`, `/models`, `/tenants`, `/health`, and demo endpoints.
        - **Layer 0** implements the adaptive routing pipeline and model abstraction.
        - **Layer 2** executes requests, applies latency budgets, guardrails, TTC, and escalation loops.
        - **Layer 4-6** enable multi-tenancy, governance, and AI Ops style evaluation.
        - Project structure enforces **clear dependency rules** and keeps side effects inside the orchestrator.

        | Area | Key files / modules | Purpose |
        | --- | --- | --- |
        | API | `src/interfaces/http/main.py`, `routes/chat.py` | Service entry and demo routes |
        | Routing | `src/layer0_model_infra/router.py` | 9-stage adaptive decision engine |
        | Optimization | `routing/bandit_router.py` | Thompson-sampling model selection |
        | Reliability | `quality_evaluator.py`, `escalation_engine.py` | Silent-failure checks and recovery |
        | Execution | `layer2_orchestrator/execution_loop.py` | Controlled response generation |

        # Results

        - Benchmark artifact analyzed: **41 evaluation cases** across simple, coding, multi-intent, cross-domain, legal, and medical categories.
        - Observed **tier-match accuracy: {summary['accuracy']}%** ({summary['passed']}/{summary['total']} cases).
        - Selected tier distribution: **{tier_dist}**.
        - Confidence distribution: **{conf_dist}**.
        - Strongest categories reached **100% accuracy** in cross-domain, legal, medical, and multi-intent cases.

        ![]({(ASSETS / 'results.svg').as_posix()}){{width=86%}}

        # Discussion

        - The system shows that **adaptive routing is feasible inside an enterprise-grade architecture**.
        - Results indicate strong handling of **risk-aware and cross-domain prompts** after policy refinements.
        - Remaining weak spots appear in **general reasoning and some premium-vs-mid boundary decisions**.
        - The codebase emphasizes **safe degradation and observability**, not cost minimization alone.
        - This makes the platform more suitable for **real deployment scenarios** than benchmark-only prototypes.

        # Contributions to the Field

        - Integrates **adaptive routing research ideas** into a deployable enterprise platform.
        - Demonstrates a **strict layered AI architecture** with governance and side-effect control.
        - Adds **contextual bandit routing, uncertainty handling, test-time compute, and bounded escalation**.
        - Bridges the gap between **research concepts** and **production engineering constraints**.

        # Limitations

        - Current evidence is based on **repository benchmarks**, not large-scale live production traffic.
        - Some higher layers are **architecturally defined more strongly than fully populated with business modules**.
        - Accuracy is measured as **tier-match**, not end-user satisfaction on a large human-labeled dataset.
        - Cost reduction claims are **directionally supported** by routing behavior but not fully quantified end-to-end here.

        # Challenges Faced

        - Balancing **cost efficiency** with **quality assurance** across diverse prompt categories.
        - Preventing unsafe under-routing for **medical, legal, and ambiguous multi-step tasks**.
        - Designing reusable architecture without violating **layer boundaries**.
        - Maintaining observability, feedback logging, and escalation safety without excessive latency overhead.

        # Future Work

        - Add larger **golden datasets** and user-facing evaluation metrics.
        - Quantify **cost and latency savings** against static baseline models on full execution runs.
        - Expand **domain engines** for banking, healthcare, retail, and education.
        - Strengthen **memory reuse, shadow routing, and online policy updates**.
        - Add richer dashboards for **governance, Phoenix tracing, and tenant analytics**.

        # Conclusion

        - The project delivers a **professional enterprise AI platform**, not just a chatbot prototype.
        - Its key innovation is **adaptive, uncertainty-aware model routing** integrated with governance and recovery logic.
        - Repository evidence shows promising routing performance with strong behavior in high-risk and multi-intent settings.
        - The system provides a solid base for **scalable, economical, and trustworthy AI deployment**.

        # References

        - Agrawal, S., and Goyal, N. (2013). *Thompson Sampling for Contextual Bandits with Linear Payoffs*.
        - Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*.
        - Wang, X. et al. (2022). *Self-Consistency Improves Chain of Thought Reasoning in Language Models*.
        - FastAPI Documentation. *High-performance Python APIs*.
        - LiteLLM Documentation. *Unified gateway for multiple LLM providers*.
        - Qdrant Documentation. *Vector search and semantic memory infrastructure*.
        - Project sources: `README.md`, `ARCHITECTURE.md`, `synopsis_utf8.txt`, `routing_benchmark_20260319_013016.*`.

        # Acknowledgments

        - Department of Computer Science, **Gujarat University**.
        - Guide and faculty support for project framing, review, and evaluation.
        - Open-source ecosystem behind **FastAPI, LangGraph, LiteLLM, Qdrant, Redis, and PostgreSQL**.

        # Thank You

        - **Thank you**
        - Questions and feedback are welcome.
        - Project theme: **adaptive enterprise AI with cost-aware intelligent routing**.
        '''
    ).strip() + '\n'


def run_pandoc(markdown_path: Path, output_path: Path) -> None:
    cmd = [
        'pandoc',
        str(markdown_path),
        '-o',
        str(output_path),
        f'--reference-doc={TEMPLATE}',
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    rows = read_benchmark()
    summary = summarize_results(rows)

    make_architecture_svg(ASSETS / 'architecture.svg')
    make_pipeline_svg(ASSETS / 'pipeline.svg')
    make_results_svg(ASSETS / 'results.svg', summary)

    markdown = build_markdown(summary)
    _write(OUTPUT_MD, markdown)
    run_pandoc(OUTPUT_MD, OUTPUT_PPT)

    print(f'Created markdown: {OUTPUT_MD}')
    print(f'Created presentation: {OUTPUT_PPT}')


if __name__ == '__main__':
    main()
