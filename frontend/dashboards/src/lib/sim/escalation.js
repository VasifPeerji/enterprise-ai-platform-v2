/* Reproduces EscalationEngine.path_from_qualifiers + should_escalate
   (src/layer0_model_infra/routing/escalation_engine.py). The ladder is built
   from Layer 3's cost-sorted qualifying set: start at the selected pick, climb
   ONLY to more-expensive ACTIVE qualifiers, skip cooled-down / rate-limited
   models, never go downward, capped at MAX_LEVELS escalations. The trigger is
   the cost-free Layer 7 quality signal — no LLM judge. */

export const MAX_LEVELS = 3

// A representative cost-sorted qualifying set from Layer 3.
export const QUALIFYING = [
  { id: 'gpt-oss-20b', label: 'GPT-OSS 20B', size: 20, active: true },
  { id: 'qwen3-32b', label: 'Qwen3 32B', size: 32, active: true },
  { id: 'llama-3.3-70b', label: 'Llama 3.3 70B', size: 70, active: true },
  { id: 'gpt-oss-120b', label: 'GPT-OSS 120B', size: 120, active: true },
  { id: 'claude-opus', label: 'Claude Opus', size: 999, active: false },
]

export function buildLadder(qualifying, selectedId, cooled = new Set()) {
  const sorted = [...qualifying].sort((a, b) => a.size - b.size)
  const start = sorted.findIndex((m) => m.id === selectedId)
  const ladder = [{ ...sorted[start], role: 'start' }]
  for (let i = start + 1; i < sorted.length && ladder.length <= MAX_LEVELS; i++) {
    const m = sorted[i]
    if (!m.active) { continue } // keyless → escalating buys nothing
    if (cooled.has(m.id)) { continue } // rate-limited / cooling down
    ladder.push({ ...m, role: 'rung' })
  }
  return ladder
}

export const SCENARIOS = [
  { label: 'First answer is good', succeedAt: 0, reasons: [] },
  { label: 'Truncated → climb once', succeedAt: 1, reasons: ['truncation'] },
  { label: 'Two weak answers', succeedAt: 2, reasons: ['low quality', 'refusal'] },
  { label: 'Persistent failure → halt', succeedAt: -1, reasons: ['truncation', 'low quality', 'refusal', 'low quality'] },
]

export function runScenario(ladder, scenario) {
  const steps = ladder.map((m, i) => {
    if (scenario.succeedAt === -1) {
      return { model: m, status: 'fail', reason: scenario.reasons[i] || 'low quality' }
    }
    if (i < scenario.succeedAt) return { model: m, status: 'fail', reason: scenario.reasons[i] || 'low quality' }
    if (i === scenario.succeedAt) return { model: m, status: 'pass', reason: '' }
    return { model: m, status: 'unreached', reason: '' }
  })
  const halted = scenario.succeedAt === -1
  const attempts = halted ? ladder.length : scenario.succeedAt + 1
  const finalModel = halted ? ladder[ladder.length - 1].label : ladder[scenario.succeedAt]?.label
  return { steps, halted, attempts, escalations: attempts - 1, finalModel }
}
