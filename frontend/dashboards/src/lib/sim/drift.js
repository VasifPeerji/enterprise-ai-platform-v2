/* Reproduces the Layer 9 DriftDetector (src/.../routing/drift_detector.py): a
   per-model KL-divergence between a recent and a reference predicted-quality
   histogram (10 bins over [0,1], Laplace-smoothed), classified info / warn /
   halt against Layer3DriftConfig. On halt the real system freezes that model's
   online calibration so the EMA stops chasing a non-stationary signal. */

export const BINS = 10
export const THRESHOLDS = { info: 0.1, warn: 0.15, halt: 0.3 }

// Deterministic gaussian-shaped histogram centred at `center` (0..1).
export function hist(center, spread = 0.2, n = 200) {
  const counts = new Array(BINS).fill(0)
  for (let i = 0; i < BINS; i++) {
    const x = (i + 0.5) / BINS
    counts[i] = Math.exp(-((x - center) ** 2) / (2 * spread * spread))
  }
  const s = counts.reduce((a, b) => a + b, 0)
  return counts.map((c) => (c / s) * n)
}

const LAPLACE = 3
function normalize(counts) {
  const s = counts.reduce((a, b) => a + b, 0) + BINS * LAPLACE
  return counts.map((c) => (c + LAPLACE) / s)
}

export function klDivergence(recent, reference) {
  const p = normalize(recent), q = normalize(reference)
  let s = 0
  for (let i = 0; i < BINS; i++) s += p[i] * Math.log(p[i] / q[i])
  return s
}

export function classify(kl) {
  if (kl >= THRESHOLDS.halt) return 'halt'
  if (kl >= THRESHOLDS.warn) return 'warn'
  if (kl >= THRESHOLDS.info) return 'info'
  return 'stable'
}

// drift = how far the recent predicted-quality distribution has shifted down.
export function driftScan(drift) {
  const reference = hist(0.75)
  const recent = hist(0.75 - drift)
  const kl = klDivergence(recent, reference)
  return { reference, recent, kl, level: classify(kl) }
}

// Representative telemetry buffer stats (what TelemetryLogger.get_buffer_stats
// returns in production from real traffic).
export const TELEMETRY = {
  buffer_size: 210,
  routing_source: [
    { source: 'knn_corpus', count: 142 },
    { source: 'fast_path', count: 38 },
    { source: 'cache_hit', count: 21 },
    { source: 'fallback', count: 9 },
  ],
  escalation_rate: 0.11,
  avg_quality: 0.74,
  avg_latency_ms: 96,
  predicted_quality: hist(0.75, 0.12, 210),
}
