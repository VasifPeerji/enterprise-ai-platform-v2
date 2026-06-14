/* Faithful port of TestTimeComputeEngine.should_use_ttc()
   (src/layer0_model_infra/routing/test_time_compute.py). Same activation
   window, band rules, strategy selection and sample counts. TTC is OFF by
   default in production — it only fires inside a narrow uncertainty band. */

export const BANDS = ['trivial', 'simple', 'moderate', 'complex', 'expert']

export const TASKS = [
  { label: 'Factual QA', task_type: 'qa', intent: 'factual' },
  { label: 'Math problem', task_type: 'qa', intent: 'question_answering' },
  { label: 'Coding', task_type: 'generation', intent: 'coding' },
  { label: 'Code analysis', task_type: 'analysis', intent: 'code_review' },
  { label: 'Creative writing', task_type: 'generation', intent: 'creative' },
]

export const STRATEGIES = {
  best_of_n: { name: 'Best-of-N', blurb: 'Generate N responses at varied temperature, keep the highest-quality one.', best_for: 'creative / planning' },
  self_consistency: { name: 'Self-Consistency', blurb: 'Generate N responses, extract the answer from each, return the majority.', best_for: 'factual / QA / math' },
  generator_verifier: { name: 'Generator-Verifier', blurb: 'Generate one response, verify it, regenerate on failure (up to 3 tries).', best_for: 'coding / analysis' },
}

function selectStrategy(task_type, intent) {
  if (['qa', 'conversation'].includes(task_type) || ['question_answering', 'factual'].includes(intent)) return 'self_consistency'
  if (task_type === 'analysis' || ['coding', 'debugging', 'code_review'].includes(intent)) return 'generator_verifier'
  return 'best_of_n'
}

export function decide({ uncertainty, band, tier, task_type, intent }) {
  if (uncertainty < 0.4) return { should_use: false, blockedBy: 'uncertainty_low', reason: 'Low uncertainty — a single sample is sufficient.' }
  if (uncertainty > 0.6) return { should_use: false, blockedBy: 'uncertainty_high', reason: 'High uncertainty — escalation is preferred over extra sampling.' }
  if (band === 'trivial' || band === 'simple') return { should_use: false, blockedBy: 'too_simple', reason: `${band} complexity — too simple to be worth extra compute.` }
  if (band === 'expert') return { should_use: false, blockedBy: 'expert', reason: 'Expert-level — escalate to a stronger model instead of sampling.' }

  const strategy = selectStrategy(task_type, intent)
  const num_samples = strategy === 'generator_verifier' ? 3 : tier === 'premium' ? 3 : 2

  if (band === 'moderate' || band === 'complex') {
    return { should_use: true, strategy, num_samples, reason: `Moderate uncertainty + ${band} complexity → ${STRATEGIES[strategy].name} with ${num_samples} samples.` }
  }
  return { should_use: false, blockedBy: 'default', reason: 'Default: single sample.' }
}
