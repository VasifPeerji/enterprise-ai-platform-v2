"""Layer 3 data pipeline scripts.

Each script in this package is independently runnable from the repo root, e.g.:

    python -m scripts.layer3.build_outcomes_corpus
    python -m scripts.layer3.benchmark_encoders
    python -m scripts.layer3.embed_corpus

Shared utilities live in ``_common.py``; per-source corpus builders in
``_sources/``.
"""
