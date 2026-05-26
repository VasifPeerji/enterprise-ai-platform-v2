# Layer 3 — Operations Runbook

> Day-to-day operational tasks for the Layer 3 benchmark-driven kNN router.

## First-time setup (fresh checkout)

```bash
# 1. Install deps (assumes the conda env is already created)
pip install -r requirements.txt

# 2. Start Qdrant
docker-compose up -d qdrant

# 3. Build the validation set FIRST (so its IDs are locked out of the kNN corpus)
python -m scripts.layer3.build_validation_set

# 4. Build the kNN corpus from public benchmark data
python -m scripts.layer3.build_outcomes_corpus

# 5. Create the Qdrant collection
python -m scripts.layer3.setup_qdrant_collection

# 6. Pick an encoder by measuring on this hardware
python -m scripts.layer3.benchmark_encoders

# 7. Embed the corpus into Qdrant
python -m scripts.layer3.embed_corpus
```

## Monthly corpus refresh

```bash
# Pull the latest LiveBench / MMLU-Pro / LiveCodeBench / SWE-bench releases
python -m scripts.layer3.build_outcomes_corpus

# Re-embed (the encoder doesn't change; only new questions get re-embedded
# because the script keeps the existing collection. To force a full rebuild:
# python -m scripts.layer3.setup_qdrant_collection  # drops + recreates)
python -m scripts.layer3.embed_corpus
```

The kNN router picks up new outcomes on its next process restart (DuckDB memory-maps the parquet file).

## Adding a new model to the registry

1. Edit `src/layer0_model_infra/data/registry.json` — add the new entry with `coverage_quality` honestly tagged based on per-question benchmark availability (audit a few benchmarks first; new releases usually start at `low`).
2. Add the new model's identifiers to `src/layer0_model_infra/data/model_id_mapping.json` so future corpus builds attribute its outcomes correctly.
3. Add an entry for it to `src/layer0_model_infra/data/model_aggregate_scores.json` with at least `arena_elo_normalised` if no per-benchmark scores are yet published.
4. Deploy. The model enters a **warmup window** automatically (~30 days or 100 observations, whichever comes first — see `Layer3Config.warmup`). During warmup it's force-selected 5% of the time to seed calibration data.
5. Monitor `layer3_warmup_routes_total{model_id="..."}` — it should accumulate ~100 over a week. After 100 observations, the model exits warmup and is governed by normal floor rules.

## Adding a new API provider key

The registry's `is_active` field is gated on each model's `required_env_var`. So:

1. Add the new key to your `.env` (or set the env var on the running process)
2. Call `Layer3Registry.refresh_activation()` — the relevant models flip to `is_active=True` without a restart
3. Or just restart — the loader reads env vars on construction

The reverse works the same way: remove a key, call refresh, those provider's models become inactive immediately.

## Common failures

### "outcomes.parquet not found"

The kNN router is being called before the corpus has been built. Run:

```bash
python -m scripts.layer3.build_validation_set
python -m scripts.layer3.build_outcomes_corpus
```

### "Qdrant collection 'layer3_benchmark_corpus' missing"

```bash
python -m scripts.layer3.setup_qdrant_collection
python -m scripts.layer3.embed_corpus
```

### "GPQA-Diamond gated"

Expected for fresh checkouts. The dataset requires accepting the gate at https://huggingface.co/datasets/Idavidrein/gpqa with a HuggingFace token:

```bash
huggingface-cli login    # paste a token that has accepted the gate
python -m scripts.layer3.build_outcomes_corpus --sources gpqa_diamond
```

If you can't accept the gate, GPQA is fine to skip — its 198 questions are well-substituted by the hardest slice of MMLU-Pro.

### "CUDA not available — falling back to CPU"

Either CUDA isn't installed correctly, or torch wasn't built with CUDA support. Reinstall:

```bash
pip uninstall -y torch
pip install --index-url https://download.pytorch.org/whl/cu124 torch
```

### "Coverage for model X is suspiciously low"

Run `python -m scripts.layer3.build_outcomes_corpus` again with the model's source-specific identifiers explicitly mapped in `model_id_mapping.json`. The build script logs unmapped source IDs at the end of each run — those are the candidates to add.

### "kNN routing latency suddenly spiked"

Check, in order:

1. `docker stats enterprise-ai-qdrant` — is Qdrant healthy?
2. GPU `nvidia-smi` — is the encoder model still loaded? OOM crashes will silently restart the encoder cold.
3. `artifacts/layer3/embed_report.json` — was the corpus partially indexed? Sanity-probe results should show high-quality neighbors.

## Calibration auto-tune

Every 30 days, regenerate the quality floor from observed Layer 7 scores:

```bash
python -m scripts.layer3.calibrate_quality_floor
```

The script reads the last 30 days of telemetry, computes the optimal floor where Layer 7 acceptance rate ≥ 90%, and proposes a new value. Apply by editing `Layer3Config.quality_floor.default` in `routing_config.py`.

(Implementation deferred to Batch 4 alongside Stage C calibration plumbing.)

## Telemetry health checks

| Metric | Healthy range | Action if outside |
|---|---|---|
| `layer3_decisions_total{source="cache_hit"} / total` | 30-50% after warmup | If <10%, cache is cold — investigate restarts |
| `layer3_decision_latency_ms{source="knn_corpus"} p99` | < 200 ms | Encoder cold-start, Qdrant slow, or batch sizing |
| `layer3_fallback_total / total` | < 5% | Corpus thin in the affected modality — add more sources |
| `layer3_over_routing_rate{modality="*"}` | < 2% | P1 coverage tags drifting; re-tag using `coverage_for_model()` |
| `layer3_rate_limit_escalations_total` | bursty, < 1/hr sustained | Free-tier rate limits saturated — buy/add paid keys |
