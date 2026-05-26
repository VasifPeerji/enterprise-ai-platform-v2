"""
Shared utilities for the Layer 3 data pipeline scripts.

  • Repo-root resolution
  • Model-ID mapping loader
  • Outcome accumulator (write to outcomes.parquet)
  • Question metadata accumulator (will be loaded into Qdrant payload later)
  • Per-source logging helpers
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ARTIFACTS_LAYER3 = REPO_ROOT / "artifacts" / "layer3"

OUTCOMES_PARQUET = PROCESSED_DIR / "outcomes.parquet"
QUESTIONS_PARQUET = PROCESSED_DIR / "questions.parquet"
VALIDATION_PARQUET = PROCESSED_DIR / "validation_set.parquet"
VALIDATION_OUTCOMES_PARQUET = PROCESSED_DIR / "validation_outcomes.parquet"
VALIDATION_IDS_JSON = DATA_DIR / "validation_set_ids.json"

REGISTRY_PATH = REPO_ROOT / "src/layer0_model_infra/data/registry.json"
AGGREGATE_SCORES_PATH = REPO_ROOT / "src/layer0_model_infra/data/model_aggregate_scores.json"
MODEL_ID_MAPPING_PATH = REPO_ROOT / "src/layer0_model_infra/data/model_id_mapping.json"


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, PROCESSED_DIR, ARTIFACTS_LAYER3):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def get_pipeline_logger(name: str) -> logging.Logger:
    """Stdout-only logger for scripts. Avoids the structlog dependency the
    main app uses, since these scripts may run in minimal envs."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# Model-ID mapping
# ---------------------------------------------------------------------------

class ModelIdMapper:
    """Loads model_id_mapping.json and maps source-specific identifiers to
    our registry model_ids. Missing mappings return None — caller drops the row.
    """

    def __init__(self, path: Path = MODEL_ID_MAPPING_PATH) -> None:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        self._by_source: dict[str, dict[str, str]] = {
            k: v for k, v in payload.items() if not k.startswith("_")
        }
        self.unmapped_seen: dict[str, set[str]] = {k: set() for k in self._by_source}

    def map(self, source_key: str, source_model_id: str) -> Optional[str]:
        """Look up our registry model_id for a source-specific identifier.

        Returns None on miss; the caller should DROP the outcome row rather
        than silently mis-attribute. Unmapped IDs are remembered for the
        post-build coverage report.
        """
        if source_key not in self._by_source:
            return None
        mapped = self._by_source[source_key].get(source_model_id)
        if mapped is None:
            self.unmapped_seen[source_key].add(source_model_id)
        return mapped

    def known_source_models(self, source_key: str) -> set[str]:
        return set(self._by_source.get(source_key, {}).keys())

    def known_registry_models(self, source_key: str) -> set[str]:
        return set(self._by_source.get(source_key, {}).values())

    def report(self, logger: logging.Logger) -> None:
        """Print which source-specific IDs were seen but not mapped — these
        are candidates for adding to the mapping file in the next refresh.
        """
        for source_key, missing in self.unmapped_seen.items():
            if missing:
                logger.info(
                    "model_id_unmapped",
                    extra={"source": source_key, "n_unmapped": len(missing)},
                )
                for name in sorted(missing)[:10]:
                    logger.info("  %s :: %s (unmapped — add to model_id_mapping.json)", source_key, name)


# ---------------------------------------------------------------------------
# Accumulator (in-memory list of outcome rows; flushed to Parquet at end)
# ---------------------------------------------------------------------------

@dataclass
class OutcomeRow:
    question_global_id: str
    model_id: str
    outcome: float
    source_url: str
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class QuestionRow:
    """One row per UNIQUE question. Loaded into Qdrant payload later."""
    question_global_id: str
    question_text: str
    benchmark_source: str
    language: str = "en"
    modality: str = "text"
    domain: str = "general"
    difficulty_tier: str = "moderate"


class CorpusAccumulator:
    """Collects outcome + question rows from per-source builders and writes
    deduplicated Parquet files at the end of a build.
    """

    def __init__(self) -> None:
        self.outcomes: list[OutcomeRow] = []
        self._seen_outcomes: set[tuple[str, str]] = set()  # (model_id, question_global_id)
        self.questions: dict[str, QuestionRow] = {}  # question_global_id → row

    # ---- ingest ----

    def add_outcome(self, row: OutcomeRow) -> bool:
        """Returns True if added, False if a (model_id, question) duplicate."""
        key = (row.model_id, row.question_global_id)
        if key in self._seen_outcomes:
            return False
        # Clamp outcome to [0, 1]
        row = OutcomeRow(
            question_global_id=row.question_global_id,
            model_id=row.model_id,
            outcome=max(0.0, min(1.0, float(row.outcome))),
            source_url=row.source_url,
            ingested_at=row.ingested_at,
        )
        self.outcomes.append(row)
        self._seen_outcomes.add(key)
        return True

    def add_question(self, row: QuestionRow) -> None:
        """Idempotent — first writer wins per question_global_id."""
        if row.question_global_id in self.questions:
            return
        self.questions[row.question_global_id] = row

    # ---- summary ----

    def summary(self) -> dict:
        unique_models = len({r.model_id for r in self.outcomes})
        unique_questions = len({r.question_global_id for r in self.outcomes})
        return {
            "n_outcomes": len(self.outcomes),
            "n_unique_models": unique_models,
            "n_unique_questions": unique_questions,
            "n_question_rows": len(self.questions),
        }

    # ---- flush ----

    def write_outcomes_parquet(self, path: Path = OUTCOMES_PARQUET) -> None:
        """Write outcomes.parquet using pyarrow. Schema matches outcome_store.py."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "question_global_id": [r.question_global_id for r in self.outcomes],
                "model_id": [r.model_id for r in self.outcomes],
                "outcome": [r.outcome for r in self.outcomes],
                "source_url": [r.source_url for r in self.outcomes],
                "ingested_at": [r.ingested_at for r in self.outcomes],
            },
            schema=pa.schema(
                [
                    ("question_global_id", pa.string()),
                    ("model_id", pa.string()),
                    ("outcome", pa.float32()),
                    ("source_url", pa.string()),
                    ("ingested_at", pa.timestamp("us", tz="UTC")),
                ]
            ),
        )
        pq.write_table(table, path, compression="zstd")

    def write_questions_parquet(self, path: Path = QUESTIONS_PARQUET) -> None:
        """Write the deduplicated questions table. Consumed by embed_corpus.py
        to populate Qdrant payload.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(self.questions.values())
        table = pa.table(
            {
                "question_global_id": [r.question_global_id for r in rows],
                "question_text": [r.question_text for r in rows],
                "benchmark_source": [r.benchmark_source for r in rows],
                "language": [r.language for r in rows],
                "modality": [r.modality for r in rows],
                "domain": [r.domain for r in rows],
                "difficulty_tier": [r.difficulty_tier for r in rows],
            }
        )
        pq.write_table(table, path, compression="zstd")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_question_global_id(benchmark: str, local_id: str | int) -> str:
    """Compose ``{benchmark}:{local_id}`` — must be deterministic so the same
    benchmark question gets the same id across builds.
    """
    return f"{benchmark}:{local_id}"


def hash_text_id(benchmark: str, text: str) -> str:
    """Stable id when the source doesn't expose its own per-question ID."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{benchmark}:sha-{digest}"


def normalise_outcome(value, *, scale_min: float = 0.0, scale_max: float = 1.0) -> float:
    """Clamp + normalise a numeric outcome to [0, 1].

    Sources report outcomes in different scales:
      • binary pass/fail → 0.0 / 1.0
      • LiveBench judge → 0.0–1.0 already
      • MT-Bench → 1–10 → /10 → [0.1, 1.0]
      • Arena-Hard win-rate vs baseline → [0, 1]

    Callers should pass scale_min/scale_max so this returns ``(value - min) / (max - min)``
    clamped to [0, 1].
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if scale_max == scale_min:
        return 0.5
    normalised = (v - scale_min) / (scale_max - scale_min)
    return max(0.0, min(1.0, normalised))


# ---------------------------------------------------------------------------
# Validation ID locking (P7)
# ---------------------------------------------------------------------------

def load_locked_validation_ids() -> set[str]:
    """Return the set of question_global_ids that must be excluded from the
    kNN corpus side. Built by scripts/layer3/build_validation_set.py.
    Returns an empty set if validation hasn't been built yet — first-time
    corpus builds proceed without exclusion.
    """
    if not VALIDATION_IDS_JSON.exists():
        return set()
    with VALIDATION_IDS_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("locked_ids", []))
