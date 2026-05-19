"""
📁 File: src/layer0_model_infra/routing/semantic_memory.py
Layer: Layer 2 — Semantic Memory Cache
Purpose: Reuse past routing decisions for similar queries; emit novelty signal
Depends on: pydantic, numpy, sqlite3 (stdlib), optional: model2vec
Used by: src/layer0_model_infra/router.py (after modality gate, before triage)

Architecture (2-tier hybrid)
============================

  Tier 1 — Local embedding (Model2Vec, ~200μs per encode)
     ├─ Compute query embedding via Model2Vec potion-base-8M (256-dim)
     ├─ Cosine similarity vs in-memory NumPy matrix of cached embeddings
     ├─ Falls back to character-trigram Jaccard if Model2Vec unavailable
     └─ One matrix-vector product → top-k candidates in ~250μs for 10K entries

  Tier 2 — Validation guards (audit-hardened, run on top-1 candidate)
     ├─ Quality / escalation gate (only HIGH quality + non-escalated reuse)
     ├─ TTL by quality band (14d high, 3d medium, 1d escalated)
     ├─ Context-length similarity (reject if word counts differ >3×)
     ├─ Entity novelty (reject if too many new named entities)
     ├─ Negation polarity (reject "install X" matching "uninstall X")
     ├─ Intent consistency (reject if downstream classifier disagrees)
     └─ Model-version freshness (reject entries pointing to old model rev)

  Persistence
     ├─ SQLite (stdlib) — embeddings stored as BLOBs
     ├─ Loaded on startup, persisted on each record()
     ├─ WAL mode for crash safety + concurrent reads
     └─ Optional via `enable_persistence` config; cache is in-memory if disabled

  Observability
     ├─ hit_count / lookup_count / total_latency_saved_us
     ├─ stats() exposes per-tier hit rates and novelty distribution
     └─ Decision provenance logged per lookup

Bug fixes from the previous iteration
======================================
- Bypass-but-not-really: the router's _create_cached_decision used to call
  triage_classifier.classify() (LLM!) and uncertainty_estimator.estimate()
  even on cache hits. Fixed in router.py — Layer 2 no longer pays the cost
  of the downstream layers when it fires.
- Negation guard: "install X" / "uninstall X" used to hit each other.
- Embedding via gateway (50-200ms network) → Model2Vec local (~200μs).
- O(n) eviction via list.pop(0) → cap-aware ordered removal.
- Singleton TOCTOU race → threading.Lock + double-checked init.
- Quality 0.7 was a flat threshold → tiered TTL by quality band.
- No persistence → SQLite backing store.
- PII left in stored entities → regex scrubber on signature + entities.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Data models (public API — kept stable across the refactor)
# ============================================================================


class MemoryEntry(BaseModel):
    """One cached routing outcome."""

    query_signature: str
    model_id: str
    quality_score: float
    escalated: bool
    escalation_count: int = 0
    intent: str = ""
    domain: str = ""
    complexity_band: str = ""
    timestamp: float = Field(default_factory=time.time)

    # Validation-guard fields
    query_word_count: int = 0
    query_entities: list[str] = Field(default_factory=list)
    model_version: str = ""
    embedding_id: str = ""

    # Tenant scope (optional — if multi-tenant, lookup filters by this)
    tenant_id: str = ""

    @property
    def is_reusable(self) -> bool:
        """Only reuse HIGH-quality, non-escalated routes."""
        return self.quality_score >= 0.7 and not self.escalated


class MemoryLookupResult(BaseModel):
    """Cache-lookup result."""

    hit: bool
    matched_model_id: Optional[str] = None
    similarity: float = 0.0
    novelty_score: float = 1.0
    reasoning: str = ""
    embedding_id: str = ""

    # Provenance: which tier/method produced the answer
    detector_used: str = "none"   # "model2vec" | "char_ngram" | "none"
    guard_rejected: Optional[str] = None
    # When hit=True, expose the cached metadata so router can synthesize a
    # decision without re-running Layer 3/4 (fixes the bypass-not-really bug)
    cached_intent: Optional[str] = None
    cached_domain: Optional[str] = None
    cached_complexity_band: Optional[str] = None


# ============================================================================
# Helpers — PII scrubbing + negation detection
# ============================================================================


# Curated PII regexes + URL scrubbing. Replace matches with type tokens so
# the structure of the query is preserved (which matters for similarity)
# but the differentiating value is gone. URLs are scrubbed because they
# typically reference variable resources where the URL itself isn't part
# of the semantic query (surfaced by wild-corpus test where two different
# URLs in otherwise-identical queries caused a false miss).
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"https?://\S+", re.IGNORECASE), "<URL>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "<PHONE>"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "<CARD>"),  # 13-19 digits (CC range)
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b"), "<IBAN>"),
]


def _scrub_pii(text: str) -> str:
    """Replace PII spans with type tokens. Cheap, no library dependency."""
    if not text:
        return text
    for pat, replacement in _PII_PATTERNS:
        text = pat.sub(replacement, text)
    return text


# Negation / polarity-flipping marker set.
#
# Three kinds of tokens lumped together for the same purpose — if one
# query has more of these than the other, intent has flipped:
#   1. Formal negations: not, never, without, cannot, …
#   2. Removal verbs:    uninstall, remove, delete, revert, disable, …
#   3. Avoidance verbs:  avoid, prevent, skip, dodge, …
#   4. Asymmetric antonym sides (the "less / regress" side of a pair):
#        lose (vs gain), lower (vs raise), decrease (vs increase),
#        shrink (vs grow), shorten (vs lengthen).
#
# We don't track pair membership — we just count flip-tokens. If query A has 1
# and query B has 0, polarity has flipped. That's what the guard rejects.
# Catches medical (take/avoid), fitness (lose/gain weight), legal (file/avoid),
# relationships (save/divorce) — surfaced by multi-domain wild-corpus testing.
_NEG_TOKENS: frozenset[str] = frozenset({
    # Formal negations
    "no", "not", "never", "none", "without", "cannot", "cant",
    "wont", "shouldnt", "wouldnt", "couldnt", "isnt", "arent",
    # Removal / undo verbs
    "disable", "uninstall", "remove", "delete", "undo", "revert",
    "stop", "prevent", "block", "reject", "deny", "exclude",
    "rid", "ditch", "kill", "shut", "abandon", "drop", "discard",
    "off", "halt", "abort", "quit", "exit", "leave",
    # Avoidance
    "avoid", "skip", "dodge", "refuse", "decline", "ignore",
    # Asymmetric antonym sides (regress / decrease direction)
    "lose", "lower", "decrease", "shrink", "shorten", "reduce",
    "minimize", "weaken", "destroy", "demolish", "sell",
    "divorce", "breakup", "break", "split", "separate",  # vs save / propose
})

# Prefixes that often flip polarity when attached to a word.
_NEG_PREFIXES: tuple[str, ...] = ("un", "dis", "de", "non", "anti")


def _negation_score(text: str) -> int:
    """Count negation-flipping signals in `text`."""
    if not text:
        return 0
    tokens = re.findall(r"[a-z']+", text.lower())
    score = sum(1 for t in tokens if t in _NEG_TOKENS)
    # Prefix-based negation: "uninstall", "disconnect", "deauthorize"
    # Require length > prefix+3 to avoid matching "underscore", "deserve" etc.
    score += sum(
        1 for t in tokens
        if any(t.startswith(p) and len(t) > len(p) + 3 for p in _NEG_PREFIXES)
    )
    return score


# ============================================================================
# Embedder — Model2Vec with graceful char-ngram fallback
# ============================================================================


class _Embedder:
    """Wraps Model2Vec; falls back to char-trigram if model2vec unavailable."""

    def __init__(self, model_name: str) -> None:
        self.dim: int = 0
        self._model = None
        try:
            from model2vec import StaticModel  # type: ignore
            self._model = StaticModel.from_pretrained(model_name)
            self.dim = self._model.dim
            logger.info("layer2_embedder_loaded", model=model_name, dim=self.dim)
        except ImportError:
            logger.warning("layer2_model2vec_unavailable", fallback="char_ngram_jaccard")
        except Exception as exc:
            logger.warning("layer2_model2vec_init_failed", reason=str(exc),
                          fallback="char_ngram_jaccard")

    @property
    def available(self) -> bool:
        return self._model is not None

    def encode(self, text: str) -> np.ndarray:
        """Return an L2-normalised embedding vector. Empty array if unavailable."""
        if self._model is None:
            return np.zeros(0, dtype=np.float32)
        vec = self._model.encode(text)
        vec = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(vec) + 1e-9
        return vec / norm


# ============================================================================
# SQLite persistence (stdlib only)
# ============================================================================


class _PersistentStore:
    """SQLite-backed persistence for cached entries + embeddings.

    Stores embeddings as packed float32 BLOBs. Loads on construction; appends
    on every record(). WAL journal mode for concurrent reads.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS memory_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signature TEXT NOT NULL,
        model_id TEXT NOT NULL,
        quality_score REAL NOT NULL,
        escalated INTEGER NOT NULL,
        escalation_count INTEGER NOT NULL DEFAULT 0,
        intent TEXT,
        domain TEXT,
        complexity_band TEXT,
        timestamp REAL NOT NULL,
        query_word_count INTEGER,
        query_entities TEXT,
        model_version TEXT,
        embedding_id TEXT,
        tenant_id TEXT,
        embedding BLOB
    );
    CREATE INDEX IF NOT EXISTS idx_mem_ts ON memory_entries(timestamp);
    CREATE INDEX IF NOT EXISTS idx_mem_tenant ON memory_entries(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_mem_model ON memory_entries(model_id);
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=2000")
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    @staticmethod
    def _pack(vec: np.ndarray) -> bytes:
        if vec.size == 0:
            return b""
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def _unpack(blob: bytes) -> np.ndarray:
        if not blob:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(blob, dtype=np.float32)

    def load_all(self) -> tuple[list[MemoryEntry], list[np.ndarray]]:
        """Return (entries, embeddings) restored from disk."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT signature, model_id, quality_score, escalated, escalation_count, "
                "intent, domain, complexity_band, timestamp, query_word_count, "
                "query_entities, model_version, embedding_id, tenant_id, embedding "
                "FROM memory_entries ORDER BY timestamp ASC"
            )
            entries: list[MemoryEntry] = []
            embeddings: list[np.ndarray] = []
            for row in cur:
                ents = (row[10] or "").split("\x1f") if row[10] else []
                entry = MemoryEntry(
                    query_signature=row[0],
                    model_id=row[1],
                    quality_score=row[2],
                    escalated=bool(row[3]),
                    escalation_count=row[4],
                    intent=row[5] or "",
                    domain=row[6] or "",
                    complexity_band=row[7] or "",
                    timestamp=row[8],
                    query_word_count=row[9] or 0,
                    query_entities=[e for e in ents if e],
                    model_version=row[11] or "",
                    embedding_id=row[12] or "",
                    tenant_id=row[13] or "",
                )
                entries.append(entry)
                embeddings.append(self._unpack(row[14]))
        return entries, embeddings

    def insert(self, entry: MemoryEntry, embedding: np.ndarray) -> None:
        ents_str = "\x1f".join(entry.query_entities) if entry.query_entities else ""
        with self._lock:
            self._conn.execute(
                "INSERT INTO memory_entries(signature, model_id, quality_score, escalated, "
                "escalation_count, intent, domain, complexity_band, timestamp, "
                "query_word_count, query_entities, model_version, embedding_id, "
                "tenant_id, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.query_signature, entry.model_id, entry.quality_score,
                 int(entry.escalated), entry.escalation_count, entry.intent,
                 entry.domain, entry.complexity_band, entry.timestamp,
                 entry.query_word_count, ents_str, entry.model_version,
                 entry.embedding_id, entry.tenant_id, self._pack(embedding)),
            )
            self._conn.commit()

    def delete_oldest(self, count: int) -> int:
        if count <= 0:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memory_entries WHERE id IN ("
                "SELECT id FROM memory_entries ORDER BY timestamp ASC LIMIT ?)",
                (count,),
            )
            self._conn.commit()
            return cur.rowcount

    def delete_by_model(self, model_id: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memory_entries WHERE model_id = ?", (model_id,)
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ============================================================================
# Semantic Memory — Layer 2
# ============================================================================


class SemanticMemory:
    """Outcome-aware semantic cache (Layer 2).

    Hybrid embedding-backed cache with validation guards and SQLite
    persistence. Replaces the previous in-memory char-ngram-only design.

    Public API (lookup / record / novelty_score / stats) is preserved.
    """

    # Context length / entity guards
    CONTEXT_LENGTH_RATIO_MAX: float = 3.0
    MAX_NEW_ENTITY_RATIO: float = 0.5

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        decay_half_life_seconds: float = 604_800.0,
        max_entries: int = 10_000,
        *,
        # Optional explicit config — when not provided, we read from
        # get_routing_config().semantic_memory.
        enable_local_embedding: Optional[bool] = None,
        enable_persistence: Optional[bool] = None,
        persistence_path: Optional[str] = None,
        enable_negation_guard: Optional[bool] = None,
        enable_pii_scrubbing: Optional[bool] = None,
        embedding_model_name: Optional[str] = None,
    ) -> None:
        # Resolve config
        try:
            from src.layer0_model_infra.config.routing_config import get_routing_config
            cfg = get_routing_config().semantic_memory
        except Exception:
            cfg = None

        self.similarity_threshold = similarity_threshold
        self.decay_half_life = decay_half_life_seconds
        self.max_entries = max_entries

        # Feature flags (config defaults, callable overrides)
        self._use_local_embed = (
            enable_local_embedding if enable_local_embedding is not None
            else (getattr(cfg, "enable_local_embedding", True) if cfg else True)
        )
        self._use_persistence = (
            enable_persistence if enable_persistence is not None
            else (getattr(cfg, "enable_persistence", True) if cfg else False)
        )
        self._use_negation_guard = (
            enable_negation_guard if enable_negation_guard is not None
            else (getattr(cfg, "enable_negation_guard", True) if cfg else True)
        )
        self._use_pii_scrubbing = (
            enable_pii_scrubbing if enable_pii_scrubbing is not None
            else (getattr(cfg, "enable_pii_scrubbing", True) if cfg else True)
        )
        embedding_model = (
            embedding_model_name
            or (getattr(cfg, "local_embedding_model_name", "minishlab/potion-base-8M") if cfg else "minishlab/potion-base-8M")
        )

        # Quality / TTL tiers (from config if available, else defaults)
        self._high_quality_threshold = getattr(cfg, "high_quality_threshold", 0.85) if cfg else 0.85
        self._medium_quality_threshold = getattr(cfg, "medium_quality_threshold", 0.70) if cfg else 0.70
        self._high_quality_ttl = getattr(cfg, "high_quality_ttl_seconds", 1_209_600.0) if cfg else 1_209_600.0
        self._medium_quality_ttl = getattr(cfg, "medium_quality_ttl_seconds", 259_200.0) if cfg else 259_200.0
        self._escalated_ttl = getattr(cfg, "escalated_ttl_seconds", 86_400.0) if cfg else 86_400.0

        # Storage
        self._store: list[MemoryEntry] = []
        self._embeddings: list[np.ndarray] = []  # parallel to _store
        self._lock = threading.RLock()

        # Embedder
        self._embedder: Optional[_Embedder] = None
        if self._use_local_embed:
            self._embedder = _get_or_build_embedder(embedding_model)

        # Persistence
        self._db: Optional[_PersistentStore] = None
        if self._use_persistence:
            path_str = (
                persistence_path
                or (getattr(cfg, "persistence_path", "artifacts/semantic_memory.db") if cfg else "artifacts/semantic_memory.db")
            )
            path = Path(path_str)
            if not path.is_absolute():
                # Resolve relative paths against the repo root (3 levels up from this file)
                repo_root = Path(__file__).resolve().parent.parent.parent.parent
                path = repo_root / path_str
            try:
                self._db = _PersistentStore(path)
                # Restore prior state
                restored, restored_embeddings = self._db.load_all()
                self._store = restored
                self._embeddings = restored_embeddings
                if restored:
                    logger.info("layer2_persistence_loaded", entries=len(restored))
            except Exception as exc:
                logger.warning("layer2_persistence_init_failed", reason=str(exc))
                self._db = None

        # Track current model version for staleness checks
        self._current_model_version = "v1.0"

        # Metrics
        self._lookup_count = 0
        self._hit_count = 0
        self._latency_saved_us = 0.0
        self._guard_rejection_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        query: str,
        query_intent: str = "",
        current_model_version: Optional[str] = None,
        *,
        tenant_id: str = "",
    ) -> MemoryLookupResult:
        """Search cache for a reusable routing decision with validation guards."""
        with self._lock:
            self._lookup_count += 1
            if not self._store:
                return MemoryLookupResult(
                    hit=False, novelty_score=1.0, detector_used="none",
                    reasoning="Cache is empty — completely novel query",
                )

            scrubbed = self._scrub(query)
            signature = self._normalise(scrubbed)
            now = time.time()
            query_wc = len(query.split())
            # Extract entities from SCRUBBED text so PII / URLs (which become
            # type tokens like <EMAIL> / <URL>) aren't treated as differentiating
            # entities. This makes "email to alice@example.com" and "email to
            # bob@example.com" produce identical entity sets.
            query_ents = self._extract_entities(scrubbed)
            model_ver = current_model_version or self._current_model_version

            # Compute similarities (vectorised when embedder is available)
            sims, detector_used = self._compute_similarities(signature)

            # Decay-adjusted scores; novelty = closest raw distance.
            # Clamp similarity to [0, 1] before computing distance — cosine
            # similarity can drift slightly above 1.0 due to FP precision,
            # which gives a negative distance / negative novelty otherwise.
            best_idx: Optional[int] = None
            best_decayed: float = 0.0
            min_distance: float = float("inf")
            for i, raw_sim in enumerate(sims):
                e = self._store[i]
                # Tenant scope: if entry's tenant_id is set, must match
                if e.tenant_id and tenant_id and e.tenant_id != tenant_id:
                    continue
                clamped = max(0.0, min(1.0, float(raw_sim)))
                dist = 1.0 - clamped
                if dist < min_distance:
                    min_distance = dist
                decayed = clamped * self._decay_factor(e.timestamp, now)
                if decayed > best_decayed:
                    best_decayed = decayed
                    best_idx = i

            novelty = max(0.0, min(min_distance if min_distance != float("inf") else 1.0, 1.0))

            if (
                best_idx is not None
                and best_decayed >= self.similarity_threshold
                and self._is_reusable(self._store[best_idx], now)
            ):
                entry = self._store[best_idx]
                guard_reason = self._run_validation_guards(
                    query_wc, query_ents, query_intent, model_ver, entry, query=query,
                )
                if guard_reason is not None:
                    self._guard_rejection_counts[guard_reason.split(":")[0]] = (
                        self._guard_rejection_counts.get(guard_reason.split(":")[0], 0) + 1
                    )
                    logger.debug("semantic_memory_guard_rejected", reason=guard_reason,
                                model=entry.model_id, similarity=round(best_decayed, 3))
                    return MemoryLookupResult(
                        hit=False, novelty_score=novelty, detector_used=detector_used,
                        reasoning=f"Guard rejected: {guard_reason}",
                        embedding_id=entry.embedding_id, guard_rejected=guard_reason,
                    )

                # All guards passed → HIT
                self._hit_count += 1
                # Rough latency-saved estimate: full pipeline ~120ms, cache ~3ms
                self._latency_saved_us += 117_000.0

                logger.debug("semantic_memory_hit",
                            model=entry.model_id, similarity=round(best_decayed, 3),
                            novelty=round(novelty, 3), detector=detector_used)
                return MemoryLookupResult(
                    hit=True,
                    matched_model_id=entry.model_id,
                    similarity=best_decayed,
                    novelty_score=novelty,
                    detector_used=detector_used,
                    reasoning=(
                        f"Cache hit — model={entry.model_id} "
                        f"sim={best_decayed:.3f} novelty={novelty:.3f} via {detector_used}"
                    ),
                    embedding_id=entry.embedding_id,
                    cached_intent=entry.intent or None,
                    cached_domain=entry.domain or None,
                    cached_complexity_band=entry.complexity_band or None,
                )

            # MISS
            reason = "Cache miss"
            matched_id = ""
            if best_idx is not None:
                e = self._store[best_idx]
                matched_id = e.embedding_id
                if not self._is_reusable(e, now):
                    reason = (
                        f"Nearest match was low-quality / escalated "
                        f"(q={e.quality_score:.2f}, esc={e.escalated})"
                    )
                elif best_decayed < self.similarity_threshold:
                    reason = (
                        f"Nearest similarity {best_decayed:.3f} below "
                        f"threshold {self.similarity_threshold}"
                    )
            return MemoryLookupResult(
                hit=False, similarity=best_decayed,
                novelty_score=novelty, detector_used=detector_used,
                reasoning=reason, embedding_id=matched_id,
            )

    def record(
        self,
        query: str,
        model_id: str,
        quality_score: float,
        escalated: bool,
        escalation_count: int = 0,
        intent: str = "",
        domain: str = "",
        complexity_band: str = "",
        model_version: str = "",
        *,
        tenant_id: str = "",
    ) -> None:
        """Store a routing outcome. Always stores so novelty stays accurate;
        only is_reusable entries are ever served from cache."""
        with self._lock:
            scrubbed = self._scrub(query)
            signature = self._normalise(scrubbed)
            # Extract entities from the scrubbed version so PII tokens
            # (<EMAIL>, <URL>, …) don't create false entity differences
            # between otherwise-equivalent queries.
            entities = self._extract_entities(scrubbed)
            embedding = self._encode(signature)
            embedding_id = hashlib.sha256(signature.encode()).hexdigest()[:16]

            entry = MemoryEntry(
                query_signature=signature,
                model_id=model_id,
                quality_score=quality_score,
                escalated=escalated,
                escalation_count=escalation_count,
                intent=intent,
                domain=domain,
                complexity_band=complexity_band,
                timestamp=time.time(),
                query_word_count=len(query.split()),
                query_entities=entities,
                model_version=model_version or self._current_model_version,
                embedding_id=embedding_id,
                tenant_id=tenant_id,
            )
            self._store.append(entry)
            self._embeddings.append(embedding)

            if self._db is not None:
                try:
                    self._db.insert(entry, embedding)
                except Exception as exc:
                    logger.warning("layer2_persist_insert_failed", reason=str(exc))

            # Eviction: capped FIFO, scrub from DB too
            if len(self._store) > self.max_entries:
                excess = len(self._store) - self.max_entries
                self._store = self._store[excess:]
                self._embeddings = self._embeddings[excess:]
                if self._db is not None:
                    try:
                        self._db.delete_oldest(excess)
                    except Exception:
                        pass

            logger.debug("semantic_memory_recorded", model=model_id,
                        quality=quality_score, escalated=escalated,
                        reusable=entry.is_reusable, embedding_id=embedding_id)

    def novelty_score(self, query: str) -> float:
        """Just the novelty without a full lookup verdict."""
        return self.lookup(query).novelty_score

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            reusable = sum(1 for e in self._store if self._is_reusable(e, now))
            return {
                "total_entries": len(self._store),
                "reusable_entries": reusable,
                "hit_rate_eligible": reusable / max(len(self._store), 1),
                "lookup_count": self._lookup_count,
                "hit_count": self._hit_count,
                "hit_rate_actual": self._hit_count / max(self._lookup_count, 1),
                "latency_saved_us": self._latency_saved_us,
                "guard_rejections": dict(self._guard_rejection_counts),
                "embedder_available": bool(self._embedder and self._embedder.available),
                "persistence_enabled": self._db is not None,
            }

    def prune_stale_entries(self, max_age_seconds: float = 2_592_000) -> int:
        """Remove entries older than max_age_seconds (default 30 days)."""
        with self._lock:
            now = time.time()
            before = len(self._store)
            keep = [
                (e, emb) for e, emb in zip(self._store, self._embeddings)
                if (now - e.timestamp) < max_age_seconds
            ]
            self._store = [e for e, _ in keep]
            self._embeddings = [emb for _, emb in keep]
            removed = before - len(self._store)
            if removed > 0:
                logger.info("semantic_memory_pruned", removed=removed)
            return removed

    def invalidate_model(self, model_id: str) -> int:
        """Drop all entries pointing to a (deprecated) model. Returns count."""
        with self._lock:
            keep = [(e, emb) for e, emb in zip(self._store, self._embeddings)
                    if e.model_id != model_id]
            removed = len(self._store) - len(keep)
            self._store = [e for e, _ in keep]
            self._embeddings = [emb for _, emb in keep]
            if self._db is not None:
                try:
                    self._db.delete_by_model(model_id)
                except Exception:
                    pass
            if removed > 0:
                logger.info("semantic_memory_model_invalidated",
                           model=model_id, removed=removed)
            return removed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _scrub(self, text: str) -> str:
        return _scrub_pii(text) if self._use_pii_scrubbing else text

    @staticmethod
    def _normalise(query: str) -> str:
        return " ".join(query.lower().split())

    # Technical-term patterns (extends capitalized-NER to catch lowercase
    # tokens that act as differentiating proper nouns in code/dev queries —
    # surfaced by wild-corpus testing where "NoneType not subscriptable" got
    # matched to "NoneType not iterable" because both had no Capitalized
    # differences beyond shared "NoneType".)
    _TECH_TERM_PATTERNS: list[re.Pattern] = [
        re.compile(r"\b(\w+Error)\b"),         # TypeError, ValueError, MyError
        re.compile(r"\b(\w+Exception)\b"),     # NullPointerException
        re.compile(r"\b(\w+(?:able|ible))\b", re.IGNORECASE),  # subscriptable, iterable, callable
        re.compile(r"\b(\w+\.\w+(?:\.\w+)?)\b"),                # foo.bar, mod.sub.fn
    ]

    # Common false-positive stopwords for the -able / -ible patterns
    _TECH_TERM_STOPWORDS: set[str] = {
        "available", "reasonable", "reliable", "viable", "table", "able",
        "stable", "valuable", "usable", "noticeable", "considerable",
        "probable", "possible", "responsible", "sensible", "terrible",
        "horrible", "visible", "audible", "edible", "comfortable",
    }

    @classmethod
    def _extract_entities(cls, text: str) -> list[str]:
        """Regex entity extraction. Two passes (general + technical) for
        broader coverage than capitalized-only.

        Returns the combined list. Use `_extract_technical_entities` separately
        when you want the technical subset (which the guard treats as hard-match).
        """
        # General entities = Capitalized proper noun phrases
        entities = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text)
        # Stopword list: question words + imperative-mode verbs commonly
        # appearing at the start of a query. Capitalised but not entities.
        # Extended for multi-domain coverage (cooking, fitness, creative, etc.).
        common_starters = {
            # Question words
            "The", "This", "That", "These", "Those", "What", "When",
            "Where", "Which", "How", "Why", "Who", "Can", "Could",
            "Would", "Should", "Will", "Do", "Does", "Did", "Is",
            "Are", "Was", "Were", "Has", "Have", "Had", "Let", "Please",
            "Hello", "Hi", "Yes", "No", "Sure", "Okay", "Got",
            # Imperative verbs (tech)
            "Write", "Create", "Build", "Make", "Add", "Send", "Update",
            "Delete", "Remove", "Install", "Run", "Show", "Display",
            "Find", "Get", "Set", "Help", "Tell", "Give", "Explain",
            "Describe", "Translate", "Generate", "Suggest", "Recommend",
            "Analyze", "Compare", "Implement", "Debug", "Fix",
            # Imperative verbs (general / multi-domain)
            "Compose", "Draft", "Edit", "Review", "Summarize",
            "Cook", "Bake", "Make", "Prepare",
            "Run", "Walk", "Lift", "Train", "Exercise",
            "Visit", "Travel", "Fly", "Drive",
            "Read", "Watch", "Listen", "Learn", "Study", "Teach",
            "Buy", "Sell", "Invest", "Save", "Spend",
            "Plan", "Schedule", "Book", "Reserve",
            "Best", "Top", "First", "Last", "Next", "Most",
        }
        entities = [e for e in entities if e not in common_starters and len(e) > 2]

        entities.extend(cls._extract_technical_entities(text))

        # De-dup while preserving order
        seen, out = set(), []
        for e in entities:
            key = e.lower()
            if key not in seen:
                seen.add(key)
                out.append(e)
        return out[:20]

    @classmethod
    def _extract_technical_entities(cls, text: str) -> list[str]:
        """Subset of entities that are technical terms / error types / module
        paths. Treated as hard-match in the guard — ANY difference rejects."""
        found: list[str] = []
        for pat in cls._TECH_TERM_PATTERNS:
            for m in pat.findall(text):
                token = m if isinstance(m, str) else m[0]
                if token.lower() not in cls._TECH_TERM_STOPWORDS and len(token) > 4:
                    found.append(token)
        return found

    def _encode(self, text: str) -> np.ndarray:
        """L2-normalised embedding (np.float32). Empty array if embedder unavailable."""
        if self._embedder is None or not self._embedder.available:
            return np.zeros(0, dtype=np.float32)
        return self._embedder.encode(text)

    def _compute_similarities(self, signature: str) -> tuple[list[float], str]:
        """Return (per-entry similarity list, detector_used)."""
        # Tier 1: Model2Vec (if embedder available AND all stored entries have
        # non-empty embeddings — we built up the store with an embedder)
        if (self._embedder is not None and self._embedder.available
                and self._embeddings and self._embeddings[0].size > 0):
            q_vec = self._embedder.encode(signature)
            # Vectorise: stack embeddings → matrix-vector dot product
            try:
                matrix = np.stack(self._embeddings, axis=0)
                sims = (matrix @ q_vec).tolist()
                return sims, "model2vec"
            except Exception:
                pass

        # Tier 2: char-trigram Jaccard fallback
        sims = [self._char_ngram_similarity(signature, e.query_signature, n=3)
                for e in self._store]
        return sims, "char_ngram"

    def _similarity(self, a: str, b: str) -> float:
        """Pairwise similarity between two strings.

        Kept as a thin wrapper for callers that want a single-pair similarity
        without going through the cache's batched matrix path. Uses Model2Vec
        when available, else char-trigram Jaccard.
        """
        if not a or not b:
            return 0.0
        if self._embedder is not None and self._embedder.available:
            try:
                va = self._embedder.encode(a)
                vb = self._embedder.encode(b)
                if va.size and vb.size:
                    return float(va @ vb)
            except Exception:
                pass
        return self._char_ngram_similarity(a, b, n=3)

    @staticmethod
    def _char_ngram_similarity(a: str, b: str, n: int = 3) -> float:
        if not a or not b:
            return 0.0
        def ngrams(s: str) -> set[str]:
            return {s[i:i + n] for i in range(len(s) - n + 1)}
        set_a = ngrams(a.lower())
        set_b = ngrams(b.lower())
        if not set_a or not set_b:
            return 1.0 if a == b else 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def _decay_factor(self, entry_ts: float, now: float) -> float:
        age = now - entry_ts
        if age <= 0:
            return 1.0
        return math.exp(-math.log(2) * age / self.decay_half_life)

    def _is_reusable(self, entry: MemoryEntry, now: float) -> bool:
        """Tiered TTL by quality. Escalated entries are NEVER reusable —
        we still keep them in the store for novelty scoring + observability,
        but they don't get served from cache.
        """
        if entry.escalated:
            return False
        if entry.quality_score >= self._high_quality_threshold:
            return (now - entry.timestamp) < self._high_quality_ttl
        if entry.quality_score >= self._medium_quality_threshold:
            return (now - entry.timestamp) < self._medium_quality_ttl
        return False

    def _run_validation_guards(
        self, query_wc: int, query_entities: list[str], query_intent: str,
        model_version: str, entry: MemoryEntry, *, query: str,
    ) -> Optional[str]:
        """Return None if all guards pass, else a reason string.

        Ordering: semantic differences (polarity, intent) come before
        lexical ones (entities, length). Polarity is fundamental — if it
        flips the meaning, no other guard matters.
        """
        # Guard 1: context-length sanity (cheap structural check)
        if entry.query_word_count > 0 and query_wc > 0:
            ratio = max(query_wc, entry.query_word_count) / max(min(query_wc, entry.query_word_count), 1)
            if ratio > self.CONTEXT_LENGTH_RATIO_MAX:
                return f"context_length_ratio:{ratio:.1f}"

        # Guard 2: NEW — negation polarity. Runs early because polarity
        # mismatch invalidates the cache hit regardless of other signals.
        if self._use_negation_guard:
            q_neg = _negation_score(query)
            e_neg = _negation_score(entry.query_signature)
            if abs(q_neg - e_neg) >= 1:
                return f"negation_polarity:{e_neg}→{q_neg}"

        # Guard 3: intent consistency (downstream classifier disagrees)
        if query_intent and entry.intent and query_intent != entry.intent:
            return f"intent_mismatch:{entry.intent}→{query_intent}"

        # Guard 4: model-version freshness
        if entry.model_version and model_version and entry.model_version != model_version:
            return f"model_version:{entry.model_version}→{model_version}"

        # Guard 5a: technical-entity HARD match (errors / module paths /
        # -able/-ible terms). Any difference rejects — these tokens are
        # rarely synonymous (TypeError ≠ ValueError, subscriptable ≠ iterable).
        # We extract from the SCRUBBED query (PII / URLs already replaced with
        # type tokens) so two queries with different emails or URLs but
        # otherwise identical structure produce identical technical-entity sets.
        scrubbed_query = self._scrub(query)
        q_tech = {e.lower() for e in self._extract_technical_entities(scrubbed_query)}
        e_tech = {e.lower() for e in self._extract_technical_entities(entry.query_signature)}
        if q_tech != e_tech:
            diff = (q_tech ^ e_tech)
            return f"technical_entity_mismatch:{list(diff)[:3]}"

        # Guard 5b: general-entity novelty (ratio-based, lenient).
        # Boundary changed from strict `>` to `>=` because exactly-50% changes
        # (1 of 2 entities differs — e.g. California vs Texas, Japan vs Korea)
        # were slipping through. With `>=`, jurisdiction / country differences
        # in 2-entity queries correctly reject.
        if query_entities and entry.query_entities:
            cached_set = {e.lower() for e in entry.query_entities}
            new_entities = [e for e in query_entities if e.lower() not in cached_set]
            if new_entities:
                new_ratio = len(new_entities) / max(len(query_entities), 1)
                if new_ratio >= self.MAX_NEW_ENTITY_RATIO:
                    return f"new_entities:{new_entities[:3]}"

        return None


# ============================================================================
# Module-level cached embedder + singleton
# ============================================================================

_embedder_cache: dict[str, _Embedder] = {}
_embedder_lock = threading.Lock()


def _get_or_build_embedder(model_name: str) -> _Embedder:
    """Process-wide cached embedder keyed by model name. Shared across instances
    so the lingua-style memory hit is paid once."""
    if model_name in _embedder_cache:
        return _embedder_cache[model_name]
    with _embedder_lock:
        if model_name in _embedder_cache:
            return _embedder_cache[model_name]
        emb = _Embedder(model_name)
        _embedder_cache[model_name] = emb
        return emb


_semantic_memory: Optional[SemanticMemory] = None
_semantic_memory_lock = threading.Lock()


def get_semantic_memory() -> SemanticMemory:
    """Return the process-wide SemanticMemory instance (thread-safe)."""
    global _semantic_memory
    if _semantic_memory is None:
        with _semantic_memory_lock:
            if _semantic_memory is None:
                _semantic_memory = SemanticMemory()
    return _semantic_memory
