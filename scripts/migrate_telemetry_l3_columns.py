"""Idempotent migration: add the Layer 3 routing-signal columns to routing_telemetry.

Fresh databases get these columns automatically (SQLModel create_all from the
RoutingTelemetryRecord model). An EXISTING database (e.g. a Postgres instance that
predates the Layer 9 observability work) needs this ALTER TABLE, because create_all
never alters a table that already exists -- so without it, every telemetry insert
fails with 'column "routing_source" does not exist'. Safe to re-run: it only adds
columns that are missing.

Run:
    python scripts/migrate_telemetry_l3_columns.py
"""
from __future__ import annotations

import os

from dotenv import dotenv_values
from sqlalchemy import inspect, text

# Make the DB URL from .env visible to the app's Settings in this standalone run.
for _k, _v in dotenv_values(".env").items():
    if _v and _k not in os.environ:
        os.environ[_k] = _v.strip()

from src.database.connection import get_engine  # noqa: E402

# (column name, postgres type, default literal)
_COLUMNS = [
    ("routing_source", "VARCHAR", "''"),
    ("predicted_quality", "DOUBLE PRECISION", "0"),
    ("prediction_confidence_score", "DOUBLE PRECISION", "0"),
    ("uncertainty_escalated", "BOOLEAN", "false"),
]


def main() -> None:
    engine = get_engine()
    dialect = engine.dialect.name
    existing = {c["name"] for c in inspect(engine).get_columns("routing_telemetry")}
    added = []
    with engine.begin() as conn:
        for name, pg_type, default in _COLUMNS:
            if name in existing:
                continue
            # SQLite has no DOUBLE PRECISION; map to REAL.
            col_type = pg_type if dialect == "postgresql" else (
                "REAL" if "PRECISION" in pg_type else pg_type
            )
            conn.execute(
                text(f"ALTER TABLE routing_telemetry ADD COLUMN {name} {col_type} DEFAULT {default}")
            )
            added.append(name)
    print(f"dialect={dialect} added={added or 'none (already present)'}")


if __name__ == "__main__":
    main()
