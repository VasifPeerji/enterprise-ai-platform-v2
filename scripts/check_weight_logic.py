"""Quick sanity check for the weight-range scoring logic introduced in
the Bug H fix. Prints predictions to stdout AND writes them to a file
to dodge any conda-stdout-capture quirks.
"""
from pathlib import Path
import io
import sys

# Make the project importable when this script is run directly
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.layer1_intelligence.grounded_answer import (
    _evaluate_weight_range_relevance,
    _extract_query_weight_kg,
    _score_sentences_with_context,
    _query_terms,
)

buf = io.StringIO()
def out(*args):
    line = " ".join(str(a) for a in args)
    print(line)
    print(line, file=buf)

text_over = (
    "Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. "
    "Maximum single dose: 1000 mg. "
    "Minimum dosing interval: 4 hours. "
    "Maximum daily dose: 4000 mg per day (all routes + all acetaminophen-containing products)."
)
text_under = (
    "Adults and adolescents weighing under 50 kg: 15 mg/kg every 6 hours OR 12.5 mg/kg every 4 hours. "
    "Maximum single dose: 15 mg/kg. "
    "Minimum dosing interval: 4 hours. "
    "Maximum daily dose: 75 mg/kg per day (all routes + all acetaminophen-containing products)."
)
combined = text_over + " " + text_under

q = "What is the maximum daily dose of acetaminophen injection for an adult weighing 45 kg?"
out("== query weight extraction ==")
out("query weight kg:", _extract_query_weight_kg(q))

out("\n== chunk-level relevance (45 kg query) ==")
out("over chunk:", _evaluate_weight_range_relevance(text_over, 45.0), "  expect -1")
out("under chunk:", _evaluate_weight_range_relevance(text_under, 45.0), "  expect +1")
out("combined chunk:", _evaluate_weight_range_relevance(combined, 45.0), "  expect +1 (one range includes 45)")

out("\n== chunk-level relevance (70 kg query) ==")
out("over chunk:", _evaluate_weight_range_relevance(text_over, 70.0), "  expect +1")
out("under chunk:", _evaluate_weight_range_relevance(text_under, 70.0), "  expect -1")

out("\n== sentence scoring with context propagation (45 kg query, COMBINED chunk) ==")
import re
sentences = [s.strip() for s in re.split(r"(?<!\d\.)(?<!\d[A-Za-z]\.)(?<=[.!?])\s+|\n+", combined) if s.strip()]
qt = _query_terms(q)
scores = _score_sentences_with_context(
    sentences, qt,
    is_dose_query=True, is_absorption_query=False,
    query_weight_kg=45.0,
)
for s, sc in zip(sentences, scores):
    marker = "***" if sc > 0 else ""
    out(f"  [{sc:6.2f}] {marker} {s[:100]}")

# Write to a file too in case stdout is captured silently
Path(r"D:/College/enterprise-ai-platform/scripts/check_weight_logic.out.txt").write_text(buf.getvalue(), encoding="utf-8")
