"""
📁 File: src/layer0_model_infra/routing/semantic_memory.py
Layer: Layer 0 – Routing Pipeline (Step 2)
Purpose: Outcome-aware semantic cache with decay, novelty scoring, and validation guards
Depends on: pydantic
Used by: router.py  (called between fast_path and modality_gate)

Design decisions
─────────────────
• No external vector-DB yet – uses an in-memory list of cached entries.
  When Qdrant / Milvus is wired, swap _store with a real ANN index.
  The public interface (lookup / record / novelty_score) stays the same.

• Outcome-aware: we only *reuse* a cached route when its stored quality
  was HIGH and it did NOT escalate.  Bad routes stay in the log for
  offline replay but are never served from cache.

• Memory decay: each entry carries a `timestamp`.  On lookup the
  similarity score is multiplied by an exponential decay factor so
  stale entries lose weight automatically.

• Novelty score: the distance from the nearest cached cluster.  A
  brand-new topic scores 1.0; something we've seen dozens of times
  scores 0.0.  This feeds directly into the uncertainty estimator.

• Validation guards (NEW): Before returning a cache hit, we verify:
  - context_length_similarity — reject if query length differs by >3x
  - entity_novelty_check    — reject if query has new named entities
  - model_version_check     — reject if model version changed
  - intent_consistency      — reject if detected intent differs
"""

import hashlib
import math
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from src.shared.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class MemoryEntry(BaseModel):
    """One cached routing outcome."""

    query_signature: str          # normalised key (lowered, stripped)
    model_id:        str          # which model was chosen
    quality_score:   float        # 0-1 quality after eval
    escalated:       bool         # did it escalate?
    escalation_count: int = 0
    intent:          str          = ""
    domain:          str          = ""
    complexity_band: str          = ""
    timestamp:       float        = Field(default_factory=time.time)

    # ── New validation fields ──────────────────────────────────────────────
    query_word_count: int         = 0     # for context-length similarity
    query_entities: list[str]     = Field(default_factory=list)  # extracted named entities
    model_version: str            = ""    # model version at time of routing
    embedding_id: str             = ""    # embedding hash for telemetry tracking

    @property
    def is_reusable(self) -> bool:
        """Only reuse HIGH-quality, non-escalated routes."""
        return self.quality_score >= 0.7 and not self.escalated


class MemoryLookupResult(BaseModel):
    """What router.py gets back from a cache lookup."""

    hit:              bool
    matched_model_id: Optional[str]  = None
    similarity:       float          = 0.0   # decayed similarity
    novelty_score:    float          = 1.0   # 1.0 = completely novel
    reasoning:        str            = ""
    embedding_id:     str            = ""    # for telemetry


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class SemanticMemory:
    """
    Outcome-aware in-memory routing cache with decay + novelty + validation guards.

    Production upgrade path
    ───────────────────────
    Replace _store + _similarity() with a Qdrant / Milvus client.
    The public methods (lookup / record / novelty_score) do NOT change.
    """

    # Validation guard constants
    CONTEXT_LENGTH_RATIO_MAX: float = 3.0    # reject if query length differs by > 3x
    MAX_NEW_ENTITY_RATIO: float = 0.5        # reject if > 50% entities are new

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        decay_half_life_seconds: float = 604800.0,  # 7 days
        max_entries: int = 10_000,
    ) -> None:
        self._store: list[MemoryEntry]   = []
        self.similarity_threshold        = similarity_threshold
        self.decay_half_life             = decay_half_life_seconds
        self.max_entries                 = max_entries

        # Embedding infrastructure (optional — graceful fallback to char-based sim)
        self._gateway = None
        self._embedding_model = None
        self._embedding_cache: dict[str, list[float]] = {}
        try:
            from src.layer0_model_infra.gateway import get_gateway
            from src.layer0_model_infra.config.routing_config import get_routing_config
            self._gateway = get_gateway()
            _cfg = get_routing_config()
            self._embedding_model = _cfg.semantic_memory.embedding_model
        except Exception:
            logger.debug("semantic_memory_no_gateway", fallback="char_similarity")

        # Track current model version for staleness checks
        self._current_model_version = "v1.0"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        query: str,
        query_intent: str = "",
        current_model_version: Optional[str] = None,
    ) -> MemoryLookupResult:
        """
        Search cache for a reusable routing decision with validation guards.

        Returns a hit only when:
          • raw similarity  ≥ threshold
          • decayed similarity still ≥ threshold
          • the stored entry is_reusable (quality OK, no escalation)
          • ALL validation guards pass
        """
        if not self._store:
            return MemoryLookupResult(
                hit=False, novelty_score=1.0,
                reasoning="Cache is empty – completely novel query",
            )

        signature = self._normalise(query)
        now       = time.time()
        query_wc  = len(query.split())
        query_ents = self._extract_entities(query)
        model_ver = current_model_version or self._current_model_version

        best_entry:    Optional[MemoryEntry] = None
        best_sim:      float                 = 0.0
        min_distance:  float                 = float("inf")   # for novelty

        for entry in self._store:
            raw_sim  = self._similarity(signature, entry.query_signature)
            dist     = 1.0 - raw_sim
            if dist < min_distance:
                min_distance = dist

            decayed  = raw_sim * self._decay_factor(entry.timestamp, now)
            if decayed > best_sim:
                best_sim   = decayed
                best_entry = entry

        # Novelty = closest distance (0 = seen before, 1 = brand new)
        novelty = min(min_distance, 1.0)

        # Cache HIT conditions (basic)
        if (
            best_entry is not None
            and best_sim >= self.similarity_threshold
            and best_entry.is_reusable
        ):
            # ── Validation Guards ──────────────────────────────────────────
            guard_result = self._run_validation_guards(
                query_wc, query_ents, query_intent, model_ver, best_entry
            )
            if guard_result is not None:
                logger.debug(
                    "semantic_memory_guard_rejected",
                    reason=guard_result,
                    model=best_entry.model_id,
                    similarity=round(best_sim, 3),
                )
                return MemoryLookupResult(
                    hit=False,
                    novelty_score=novelty,
                    reasoning=f"Cache guard rejected: {guard_result}",
                    embedding_id=best_entry.embedding_id,
                )

            # All guards passed → return cache hit
            logger.debug(
                "semantic_memory_hit",
                model=best_entry.model_id,
                similarity=round(best_sim, 3),
                novelty=round(novelty, 3),
            )
            return MemoryLookupResult(
                hit=True,
                matched_model_id=best_entry.model_id,
                similarity=best_sim,
                novelty_score=novelty,
                reasoning=(
                    f"Cache hit – model={best_entry.model_id} "
                    f"sim={best_sim:.3f} novelty={novelty:.3f}"
                ),
                embedding_id=best_entry.embedding_id,
            )

        # MISS – but novelty is still useful for uncertainty
        reason = "Cache miss"
        if best_entry and not best_entry.is_reusable:
            reason = (
                f"Nearest match was low-quality "
                f"(q={best_entry.quality_score:.2f}, esc={best_entry.escalated})"
            )
        elif best_entry and best_sim < self.similarity_threshold:
            reason = f"Nearest similarity {best_sim:.3f} below threshold {self.similarity_threshold}"

        logger.debug("semantic_memory_miss", novelty=round(novelty, 3), reason=reason)
        return MemoryLookupResult(
            hit=False, novelty_score=novelty, reasoning=reason,
        )

    def record(
        self,
        query:           str,
        model_id:        str,
        quality_score:   float,
        escalated:       bool,
        escalation_count: int  = 0,
        intent:          str   = "",
        domain:          str   = "",
        complexity_band: str   = "",
        model_version:   str   = "",
    ) -> None:
        """
        Store a routing outcome for future lookups.

        Always stores – even bad outcomes – so novelty scoring stays
        accurate.  Only is_reusable entries are ever *served* from cache.
        """
        signature = self._normalise(query)
        entities = self._extract_entities(query)
        embedding_id = hashlib.sha256(signature.encode()).hexdigest()[:16]

        entry = MemoryEntry(
            query_signature  = signature,
            model_id         = model_id,
            quality_score    = quality_score,
            escalated        = escalated,
            escalation_count = escalation_count,
            intent           = intent,
            domain           = domain,
            complexity_band  = complexity_band,
            timestamp        = time.time(),
            query_word_count = len(query.split()),
            query_entities   = entities,
            model_version    = model_version or self._current_model_version,
            embedding_id     = embedding_id,
        )
        self._store.append(entry)

        # Evict oldest if over cap
        if len(self._store) > self.max_entries:
            self._store.pop(0)

        logger.debug(
            "semantic_memory_recorded",
            model=model_id, quality=quality_score,
            escalated=escalated, reusable=entry.is_reusable,
            embedding_id=embedding_id,
        )

    def novelty_score(self, query: str) -> float:
        """Shortcut: just get novelty without a full lookup."""
        return self.lookup(query).novelty_score

    def stats(self) -> dict:
        """Diagnostic snapshot."""
        reusable = sum(1 for e in self._store if e.is_reusable)
        return {
            "total_entries":    len(self._store),
            "reusable_entries": reusable,
            "hit_rate_eligible": reusable / max(len(self._store), 1),
        }

    def prune_stale_entries(self, max_age_seconds: float = 2_592_000) -> int:
        """Remove entries older than max_age_seconds (default 30 days). Returns count removed."""
        now = time.time()
        before_count = len(self._store)
        self._store = [e for e in self._store if (now - e.timestamp) < max_age_seconds]
        removed = before_count - len(self._store)
        if removed > 0:
            logger.info("semantic_memory_pruned", removed=removed)
        return removed

    # ------------------------------------------------------------------
    # Validation Guards
    # ------------------------------------------------------------------

    def _run_validation_guards(
        self,
        query_wc: int,
        query_entities: list[str],
        query_intent: str,
        model_version: str,
        entry: MemoryEntry,
    ) -> Optional[str]:
        """
        Run all validation guards. Returns None if all pass,
        or a string reason if any guard rejects.
        """
        # Guard 1: Context length similarity
        if entry.query_word_count > 0 and query_wc > 0:
            ratio = max(query_wc, entry.query_word_count) / max(min(query_wc, entry.query_word_count), 1)
            if ratio > self.CONTEXT_LENGTH_RATIO_MAX:
                return f"context_length_ratio={ratio:.1f} exceeds {self.CONTEXT_LENGTH_RATIO_MAX}"

        # Guard 2: Entity novelty
        if query_entities and entry.query_entities:
            cached_set = set(e.lower() for e in entry.query_entities)
            new_entities = [e for e in query_entities if e.lower() not in cached_set]
            if len(new_entities) > 0:
                new_ratio = len(new_entities) / max(len(query_entities), 1)
                if new_ratio > self.MAX_NEW_ENTITY_RATIO:
                    return f"new_entity_ratio={new_ratio:.2f} ({new_entities[:3]})"

        # Guard 3: Model version
        if entry.model_version and model_version:
            if entry.model_version != model_version:
                return f"model_version_changed ({entry.model_version} → {model_version})"

        # Guard 4: Intent consistency
        if query_intent and entry.intent:
            if query_intent != entry.intent:
                return f"intent_mismatch ({entry.intent} → {query_intent})"

        return None  # All guards passed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(query: str) -> str:
        """Lightweight normalisation."""
        return " ".join(query.lower().split())

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """
        Lightweight named-entity extraction using capitalization heuristics.

        Not NER-level quality, but sufficient for cache-guard novelty checks.
        """
        # Find capitalised multi-word names (e.g., "New York", "John Smith")
        entities = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text)

        # Filter common sentence starters and short words
        common_starters = {
            "The", "This", "That", "These", "Those", "What", "When",
            "Where", "Which", "How", "Why", "Who", "Can", "Could",
            "Would", "Should", "Will", "Do", "Does", "Did", "Is",
            "Are", "Was", "Were", "Has", "Have", "Had", "Let", "Please",
            "Hello", "Hi", "Yes", "No", "Sure", "Okay",
        }
        entities = [e for e in entities if e not in common_starters and len(e) > 2]

        return entities[:20]  # cap to avoid memory issues

    def _similarity(self, query_a: str, query_b: str) -> float:
        """
        Compute similarity between two queries.

        Tries embedding-based cosine similarity first (via gateway).
        Falls back to character n-gram Jaccard similarity when no embeddings.
        """
        if self._gateway is not None and self._embedding_model is not None:
            try:
                return self._embedding_similarity(query_a, query_b)
            except Exception:
                pass

        # Fallback: character trigram Jaccard similarity
        return self._char_ngram_similarity(query_a, query_b, n=3)

    def _embedding_similarity(self, query_a: str, query_b: str) -> float:
        """Cosine similarity via embedding gateway."""
        from src.layer0_model_infra.gateway import EmbeddingRequest

        emb_a = self._get_embedding(query_a)
        emb_b = self._get_embedding(query_b)

        dot_product = sum(a * b for a, b in zip(emb_a, emb_b))
        norm_a = math.sqrt(sum(a * a for a in emb_a))
        norm_b = math.sqrt(sum(b * b for b in emb_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    def _get_embedding(self, text: str) -> list[float]:
        """Get embedding for text, using cache if available."""
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        from src.layer0_model_infra.gateway import EmbeddingRequest
        request = EmbeddingRequest(
            model_id=self._embedding_model,
            text=text,
        )
        response = self._gateway.embed(request)
        embedding = response.embedding

        if len(self._embedding_cache) < 1000:
            self._embedding_cache[text] = embedding
        return embedding

    @staticmethod
    def _char_ngram_similarity(a: str, b: str, n: int = 3) -> float:
        """
        Character n-gram Jaccard similarity.

        Lightweight fallback when no embedding model is available.
        Returns 0-1 similarity score.
        """
        if not a or not b:
            return 0.0

        def ngrams(text: str) -> set[str]:
            return {text[i:i + n] for i in range(len(text) - n + 1)}

        set_a = ngrams(a.lower())
        set_b = ngrams(b.lower())

        if not set_a or not set_b:
            return 1.0 if a == b else 0.0

        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _decay_factor(self, entry_ts: float, now: float) -> float:
        """Exponential decay: 1.0 when fresh, 0.5 after one half-life."""
        age = now - entry_ts
        if age <= 0:
            return 1.0
        return math.exp(-math.log(2) * age / self.decay_half_life)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_semantic_memory: Optional[SemanticMemory] = None


def get_semantic_memory() -> SemanticMemory:
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory()
    return _semantic_memory