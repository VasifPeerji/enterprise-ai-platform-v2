"""Layer 1 intelligence foundation exports."""

from src.layer1_intelligence.claim_verifier import (
    ClaimDecomposer,
    ClaimVerdict,
    ClaimVerification,
    ClaimVerifier,
    VerificationReport,
    get_claim_verifier,
)
from src.layer1_intelligence.document_grounding import (
    InMemoryDocumentRetriever,
    build_citation,
    locate_highlight_span,
)
from src.layer1_intelligence.rag_service import GroundedRAGService
from src.layer1_intelligence.vector_index import DocumentIndexService

__all__ = [
    "ClaimDecomposer",
    "ClaimVerdict",
    "ClaimVerification",
    "ClaimVerifier",
    "DocumentIndexService",
    "GroundedRAGService",
    "InMemoryDocumentRetriever",
    "VerificationReport",
    "build_citation",
    "get_claim_verifier",
    "locate_highlight_span",
]
