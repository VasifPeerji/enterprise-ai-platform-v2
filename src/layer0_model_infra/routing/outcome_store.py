"""
📁 File: src/layer0_model_infra/routing/outcome_store.py
Layer: Layer 0 — Layer 3 redesign (Stage C dependency)
Purpose: Fast per-(model, question) outcome lookup over the benchmark corpus.
Depends on: duckdb, pyarrow
Used by: knn_router (next batch), validation scripts, calibration auto-tuner

The kNN router's per-model quality prediction (Stage C) needs to look up the
outcomes of the queried kNN neighbors for every active model in the registry.
For a 22-model registry × ~20 neighbors = 440 lookups per query. At ~5 ms p99
budget for the entire lookup phase, individual lookups must be sub-millisecond.

DuckDB on a memory-mapped Parquet file gives us ~50-200 µs per batched lookup
without loading 2-4M rows into RAM. The whole interface is built around the
``lookup_batch`` method that fetches outcomes for one model across many
question_global_ids in a single SQL query — that's the hot path.

Schema (matches outcomes.parquet — see P5 of the patch list):
    question_global_id  string   FK to Qdrant payload
    model_id            string   matches registry.json
    outcome             float32  0.0–1.0 (normalised pass/fail or graded)
    source_url          string   provenance
    ingested_at         timestamp

Question metadata (text, modality, language, etc.) lives in the Qdrant payload
only — NOT denormalised here. That's the deliberate design from the revised
plan: Qdrant answers "what's the question?", DuckDB answers "did this model
get it right?".
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Schema constants — shared with the build scripts
# ============================================================================

OUTCOME_COLUMNS = ["question_global_id", "model_id", "outcome", "source_url", "ingested_at"]


# ============================================================================
# Store
# ============================================================================


class OutcomeStore:
    """DuckDB-backed read-only view over outcomes.parquet.

    Thread-safe. Lazy-loads the DuckDB connection on first lookup so unit tests
    don't pay the import cost just by importing this module.

    All public methods take ``model_id`` first then question identifiers so
    batched queries hit DuckDB with a single SQL statement.
    """

    def __init__(self, parquet_path: str | Path) -> None:
        self._path = Path(parquet_path)
        if not self._path.is_absolute():
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            self._path = (repo_root / self._path).resolve()
        self._lock = threading.RLock()
        self._conn = None
        self._loaded = False

    # ---------- lifecycle ----------

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                import duckdb  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "duckdb is required for OutcomeStore — run `pip install duckdb`"
                ) from exc

            if not self._path.exists():
                raise FileNotFoundError(
                    f"outcomes.parquet not found at {self._path} — "
                    f"run scripts/layer3/build_outcomes_corpus.py first"
                )

            self._conn = duckdb.connect(":memory:")
            # Register as a view rather than loading into memory — DuckDB will
            # memory-map and scan the Parquet file on demand.
            self._conn.execute(
                f"CREATE VIEW outcomes AS SELECT * FROM read_parquet('{self._path.as_posix()}')"
            )
            # Index helpers (DuckDB doesn't need explicit indexes for Parquet,
            # but we cache the row count for stats() and a sanity check).
            row_count = self._conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            unique_models = self._conn.execute(
                "SELECT COUNT(DISTINCT model_id) FROM outcomes"
            ).fetchone()[0]
            unique_questions = self._conn.execute(
                "SELECT COUNT(DISTINCT question_global_id) FROM outcomes"
            ).fetchone()[0]

            logger.info(
                "layer3_outcome_store_loaded",
                path=str(self._path),
                rows=row_count,
                unique_models=unique_models,
                unique_questions=unique_questions,
            )
            self._loaded = True

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                self._loaded = False

    # ---------- single-model batched lookup (the hot path) ----------

    def lookup_batch(
        self,
        model_id: str,
        question_global_ids: list[str],
    ) -> dict[str, float]:
        """Return ``{question_global_id: outcome}`` for the (model_id, qid)
        pairs present in the corpus. Missing pairs are omitted from the dict
        — callers handle the prior fallback.
        """
        if not question_global_ids:
            return {}
        self._ensure_loaded()
        with self._lock:
            assert self._conn is not None
            placeholders = ",".join("?" * len(question_global_ids))
            sql = (
                "SELECT question_global_id, outcome "
                "FROM outcomes "
                f"WHERE model_id = ? AND question_global_id IN ({placeholders})"
            )
            params = [model_id, *question_global_ids]
            rows = self._conn.execute(sql, params).fetchall()
            return {qid: float(outcome) for qid, outcome in rows}

    def lookup_for_all_models(
        self,
        question_global_ids: list[str],
        model_ids: list[str],
    ) -> dict[str, dict[str, float]]:
        """Return ``{model_id: {question_global_id: outcome}}`` across many models.

        Used by the kNN router's per-model quality prediction. One SQL roundtrip
        for all (model, question) combinations.
        """
        if not question_global_ids or not model_ids:
            return {model_id: {} for model_id in model_ids}
        self._ensure_loaded()
        with self._lock:
            assert self._conn is not None
            q_placeholders = ",".join("?" * len(question_global_ids))
            m_placeholders = ",".join("?" * len(model_ids))
            sql = (
                "SELECT model_id, question_global_id, outcome "
                "FROM outcomes "
                f"WHERE model_id IN ({m_placeholders}) "
                f"AND question_global_id IN ({q_placeholders})"
            )
            params = [*model_ids, *question_global_ids]
            rows = self._conn.execute(sql, params).fetchall()

            result: dict[str, dict[str, float]] = {mid: {} for mid in model_ids}
            for model_id, qid, outcome in rows:
                result[model_id][qid] = float(outcome)
            return result

    # ---------- coverage analytics ----------

    def coverage_for_model(self, model_id: str) -> dict:
        """Per-model coverage stats. Used by build_aggregate_scores.py to
        auto-tag coverage_quality, and by validation scripts to report
        per-(model, validation_query) coverage.
        """
        self._ensure_loaded()
        with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT COUNT(*) AS n_outcomes, "
                "COUNT(DISTINCT question_global_id) AS n_unique_questions, "
                "AVG(outcome) AS mean_outcome "
                "FROM outcomes WHERE model_id = ?",
                [model_id],
            ).fetchone()
            n_outcomes, n_unique, mean_outcome = row
            return {
                "model_id": model_id,
                "n_outcomes": int(n_outcomes or 0),
                "n_unique_questions": int(n_unique or 0),
                "mean_outcome": float(mean_outcome) if mean_outcome is not None else None,
            }

    def coverage_by_source(self, source_url_prefix: Optional[str] = None) -> list[dict]:
        """Per-source counts. ``source_url_prefix`` filters to one source family."""
        self._ensure_loaded()
        with self._lock:
            assert self._conn is not None
            if source_url_prefix is None:
                sql = (
                    "SELECT source_url, COUNT(*) AS n "
                    "FROM outcomes GROUP BY source_url ORDER BY n DESC"
                )
                rows = self._conn.execute(sql).fetchall()
            else:
                sql = (
                    "SELECT source_url, COUNT(*) AS n "
                    "FROM outcomes WHERE source_url LIKE ? "
                    "GROUP BY source_url ORDER BY n DESC"
                )
                rows = self._conn.execute(sql, [source_url_prefix + "%"]).fetchall()
            return [{"source_url": s, "n": int(n)} for s, n in rows]

    def stats(self) -> dict:
        """Top-level corpus summary."""
        self._ensure_loaded()
        with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT COUNT(*) AS rows, "
                "COUNT(DISTINCT model_id) AS unique_models, "
                "COUNT(DISTINCT question_global_id) AS unique_questions "
                "FROM outcomes"
            ).fetchone()
            rows, n_models, n_questions = row
            return {
                "rows": int(rows or 0),
                "unique_models": int(n_models or 0),
                "unique_questions": int(n_questions or 0),
                "parquet_path": str(self._path),
            }

    def all_models(self) -> list[str]:
        """Distinct model_ids present in the corpus. Useful for sanity-checking
        against the registry.
        """
        self._ensure_loaded()
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT DISTINCT model_id FROM outcomes ORDER BY model_id"
            ).fetchall()
            return [r[0] for r in rows]


# ============================================================================
# Singleton
# ============================================================================

_store: Optional[OutcomeStore] = None
_store_lock = threading.Lock()


def get_outcome_store() -> OutcomeStore:
    """Process-wide OutcomeStore using the path from routing_config."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                cfg = get_routing_config()
                _store = OutcomeStore("data/processed/outcomes.parquet")
    return _store


def reset_outcome_store() -> None:
    """Test helper."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
