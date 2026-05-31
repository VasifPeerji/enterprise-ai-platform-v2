"""
📁 File: src/layer0_model_infra/routing/high_risk_classifier.py
Layer: Layer 0 — Layer 3 redesign (Stage B, Tier-2 high-risk detection)
Purpose: Catch medical / legal / financial queries the narrow Tier-1 regex
         misses, WITHOUT re-introducing the old "vision → MEDICAL" over-routing.
Depends on: sentence-transformers (Arm B), transformers (Arm C) — both optional
            and lazily loaded.
Used by: feature_extractor (Tier-2 hook), benchmark_high_risk_detection.py

The Tier-1 regex (in feature_extractor) is deliberately narrow — measured at
1/8 recall on genuine high-risk queries ("chest pain, what do I do?",
"can I mix alcohol with antidepressants?", "fired for being pregnant?"). The
owner chose the more-aggressive path: add a Tier-2 semantic classifier that
raises recall while keeping precision (no false positives on coding/general
queries that merely share a word).

Two candidate arms are implemented here so the choice is DATA-DRIVEN
(benchmark_high_risk_detection.py picks the winner; see
docs/layer3/high_risk_classifier_choice.md):

  • Arm B — BgeKnnHighRiskClassifier: embed the query with bge-small-en and
    take the max cosine to a bank of ~30 prototype utterances per domain.
    ~5 ms/query on GPU, tiny footprint.
  • Arm C — ZeroShotHighRiskClassifier: MoritzLaurer/mDeBERTa-v3 zero-shot NLI
    ("is this text asking for medical/legal/financial advice?"). ~10 ms GPU /
    ~80 ms CPU, ~279 MB on disk, multilingual.

Both return ``(Optional[HighRiskDomain], score)``. Both are lazy — importing
this module loads nothing; the model loads on first classify().
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from src.layer0_model_infra.routing.layer3_types import HighRiskDomain
from src.shared.logger import get_logger

logger = get_logger(__name__)


_DOMAIN_ENUM = {
    "medical": HighRiskDomain.MEDICAL,
    "legal": HighRiskDomain.LEGAL,
    "financial": HighRiskDomain.FINANCIAL,
}


# ============================================================================
# Prototype utterances for the embedding-kNN arm (Arm B)
# ============================================================================
# ~30 per domain, covering the spread of real high-risk phrasings (symptoms,
# dosage, safety, rights, charges, advice, investment decisions). These are the
# anchors a query is matched against; they are NOT the benchmark eval set (that
# lives in scripts/layer3/_high_risk_eval.py and is disjoint from these).

HIGH_RISK_PROTOTYPES: dict[str, list[str]] = {
    "medical": [
        "I have chest pain and shortness of breath, what should I do",
        "is it safe to take ibuprofen with alcohol",
        "can I mix my antidepressant with alcohol",
        "what is the correct dosage of acetaminophen for a child",
        "my toddler swallowed a battery, is it dangerous",
        "should I go to the emergency room for these symptoms",
        "what are the side effects of metformin",
        "is this mole likely to be cancerous",
        "how do I treat a deep cut at home",
        "can I take expired antibiotics safely",
        "what medication helps with severe anxiety",
        "I think I'm having an allergic reaction, what do I do",
        "is it safe to stop taking my blood pressure medication",
        "what is the right insulin dose for type 1 diabetes",
        "how much ibuprofen counts as an overdose",
        "should I be worried about a lump in my breast",
        "what should I do for a suspected concussion",
        "can pregnant women take this medication safely",
        "my blood sugar is 300, what should I do",
        "are these symptoms a sign of a heart attack",
        "how do I lower my blood pressure quickly",
        "what antibiotics treat a urinary tract infection",
        "can I drive after taking these painkillers",
        "should I see a doctor about persistent headaches",
        "how do I know if my wound is infected",
        "what are the warning signs of a stroke",
        "is it safe to combine these two supplements",
        "my child has a fever of 104, what should I do",
        "what's a safe daily dose of vitamin D",
        "should I stop my medication now that I feel better",
    ],
    "legal": [
        "can I sue my employer for wrongful termination",
        "what are my rights if I'm being evicted without notice",
        "should I plead guilty to avoid a longer sentence",
        "can my employer fire me for being pregnant",
        "how do I file for divorce",
        "is my non-compete agreement legally enforceable",
        "what should I do if I'm arrested",
        "do I need a lawyer for a DUI charge",
        "can I break my lease without penalty",
        "how do I contest a will",
        "what are the grounds for a restraining order",
        "can I sue for medical malpractice",
        "is it legal to record a conversation without consent",
        "what happens legally if I don't pay my taxes",
        "can my landlord keep my security deposit",
        "how do I report workplace discrimination",
        "what are my rights during a police stop",
        "can I get custody of my children",
        "is this contract legally binding",
        "what is the statute of limitations for filing a lawsuit",
        "can I sue someone for defamation",
        "how do I fight a wrongful eviction",
        "do I have a case for a personal injury claim",
        "can I be held liable for this accident",
        "what should I do if I'm being sued",
        "can the police search my car without a warrant",
        "is my severance agreement fair and legal",
        "what are my rights as a tenant",
        "how do I file a workers compensation claim",
        "am I allowed to fire an employee for this reason",
    ],
    "financial": [
        "should I move my 401k into gold",
        "how should I invest my savings",
        "should I pay off debt or invest first",
        "is now a good time to buy a house",
        "how do I minimize taxes on my crypto gains",
        "should I declare bankruptcy",
        "what is the best way to consolidate my debt",
        "should I take out a loan to invest in stocks",
        "how much should I save for retirement",
        "is this a good stock to buy right now",
        "should I refinance my mortgage",
        "how do I improve my credit score fast",
        "should I cash out my pension early",
        "is whole life insurance worth it for me",
        "how do I structure my business to pay less tax",
        "what should I do with an inheritance",
        "how do I avoid capital gains tax",
        "should I invest in this cryptocurrency",
        "what's the safest way to grow my retirement savings",
        "should I co-sign a loan for my friend",
        "how do I get out of credit card debt",
        "is this investment opportunity a scam",
        "how much house can I afford on my salary",
        "should I claim social security early",
        "what is the best retirement account for me",
        "should I sell my stocks during this market dip",
        "is it a good idea to take a payday loan",
        "should I withdraw from my retirement account to pay bills",
        "how do I plan my finances for early retirement",
        "should I put all my money in index funds",
    ],
}


def _resolve_device_index() -> int:
    """transformers pipeline device: 0 for first CUDA GPU, -1 for CPU."""
    try:
        import torch  # type: ignore
        return 0 if torch.cuda.is_available() else -1
    except Exception:
        return -1


def _resolve_st_device() -> str:
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# ============================================================================
# Arm B — embedding kNN over prototypes (bge-small-en)
# ============================================================================


class BgeKnnHighRiskClassifier:
    """Max-cosine to a bank of high-risk prototype utterances."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        threshold: float = 0.62,
        device: Optional[str] = None,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._device = device
        self._model = None
        self._proto: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer  # type: ignore
            device = self._device or _resolve_st_device()
            model = SentenceTransformer(self._model_name, device=device)
            proto: dict[str, np.ndarray] = {}
            for domain, utterances in HIGH_RISK_PROTOTYPES.items():
                proto[domain] = model.encode(
                    utterances, normalize_embeddings=True, convert_to_numpy=True,
                    show_progress_bar=False,
                )
            self._model = model
            self._proto = proto
            logger.info("layer3_high_risk_bge_loaded", model=self._model_name, device=device)

    def classify(self, query: str, threshold: Optional[float] = None) -> tuple[Optional[HighRiskDomain], float]:
        if not query or not query.strip():
            return None, 0.0
        self._ensure_loaded()
        thr = self._threshold if threshold is None else threshold
        qv = self._model.encode(query, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        best_domain, best_sim = None, -1.0
        for domain, matrix in self._proto.items():
            sim = float(np.max(matrix @ qv))
            if sim > best_sim:
                best_sim, best_domain = sim, domain
        if best_domain is not None and best_sim >= thr:
            return _DOMAIN_ENUM[best_domain], best_sim
        return None, best_sim


# ============================================================================
# Arm C — mDeBERTa-v3 zero-shot NLI
# ============================================================================


class ZeroShotHighRiskClassifier:
    """Multilingual zero-shot NLI. Each candidate label is turned into a
    hypothesis ("This text is {label}.") and entailment-scored against the
    query; the highest-scoring label wins, with a neutral catch-all so general
    queries map to None."""

    # label text -> domain (None = the neutral catch-all)
    _LABELS: dict[str, Optional[str]] = {
        "a medical question or a request for medical advice": "medical",
        "a legal question or a request for legal advice": "legal",
        "a personal finance, money, or investment question": "financial",
        "a general, technical, or everyday question": None,
    }

    def __init__(
        self,
        model_name: str = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        threshold: float = 0.55,
        device: Optional[int] = None,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._device = device
        self._pipe = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._pipe is not None:
            return
        with self._lock:
            if self._pipe is not None:
                return
            from transformers import pipeline  # type: ignore
            device = self._device if self._device is not None else _resolve_device_index()
            self._pipe = pipeline(
                "zero-shot-classification",
                model=self._model_name,
                device=device,
            )
            logger.info("layer3_high_risk_mdeberta_loaded", model=self._model_name, device=device)

    def classify(self, query: str, threshold: Optional[float] = None) -> tuple[Optional[HighRiskDomain], float]:
        if not query or not query.strip():
            return None, 0.0
        self._ensure_loaded()
        thr = self._threshold if threshold is None else threshold
        labels = list(self._LABELS.keys())
        result = self._pipe(
            query, candidate_labels=labels,
            hypothesis_template="This text is {}.", multi_label=False,
        )
        top_label = result["labels"][0]
        top_score = float(result["scores"][0])
        domain = self._LABELS.get(top_label)
        if domain is not None and top_score >= thr:
            return _DOMAIN_ENUM[domain], top_score
        return None, top_score


# ============================================================================
# Factory + singletons
# ============================================================================

_bge: Optional[BgeKnnHighRiskClassifier] = None
_mdeberta: Optional[ZeroShotHighRiskClassifier] = None
_factory_lock = threading.Lock()


def get_bge_classifier(threshold: Optional[float] = None) -> BgeKnnHighRiskClassifier:
    global _bge
    if _bge is None:
        with _factory_lock:
            if _bge is None:
                _bge = BgeKnnHighRiskClassifier(threshold=threshold if threshold is not None else 0.62)
    return _bge


def get_mdeberta_classifier(threshold: Optional[float] = None) -> ZeroShotHighRiskClassifier:
    global _mdeberta
    if _mdeberta is None:
        with _factory_lock:
            if _mdeberta is None:
                _mdeberta = ZeroShotHighRiskClassifier(threshold=threshold if threshold is not None else 0.55)
    return _mdeberta


def get_high_risk_tier2(mode: str, threshold: Optional[float] = None):
    """Return the configured Tier-2 classifier, or None when disabled.

    mode ∈ {"off", "bge", "mdeberta"}. Anything else → None (Tier-1 only).
    """
    if mode == "bge":
        return get_bge_classifier(threshold)
    if mode == "mdeberta":
        return get_mdeberta_classifier(threshold)
    return None


def reset_high_risk_classifiers() -> None:
    """Test helper — drop the singletons."""
    global _bge, _mdeberta
    with _factory_lock:
        _bge = None
        _mdeberta = None
