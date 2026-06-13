<script>
  // tone: neutral | accent | green | amber | red | blue | violet
  let { tone = 'neutral', mono = false, dot = false, children } = $props()
</script>

<span class="pill {tone}" class:mono>
  {#if dot}<i class="dot"></i>{/if}
  {@render children()}
</span>

<style>
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border-radius: var(--r-pill);
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
    border: 1px solid transparent;
    white-space: nowrap;
  }
  .mono { font-family: var(--font-mono); font-weight: 500; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .neutral { background: var(--surface-3); color: var(--text-2); border-color: var(--border-1); }
  .accent { background: var(--accent-soft); color: var(--accent-2); border-color: var(--accent-line); }
  .green { background: var(--green-soft); color: var(--green); }
  .amber { background: var(--amber-soft); color: var(--amber); }
  .red { background: var(--red-soft); color: var(--red); }
  .blue { background: var(--blue-soft); color: var(--blue); }
  .violet { background: var(--violet-soft); color: var(--violet); }
</style>
