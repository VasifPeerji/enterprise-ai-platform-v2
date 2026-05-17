"""Reproduce the assembler behaviour for the 45 kg test in isolation."""
from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.layer1_intelligence.grounded_answer import GroundedAnswerAssembler
from src.layer3_domain.document_models import DocumentChunk, RetrievalResult

content = (
    "Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. "
    "Maximum single dose: 1000 mg. "
    "Minimum dosing interval: 4 hours. "
    "Maximum daily dose: 4000 mg per day (all routes + all acetaminophen-containing products). "
    "Adults and adolescents weighing under 50 kg: 15 mg/kg every 6 hours OR 12.5 mg/kg every 4 hours. "
    "Maximum single dose: 15 mg/kg. "
    "Minimum dosing interval: 4 hours. "
    "Maximum daily dose: 75 mg/kg per day (all routes + all acetaminophen-containing products)."
)

result = RetrievalResult(
    chunk=DocumentChunk(
        chunk_id="c1",
        document_id="acetaminophen",
        tenant_id="tenant-a",
        domain="lending",
        title="Acetaminophen.pdf",
        source_uri="/docs/acetaminophen.pdf",
        page_number=2,
        page_text=content,
        content=content,
        section_title="DOSAGE AND ADMINISTRATION",
        start_char=0,
        end_char=len(content),
    ),
    score=0.8,
    matched_terms=[],
)

assembler = GroundedAnswerAssembler()
ctx = assembler.assemble(
    "What is the maximum daily dose of acetaminophen injection for an adult weighing 45 kg?",
    [result],
)

cite = ctx.citations[0]
print(f"snippet ({len(cite.snippet)} chars): {cite.snippet[:200]!r}...{cite.snippet[-80:]!r}")
print(f"\ncite.highlights count: {len(cite.highlights)}")
for i, h in enumerate(cite.highlights):
    print(f"  H{i} [{h.start_char}:{h.end_char}] len={len(h.text)} {h.text[:80]!r}")

print(f"\npage_proofs[0].highlights count: {len(ctx.page_proofs[0].highlights)}")
for i, h in enumerate(ctx.page_proofs[0].highlights):
    print(f"  H{i} [{h.start_char}:{h.end_char}] len={len(h.text)} {h.text[:80]!r}")
