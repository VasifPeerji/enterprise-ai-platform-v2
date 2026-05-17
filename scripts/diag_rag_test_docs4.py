"""
Diagnostic harness for the grounded RAG demo against the `test-docs4` collection
(8 FDA-style drug labels: Acetaminophen, Albuterol, Amlodipine/Norvasc,
Atorvastatin, Levothyroxine, Metformin, Omeprazole, Sertraline).

Hits two endpoints per query:
  1) POST /grounded-documents/collections/test-docs4/analyze
     -> retrieval results + assembler output, NO grounding gate, NO LLM
  2) POST /grounded-documents/collections/test-docs4/answer
     -> full pipeline including grounding gate; we detect 404 (gate rejected)

For each query we print:
  - top retrieval scores
  - chosen snippet length(s) and a short prefix
  - count and total length of HighlightSpans across page_proofs
  - whether section_title contains the corrupt "Article N" tag (Bug E)
  - whether /answer succeeded, was gate-rejected, or 5xx-failed (Bug A/B)

Run with the API server already up on http://localhost:8000.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

BASE_URL = "http://localhost:8000"
COLLECTION = "test-docs4"
TENANT = "default"
DOMAIN = "general"
TOP_K = 6


# ---------------------------------------------------------------------------
# Query battery
# ---------------------------------------------------------------------------
# The 8 queries the user reported failing on, plus 12 additional probes that
# exercise different failure modes (numeric-anchored, table-answer, multi-doc
# compare, contraindication, lactation, mechanism, etc.).

QUERIES: list[dict[str, str]] = [
    # ---- 8 user-reported failing queries -----------------------------------
    {
        "id": "U1_acet_45kg",
        "query": "What is the maximum daily dose of acetaminophen injection for an adult weighing 45 kg?",
        "expected_doc": "Acetaminophen.pdf",
        "expected_page": 2,
        "expected_keywords": ["75 mg/kg", "3750 mg"],
        "user_symptom": "False negative ('No relevant knowledge found')",
    },
    {
        "id": "U2_proair_dose_counter",
        "query": "How does the dose counter on the ProAir HFA inhaler work, and when should the inhaler be discarded?",
        "expected_doc": "Albuterol.pdf",
        "expected_page": 2,
        "expected_keywords": ["200", "20", "RED", "discard", "expiration"],
        "user_symptom": "Grounded query failed",
    },
    {
        "id": "U3_amlo_simva",
        "query": "What is the drug interaction between amlodipine and simvastatin, and what dose adjustment is required?",
        "expected_doc": "Amlodipine_Norvasc.pdf",
        "expected_page": 7,
        "expected_keywords": ["simvastatin", "20 mg"],
        "user_symptom": "Partial answer; LLM said mechanism not detailed",
    },
    {
        "id": "U4_lipitor_tipranavir",
        "query": "Why is it not recommended to take Lipitor concurrently with tipranavir plus ritonavir?",
        "expected_doc": "Atorvastatin.pdf",
        "expected_page": None,
        "expected_keywords": ["tipranavir", "ritonavir"],
        "user_symptom": "Possibly hallucinated CYP3A4 mechanism",
    },
    {
        "id": "U5_synthroid_weight_loss",
        "query": "What does the boxed warning state regarding the use of Synthroid for weight loss?",
        "expected_doc": "Levothyroxine.pdf",
        "expected_page": 1,
        "expected_keywords": ["obesity", "weight loss"],
        "user_symptom": "Correct (sanity check)",
    },
    {
        "id": "U6_metformin_renal",
        "query": "In what specific scenario regarding renal function is Metformin extended-release contraindicated?",
        "expected_doc": "Metformin.pdf",
        "expected_page": 3,
        "expected_keywords": ["eGFR", "30"],
        "user_symptom": "LLM said 'snippet truncates before detailing specific conditions'",
    },
    {
        "id": "U7_omeprazole_alt_admin",
        "query": "If a patient cannot swallow an intact omeprazole capsule, what is the alternative administration option?",
        "expected_doc": "Omeprazole.pdf",
        "expected_page": None,
        "expected_keywords": ["applesauce", "pellets"],
        "user_symptom": "Correct, but section labeled 'Article 2' (Bug E)",
    },
    {
        "id": "U8_sertraline_serotonin_syndrome",
        "query": "What are the neuromuscular and autonomic instability signs of Serotonin Syndrome?",
        "expected_doc": "Sertraline.pdf",
        "expected_page": 6,
        "expected_keywords": ["tremor", "rigidity", "myoclonus", "tachycardia", "diaphoresis"],
        "user_symptom": "False negative — table on p.6 has the answer",
    },

    # ---- 12 additional designed probes ------------------------------------
    {
        "id": "P1_acet_max_adult_50kg",
        "query": "What is the maximum daily dose of acetaminophen injection for an adult weighing 70 kg?",
        "expected_doc": "Acetaminophen.pdf",
        "expected_page": 2,
        "expected_keywords": ["4000 mg"],
        "user_symptom": "Numeric (70) not in chunk; should still answer",
    },
    {
        "id": "P2_acet_neonate",
        "query": "What is the maximum daily dose for neonates receiving acetaminophen injection?",
        "expected_doc": "Acetaminophen.pdf",
        "expected_page": 3,
        "expected_keywords": ["50 mg/kg"],
        "user_symptom": "Pediatric dosing chunk lookup",
    },
    {
        "id": "P3_metformin_egfr_45",
        "query": "Is metformin recommended for a patient with eGFR of 35 mL/min/1.73 m²?",
        "expected_doc": "Metformin.pdf",
        "expected_page": 2,
        "expected_keywords": ["30 to <45", "not recommended"],
        "user_symptom": "Range lookup with numeric (35)",
    },
    {
        "id": "P4_metformin_lactic_acidosis_treatment",
        "query": "How should suspected lactic acidosis from metformin be treated?",
        "expected_doc": "Metformin.pdf",
        "expected_page": 4,
        "expected_keywords": ["hemodialysis", "discontinue"],
        "user_symptom": "Multi-sentence answer in tables/paragraphs",
    },
    {
        "id": "P5_sertraline_pregnancy_pphn",
        "query": "What is the risk of PPHN with sertraline use in late pregnancy?",
        "expected_doc": "Sertraline.pdf",
        "expected_page": 12,
        "expected_keywords": ["6-fold", "20th week"],
        "user_symptom": "Specific numeric fact",
    },
    {
        "id": "P6_sertraline_maoi_washout",
        "query": "How many days must elapse between stopping an MAOI and starting sertraline?",
        "expected_doc": "Sertraline.pdf",
        "expected_page": None,
        "expected_keywords": ["14 days"],
        "user_symptom": "Numeric anchor (14) appears verbatim",
    },
    {
        "id": "P7_albuterol_priming",
        "query": "When should the ProAir HFA inhaler be primed?",
        "expected_doc": "Albuterol.pdf",
        "expected_page": 2,
        "expected_keywords": ["3 sprays", "2 weeks", "first time"],
        "user_symptom": "Multi-condition list",
    },
    {
        "id": "P8_omeprazole_indications",
        "query": "What are the FDA-approved indications for omeprazole delayed-release capsules?",
        "expected_doc": "Omeprazole.pdf",
        "expected_page": None,
        "expected_keywords": ["GERD"],
        "user_symptom": "List answer",
    },
    {
        "id": "P9_levo_overdose_symptoms",
        "query": "What are the signs and symptoms of levothyroxine overdose?",
        "expected_doc": "Levothyroxine.pdf",
        "expected_page": None,
        "expected_keywords": ["tachycardia", "weight loss"],
        "user_symptom": "Adverse-reaction list",
    },
    {
        "id": "P10_atorva_pregnancy",
        "query": "Is atorvastatin contraindicated in pregnancy?",
        "expected_doc": "Atorvastatin.pdf",
        "expected_page": None,
        "expected_keywords": ["pregnancy", "contraindicated"],
        "user_symptom": "Yes/no with reason",
    },
    {
        "id": "P11_sertraline_pediatric_indications",
        "query": "Which sertraline indications are approved for pediatric patients?",
        "expected_doc": "Sertraline.pdf",
        "expected_page": 2,
        "expected_keywords": ["OCD"],
        "user_symptom": "Single specific indication from table",
    },
    {
        "id": "P12_compare_dosing_intervals",
        "query": "What is the minimum dosing interval for acetaminophen injection in adults?",
        "expected_doc": "Acetaminophen.pdf",
        "expected_page": 2,
        "expected_keywords": ["4 hours"],
        "user_symptom": "Specific fact",
    },
]


# ---------------------------------------------------------------------------
# HTTP helpers (urllib only, no extra deps)
# ---------------------------------------------------------------------------
def _post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | str]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except error.URLError as exc:
        return -1, f"URLError: {exc.reason}"


def analyze(query: str) -> tuple[int, dict[str, Any] | str]:
    return _post(
        f"{BASE_URL}/grounded-documents/collections/{COLLECTION}/analyze",
        {"query": query, "tenant_id": TENANT, "domain": DOMAIN, "top_k": TOP_K},
    )


def answer(query: str, generation_mode: str = "heuristic") -> tuple[int, dict[str, Any] | str]:
    """Use heuristic mode for the harness so we don't burn the gateway on each run."""
    return _post(
        f"{BASE_URL}/grounded-documents/collections/{COLLECTION}/answer",
        {
            "query": query,
            "tenant_id": TENANT,
            "domain": DOMAIN,
            "top_k": TOP_K,
            "generation_mode": generation_mode,
        },
    )


# ---------------------------------------------------------------------------
# Per-query summarisation
# ---------------------------------------------------------------------------
@dataclass
class QueryReport:
    qid: str
    query: str
    expected_doc: str
    expected_kw: list[str]
    user_symptom: str

    # /analyze view
    retrieval_count: int = 0
    top_score: float = 0.0
    second_score: float = 0.0
    citation_count: int = 0
    citation_titles: list[str] = None
    citation_pages: list[int] = None
    snippet_lens: list[int] = None
    snippet_truncated_flags: list[bool] = None
    first_snippet: str = ""
    page_proof_count: int = 0
    total_highlight_spans: int = 0
    total_highlight_chars: int = 0
    total_page_text_chars: int = 0
    section_titles: list[str] = None
    article_section_leak: bool = False  # Bug E
    expected_doc_in_top: bool = False
    expected_kw_in_snippets: dict[str, bool] = None
    expected_kw_in_proofs: dict[str, bool] = None  # snippets ∪ page_texts

    # /answer view
    answer_status: int = 0
    answer_grounded: bool | None = None
    answer_text: str = ""
    answer_error: str = ""

    def render(self) -> str:
        kw_hits = ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in (self.expected_kw_in_snippets or {}).items())
        kw_proof_hits = ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in (self.expected_kw_in_proofs or {}).items())
        sec_str = "; ".join((s or "—") for s in (self.section_titles or [])[:3])
        return (
            f"### {self.qid}\n"
            f"**Query:** {self.query}\n"
            f"**Expected:** {self.expected_doc} | KWs: [{', '.join(self.expected_kw)}]\n"
            f"**User symptom:** {self.user_symptom}\n"
            f"\n"
            f"- /analyze: retrieval_count={self.retrieval_count} top_score={self.top_score:.3f} 2nd={self.second_score:.3f}\n"
            f"- citations={self.citation_count} pages={self.citation_pages} expected_doc_in_top={self.expected_doc_in_top}\n"
            f"- snippet_lens={self.snippet_lens} truncated={self.snippet_truncated_flags}\n"
            f"- first_snippet[:160]={self.first_snippet[:160]!r}\n"
            f"- expected_kw_in_snippets: {kw_hits}\n"
            f"- expected_kw_in_proofs:   {kw_proof_hits}\n"
            f"- page_proofs={self.page_proof_count} highlight_spans={self.total_highlight_spans} "
            f"highlight_chars={self.total_highlight_chars} page_text_chars={self.total_page_text_chars}\n"
            f"  -> highlight coverage: "
            f"{(self.total_highlight_chars / self.total_page_text_chars * 100) if self.total_page_text_chars else 0:.1f}%\n"
            f"- section_titles[0:3]: {sec_str}\n"
            f"- ARTICLE_SECTION_LEAK (Bug E): {self.article_section_leak}\n"
            f"\n"
            f"- /answer: status={self.answer_status} grounded={self.answer_grounded} "
            f"err={self.answer_error[:120]!r}\n"
            f"- answer[:240]={self.answer_text[:240]!r}\n"
        )


def summarise(spec: dict[str, Any], analyze_resp: Any, answer_resp: Any, answer_status: int) -> QueryReport:
    rep = QueryReport(
        qid=spec["id"],
        query=spec["query"],
        expected_doc=spec["expected_doc"],
        expected_kw=spec["expected_keywords"],
        user_symptom=spec["user_symptom"],
        citation_titles=[],
        citation_pages=[],
        snippet_lens=[],
        snippet_truncated_flags=[],
        section_titles=[],
        expected_kw_in_snippets={kw: False for kw in spec["expected_keywords"]},
        expected_kw_in_proofs={kw: False for kw in spec["expected_keywords"]},
    )

    if isinstance(analyze_resp, dict):
        rep.retrieval_count = int(analyze_resp.get("retrieval_count", 0))
        citations = analyze_resp.get("citations", []) or []
        page_proofs = analyze_resp.get("page_proofs", []) or []
        rep.citation_count = len(citations)
        rep.citation_titles = [c.get("title", "") for c in citations]
        rep.citation_pages = [c.get("page_number") for c in citations]
        rep.snippet_lens = [len(c.get("snippet") or "") for c in citations]
        rep.snippet_truncated_flags = [bool(c.get("snippet_truncated")) for c in citations]
        rep.first_snippet = citations[0].get("snippet", "") if citations else ""
        scores = [float(c.get("score", 0.0)) for c in citations]
        rep.top_score = scores[0] if scores else 0.0
        rep.second_score = scores[1] if len(scores) > 1 else 0.0
        rep.section_titles = [c.get("section_title") for c in citations]
        rep.article_section_leak = any(
            (s or "").startswith("Article ") and not str(s).lower().__contains__("constitution")
            for s in rep.section_titles
        )
        rep.expected_doc_in_top = any(spec["expected_doc"].lower() in (t or "").lower() for t in rep.citation_titles)

        joined_snippets = " ".join((c.get("snippet") or "").lower() for c in citations)
        rep.expected_kw_in_snippets = {
            kw: kw.lower() in joined_snippets for kw in spec["expected_keywords"]
        }

        # Also check the FULL page text (which the user can see in the UI's
        # page proof viewer, and which the LLM can see when context blocks
        # include adjacent chunks). This captures the "answer is on the
        # retrieved page but not in the chosen snippet" case as a partial
        # success rather than a flat failure.
        joined_proofs = joined_snippets + " " + " ".join(
            (p.get("page_text") or "").lower() for p in page_proofs
        )
        rep.expected_kw_in_proofs = {
            kw: kw.lower() in joined_proofs for kw in spec["expected_keywords"]
        }

        rep.page_proof_count = len(page_proofs)
        for proof in page_proofs:
            spans = proof.get("highlights") or []
            rep.total_highlight_spans += len(spans)
            rep.total_highlight_chars += sum(len(span.get("text") or "") for span in spans)
            rep.total_page_text_chars += len(proof.get("page_text") or "")

    rep.answer_status = answer_status
    if isinstance(answer_resp, dict):
        rep.answer_grounded = answer_resp.get("grounded")
        rep.answer_text = (answer_resp.get("answer") or "").strip()
        if "detail" in answer_resp:
            rep.answer_error = str(answer_resp["detail"])
    elif isinstance(answer_resp, str):
        rep.answer_error = answer_resp[:300]

    return rep


# ---------------------------------------------------------------------------
# Aggregate metrics across queries
# ---------------------------------------------------------------------------
def aggregate(reports: list[QueryReport]) -> str:
    n = len(reports)
    n_correct_doc = sum(1 for r in reports if r.expected_doc_in_top)
    n_kw_all = sum(1 for r in reports if all((r.expected_kw_in_snippets or {}).values()))
    n_kw_all_proofs = sum(1 for r in reports if all((r.expected_kw_in_proofs or {}).values()))
    n_answer_ok = sum(1 for r in reports if r.answer_status == 200)
    n_answer_404 = sum(1 for r in reports if r.answer_status == 404)
    n_answer_5xx = sum(1 for r in reports if 500 <= r.answer_status < 600)
    n_article_leak = sum(1 for r in reports if r.article_section_leak)
    n_truncated_snippets = sum(1 for r in reports if any(r.snippet_truncated_flags or []))
    avg_hl_chars = sum(r.total_highlight_chars for r in reports) / max(n, 1)
    avg_page_chars = sum(r.total_page_text_chars for r in reports) / max(n, 1)
    avg_hl_pct = (avg_hl_chars / avg_page_chars * 100) if avg_page_chars else 0.0
    avg_citations = sum(r.citation_count for r in reports) / max(n, 1)
    avg_first_snippet_len = sum(len(r.first_snippet) for r in reports) / max(n, 1)

    return (
        f"## Aggregate ({n} queries)\n"
        f"- Expected doc in top citations: {n_correct_doc}/{n}\n"
        f"- All expected keywords found in snippets: {n_kw_all}/{n}\n"
        f"- All expected keywords found in snippets+page_proofs: {n_kw_all_proofs}/{n}\n"
        f"- /answer 200: {n_answer_ok}/{n} | 404 (gate-rejected): {n_answer_404}/{n} | 5xx: {n_answer_5xx}/{n}\n"
        f"- Article-section leak (Bug E): {n_article_leak}/{n}\n"
        f"- Queries with at least one truncated snippet (Bug D): {n_truncated_snippets}/{n}\n"
        f"- Avg first snippet len: {avg_first_snippet_len:.1f} chars\n"
        f"- Avg citations per query: {avg_citations:.2f}\n"
        f"- Avg highlight coverage: {avg_hl_chars:.1f} / {avg_page_chars:.1f} chars = {avg_hl_pct:.2f}%\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    out_lines: list[str] = []
    out_lines.append(f"# RAG diagnostic against `{COLLECTION}`")
    out_lines.append(f"_{time.strftime('%Y-%m-%d %H:%M:%S')}_")
    out_lines.append("")

    reports: list[QueryReport] = []
    for spec in QUERIES:
        sys.stderr.write(f"[run] {spec['id']}\n")
        a_status, a_body = analyze(spec["query"])
        if a_status != 200:
            sys.stderr.write(f"  /analyze status={a_status}: {str(a_body)[:200]}\n")
        ans_status, ans_body = answer(spec["query"], generation_mode="heuristic")
        rep = summarise(spec, a_body, ans_body, ans_status)
        reports.append(rep)
        out_lines.append(rep.render())

    out_lines.append("")
    out_lines.append(aggregate(reports))

    report_text = "\n".join(out_lines)
    if out_path:
        # Always utf-8 on disk so Windows cp1252 stdout doesn't choke on
        # characters like '≥' in the pharma docs.
        from pathlib import Path
        Path(out_path).write_text(report_text, encoding="utf-8")
        sys.stderr.write(f"[done] wrote {out_path} ({len(report_text)} chars)\n")
    else:
        # Best-effort stdout: replace anything cp1252 can't encode.
        try:
            print(report_text)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(report_text.encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
