<script>
  // Interactive end-to-end view of the routing pipeline. Pick an example query
  // and watch which stages fire, short-circuit, or are skipped — with the real
  // decision shown at each stage. Faithful to ModelRouter.route() +
  // execution_loop.py ordering.

  const stages = [
    { id: 'l0', badge: 'L0', name: 'Fast Path', phase: 'route', desc: 'Trivial-query bypass' },
    { id: 'l1', badge: 'L1', name: 'Modality Gate', phase: 'route', desc: 'Security + modality / language / code' },
    { id: 'l15', badge: 'L1½', name: 'Input Signals', phase: 'route', desc: 'Continuous difficulty' },
    { id: 'l2', badge: 'L2', name: 'Semantic Memory', phase: 'route', desc: 'Outcome-aware cache' },
    { id: 'l3', badge: 'L3', name: 'kNN Router', phase: 'route', desc: 'Benchmark-grounded model pick' },
    { id: 'exec', badge: '⚙', name: 'Gateway Execute', phase: 'exec', desc: 'Run the selected model' },
    { id: 'l6', badge: 'L6', name: 'Test-Time Compute', phase: 'exec', desc: 'Extra samples if uncertain' },
    { id: 'l7', badge: 'L7', name: 'Quality Eval', phase: 'exec', desc: 'Cost-free correctness check' },
    { id: 'l8', badge: 'L8', name: 'Escalation', phase: 'exec', desc: 'Climb only on failure' },
    { id: 'l9', badge: 'L9', name: 'Telemetry + Drift', phase: 'exec', desc: 'Log, calibrate, watch drift' },
  ]

  // status per stage: fire | route | active | miss | skip | fail | na
  const examples = [
    {
      label: 'Greeting',
      query: 'hey there, how are you?',
      exit: 'L0 bypass',
      exitTone: 'amber',
      s: {
        l0: ['fire', 'TRIVIAL_GREETING → bypass'], l1: ['skip', 'bypassed'], l15: ['skip', ''],
        l2: ['skip', ''], l3: ['skip', ''], exec: ['active', 'llama-3.1-8b · $0'],
        l6: ['skip', ''], l7: ['active', 'ok'], l8: ['skip', 'no escalation'], l9: ['active', 'source: fast_path'],
      },
    },
    {
      label: 'Simple fact',
      query: 'what is the capital of Japan?',
      exit: 'L0 bypass',
      exitTone: 'amber',
      s: {
        l0: ['fire', 'SIMPLE_FACTUAL → bypass'], l1: ['skip', ''], l15: ['skip', ''],
        l2: ['skip', ''], l3: ['skip', ''], exec: ['active', 'llama-3.1-8b · $0'],
        l6: ['skip', ''], l7: ['active', 'ok'], l8: ['skip', ''], l9: ['active', 'source: fast_path'],
      },
    },
    {
      label: 'Coding task',
      query: 'Write a Python function to merge two sorted lists.',
      exit: 'L3 route',
      exitTone: 'accent',
      s: {
        l0: ['active', 'no bypass'], l1: ['active', 'CODE_HEAVY · en'], l15: ['active', 'difficulty: normal 0.42'],
        l2: ['miss', 'novel → MISS'], l3: ['route', 'kNN → gpt-oss-20b · pred 0.71'], exec: ['active', 'gpt-oss-20b'],
        l6: ['skip', 'confident → off'], l7: ['active', 'compiles · ok'], l8: ['skip', 'no escalation'], l9: ['active', 'source: knn_corpus'],
      },
    },
    {
      label: 'Repeat query',
      query: 'Write a Python function to merge two sorted lists.',
      exit: 'L2 cache hit',
      exitTone: 'amber',
      s: {
        l0: ['active', 'no bypass'], l1: ['active', 'CODE_HEAVY · en'], l15: ['active', 'difficulty: normal'],
        l2: ['fire', 'HIT sim 0.97 → reuse gpt-oss-20b'], l3: ['skip', 'served from cache'], exec: ['active', 'gpt-oss-20b (cached)'],
        l6: ['skip', ''], l7: ['active', 'ok'], l8: ['skip', ''], l9: ['active', 'source: cache_hit'],
      },
    },
    {
      label: 'Hard proof',
      query: 'Prove that the square root of 2 is irrational.',
      exit: 'L3 route',
      exitTone: 'accent',
      s: {
        l0: ['active', 'no bypass'], l1: ['active', 'TEXT · en'], l15: ['active', 'difficulty: hard 0.78'],
        l2: ['miss', 'novel → MISS'], l3: ['route', 'hard floor +0.10 → claude-opus*'], exec: ['active', 'claude-opus* → exec free 70B'],
        l6: ['skip', ''], l7: ['active', 'ok'], l8: ['skip', ''], l9: ['active', 'source: knn_corpus'],
      },
    },
    {
      label: 'High-risk',
      query: 'How do I treat a deep cut at home?',
      exit: 'L3 route',
      exitTone: 'violet',
      s: {
        l0: ['active', 'no bypass'], l1: ['active', 'TEXT · en'], l15: ['active', 'difficulty: normal'],
        l2: ['miss', 'MISS'], l3: ['route', 'HIGH-RISK medical → floor 0.75'], exec: ['active', 'strong free model'],
        l6: ['skip', ''], l7: ['active', 'ok'], l8: ['skip', ''], l9: ['active', 'high_risk: medical'],
      },
    },
    {
      label: 'Escalation',
      query: 'Summarize this 40-page contract into 5 bullet points.',
      exit: 'L8 escalates',
      exitTone: 'amber',
      s: {
        l0: ['active', 'no bypass'], l1: ['active', 'DOCUMENT · long'], l15: ['active', 'difficulty: normal, long'],
        l2: ['miss', 'MISS'], l3: ['route', 'kNN → gpt-oss-20b'], exec: ['active', 'gpt-oss-20b → truncates'],
        l6: ['skip', ''], l7: ['fail', 'truncation detected'], l8: ['active', 'climb → llama-3.3-70b ✓'], l9: ['active', 'uncertainty_escalated'],
      },
    },
  ]

  let selected = $state(2)
  const cur = $derived(examples[selected])
  const star = $derived(cur.exit.includes('claude') || cur.s.l3?.[1]?.includes('claude'))
</script>

<div class="flow">
  <div class="picker">
    <span class="picker-label">Try a query:</span>
    <div class="chips">
      {#each examples as ex, i}
        <button class="chip" class:on={selected === i} onclick={() => (selected = i)}>{ex.label}</button>
      {/each}
    </div>
  </div>

  <div class="query-bar">
    <span class="prompt">›</span>
    <span class="qtext">{cur.query}</span>
    <span class="exit {cur.exitTone}">{cur.exit}</span>
  </div>

  {#key selected}
    <div class="stages">
      {#each stages as st, i}
        {@const status = cur.s[st.id]?.[0] || 'na'}
        {@const note = cur.s[st.id]?.[1] || ''}
        {#if st.phase === 'exec' && stages[i - 1]?.phase === 'route'}
          <div class="divider"><span>Execution loop · execution_loop.py</span></div>
        {/if}
        <div class="stage {status}" style="animation-delay:{i * 55}ms">
          <div class="rail">
            <span class="node">{st.badge}</span>
          </div>
          <div class="content">
            <div class="line1">
              <span class="sname">{st.name}</span>
              {#if note}<span class="snote {status}">{note}</span>{/if}
            </div>
            <div class="sdesc">{st.desc}</div>
          </div>
        </div>
      {/each}
    </div>
  {/key}

  {#if star}
    <p class="footnote">* premium model is <em>selected</em> when benchmark-best, but execution falls back to a free model until a key is added — so the displayed pick can differ from what actually runs.</p>
  {/if}
</div>

<style>
  .flow { display: flex; flex-direction: column; gap: 16px; }
  .picker { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .picker-label { font-size: 13px; color: var(--text-3); font-weight: 600; }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; }
  .chip {
    background: var(--surface-2);
    border: 1px solid var(--border-1);
    color: var(--text-2);
    border-radius: var(--r-pill);
    padding: 6px 13px;
    font-size: 12.5px;
    font-weight: 600;
    transition: all 0.13s ease;
  }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--text-1);
  }

  .query-bar {
    display: flex; align-items: center; gap: 11px;
    background: var(--bg-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
    padding: 12px 15px;
  }
  .prompt { font-family: var(--font-mono); color: var(--accent-2); font-weight: 700; }
  .qtext { flex: 1; font-size: 14px; color: var(--text-1); }
  .exit {
    font-size: 11.5px; font-weight: 700; padding: 3px 10px; border-radius: var(--r-pill);
    white-space: nowrap;
  }
  .exit.amber { background: var(--amber-soft); color: var(--amber); }
  .exit.accent { background: var(--accent-soft); color: var(--accent-2); }
  .exit.violet { background: var(--violet-soft); color: var(--violet); }

  .stages { display: flex; flex-direction: column; }
  .divider {
    margin: 10px 0 10px 17px;
    padding-left: 26px;
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.13em;
    color: var(--text-3); font-weight: 700;
    position: relative;
  }
  .divider::before {
    content: ''; position: absolute; left: 0; top: 50%;
    width: 18px; height: 1px; background: var(--border-2);
  }

  .stage {
    display: flex; gap: 16px; align-items: stretch;
    animation: fade-up 0.32s ease both;
  }
  .rail { position: relative; width: 36px; flex-shrink: 0; display: flex; justify-content: center; }
  .rail::before {
    content: ''; position: absolute; top: 0; bottom: 0; left: 50%;
    width: 2px; transform: translateX(-50%);
    background: var(--border-1);
  }
  .stage:first-child .rail::before { top: 18px; }
  .stage:last-child .rail::before { bottom: calc(100% - 18px); }
  .node {
    position: relative; z-index: 1;
    margin-top: 5px;
    width: 34px; height: 34px; flex-shrink: 0;
    display: grid; place-items: center;
    border-radius: 9px;
    font-family: var(--font-mono); font-size: 11.5px; font-weight: 700;
    background: var(--surface-3);
    border: 1px solid var(--border-2);
    color: var(--text-2);
    transition: all 0.2s ease;
  }
  .content { flex: 1; padding: 6px 0 16px; }
  .line1 { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .sname { font-size: 14.5px; font-weight: 650; color: var(--text-1); }
  .sdesc { font-size: 12.5px; color: var(--text-3); margin-top: 2px; }
  .snote {
    font-family: var(--font-mono); font-size: 11.5px; font-weight: 500;
    padding: 2px 9px; border-radius: var(--r-pill);
    background: var(--surface-3); color: var(--text-2);
  }

  /* status treatments */
  .stage.skip { opacity: 0.4; }
  .stage.skip .node { border-style: dashed; }
  .stage.na { opacity: 0.4; }

  .stage.active .node, .stage.route .node, .stage.fire .node {
    color: var(--text-on-accent);
    background: linear-gradient(135deg, var(--accent-1), var(--accent-2));
    border-color: transparent;
    box-shadow: 0 0 0 4px var(--accent-soft);
  }
  .stage.route .node { box-shadow: 0 0 0 4px var(--accent-soft), 0 6px 18px -4px var(--accent-1); }
  .snote.route { background: var(--accent-soft); color: var(--accent-2); }

  .stage.fire .node { background: linear-gradient(135deg, var(--amber), #f59e0b); }
  .snote.fire { background: var(--amber-soft); color: var(--amber); }

  .stage.miss .node { color: var(--text-2); border-color: var(--border-2); }
  .snote.miss { background: var(--surface-3); color: var(--text-3); }

  .stage.fail .node { background: linear-gradient(135deg, var(--red), #ef4444); color: #fff; border-color: transparent; }
  .snote.fail { background: var(--red-soft); color: var(--red); }

  .footnote { font-size: 12px; color: var(--text-3); margin-top: 2px; }
  .footnote em { color: var(--text-2); font-style: italic; }
</style>
